"""Lectura de lo que devuelven las herramientas y de lo que Grok ve de ellas.

El grafo no conoce la base de datos: recibe ``tool_executor(name, arguments) -> dict`` y espera
el sobre común ``{"status", "data", "error", "source", "observed_at"}``. Formas de ``data`` que
lee este módulo (si cambian, solo hay que ajustar ``search_findings`` y ``latest_quote``):

- buscar_productos: ``{"results": [{"matches": [producto], "nearby": [producto]}]}``, un
  resultado por artículo en el orden de ``items``.
- consultar_disponibilidad: ``{"sku", "stock", "unit", "restock", ...}``; ``restock`` es el surtido
  (``restock.py``).
- calcular_cotizacion_informativa: ``{"lines": [{"sku", "quantity", "unit_price_cop",
  "subtotal_cop", ...}], "total_cop", "reservation_created": false}``.
- consultar_info_tienda: ``{"tema", "texto"}``; con ``tema="horario"``: ``{"dias": {día: [abre,
  cierra] | None}, "festivos", "zona_horaria", "ahora", "dia_actual", "abierto_ahora"}``.
- explorar_categoria: ``{"categorias": [{"categoria", "variantes", "con_existencias"}]}`` o
  ``{"categoria", "productos": [{"nombre", "variantes", "con_existencias"}]}``, sin precios.
- registrar_pedido, confirmar_pedido, agendar_recogida y cancelar_pedido: un pedido ``{"pedido", "estado",
  "lineas": [{"sku", "nombre", "variante", "unidad", "cantidad", "precio_unitario_cop", "subtotal_cop"}],
  "total_cop", "aparta_hasta", "recogida", "nota", "creado", "pago"}`` (``orders.OrderBook``);
  consultar_pedido: ``{"pedidos": [pedido]}``. ``order_results`` los lee.

``producto`` usa los campos de ``catalog.Product``, con ``restock`` (el surtido) opcional.
"""

from collections.abc import Callable
from datetime import datetime, timezone
from typing import TypedDict

from asistendero.catalog import Product


ToolExecutor = Callable[[str, dict], dict]


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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def error_envelope(status: str, code: str, message: str, source: str) -> dict:
    return {"status": status, "data": None, "error": {"code": code, "message": message},
            "source": source, "observed_at": _now()}


def _product(raw: object) -> Product | None:
    if not isinstance(raw, dict):
        return None
    # «restock» tiene valor por omisión: una respuesta sin surtido (base de S2) sigue siendo un producto.
    try:
        product = Product(**{field: raw[field] for field in Product.__dataclass_fields__
                             if field in raw or field != "restock"})
    except (KeyError, TypeError):
        return None
    if not isinstance(product.price_cop, int) or not isinstance(product.stock, int) or not isinstance(product.restock, str):
        return None
    return product


def search_findings(calls: list[ToolCall]) -> list[Finding]:
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


def availability_by_sku(calls: list[ToolCall]) -> dict[str, dict]:
    result = {}
    for call in calls:
        if call["requested_tool"] == "consultar_disponibilidad" and call["response"]["status"] == "ok":
            data = call["response"].get("data")
            if isinstance(data, dict) and isinstance(data.get("stock"), int):
                result[call["arguments"]["sku"]] = data
    return result


def store_info_by_topic(calls: list[ToolCall]) -> dict[str, dict]:
    """Última respuesta válida de consultar_info_tienda por tema."""
    result = {}
    for call in calls:
        if call["requested_tool"] == "consultar_info_tienda" and call["response"]["status"] == "ok":
            data = call["response"].get("data")
            if isinstance(data, dict) and isinstance(data.get("tema"), str):
                result[data["tema"]] = data
    return result


def category_listings(calls: list[ToolCall]) -> list[dict]:
    """Respuestas válidas de explorar_categoria, en orden."""
    listings = []
    for call in calls:
        if call["requested_tool"] == "explorar_categoria" and call["response"]["status"] == "ok":
            data = call["response"].get("data")
            if isinstance(data, dict) and (isinstance(data.get("categorias"), list) or isinstance(data.get("productos"), list)):
                listings.append(data)
    return listings


ORDER_TOOLS_DATA = ("registrar_pedido", "confirmar_pedido", "agendar_recogida", "cancelar_pedido", "consultar_pedido")


def _valid_order(order: object) -> bool:
    return (
        isinstance(order, dict) and isinstance(order.get("pedido"), str) and isinstance(order.get("estado"), str)
        and isinstance(order.get("total_cop"), int) and isinstance(order.get("lineas"), list)
        and all(isinstance(line, dict) and isinstance(line.get("sku"), str)
                and all(isinstance(line.get(key), int) for key in ("cantidad", "precio_unitario_cop", "subtotal_cop"))
                for line in order["lineas"])
    )


def order_results(calls: list[ToolCall]) -> list[tuple[str, dict]]:
    """(herramienta, pedido) de cada respuesta válida de pedidos, en orden; consultar_pedido aporta varios."""
    results = []
    for call in calls:
        if call["requested_tool"] not in ORDER_TOOLS_DATA or call["response"].get("status") != "ok":
            continue
        data = call["response"].get("data") or {}
        orders = data.get("pedidos") if call["requested_tool"] == "consultar_pedido" else [data]
        results.extend((call["requested_tool"], order) for order in orders or [] if _valid_order(order))
    return results


def latest_quote(calls: list[ToolCall]) -> tuple[dict | None, ToolCall | None]:
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
        return None, {**call, "response": error_envelope("error", "TOOL_FAILURE", "Cotización con formato inválido.", "agent_validation")}
    return None, None


def execute_safely(tool_executor: ToolExecutor, name: str, arguments: dict) -> dict:
    try:
        response = tool_executor(name, arguments)
    except Exception as exc:
        return error_envelope("error", "TOOL_FAILURE", f"La herramienta falló ({type(exc).__name__}).", "agent_validation")
    if not isinstance(response, dict) or response.get("status") not in {"ok", "error"}:
        return error_envelope("error", "TOOL_FAILURE", "Respuesta de herramienta con formato inválido.", "agent_validation")
    if response["status"] == "ok" and not isinstance(response.get("data"), dict):
        return error_envelope("error", "TOOL_FAILURE", "Respuesta de herramienta sin datos.", "agent_validation")
    if response["status"] == "error" and not isinstance((response.get("error") or {}).get("code"), str):
        return error_envelope("error", "TOOL_FAILURE", "Error de herramienta sin código.", "agent_validation")
    return response


MODEL_MATCH_FIELDS = ("sku", "name", "variant", "price_cop", "stock", "unit", "restock")
MODEL_AVAILABILITY_FIELDS = ("sku", "name", "variant", "unit", "stock", "restock")


def _model_match(product: Product) -> dict:
    return {
        "sku": product.sku,
        "name": product.name,
        "variant": product.variant,
        "price_cop": product.price_cop,
        "stock": product.stock,
        "unit": product.unit,
        "restock": product.restock,
    }


def observation_for_model(call: ToolCall) -> dict:
    """Lo que Grok ve de cada llamada: solo los atributos de razonamiento y nearby sin precio."""
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
                "matches": [_model_match(p) for p in finding["matches"]],
                "nearby": [{"sku": p.sku, "name": p.name, "variant": p.variant, "stock": p.stock}
                           for p in finding["nearby"]],
            }
            for finding in search_findings([call])
        ]}
    elif call["requested_tool"] == "consultar_disponibilidad" and isinstance(data, dict):
        data = {key: data[key] for key in MODEL_AVAILABILITY_FIELDS if key in data}
    observation["datos"] = data
    return observation
