"""Flujo: barreras → Grok decide → el servidor valida y ejecuta la herramienta → respuesta verificada.

Cada paso vive en su módulo: ``guardrails`` (lo que nunca llega a Grok), ``validation`` (antes de
ejecutar), ``observations`` (lo que devuelven las herramientas) y ``answers`` (la respuesta final).
En una sesión de chat, ``contexto`` trae los turnos previos que guardó ``sessions``.
"""

from collections.abc import Callable
from time import perf_counter
from typing import NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from asistendero.answers import direct_response, render_answer, reply_is_grounded, with_reservation_note
from asistendero.grok import ORDER_TOOLS, PROMPT_VERSION, Decision, ModelError
from asistendero.guardrails import screen_message
from asistendero.observations import ToolCall, ToolExecutor, error_envelope, execute_safely, observation_for_model
from asistendero.order_rules import validate_order_request
from asistendero.reminders import pending_reminder, with_reminders
from asistendero.validation import Rejected, quantities_in_message, validate_request


__all__ = ["MAX_MESSAGE_CHARS", "MAX_TOOL_CALLS", "AgentState", "Planner", "ToolExecutor", "build_graph", "next_node"]

# planner(mensaje, observaciones, llamadas_disponibles[, context=...]): el contexto solo va en una sesión.
Planner = Callable[..., Decision]

MAX_TOOL_CALLS = 6
MAX_MESSAGE_CHARS = 2000
# Turnos previos del cliente que cuentan como «lo que dijo» para elegir variante y cantidad.
REFERENCE_TURNS = 3
REFUSAL_CLOSING = ("Con gusto te ayudo con productos, precios y existencias del catálogo de demostración, "
                   "o con información de la tienda.")
PERSONAL_DATA_NOTE = "No hace falta compartir datos personales para cotizar; no los guardo."


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
    avisos: NotRequired[list[dict]]
    contexto: NotRequired[dict | None]
    referencia: NotRequired[str]
    filtro: NotRequired[dict]


def _pending(state: AgentState) -> str | None:
    calls = state.get("tool_calls", [])
    if len(calls) >= MAX_TOOL_CALLS:
        return None
    sent = {item["code"] for item in state.get("avisos", [])}
    return pending_reminder(state["consulta"], state["decisiones"][-1], calls, sent, state.get("referencia"),
                            state.get("contexto"))


def next_node(state: AgentState) -> str:
    """Ruta tras cada decisión de Grok; la traza usa la misma regla."""
    if state.get("error"):
        return "respond"
    decision = state["decisiones"][-1]
    if decision.valid_json and decision.action == "call_tool" and len(state.get("tool_calls", [])) < MAX_TOOL_CALLS:
        return "retrieve"
    if _pending(state):
        return "interpret"
    return "respond"


def after_validate(state: AgentState) -> str:
    """Si todo el mensaje pedía algo que no se entrega, se responde sin llamar a Grok."""
    return "interpret" if state["consulta"] else "respond"


def reference_text(message: str, context: dict | None) -> str:
    """Lo que el cliente dijo en la conversación reciente más el mensaje actual."""
    turns = (context or {}).get("turnos") or []
    previous = [turn["cliente"] for turn in turns[-REFERENCE_TURNS:] if isinstance(turn.get("cliente"), str)]
    return "\n".join([*previous, message])


