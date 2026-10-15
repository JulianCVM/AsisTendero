"""Harness LangGraph: validar → leer fuente → interpretar → verificar → responder."""

from collections.abc import Callable
from typing import NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from asistendero.catalog import MockCatalog, Product, tokens
from asistendero.grok import Decision, PROMPT_VERSION


class AgentState(TypedDict):
    consulta: str
    candidatos: NotRequired[list[Product]]
    decision: NotRequired[Decision | None]
    respuesta: NotRequired[str]
    estado: NotRequired[str]
    fuente: NotRequired[str]
    prompt_version: NotRequired[str]
    model_called: NotRequired[bool]


def _is_distinguished(query: str, selected: Product, candidates: list[Product]) -> bool:
    peers = [item for item in candidates if item.name == selected.name and item.sku != selected.sku]
    if not peers:
        return True
    # Un SKU citado en el mensaje puede ser parte de una instrucción indebida;
    # por sí solo no demuestra que el cliente haya pedido esa variante.
    unique_variant = tokens(selected.variant) - set().union(*(tokens(item.variant) for item in peers))
    return bool(tokens(query) & unique_variant)


def _format_cop(value: int) -> str:
    return f"${value:,}".replace(",", ".")


def build_graph(catalog: MockCatalog, decider: Callable[[str, list[Product]], Decision]):
    def validate(state: AgentState) -> dict:
        query = state["consulta"].strip()
        if not query:
            raise ValueError("La consulta no puede estar vacía.")
        if len(query) > 2000:
            raise ValueError("La consulta supera el límite de 2000 caracteres.")
        return {"consulta": query}

    def retrieve(state: AgentState) -> dict:
        return {"candidatos": catalog.search(state["consulta"]), "fuente": "mock_sqlite"}

    def route(state: AgentState) -> str:
        return "decide" if state["candidatos"] else "render"

    def decide(state: AgentState) -> dict:
        return {"decision": decider(state["consulta"], state["candidatos"]), "model_called": True}

    def render(state: AgentState) -> dict:
        candidates = state["candidatos"]
        decision = state.get("decision")
        common = {"prompt_version": PROMPT_VERSION, "model_called": state.get("model_called", False)}
        if not candidates:
            return {**common, "estado": "not_found", "respuesta": "No encuentro ese producto en el catálogo de demostración. ¿Puedes indicar el tipo, medida o presentación?"}

        selected = next((item for item in candidates if decision and item.sku == decision.selected_sku), None)
        if selected and _is_distinguished(state["consulta"], selected, candidates):
            plural = {"metro": "metros", "unidad": "unidades", "bulto": "bultos", "galón": "galones"}
            stock_text = f"stock simulado: {selected.stock} {plural.get(selected.unit, 'unidades')}" if selected.stock else "agotado en el catálogo simulado"
            return {**common, "estado": "found", "respuesta": (
                f"Datos simulados: {selected.name}, {selected.variant} (SKU {selected.sku}): "
                f"{_format_cop(selected.price_cop)} COP por {selected.unit}; {stock_text}. "
                "Para una compra real hay que confirmar los datos con la ferretería."
            )}

        options = "; ".join(f"{item.name} {item.variant}" for item in candidates[:3])
        state_name = "model_invalid" if decision and not decision.valid_json else "clarify"
        return {**common, "estado": state_name, "respuesta": (
            f"En el catálogo de demostración veo estas opciones: {options}. "
            "¿Cuál medida o presentación necesitas?"
        )}

    builder = StateGraph(AgentState)
    builder.add_node("validate", validate)
    builder.add_node("retrieve", retrieve)
    builder.add_node("decide", decide)
    builder.add_node("render", render)
    builder.add_edge(START, "validate")
    builder.add_edge("validate", "retrieve")
    builder.add_conditional_edges("retrieve", route, {"decide": "decide", "render": "render"})
    builder.add_edge("decide", "render")
    builder.add_edge("render", END)
    return builder.compile()
