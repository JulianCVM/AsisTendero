"""Flujo S2: Grok decide → el servidor valida y ejecuta la herramienta → respuesta verificada.

El grafo no conoce la base de datos: recibe ``tool_executor(name, arguments) -> dict`` y espera
el sobre común ``{"status", "data", "error", "source", "observed_at"}``. Formas de ``data`` que
lee este módulo (si cambian, solo hay que ajustar ``_findings`` y ``_quote``):

- buscar_productos: ``{"results": [{"matches": [producto], "nearby": [producto]}]}``, un
  resultado por artículo en el orden de ``items``.
- consultar_disponibilidad: ``{"sku", "stock", "unit", ...}``.
- calcular_cotizacion_informativa: ``{"lines": [{"sku", "quantity", "unit_price_cop",
  "subtotal_cop", ...}], "total_cop", "reservation_created": false}``.

``producto`` usa los campos de ``catalog.Product``.
"""

from collections.abc import Callable
from datetime import datetime, timezone
import json
import re
from time import perf_counter
from typing import NotRequired, TypedDict
import unicodedata

from langgraph.graph import END, START, StateGraph

from asistendero.catalog import Product, tokens
from asistendero.grok import MAX_ARGUMENT_CHARS, MAX_ITEMS, PROMPT_VERSION, TOOL_NAMES, Decision, ModelError
from asistendero.search import ProductQuery


ToolExecutor = Callable[[str, dict], dict]
Planner = Callable[[str, list[dict], int], Decision]

MAX_TOOL_CALLS = 6
MAX_QUANTITY = 1000
QUERY_FIELDS = ("product", "use", "material", "measure", "presentation", "color", "brand")
SKU_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,31}$")
PLURAL = {"metro": "metros", "unidad": "unidades", "bulto": "bultos", "galón": "galones"}
NUMBER_WORDS = {
    "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "quince": 15, "veinte": 20,
}
# Una afirmación de acción ejecutada, descuento o equivalencia invalida la redacción de Grok.
FORBIDDEN_CLAIMS = re.compile(
    r"\b(reservad|apartad|pagad|despachad|entregad|facturad|descuent|compatib|equivalen|abiert|cerrad)\w*"
    r"|\bpedido\s+(?:creado|registrado|confirmado|listo)",
    re.I,
)


class Finding(TypedDict):
    query: str
    request: dict
    matches: list[Product]
    nearby: list[Product]


class ToolCall(TypedDict):
    step: int
    requested_tool: str
    requested_arguments: dict | None
    executed: bool
    arguments: dict | None
    response: dict
    duration_ms: int


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


