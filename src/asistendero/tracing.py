"""Traza local del mismo grafo que ejecuta la terminal."""

from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timezone
import os
from time import perf_counter
from urllib.parse import urlsplit
from uuid import uuid4

from asistendero.catalog import MockCatalog, tokens
from asistendero.executor import catalog_executor
from asistendero.graph import Planner, ToolExecutor, after_validate, build_graph, next_node
from asistendero.grok import (
    AGENT_PROMPT, DEFAULT_BASE_URL, PROMPT_VERSION, Decision, ModelError, current_model, decide_with_grok,
)
from asistendero.guardrails import redact_personal_data
from asistendero.pricing import call_cost, run_cost


def _visible_endpoint() -> str:
    parts = urlsplit(os.getenv("GROK_BASE_URL", DEFAULT_BASE_URL))
    if not parts.scheme or not parts.hostname:
        return "URL no válida"
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{parts.hostname}{port}{parts.path}"


def _sum_tokens(decisions: list[Decision], field: str) -> int | None:
    values = [getattr(decision, field) for decision in decisions]
    known = [value for value in values if isinstance(value, int) and not isinstance(value, bool)]
    if not known:
        return None
    return sum(known)


def run_traced(
    query: str,
    emit: Callable[[dict], None],
    tool_executor: ToolExecutor | None = None,
    planner: Planner = decide_with_grok,
    context: dict | None = None,
) -> dict:
    """Ejecuta el grafo y emite cada evento; ``context`` es la conversación previa de una sesión."""
    tool_executor = tool_executor or catalog_executor(MockCatalog())
    run_id = uuid4().hex[:12]
    started = perf_counter()
    node_started = perf_counter()
    state: dict = {"consulta": query, "run_id": run_id}
    call_costs: list[dict | None] = []

    def push(event_type: str, **payload: object) -> None:
        emit({
            "run_id": run_id,
            "type": event_type,
            "at": datetime.now(timezone.utc).isoformat(),
            "elapsed_ms": round((perf_counter() - started) * 1000),
            **payload,
        })

    def start_node(name: str) -> None:
        nonlocal node_started
        node_started = perf_counter()
        push("node", node=name, status="running", details={"run_id": run_id})

    def traced_planner(message: str, observations: list[dict], remaining: int, **extra: object) -> Decision:
        phase = "resolve" if observations else "interpret"
        step_number = len(call_costs) + 1
        call_started = perf_counter()
        push("model_request", details={
            "run_id": run_id,
            "step": step_number,
            "phase": phase,
            "endpoint": _visible_endpoint(),
            "model": current_model(),
            "instructions": AGENT_PROMPT,
            "mensaje": message,
            "observaciones": observations,
            "llamadas_disponibles": remaining,
            "conversacion": extra.get("context"),
            "api_key": "[omitida]",
        })
        try:
            decision = planner(message, observations, remaining, **extra)
        except ModelError as exc:
            call_costs.append(None)
            push("model_response", details={
                "run_id": run_id,
                "step": step_number,
                "phase": phase,
                "duration_ms": round((perf_counter() - call_started) * 1000),
                "error": {"code": exc.code, "message": str(exc)},
                "cost": None,
            })
            raise
        cost = call_cost(
            decision.model,
            decision.input_tokens,
            decision.output_tokens,
            decision.cached_input_tokens,
            decision.reported_cost_usd_ticks,
        )
        call_costs.append(cost)
        push("model_response", details={
            "run_id": run_id,
            "step": step_number,
            "phase": phase,
            "duration_ms": round((perf_counter() - call_started) * 1000),
            **asdict(decision),
            "cost": cost,
        })
        return decision

    # Los datos personales no quedan en la traza ni en los reportes del evaluador.
    push("input", details={"run_id": run_id, "consulta": redact_personal_data(query)[0],
                           "prompt_version": PROMPT_VERSION, "sesion": bool(context)})
    start_node("validate")
    graph = build_graph(tool_executor, traced_planner)
    for chunk in graph.stream({"consulta": query, "contexto": context}, stream_mode="updates"):
        for node, update in chunk.items():
            state.update(update)
            if node == "validate":
                details = {"consulta_normalizada": update["consulta"], "longitud": len(update["consulta"]),
                           "barreras": update["filtro"]["codes"], "datos_personales_omitidos": update["filtro"]["redacted"],
                           "inyeccion": update.get("inyeccion")}
            elif node == "interpret":
                decision = update.get("decisiones", [None])[-1] if update.get("decisiones") else None
                details = {
                    "decision": asdict(decision) if decision else None,
                    "error": update.get("error"),
                    "model_calls": update["model_calls"],
                }
            elif node == "retrieve":
                call = update["tool_calls"][-1]
                details = {"tool_call": call}
                if call["requested_tool"] == "buscar_productos" and call["executed"]:
                    details["terminos"] = [sorted(tokens(item["text"])) for item in call["arguments"]["items"]]
            else:
                details = {
                    "estado": update["estado"],
                    "respuesta": update["respuesta"],
                    "error": update.get("error"),
                    "model_calls": state["model_calls"],
                    "prompt_version": update["prompt_version"],
                }
            push(
                "node",
                node=node,
                status="complete",
                duration_ms=round((perf_counter() - node_started) * 1000),
                details=details,
            )
            if node == "validate" and after_validate(state) == "respond":
                push("route", details={"motivo": "El mensaje intentaba cambiar las reglas del agente; se bloquea sin "
                                                 "llamar a Grok." if state.get("inyeccion") else
                                                 "El mensaje solo pedía información que no se entrega; "
                                                 "se responde sin llamar a Grok."})
                start_node("respond")
            elif node in {"validate", "retrieve"}:
                start_node("interpret")
            elif node == "interpret":
                following = next_node(state)
                if following == "interpret":
                    # El código del aviso llega en las observaciones del siguiente model_request.
                    push("route", details={
                        "motivo": "Grok respondió sin un paso que el mensaje exige; el servidor le envía un aviso.",
                        "aviso": True,
                    })
                elif following == "respond" and not state.get("tool_calls"):
                    push("route", details={
                        "motivo": "Grok decidió responder sin herramientas."
                        if not state.get("error")
                        else "Fallo del modelo; respuesta segura."
                    })
                start_node(following)

    decisions = state.get("decisiones", [])
    tool_calls = state.get("tool_calls", [])
    input_tokens = _sum_tokens(decisions, "input_tokens")
    output_tokens = _sum_tokens(decisions, "output_tokens")
    cached_tokens = _sum_tokens(decisions, "cached_input_tokens")
    total_tokens = (
        input_tokens + output_tokens
        if input_tokens is not None and output_tokens is not None
        else None
    )
    duration_ms = round((perf_counter() - started) * 1000)
    total_cost = run_cost(call_costs)

    final_details = {
        "run_id": run_id,
        "prompt_version": state.get("prompt_version", PROMPT_VERSION),
        "estado": state["estado"],
        "respuesta": state["respuesta"],
        "error": state.get("error"),
        "model_called": state["model_called"],
        "model_calls": state["model_calls"],
        "barreras": (state.get("filtro") or {}).get("codes", []),
        "inyeccion": state.get("inyeccion"),
        "tool_calls": len(tool_calls),
        "tools_requested": [call["requested_tool"] for call in tool_calls],
        "tools_executed": [call["requested_tool"] for call in tool_calls if call["executed"]],
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_input_tokens": cached_tokens,
        "total_tokens": total_tokens,
        "duration_ms": duration_ms,
        "cost": total_cost,
    }
    state.update(run_id=run_id, duration_ms=duration_ms, cost=total_cost)
    push("final", details=final_details)
    return state
