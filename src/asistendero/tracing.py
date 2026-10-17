"""Traza local del mismo grafo que ejecuta la terminal."""

from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timezone
import os
from time import perf_counter
from urllib.parse import urlsplit

from asistendero.catalog import MockCatalog, tokens
from asistendero.graph import Finding, build_graph
from asistendero.pricing import call_cost, run_cost
from asistendero.grok import (
    DEFAULT_BASE_URL, DEFAULT_MODEL, PLAN_PROMPT, RESOLVE_PROMPT,
    PROMPT_VERSION, Plan, Resolution, plan_with_grok, resolve_with_grok,
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
    catalog: MockCatalog | None = None,
    planner: Callable[[str], Plan] = plan_with_grok,
    resolver: Callable[[str, list[Finding]], Resolution] = resolve_with_grok,
) -> dict:
    catalog = catalog or MockCatalog()
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

    def traced_planner(message: str) -> Plan:
        push("model_request", details={
            "phase": "interpret", "endpoint": _visible_endpoint(),
            "model": os.getenv("GROK_MODEL", DEFAULT_MODEL),
            "instructions": PLAN_PROMPT, "mensaje": message, "api_key": "[omitida]",
        })
        plan = planner(message)
        cost = call_cost(plan.model, plan.input_tokens, plan.output_tokens,
                         plan.cached_input_tokens, plan.reported_cost_usd_ticks)
        call_costs.append(cost)
        push("model_response", details={"phase": "interpret", **asdict(plan), "cost": cost})
        return plan

    def traced_resolver(message: str, findings: list[Finding]) -> Resolution:
        push("model_request", details={
            "phase": "resolve", "endpoint": _visible_endpoint(),
            "model": os.getenv("GROK_MODEL", DEFAULT_MODEL),
            "instructions": RESOLVE_PROMPT,
            "mensaje": message,
            "hallazgos": [
                {
                    "query": item["query"], "request": asdict(item["request"]),
                    "candidates": [asdict(p) for p in item["candidates"]],
                    "nearby": [asdict(p) for p in item["nearby"]],
                }
                for item in findings
            ],
            "api_key": "[omitida]",
        })
        resolution = resolver(message, findings)
        cost = call_cost(resolution.model, resolution.input_tokens, resolution.output_tokens,
                         resolution.cached_input_tokens, resolution.reported_cost_usd_ticks)
        call_costs.append(cost)
        push("model_response", details={"phase": "resolve", **asdict(resolution), "cost": cost})
        return resolution

    push("input", details={"consulta": query, "prompt_version": PROMPT_VERSION})
    start_node("validate")
    graph = build_graph(catalog, traced_planner, traced_resolver)
    for chunk in graph.stream({"consulta": query}, stream_mode="updates"):
        for node, update in chunk.items():
            state.update(update)
            if node == "validate":
                details = {"consulta_normalizada": update["consulta"], "longitud": len(update["consulta"])}
            elif node == "interpret":
                details = {"plan": asdict(update["plan"]), "model_calls": 1}
            elif node == "retrieve":
                details = {
                    "fuente": update["fuente"], "archivo": str(catalog.path),
                    "business_id": catalog.business_id, "store_id": catalog.store_id,
                    "hallazgos": [
                        {
                            "query": item["query"], "request": asdict(item["request"]),
                            "terminos": sorted(tokens(item["query"])),
                            "candidates": [asdict(p) for p in item["candidates"]],
                            "nearby": [asdict(p) for p in item["nearby"]],
                        }
                        for item in update["hallazgos"]
                    ],
                }
            else:
                details = {
                    "estado": update["estado"], "respuesta": update["respuesta"],
                    "model_calls": update["model_calls"], "prompt_version": update["prompt_version"],
                }
            push("node", node=node, status="complete", duration_ms=round((perf_counter() - node_started) * 1000), details=details)
            if node == "validate":
                start_node("interpret")
            elif node == "interpret":
                if update["plan"].action == "search_products":
                    start_node("retrieve")
                else:
                    push("route", details={"motivo": "Grok decidió responder sin consultar catálogo."})
                    start_node("respond")
            elif node == "retrieve":
                start_node("respond")
    push("final", details={
        "estado": state["estado"], "respuesta": state["respuesta"],
        "model_called": state["model_called"], "model_calls": state["model_calls"],
        "cost": run_cost(call_costs),
    })
    return state