def build_graph(tool_executor: ToolExecutor, planner: Planner):
    def validate(state: AgentState) -> dict:
        message = state["consulta"].strip()
        if not message:
            raise ValueError("La consulta no puede estar vacía.")
        if len(message) > MAX_MESSAGE_CHARS:
            raise ValueError(f"La consulta supera el límite de {MAX_MESSAGE_CHARS} caracteres.")
        screening = screen_message(message)
        context = state.get("contexto") or None
        return {
            "consulta": screening.consulta, "decisiones": [], "tool_calls": [], "error": None, "model_calls": 0,
            "referencia": reference_text(screening.consulta, context) if screening.consulta else "",
            "filtro": {"codes": list(screening.codes), "refusal": screening.refusal, "redacted": screening.redacted},
        }

    def interpret(state: AgentState) -> dict:
        calls = state["tool_calls"]
        model_calls = state["model_calls"] + 1
        update: dict = {"model_called": True, "model_calls": model_calls}
        avisos = state.get("avisos", [])
        # Solo se vuelve aquí tras un «respond» cuando next_node detectó un aviso pendiente.
        if state["decisiones"] and state["decisiones"][-1].action == "respond":
            avisos = update["avisos"] = avisos + [{"code": _pending(state), "at": len(calls)}]
        observations = with_reminders([observation_for_model(call) for call in calls], avisos)
        context = state.get("contexto")
        try:
            decision = planner(state["consulta"], observations, MAX_TOOL_CALLS - len(calls),
                               **({"context": context} if context else {}))
        except ModelError as exc:
            return {**update, "error": {"code": exc.code, "message": str(exc)}}
        except Exception as exc:
            return {**update, "error": {"code": "MODEL_UNAVAILABLE",
                                        "message": f"Fallo inesperado del modelo ({type(exc).__name__})."}}
        return {**update, "decisiones": state["decisiones"] + [decision]}

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
            # Las cantidades son las del turno; si el turno no dice ninguna («cotízalo»), las de la conversación.
            quantities = quantities_in_message(state["consulta"]) or quantities_in_message(state["referencia"])
            if decision.tool in ORDER_TOOLS and isinstance(decision.arguments, dict):
                # Los pedidos miran el mensaje del turno: confirmar o cancelar lo tiene que decir ahora el cliente.
                arguments = validate_order_request(decision.tool, decision.arguments, current=state["consulta"],
                                                   reference=state["referencia"], calls=calls,
                                                   context=state.get("contexto"))
            else:
                arguments = validate_request(decision.tool, decision.arguments, state["referencia"], calls, quantities)
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
        guard = state.get("filtro") or {}
        notes = [note for note in (guard.get("refusal"), PERSONAL_DATA_NOTE if guard.get("redacted") else "") if note]
        if not state["consulta"]:
            return {"prompt_version": PROMPT_VERSION, "model_called": False, "model_calls": 0,
                    "estado": "refused", "respuesta": " ".join([*notes, REFUSAL_CLOSING])}
        update = _respond(state)
        update["respuesta"] = with_reservation_note(state["consulta"], update["respuesta"], state["tool_calls"],
                                                    state.get("contexto"))
        if notes:
            update["respuesta"] = " ".join(notes) + "\n" + update["respuesta"]
        return update

    def _respond(state: AgentState) -> dict:
        message, calls = state["referencia"], state["tool_calls"]
        common = {"prompt_version": PROMPT_VERSION, "model_called": state.get("model_called", False),
                  "model_calls": state.get("model_calls", 0)}
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
            return {**common, "estado": "answered", "respuesta": direct_response(state["consulta"], decision)}
        status, answer = render_answer(message, calls)
        if reply_is_grounded(decision.reply, message, calls, state.get("contexto")):
            answer = decision.reply.strip()
        return {**common, "estado": status, "respuesta": answer}

    builder = StateGraph(AgentState)
    builder.add_node("validate", validate)
    builder.add_node("interpret", interpret)
    builder.add_node("retrieve", retrieve)
    builder.add_node("respond", respond)
    builder.add_edge(START, "validate")
    builder.add_conditional_edges("validate", after_validate, {"interpret": "interpret", "respond": "respond"})
    builder.add_conditional_edges(
        "interpret", next_node, {"retrieve": "retrieve", "respond": "respond", "interpret": "interpret"},
    )
    builder.add_edge("retrieve", "interpret")
    builder.add_edge("respond", END)
    return builder.compile()
