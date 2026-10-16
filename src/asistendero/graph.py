"""Harness LangGraph: validar → leer fuente → interpretar → verificar → responder."""

from collections.abc import Callable
import re
from typing import NotRequired, TypedDict
import unicodedata

from langgraph.graph import END, START, StateGraph

from asistendero.catalog import MockCatalog, Product, tokens
from asistendero.grok import Decision, PROMPT_VERSION, VALID_INTENTS


class AgentState(TypedDict):
    consulta: str
    candidatos: NotRequired[list[Product]]
    decision: NotRequired[Decision | None]
    intencion: NotRequired[str]
    respuesta: NotRequired[str]
    estado: NotRequired[str]
    fuente: NotRequired[str]
    prompt_version: NotRequired[str]
    model_called: NotRequired[bool]


GENERIC_MEASURE_TOKENS = {"pulgada", "pulgadas", "1", "2", "1/2", "3/4", "1/4", "50", "kg", "x"}


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _detect_intent(query: str, decision: Decision | None = None) -> str:
    text = _normalize_text(query)
    if re.search(r"\b(compar\w*|diferencia\w*|versus|vs)\b|\bentre\b.+\by\b", text):
        return "comparacion"
    if re.search(
        r"\b(recomiend\w*|recomendacion\w*|aconsej\w*|sugier\w*|cual me sirve|que me sirve|cual conviene)\b",
        text,
    ):
        return "recomendacion"
    if re.search(
        r"\b(existencia\w*|stock|disponible\w*|disponibilidad|agotad\w*|cuantos quedan|cuantas quedan|cuantos hay|cuantas hay|hay disponible\w*|tienen disponible\w*)\b",
        text,
    ):
        return "existencias"
    if re.search(
        r"\b(precio\w*|cuanto cuesta\w*|cuanto vale\w*|a como|valor|cotiza\w*|que cuesta\w*|que vale\w*)\b",
        text,
    ):
        return "precio"
    if decision and decision.intent in VALID_INTENTS:
        return decision.intent
    return "producto"


def _relevant_candidates(query: str, candidates: list[Product]) -> list[Product]:
    if len(candidates) <= 1:
        return candidates
    query_words = tokens(query)
    specific_query_words = query_words - GENERIC_MEASURE_TOKENS
    if not specific_query_words:
        return candidates
    filtered = [
        item
        for item in candidates
        if specific_query_words & tokens(f"{item.name} {item.variant}")
    ]
    return filtered or candidates


def _is_distinguished(query: str, selected: Product, candidates: list[Product]) -> bool:
    ascii_query = _normalize_text(query)
    explicit_measures = re.findall(r"\b(\d+(?:/\d+)?)\s*(?:pulgada\w*|kg|kilo\w*)\b", ascii_query)
    variant_tokens = tokens(selected.variant)
    if explicit_measures and not (set(explicit_measures) & variant_tokens):
        return False

    peers = [item for item in candidates if item.name == selected.name and item.sku != selected.sku]
    if not peers:
        return True
    # Un SKU citado en el mensaje puede ser parte de una instrucción indebida;
    # por sí solo no demuestra que el cliente haya pedido esa variante.
    unique_variant = variant_tokens - set().union(*(tokens(item.variant) for item in peers))
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
        candidates = _relevant_candidates(state["consulta"], state["candidatos"])
        decision = state.get("decision")
        intent = _detect_intent(state["consulta"], decision)
        common = {
            "intencion": intent,
            "prompt_version": PROMPT_VERSION,
            "model_called": state.get("model_called", False),
        }
        if not candidates:
            return {
                **common,
                "estado": "not_found",
                "respuesta": (
                    "¡Hola! No encuentro ese producto en el catálogo de demostración. "
                    "¿Puedes indicar el tipo, medida o presentación que buscas?"
                ),
            }

        plural = {"metro": "metros", "unidad": "unidades", "bulto": "bultos", "galón": "galones"}

        if (
            intent == "comparacion"
            and len(candidates) >= 2
            and (not decision or decision.valid_json)
            and (not decision or decision.selected_sku is None or any(item.sku == decision.selected_sku for item in candidates))
        ):
            comparison_items = "; ".join(
                f"{item.name} {item.variant} (SKU {item.sku}): {_format_cop(item.price_cop)} COP por {item.unit}, "
                + (f"{item.stock} {plural.get(item.unit, 'unidades')} disponibles" if item.stock else "agotado")
                for item in candidates[:3]
            )
            return {
                **common,
                "estado": "found",
                "respuesta": (
                    f"¡Con gusto! Así se comparan las opciones en el catálogo (Datos simulados): "
                    f"{comparison_items}. ¿Cuál de estas opciones prefieres?"
                ),
            }

        selected = next((item for item in candidates if decision and item.sku == decision.selected_sku), None)
        if selected and _is_distinguished(state["consulta"], selected, candidates):
            unit_plural = plural.get(selected.unit, "unidades")
            price_text = f"{_format_cop(selected.price_cop)} COP por {selected.unit}"
            stock_text = (
                f"stock simulado: {selected.stock} {unit_plural}"
                if selected.stock
                else "agotado en el catálogo simulado"
            )
            if intent == "precio":
                disponibilidad = (
                    f"hay {selected.stock} {unit_plural} disponibles"
                    if selected.stock
                    else "actualmente está agotado"
                )
                respuesta = (
                    f"¡Con gusto! El precio de {selected.name} ({selected.variant}, SKU {selected.sku}) "
                    f"es {price_text} ({disponibilidad} — Datos simulados)."
                )
            elif intent == "existencias":
                if selected.stock:
                    respuesta = (
                        f"¡Claro! Tenemos {selected.stock} {unit_plural} disponibles de "
                        f"{selected.name} ({selected.variant}, SKU {selected.sku}), a {price_text} (Datos simulados)."
                    )
                else:
                    respuesta = (
                        f"En el momento {selected.name} ({selected.variant}, SKU {selected.sku}) está agotado "
                        f"(0 {unit_plural} disponibles; precio de referencia {price_text} — Datos simulados)."
                    )
            elif intent == "recomendacion":
                respuesta = (
                    f"Según nuestro catálogo, te recomiendo {selected.name} ({selected.variant}, SKU {selected.sku}): "
                    f"{price_text}; {stock_text} (Datos simulados)."
                )
            else:
                respuesta = (
                    f"¡Con gusto! {selected.name}, {selected.variant} (SKU {selected.sku}): "
                    f"{price_text}; {stock_text}. "
                    "Datos simulados; para una compra real se confirma en la ferretería."
                )
            return {**common, "estado": "found", "respuesta": respuesta}

        options = "; ".join(f"{item.name} {item.variant}" for item in candidates[:3])
        state_name = "model_invalid" if decision and not decision.valid_json else "clarify"
        if intent == "recomendacion":
            respuesta = (
                f"Para recomendarte la opción adecuada dentro del catálogo tenemos: {options}. "
                "¿Cuál medida o presentación necesitas?"
            )
        else:
            respuesta = (
                f"En el catálogo de demostración tenemos estas opciones: {options}. "
                "¿Cuál medida o presentación necesitas?"
            )
        return {**common, "estado": state_name, "respuesta": respuesta}

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
