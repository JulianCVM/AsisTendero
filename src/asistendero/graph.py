"""Flujo del entregable 1: Grok interpreta → herramienta de lectura → Grok resuelve."""

from collections.abc import Callable
import re
from typing import NotRequired, TypedDict
import unicodedata

from langgraph.graph import END, START, StateGraph

from asistendero.catalog import MockCatalog, Product, tokens
from asistendero.grok import Plan, Resolution, PROMPT_VERSION
from asistendero.search import ProductQuery


class Finding(TypedDict):
    query: str
    request: ProductQuery
    candidates: list[Product]
    nearby: list[Product]


class AgentState(TypedDict):
    consulta: str
    plan: NotRequired[Plan]
    hallazgos: NotRequired[list[Finding]]
    resolucion: NotRequired[Resolution]
    respuesta: NotRequired[str]
    estado: NotRequired[str]
    fuente: NotRequired[str]
    prompt_version: NotRequired[str]
    model_called: NotRequired[bool]
    model_calls: NotRequired[int]


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _is_distinguished(original: str, item_query: str, selected: Product, candidates: list[Product]) -> bool:
    """La variante debe estar respaldada por el mensaje original y por el item extraído."""
    original_tokens = tokens(original)
    item_tokens = tokens(item_query)
    variant_tokens = tokens(selected.variant)
    explicit_measures = re.findall(
        r"\b(\d+(?:/\d+)?)\s*(?:pulgada\w*|kg|kilo\w*)\b",
        _normalize_text(item_query),
    )
    if explicit_measures and not (set(explicit_measures) & variant_tokens):
        return False
    peers = [item for item in candidates if item.name == selected.name and item.sku != selected.sku]
    if not peers:
        # Para un producto único tampoco aceptamos una medida contradictoria.
        return not explicit_measures or bool(set(explicit_measures) & variant_tokens)
    unique_variant = variant_tokens - set().union(*(tokens(item.variant) for item in peers))
    return bool(unique_variant & original_tokens & item_tokens)


def _format_cop(value: int) -> str:
    return f"${value:,}".replace(",", ".")


def _join_options(options: list[str]) -> str:
    if len(options) < 2:
        return options[0] if options else ""
    return ", ".join(options[:-1]) + " y " + options[-1]


def _available_options(products: list[Product], plural: dict[str, str]) -> str:
    same_name = len({item.name for item in products}) == 1
    return _join_options([
        f"{'' if same_name else item.name + ' '}{item.variant} "
        f"({str(item.stock) + ' ' + plural.get(item.unit, 'unidades') + ' disponibles' if item.stock else 'agotado'})"
        for item in products
    ])


def _direct_response(original: str, plan: Plan) -> str:
    # La clasificación del modelo puede confundir «¿están atendiendo?» con un saludo.
    # Nunca afirmar apertura sin un horario verificado, aunque el intent sea erróneo.
    if plan.intent == "horario" or re.search(
        r"\b(atendiendo|atienden|atiende|abiert[oa]s?|cerrad[oa]s?|horario|abren|cierran)\b",
        _normalize_text(original),
    ):
        return ("No tengo un horario verificado de esta ferretería de demostración. "
                "Si me dices qué producto buscas, puedo revisar el catálogo de prueba contigo.")
    reply = plan.reply.strip()
    if not reply or len(reply) > 400 or re.search(r"\b(reservad|pagad|despachad|entregad)\w*\b", reply, re.I):
        return "Puedo ayudarte a consultar productos del catálogo de demostración. ¿Qué necesitas?"
    return reply


