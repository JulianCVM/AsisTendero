"""Traza local del mismo grafo que ejecuta la terminal."""

from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timezone
import os
from time import perf_counter
from urllib.parse import urlsplit

from asistendero.catalog import MockCatalog, tokens
from asistendero.executor import catalog_executor
from asistendero.graph import Planner, ToolExecutor, build_graph, next_node
from asistendero.pricing import call_cost, run_cost
from asistendero.grok import (
    AGENT_PROMPT, DEFAULT_BASE_URL, DEFAULT_MODEL, PROMPT_VERSION, Decision, ModelError, decide_with_grok,
)


def _visible_endpoint() -> str:
    parts = urlsplit(os.getenv("GROK_BASE_URL", DEFAULT_BASE_URL))
    if not parts.scheme or not parts.hostname:
        return "URL no válida"
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{parts.hostname}{port}{parts.path}"


def run_traced(
    query: str,
    emit: Callable[[dict], None],
    tool_executor: ToolExecutor | None = None,
    planner: Planner = decide_with_grok,
) -> dict:
    tool_executor = tool_executor or catalog_executor(MockCatalog())
    started = perf_counter()
    node_started = perf_counter()
    state: dict = {"consulta": query}
    call_costs: list[dict | None] = []

    def push(event_type: str, **payload: object) -> None:
        emit({
            "type": event_type,
            "at": datetime.now(timezone.utc).isoformat(),
            "elapsed_ms": round((perf_counter() - started) * 1000),
            **payload,
        })

    def start_node(name: str) -> None:
        nonlocal node_started
        node_started = perf_counter()
        push("node", node=name, status="running", details={})

    def traced_planner(message: str, observations: list[dict], remaining: int) -> Decision:
        phase = "resolve" if observations else "interpret"
        push("model_request", details={
            "phase": phase, "endpoint": _visible_endpoint(),
            "model": os.getenv("GROK_MODEL", DEFAULT_MODEL),
            "instructions": AGENT_PROMPT, "mensaje": message,
            "observaciones": observations, "llamadas_disponibles": remaining, "api_key": "[omitida]",
        })
        try:
            decision = planner(message, observations, remaining)
        except ModelError as exc:
            call_costs.append(None)
            push("model_response", details={"phase": phase, "error": {"code": exc.code, "message": str(exc)}, "cost": None})
            raise
        cost = call_cost(decision.model, decision.input_tokens, decision.output_tokens,
                         decision.cached_input_tokens, decision.reported_cost_usd_ticks)
        call_costs.append(cost)
        push("model_response", details={"phase": phase, **asdict(decision), "cost": cost})
        return decision

    push("input", details={"consulta": query, "prompt_version": PROMPT_VERSION})
    start_node("validate")
    graph = build_graph(tool_executor, traced_planner)
    for chunk in graph.stream({"consulta": query}, stream_mode="updates"):
        for node, update in chunk.items():
            state.update(update)
            if node == "validate":
                details = {"consulta_normalizada": update["consulta"], "longitud": len(update["consulta"])}
            elif node == "interpret":
                decision = update.get("decisiones", [None])[-1] if update.get("decisiones") else None
                details = {"decision": asdict(decision) if decision else None,
                           "error": update.get("error"), "model_calls": update["model_calls"]}
            elif node == "retrieve":
                call = update["tool_calls"][-1]
                details = {"tool_call": call}
                if call["requested_tool"] == "buscar_productos" and call["executed"]:
                    details["terminos"] = [sorted(tokens(item["text"])) for item in call["arguments"]["items"]]
            else:
                details = {
                    "estado": update["estado"], "respuesta": update["respuesta"], "error": update.get("error"),
                    "model_calls": state["model_calls"], "prompt_version": update["prompt_version"],
                }
            push("node", node=node, status="complete", duration_ms=round((perf_counter() - node_started) * 1000), details=details)
            if node in {"validate", "retrieve"}:
                start_node("interpret")
            elif node == "interpret":
                following = next_node(state)
                if following == "respond" and not state.get("tool_calls"):
                    push("route", details={"motivo": "Grok decidió responder sin herramientas."
                                           if not state.get("error") else "Fallo del modelo; respuesta segura."})
                start_node(following)
    push("final", details={
        "estado": state["estado"], "respuesta": state["respuesta"], "error": state.get("error"),
        "model_called": state["model_called"], "model_calls": state["model_calls"],
        "tool_calls": len(state.get("tool_calls", [])),
        "cost": run_cost(call_costs),
    })
    return state