class _Rejected(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _error_envelope(status: str, code: str, message: str, source: str) -> dict:
    return {"status": status, "data": None, "error": {"code": code, "message": message},
            "source": source, "observed_at": _now()}


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


def _quantities_in_message(message: str) -> set[int]:
    """Cantidades que el cliente expresó; excluye medidas como 1/2, 50 kg o 2 pulgadas."""
    text = re.sub(r"\d+\s*/\s*\d+", " ", _normalize_text(message))
    measure = r"(?!\s*(?:pulgad|kg|kilo|v\b|mm|cm|\"|x\b|×))"
    found = {int(value) for value in re.findall(rf"\b(\d{{1,4}})\b{measure}", text)}
    found |= {
        NUMBER_WORDS[word]
        for word in re.findall(rf"\b({'|'.join(NUMBER_WORDS)})\b{measure}", text)
    }
    return found


def _product(raw: object) -> Product | None:
    if not isinstance(raw, dict):
        return None
    try:
        product = Product(**{field: raw[field] for field in Product.__dataclass_fields__})
    except (KeyError, TypeError):
        return None
    if not isinstance(product.price_cop, int) or not isinstance(product.stock, int):
        return None
    return product


def _findings(calls: list[ToolCall]) -> list[Finding]:
    findings: list[Finding] = []
    for call in calls:
        if call["requested_tool"] != "buscar_productos" or call["response"]["status"] != "ok":
            continue
        results = (call["response"].get("data") or {}).get("results")
        items = call["arguments"]["items"]
        if not isinstance(results, list):
            continue
        for item, result in zip(items, results):
            if not isinstance(result, dict):
                continue
            findings.append({
                "query": item["text"],
                "request": item,
                "matches": [p for p in map(_product, result.get("matches") or []) if p],
                "nearby": [p for p in map(_product, result.get("nearby") or []) if p],
            })
    return findings


def _grounded_selection(message: str, finding: Finding) -> Product | None:
    """Única variante de matches que el mensaje permite elegir sin preguntar."""
    chosen = [
        product for product in finding["matches"]
        if product.sku.casefold() in message.casefold()
        or _is_distinguished(message, finding["query"], product, finding["matches"])
    ]
    return chosen[0] if len(chosen) == 1 else None


def _grounded_products(message: str, calls: list[ToolCall]) -> dict[str, Product]:
    selected = {}
    for finding in _findings(calls):
        product = _grounded_selection(message, finding)
        if product:
            selected[product.sku] = product
    return selected


def _availability(calls: list[ToolCall]) -> dict[str, dict]:
    result = {}
    for call in calls:
        if call["requested_tool"] == "consultar_disponibilidad" and call["response"]["status"] == "ok":
            data = call["response"].get("data")
            if isinstance(data, dict) and isinstance(data.get("stock"), int):
                result[call["arguments"]["sku"]] = data
    return result


def _quote(calls: list[ToolCall]) -> tuple[dict | None, ToolCall | None]:
    """Última cotización ejecutada: (datos válidos, llamada) o (None, llamada con error)."""
    for call in reversed(calls):
        if call["requested_tool"] != "calcular_cotizacion_informativa" or not call["executed"]:
            continue
        data = call["response"].get("data")
        if call["response"]["status"] != "ok":
            return None, call
        lines = data.get("lines") if isinstance(data, dict) else None
        if (
            isinstance(lines, list) and lines and isinstance(data.get("total_cop"), int)
            and data.get("reservation_created") is False
            and all(
                isinstance(line, dict)
                and all(isinstance(line.get(key), int) for key in ("quantity", "unit_price_cop", "subtotal_cop"))
                and isinstance(line.get("sku"), str)
                for line in lines
            )
        ):
            return data, call
        return None, {**call, "response": _error_envelope("error", "TOOL_FAILURE", "Cotización con formato inválido.", "agent_validation")}
    return None, None


def _validate_request(name: str | None, arguments: object, message: str, calls: list[ToolCall]) -> dict:
    """Devuelve los argumentos que efectivamente recibirá el ejecutor o rechaza la solicitud."""
    if name not in TOOL_NAMES:
        raise _Rejected("UNKNOWN_TOOL", "Herramienta fuera de la lista permitida.")
    if not isinstance(arguments, dict):
        raise _Rejected("INVALID_ARGUMENT", "Los argumentos deben ser un objeto.")
    if len(json.dumps(arguments, ensure_ascii=False)) > MAX_ARGUMENT_CHARS:
        raise _Rejected("INVALID_ARGUMENT", "Los argumentos superan el límite de longitud.")

    if name == "buscar_productos":
        items = arguments.get("items")
        if set(arguments) != {"items"} or not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS:
            raise _Rejected("INVALID_ARGUMENT", f"Se requieren de 1 a {MAX_ITEMS} artículos en items.")
        clean = []
        for item in items:
            # quantity se tolera porque Grok la extrae con el artículo, pero la búsqueda no la usa.
            if not isinstance(item, dict) or not set(item) <= {"text", "quantity", *QUERY_FIELDS}:
                raise _Rejected("INVALID_ARGUMENT", "Artículo con campos no permitidos.")
            text = item.get("text")
            if not isinstance(text, str) or not text.strip() or len(text) > 180:
                raise _Rejected("INVALID_ARGUMENT", "Cada artículo necesita un texto breve.")
            fields = {}
            for field in QUERY_FIELDS:
                value = item.get(field)
                if value is not None:
                    if not isinstance(value, str) or not value.strip() or len(value) > 80:
                        raise _Rejected("INVALID_ARGUMENT", f"Atributo {field} inválido.")
                    fields[field] = value.strip()
            query = ProductQuery(text.strip(), **fields).grounded(message, tokens)
            clean.append({key: value for key, value in vars(query).items() if value is not None})
        return {"items": clean}

    grounded = _grounded_products(message, calls)
    if name == "consultar_disponibilidad":
        sku = arguments.get("sku")
        if set(arguments) != {"sku"} or not isinstance(sku, str) or not SKU_PATTERN.match(sku):
            raise _Rejected("INVALID_ARGUMENT", "Se requiere un SKU válido.")
        if sku not in grounded:
            raise _Rejected("SKU_NOT_GROUNDED", "El SKU no es una coincidencia que el mensaje distinga; pregunta al cliente.")
        return {"sku": sku}

    lines = arguments.get("lines")
    if set(arguments) != {"lines"} or not isinstance(lines, list) or not 1 <= len(lines) <= MAX_ITEMS:
        raise _Rejected("INVALID_ARGUMENT", f"Se requieren de 1 a {MAX_ITEMS} líneas.")
    allowed_quantities = _quantities_in_message(message)
    clean_lines = []
    for line in lines:
        if not isinstance(line, dict) or set(line) != {"sku", "quantity"}:
            raise _Rejected("INVALID_ARGUMENT", "Cada línea lleva solo sku y quantity.")
        sku, quantity = line["sku"], line["quantity"]
        if not isinstance(sku, str) or not SKU_PATTERN.match(sku):
            raise _Rejected("INVALID_ARGUMENT", "Se requiere un SKU válido.")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= MAX_QUANTITY:
            raise _Rejected("INVALID_QUANTITY", f"La cantidad debe ser un entero de 1 a {MAX_QUANTITY}.")
        if sku not in grounded:
            raise _Rejected("SKU_NOT_GROUNDED", "El SKU no es una coincidencia que el mensaje distinga; pregunta al cliente.")
        if quantity not in allowed_quantities:
            raise _Rejected("QUANTITY_NOT_GROUNDED", "El cliente no expresó esa cantidad; pregúntala.")
        if any(previous["sku"] == sku for previous in clean_lines):
            raise _Rejected("INVALID_ARGUMENT", "SKU repetido en la cotización.")
        clean_lines.append({"sku": sku, "quantity": quantity})
    return {"lines": clean_lines}


def _execute(tool_executor: ToolExecutor, name: str, arguments: dict) -> dict:
    try:
        response = tool_executor(name, arguments)
    except Exception as exc:
        return _error_envelope("error", "TOOL_FAILURE", f"La herramienta falló ({type(exc).__name__}).", "agent_validation")
    if not isinstance(response, dict) or response.get("status") not in {"ok", "error"}:
        return _error_envelope("error", "TOOL_FAILURE", "Respuesta de herramienta con formato inválido.", "agent_validation")
    if response["status"] == "ok" and not isinstance(response.get("data"), dict):
        return _error_envelope("error", "TOOL_FAILURE", "Respuesta de herramienta sin datos.", "agent_validation")
    if response["status"] == "error" and not isinstance((response.get("error") or {}).get("code"), str):
        return _error_envelope("error", "TOOL_FAILURE", "Error de herramienta sin código.", "agent_validation")
    return response


def observation_for_model(call: ToolCall) -> dict:
    """Lo que Grok ve de cada llamada: nearby nunca lleva precio."""
    response = call["response"]
    observation = {
        "herramienta": call["requested_tool"],
        "argumentos": call["arguments"] if call["executed"] else call["requested_arguments"],
        "estado": "rechazada" if response["status"] == "rejected" else response["status"],
    }
    if response["status"] != "ok":
        observation["error"] = response["error"]
        return observation
    data = response["data"]
    if call["requested_tool"] == "buscar_productos":
        data = {"results": [
            {
                "matches": [vars(p) for p in finding["matches"]],
                "nearby": [{"sku": p.sku, "name": p.name, "variant": p.variant, "stock": p.stock}
                           for p in finding["nearby"]],
            }
            for finding in _findings([call])
        ]}
    observation["datos"] = data
    return observation


def _format_cop(value: int) -> str:
    return f"${value:,}".replace(",", ".")


def _units(unit: str, amount: int) -> str:
    return unit if amount == 1 else PLURAL.get(unit, "unidades")


def _join_options(options: list[str]) -> str:
    if len(options) < 2:
        return options[0] if options else ""
    return ", ".join(options[:-1]) + " y " + options[-1]


def _available_options(products: list[Product]) -> str:
    same_name = len({item.name for item in products}) == 1
    return _join_options([
        f"{'' if same_name else item.name + ' '}{item.variant} "
        f"({str(item.stock) + ' ' + _units(item.unit, item.stock) + ' disponibles' if item.stock else 'agotado'})"
        for item in products
    ])


def _direct_response(original: str, decision: Decision) -> str:
    # La clasificación del modelo puede confundir «¿están atendiendo?» con un saludo.
    # Nunca afirmar apertura sin un horario verificado, aunque el intent sea erróneo.
    if decision.intent == "horario" or re.search(
        r"\b(atendiendo|atienden|atiende|abiert[oa]s?|cerrad[oa]s?|horario|abren|cierran)\b",
        _normalize_text(original),
    ):
        return ("No tengo un horario verificado de esta ferretería de demostración. "
                "Si me dices qué producto buscas, puedo revisar el catálogo de prueba contigo.")
    reply = decision.reply.strip()
    # Sin herramientas no hay precio ni existencias comprobadas que se puedan afirmar.
    if (
        not reply or len(reply) > 400 or FORBIDDEN_CLAIMS.search(reply) or "$" in reply
        or re.search(r"\b\d+\s+(metro|bulto|unidad|galon)", _normalize_text(reply))
    ):
        return "Puedo ayudarte a consultar productos del catálogo de demostración. ¿Qué necesitas?"
    return reply


def _render(message: str, calls: list[ToolCall]) -> tuple[str, str]:
    """Respuesta determinista construida solo con lo que devolvieron las herramientas."""
    findings = _findings(calls)
    if not findings:
        if any(call["response"]["status"] == "error" for call in calls):
            return "tool_error", ("No pude consultar el catálogo de demostración en este momento, así que no "
                                  "tengo precios ni existencias verificados. Intenta de nuevo en unos minutos.")
        return "not_verified", ("No pude verificar ese producto en el catálogo de demostración. "
                                "¿Me dices qué producto y qué medida buscas?")

    availability = _availability(calls)
    lines, statuses, products = [], [], {}
    for finding in findings:
        matches, nearby = finding["matches"], finding["nearby"]
        for product in matches + nearby:
            products[product.sku] = product
        selected = _grounded_selection(message, finding) if matches else None
        if not matches and nearby:
            category = nearby[0].name if len({item.name for item in nearby}) == 1 else "esa categoría"
            category = category[0].lower() + category[1:]
            material = finding["request"].get("material")
            material_differs = material and all(
                not tokens(material) <= tokens(f"{item.name} {item.variant}") for item in nearby
            )
            caveat = " Son de otro material; habría que confirmar si te sirven para ese uso." if material_differs else ""
            lines.append(f"No encontré {finding['query']} tal como lo pides. De {category} sí aparecen "
                         f"{_available_options(nearby[:2])}, que no son lo mismo.{caveat} ¿Alguna de esas opciones te interesa?")
            statuses.append("nearby")
        elif not matches:
            lines.append(f"No encontré {finding['query']} en el catálogo de prueba. Si tienes otra referencia o medida, la reviso.")
            statuses.append("not_found")
        elif selected:
            stock = availability.get(selected.sku, {}).get("stock", selected.stock)
            state = f"{stock} {_units(selected.unit, stock)} disponibles" if stock else "agotado"
            lines.append(f"Encontré {selected.name} ({selected.variant}, SKU {selected.sku}): "
                         f"{_format_cop(selected.price_cop)} COP por {selected.unit}; {state}.")
            statuses.append("found")
        else:
            category = matches[0].name if len({item.name for item in matches}) == 1 else finding["query"]
            lines.append(f"Para {category} veo {_available_options(matches[:3])}. ¿Qué medida o presentación necesitas?")
            statuses.append("clarify")

    status = "found" if all(s == "found" for s in statuses) else (statuses[0] if len(statuses) == 1 else "partial")
    answer = ("Con gusto, esto encontré:\n" if len(lines) > 1 else "")
    answer += ("\n".join(f"• {line.removeprefix('Encontré ')}" for line in lines) if len(lines) > 1 else lines[0])

    quote, quote_call = _quote(calls)
    if quote:
        quote_lines = []
        for line in quote["lines"]:
            product = products.get(line["sku"])
            label = f"{product.name} {product.variant}" if product else f"SKU {line['sku']}"
            unit = product.unit if product else "unidad"
            quote_lines.append(f"• {line['quantity']} {_units(unit, line['quantity'])} de {label}: "
                               f"{_format_cop(line['unit_price_cop'])} COP c/u → {_format_cop(line['subtotal_cop'])} COP")
        answer += ("\nCotización informativa:\n" + "\n".join(quote_lines)
                   + f"\nTotal informativo: {_format_cop(quote['total_cop'])} COP. No es un pedido ni una reserva.")
        if status == "found":
            status = "quoted"
    elif quote_call:
        error = quote_call["response"]["error"]
        if error["code"] == "INSUFFICIENT_STOCK":
            short = []
            for line in quote_call["arguments"]["lines"]:
                product = products.get(line["sku"])
                stock = availability.get(line["sku"], {}).get("stock", product.stock if product else None)
                if product and stock is not None and line["quantity"] > stock:
                    short.append(f"pides {line['quantity']} {_units(product.unit, line['quantity'])} de "
                                 f"{product.name} ({product.variant}) y hay {stock} {_units(product.unit, stock)} disponibles")
            detail = "; ".join(short) if short else "la cantidad pedida supera las existencias"
            answer += f"\nNo alcanza para cotizar: {detail}. ¿Quieres que cotice una cantidad menor?"
            status = "insufficient_stock"
        else:
            answer += "\nNo pude calcular la cotización en este momento; los datos anteriores sí vienen del catálogo."
            status = "quote_error"
    return status, answer + "\nSon datos de demostración."


def _reply_is_grounded(reply: str, message: str, calls: list[ToolCall]) -> bool:
    """La redacción de Grok solo se usa si cada cifra sale de una observación de esta ejecución."""
    if not reply or len(reply) > 1200 or FORBIDDEN_CLAIMS.search(reply):
        return False
    normalized = _normalize_text(reply)
    if not re.search(r"simulad|demostracion|fictici|de prueba", normalized):
        return False
    findings = _findings(calls)
    selected = _grounded_products(message, calls)
    availability = _availability(calls)
    quote, quote_call = _quote(calls)
    allowed_amounts = {_format_cop(p.price_cop) for p in selected.values()}
    allowed_counts = {p.stock for f in findings for p in f["matches"] + f["nearby"]}
    allowed_counts |= {data["stock"] for data in availability.values()}
    allowed_skus = {p.sku for f in findings for p in f["matches"] + f["nearby"]}
    if quote:
        allowed_amounts |= {_format_cop(quote["total_cop"])}
        for line in quote["lines"]:
            allowed_amounts |= {_format_cop(line["unit_price_cop"]), _format_cop(line["subtotal_cop"])}
            allowed_counts.add(line["quantity"])
        if _format_cop(quote["total_cop"]) not in reply:
            return False
    elif quote_call:
        allowed_counts |= {line["quantity"] for line in quote_call["arguments"]["lines"]}
    if not set(re.findall(r"\$[\d.,]*\d", reply)) <= allowed_amounts:
        return False
    if not set(re.findall(r"\b[A-Z]{2,5}-[A-Z0-9-]+\b", reply)) <= allowed_skus:
        return False
    counts = re.findall(r"\b(\d+)\s+(?:metros?|bultos?|unidad(?:es)?|galon(?:es)?)\b", normalized)
    if any(int(count) not in allowed_counts for count in counts):
        return False
    # Cada producto elegido debe aparecer con su precio y su estado real.
    for product in selected.values():
        stock = availability.get(product.sku, {}).get("stock", product.stock)
        if _format_cop(product.price_cop) not in reply:
            return False
        if stock == 0 and "agotad" not in normalized:
            return False
        if stock > 0 and not re.search(rf"\b{stock}\s+{_normalize_text(_units(product.unit, stock))}\b", normalized):
            return False
    return True


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
            arguments = _validate_request(decision.tool, decision.arguments, state["consulta"], calls)
            if any(previous["executed"] and previous["requested_tool"] == decision.tool
                   and previous["arguments"] == arguments for previous in calls):
                raise _Rejected("DUPLICATE_CALL", "Esa llamada ya se ejecutó; usa su observación.")
        except _Rejected as exc:
            call["response"] = _error_envelope("rejected", exc.code, str(exc), "agent_validation")
        else:
            call.update(executed=True, arguments=arguments, response=_execute(tool_executor, decision.tool, arguments))
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
                _, answer = _render(message, calls)
            elif estado == "model_invalid":
                answer = "No pude interpretar bien tu mensaje. ¿Puedes contarme de nuevo qué producto necesitas?"
            else:
                answer = ("No pude completar la consulta con el asistente en este momento, así que no tengo "
                          "precios ni existencias verificados. Intenta de nuevo en unos minutos.")
            return {**common, "estado": estado, "error": error, "respuesta": answer}

        if not calls:
            return {**common, "estado": "answered", "respuesta": _direct_response(message, decision)}
        status, answer = _render(message, calls)
        if _reply_is_grounded(decision.reply, message, calls):
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