def _product_response(original: str, findings: list[Finding], resolution: Resolution) -> tuple[str, str]:
    lines = []
    statuses = []
    selected_products = []
    plural = {"metro": "metros", "unidad": "unidades", "bulto": "bultos", "galón": "galones"}
    for index, finding in enumerate(findings):
        candidates = finding["candidates"]
        nearby = finding["nearby"]
        sku = resolution.selected_skus[index] if index < len(resolution.selected_skus) else None
        selected = next((item for item in candidates if item.sku == sku), None)
        if not candidates and nearby:
            options = _available_options(nearby[:2], plural)
            category = nearby[0].name if len({item.name for item in nearby}) == 1 else "esa categoría"
            category = category[0].lower() + category[1:]
            requested_material = finding["request"].material
            material_differs = requested_material and all(
                not tokens(requested_material) <= tokens(f"{item.name} {item.variant}")
                for item in nearby
            )
            caveat = " Son de otro material; habría que confirmar si te sirven para ese uso." if material_differs else ""
            lines.append(
                f"No encontré {finding['query']} tal como lo pides. "
                f"De {category} sí aparecen {options}.{caveat} ¿Alguna de esas opciones te interesa?"
            )
            statuses.append("nearby")
        elif not candidates:
            lines.append(f"No encontré {finding['query']} en el catálogo de prueba. Si tienes otra referencia o medida, la reviso.")
            statuses.append("not_found")
        elif selected and _is_distinguished(original, finding["query"], selected, candidates):
            availability = f"{selected.stock} {plural.get(selected.unit, 'unidades')} disponibles" if selected.stock else "agotado"
            lines.append(f"Encontré {selected.name} ({selected.variant}, SKU {selected.sku}): "
                         f"{_format_cop(selected.price_cop)} COP por {selected.unit}; {availability}.")
            statuses.append("found")
            selected_products.append(selected)
        else:
            options = _available_options(candidates[:3], plural)
            category = candidates[0].name if len({item.name for item in candidates}) == 1 else finding["query"]
            lines.append(f"Para {category} veo {options}. ¿Qué medida o presentación necesitas?")
            statuses.append("clarify")
    status = "found" if all(s == "found" for s in statuses) else (
        statuses[0] if len(statuses) == 1 else "partial"
    )
    answer = ("Con gusto, esto encontré:\n" if len(lines) > 1 else "")
    answer += ("\n".join(f"• {line.removeprefix('Encontré ')}" for line in lines)
               if len(lines) > 1 else lines[0])
    answer += "\nSon datos de demostración."
    candidate_answer = resolution.answer.strip()
    # Usar la redacción de Grok solo si conserva todos los hechos comprobables.
    if statuses and all(s == "found" for s in statuses) and candidate_answer and len(candidate_answer) <= 1200:
        amounts = set(re.findall(r"\$[\d.,]+", candidate_answer))
        allowed_amounts = {_format_cop(item.price_cop) for item in selected_products}
        forbidden = re.search(r"\b(reservad|pagad|entregad|abiert|cerrad|descuent|compatib)\w*\b", candidate_answer, re.I)
        grounded = (
            not forbidden
            and "simulad" in _normalize_text(candidate_answer)
            and amounts == allowed_amounts
            and set(re.findall(r"\b[A-Z]{2,5}-[A-Z0-9-]+\b", candidate_answer))
                <= {item.sku for item in selected_products}
            and all(
                any(
                    _normalize_text(item.name) in _normalize_text(line)
                    and _normalize_text(item.variant) in _normalize_text(line)
                    and f"{_format_cop(item.price_cop)} COP" in line
                    and (
                        item.stock == 0 and "agotad" in _normalize_text(line)
                        or item.stock > 0 and re.search(
                            rf"\b{item.stock}\s+{plural.get(item.unit, 'unidades')}\b",
                            _normalize_text(line),
                        )
                    )
                    for line in candidate_answer.splitlines()
                )
                for item in selected_products
            )
        )
        if grounded:
            answer = candidate_answer
    return status, answer


def build_graph(
    catalog: MockCatalog,
    planner: Callable[[str], Plan],
    resolver: Callable[[str, list[Finding]], Resolution],
):
    def validate(state: AgentState) -> dict:
        message = state["consulta"].strip()
        if not message:
            raise ValueError("La consulta no puede estar vacía.")
        if len(message) > 2000:
            raise ValueError("La consulta supera el límite de 2000 caracteres.")
        return {"consulta": message}

    def interpret(state: AgentState) -> dict:
        plan = planner(state["consulta"])
        return {"plan": plan, "model_called": True, "model_calls": 1}

    def route(state: AgentState) -> str:
        return "retrieve" if state["plan"].action == "search_products" else "respond"

    def retrieve(state: AgentState) -> dict:
        findings: list[Finding] = []
        for item in state["plan"].items:
            request = item.grounded(state["consulta"], tokens)
            result = catalog.search(request)
            findings.append({
                "query": request.text, "request": request,
                "candidates": list(result.matches), "nearby": list(result.nearby),
            })
        return {"hallazgos": findings, "fuente": "mock_sqlite"}

    def respond(state: AgentState) -> dict:
        common = {"prompt_version": PROMPT_VERSION, "model_called": True}
        plan = state["plan"]
        if plan.action == "respond":
            return {
                **common,
                "model_calls": 1,
                "estado": "model_invalid" if not plan.valid_json else "answered",
                "respuesta": _direct_response(state["consulta"], plan),
            }
        findings = state["hallazgos"]
        resolution = resolver(state["consulta"], findings)
        status, answer = _product_response(state["consulta"], findings, resolution)
        return {
            **common,
            "model_calls": 2,
            "resolucion": resolution,
            "estado": status if resolution.valid_json else "model_invalid",
            "respuesta": answer,
        }

    builder = StateGraph(AgentState)
    builder.add_node("validate", validate)
    builder.add_node("interpret", interpret)
    builder.add_node("retrieve", retrieve)
    builder.add_node("respond", respond)
    builder.add_edge(START, "validate")
    builder.add_edge("validate", "interpret")
    builder.add_conditional_edges("interpret", route, {"retrieve": "retrieve", "respond": "respond"})
    builder.add_edge("retrieve", "respond")
    builder.add_edge("respond", END)
    return builder.compile()
