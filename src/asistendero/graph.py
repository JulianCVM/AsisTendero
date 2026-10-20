"""Flujo S2: Grok decide → el servidor valida y ejecuta la herramienta → respuesta verificada.

Cada paso vive en su módulo: ``validation`` (antes de ejecutar), ``observations`` (lo que
devuelven las herramientas) y ``answers`` (la respuesta final).
"""

from collections.abc import Callable
from time import perf_counter
from typing import NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from asistendero.answers import direct_response, render_answer, reply_is_grounded
from asistendero.grok import PROMPT_VERSION, Decision, ModelError
from asistendero.observations import ToolCall, ToolExecutor, error_envelope, execute_safely, observation_for_model
from asistendero.validation import Rejected, validate_request


__all__ = ["MAX_TOOL_CALLS", "AgentState", "Planner", "ToolExecutor", "build_graph", "next_node"]

Planner = Callable[[str, list[dict], int], Decision]

MAX_TOOL_CALLS = 6


class AgentState(TypedDict):
    consulta: str
    decisiones: NotRequired[list[Decision]]
    tool_calls: NotRequired[list[ToolCall]]
    error: NotRequired[dict | None]
    respuesta: NotRequired[str]
    estado: NotRequired[str]
    fuente: NotRequired[str]
    prompt_version: NotRequired[str]
    model_called: NotRequired[bool]
    model_calls: NotRequired[int]


def next_node(state: AgentState) -> str:
    """Ruta tras cada decisión de Grok; la traza usa la misma regla."""
    if state.get("error"):
        return "respond"
    decision = state["decisiones"][-1]
    if decision.valid_json and decision.action == "call_tool" and len(state.get("tool_calls", [])) < MAX_TOOL_CALLS:
        return "retrieve"
    return "respond"


def build_graph(tool_executor: ToolExecutor, planner: Planner):
    def validate(state: AgentState) -> dict:
        message = state["consulta"].strip()
        if not message:
            raise ValueError("La consulta no puede estar vacía.")
        if len(message) > 2000:
            raise ValueError("La consulta supera el límite de 2000 caracteres.")
        return {"consulta": message, "decisiones": [], "tool_calls": [], "error": None, "model_calls": 0}

    def interpret(state: AgentState) -> dict:
        calls = state["tool_calls"]
        model_calls = state["model_calls"] + 1
        try:
            decision = planner(state["consulta"], [observation_for_model(call) for call in calls],
                               MAX_TOOL_CALLS - len(calls))
        except ModelError as exc:
            return {"model_called": True, "model_calls": model_calls,
                    "error": {"code": exc.code, "message": str(exc)}}
        except Exception as exc:
            return {"model_called": True, "model_calls": model_calls,
                    "error": {"code": "MODEL_UNAVAILABLE", "message": f"Fallo inesperado del modelo ({type(exc).__name__})."}}
        return {"decisiones": state["decisiones"] + [decision], "model_called": True, "model_calls": model_calls}

    def retrieve(state: AgentState) -> dict:
        decision = state["decisiones"][-1]
        calls = state["tool_calls"]
        started = perf_counter()
        call: ToolCall = {
            "step": len(calls) + 1, "requested_tool": decision.tool,
            "requested_arguments": decision.arguments, "executed": False, "arguments": None,
            "response": {}, "duration_ms": 0,
        }
        try:
            arguments = validate_request(decision.tool, decision.arguments, state["consulta"], calls)
            if any(previous["executed"] and previous["requested_tool"] == decision.tool
                   and previous["arguments"] == arguments for previous in calls):
                raise Rejected("DUPLICATE_CALL", "Esa llamada ya se ejecutó; usa su observación.")
        except Rejected as exc:
            call["response"] = error_envelope("rejected", exc.code, str(exc), "agent_validation")
        else:
            call.update(executed=True, arguments=arguments, response=execute_safely(tool_executor, decision.tool, arguments))
        call["duration_ms"] = round((perf_counter() - started) * 1000)
        return {"tool_calls": calls + [call], "fuente": "mock_sqlite"}

    def respond(state: AgentState) -> dict:
        message, calls = state["consulta"], state["tool_calls"]
        common = {"prompt_version": PROMPT_VERSION, "model_called": state.get("model_called", False)}
        error = state.get("error")
        decision = state["decisiones"][-1] if state["decisiones"] else None
        if error is None and decision is not None and not decision.valid_json:
            error = {"code": "MODEL_INVALID_OUTPUT", "message": "Grok devolvió una decisión con formato inválido."}
        elif error is None and decision is not None and decision.action == "call_tool":
            error = {"code": "TOOL_CALL_LIMIT", "message": f"Se alcanzó el límite de {MAX_TOOL_CALLS} herramientas."}

        if error:
            estado = {"MODEL_INVALID_OUTPUT": "model_invalid", "TOOL_CALL_LIMIT": "limit_reached"}.get(error["code"], "model_error")
            if calls:
                # Lo ya consultado es verificable; se muestra aunque el modelo haya fallado.
                _, answer = render_answer(message, calls)
            elif estado == "model_invalid":
                answer = "No pude interpretar bien tu mensaje. ¿Puedes contarme de nuevo qué producto necesitas?"
            else:
                answer = ("No pude completar la consulta con el asistente en este momento, así que no tengo "
                          "precios ni existencias verificados. Intenta de nuevo en unos minutos.")
            return {**common, "estado": estado, "error": error, "respuesta": answer}

        if not calls:
            return {**common, "estado": "answered", "respuesta": direct_response(message, decision)}
        status, answer = render_answer(message, calls)
        if reply_is_grounded(decision.reply, message, calls):
            answer = decision.reply.strip()
        return {**common, "estado": status, "respuesta": answer}

    builder = StateGraph(AgentState)
    builder.add_node("validate", validate)
    builder.add_node("interpret", interpret)
    builder.add_node("retrieve", retrieve)
    builder.add_node("respond", respond)
    builder.add_edge(START, "validate")
    builder.add_edge("validate", "interpret")
    builder.add_conditional_edges("interpret", next_node, {"retrieve": "retrieve", "respond": "respond"})
    builder.add_edge("retrieve", "interpret")
    builder.add_edge("respond", END)
    return builder.compile()
