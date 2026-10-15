"""Observabilidad local del mismo grafo usado por CLI y evaluación."""

from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timezone
import os
from time import perf_counter
from urllib.parse import urlsplit

from asistendero.catalog import MockCatalog, Product, tokens
from asistendero.graph import build_graph
from asistendero.grok import (
    DEFAULT_BASE_URL, DEFAULT_MODEL, MAX_OUTPUT_TOKENS, PROMPT_VERSION,
    RESPONSE_FORMAT, TEMPERATURE, Decision, build_messages, decide_with_grok,
)
from asistendero.seed import DEMO_BUSINESS_ID, DEMO_STORE_ID


def _visible_endpoint() -> str:
    """Nunca incluir credenciales, query string ni fragmento de una URL configurable."""
    parts = urlsplit(os.getenv("GROK_BASE_URL", DEFAULT_BASE_URL))
    if not parts.scheme or not parts.hostname:
        return "URL no válida"
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{parts.hostname}{port}{parts.path}"


def run_traced(
    query: str,
    emit: Callable[[dict], None],
    catalog: MockCatalog | None = None,
    decider: Callable[[str, list[Product]], Decision] = decide_with_grok,
) -> dict:
    """Ejecuta el grafo y emite eventos al completar cada nodo, sin llamadas extra al modelo."""
    catalog = catalog or MockCatalog()
    started = perf_counter()
    node_started = perf_counter()
    state: dict = {"consulta": query}

    def push(event_type: str, **payload: object) -> None:
        emit({
            "type": event_type,
            "at": datetime.now(timezone.utc).isoformat(),
            "elapsed_ms": round((perf_counter() - started) * 1000),
            **payload,
        })

    def start_node(name: str, details: dict | None = None) -> None:
        nonlocal node_started
        node_started = perf_counter()
        push("node", node=name, status="running", details=details or {})

    def traced_decider(text: str, candidates: list[Product]) -> Decision:
        push("model_request", details={
            "endpoint": _visible_endpoint(),
            "model": os.getenv("GROK_MODEL", DEFAULT_MODEL),
            "temperature": TEMPERATURE,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "response_format": RESPONSE_FORMAT,
            "messages": build_messages(text, candidates),
            "api_key": "[omitida]",
        })
        decision = decider(text, candidates)
        push("model_response", details=asdict(decision))
        return decision

    push("input", details={"consulta": query, "prompt_version": PROMPT_VERSION})
    start_node("validate", {"consulta": query})
    graph = build_graph(catalog, traced_decider)
    for chunk in graph.stream({"consulta": query}, stream_mode="updates"):
        for node, update in chunk.items():
            state.update(update)
            if node == "validate":
                details = {"consulta_normalizada": update["consulta"], "longitud": len(update["consulta"])}
            elif node == "retrieve":
                details = {
                    "fuente": update["fuente"],
                    "archivo": str(catalog.path),
                    "business_id": DEMO_BUSINESS_ID,
                    "store_id": DEMO_STORE_ID,
                    "terminos": sorted(tokens(state["consulta"])),
                    "limite_candidatos": 5,
                    "candidatos": [asdict(item) for item in update["candidatos"]],
                }
            elif node == "decide":
                details = {"selected_sku": update["decision"].selected_sku, "model_called": True}
            else:
                details = {
                    "estado": update["estado"],
                    "respuesta": update["respuesta"],
                    "model_called": update["model_called"],
                    "prompt_version": update["prompt_version"],
                }
            push("node", node=node, status="complete", duration_ms=round((perf_counter() - node_started) * 1000), details=details)
            if node == "validate":
                start_node("retrieve", {"consulta": state["consulta"], "limite_candidatos": 5})
            elif node == "retrieve":
                if update["candidatos"]:
                    start_node("decide", {"candidatos_enviados": [item.sku for item in update["candidatos"]]})
                else:
                    push("route", details={"motivo": "Sin candidatos: se omite Grok."})
                    start_node("render")
            elif node == "decide":
                start_node("render")
    push("final", details={"estado": state["estado"], "respuesta": state["respuesta"], "model_called": state["model_called"]})
    return state
