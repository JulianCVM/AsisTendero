"""Herramientas del servidor que Grok puede solicitar sobre el catálogo ficticio."""

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import sqlite3

from asistendero.catalog import MockCatalog, tokens
from asistendero.grok import MAX_ARGUMENT_CHARS, MAX_ITEMS, STORE_TOPICS, TOOL_NAMES
from asistendero.observations import error_envelope
from asistendero.search import ProductQuery
from asistendero.validation import MAX_QUANTITY, QUERY_FIELDS, SKU_PATTERN


SOURCE = "mock_sqlite"
MAX_TEXT_CHARS = 180
MAX_FIELD_CHARS = 80
MAX_CATEGORY_CHARS = 60
# Colombia no cambia de hora en el año: un desfase fijo evita depender de tzdata en Windows.
BOGOTA = timezone(timedelta(hours=-5), "America/Bogota")
WEEKDAYS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")


class _ToolError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _ok(data: dict) -> dict:
    return {
        "status": "ok",
        "data": data,
        "error": None,
        "source": SOURCE,
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }


def _validate_sku(value: object) -> str:
    if not isinstance(value, str) or not SKU_PATTERN.match(value):
        raise _ToolError("INVALID_ARGUMENT", "Se requiere un SKU válido.")
    return value


def _validate_quantity(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= MAX_QUANTITY:
        raise _ToolError("INVALID_QUANTITY", f"La cantidad debe ser un entero de 1 a {MAX_QUANTITY}.")
    return value


def _search_products(arguments: dict, catalog: MockCatalog) -> dict:
    items = arguments.get("items")
    if set(arguments) != {"items"} or not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS:
        raise _ToolError("INVALID_ARGUMENT", f"Se requieren de 1 a {MAX_ITEMS} artículos en items.")

    queries: list[ProductQuery] = []
    for item in items:
        if not isinstance(item, dict) or not set(item) <= {"text", *QUERY_FIELDS}:
            raise _ToolError("INVALID_ARGUMENT", "Artículo con campos no permitidos.")
        text = item.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_CHARS:
            raise _ToolError("INVALID_ARGUMENT", "Cada artículo necesita un texto breve.")
        fields: dict[str, str] = {}
        for field in QUERY_FIELDS:
            value = item.get(field)
            if value is not None:
                if not isinstance(value, str) or not value.strip() or len(value) > MAX_FIELD_CHARS:
                    raise _ToolError("INVALID_ARGUMENT", f"Atributo {field} inválido.")
                fields[field] = value.strip()
        queries.append(ProductQuery(text=text.strip(), **fields))

    results = []
    for query in queries:
        found = catalog.search(query)
        results.append({
            "matches": [asdict(product) for product in found.matches],
            "nearby": [asdict(product) for product in found.nearby],
        })
    return _ok({"results": results})


def _check_availability(arguments: dict, catalog: MockCatalog) -> dict:
    if set(arguments) != {"sku"}:
        raise _ToolError("INVALID_ARGUMENT", "consultar_disponibilidad solo acepta el campo sku.")
    sku = _validate_sku(arguments.get("sku"))
    product = catalog.get(sku)
    if product is None:
        raise _ToolError("NOT_FOUND", f"No existe el SKU {sku} en el catálogo de esta sede.")
    return _ok({
        "sku": product.sku,
        "name": product.name,
        "variant": product.variant,
        "unit": product.unit,
        "stock": product.stock,
        "updated_at": product.updated_at,
    })


def _calculate_quote(arguments: dict, catalog: MockCatalog) -> dict:
    lines = arguments.get("lines")
    if set(arguments) != {"lines"} or not isinstance(lines, list) or not 1 <= len(lines) <= MAX_ITEMS:
        raise _ToolError("INVALID_ARGUMENT", f"Se requieren de 1 a {MAX_ITEMS} líneas.")

    validated: list[tuple[str, int]] = []
    seen_skus: set[str] = set()
    for line in lines:
        if not isinstance(line, dict) or set(line) != {"sku", "quantity"}:
            raise _ToolError("INVALID_ARGUMENT", "Cada línea lleva solo sku y quantity.")
        sku = _validate_sku(line.get("sku"))
        quantity = _validate_quantity(line.get("quantity"))
        if sku in seen_skus:
            raise _ToolError("INVALID_ARGUMENT", "SKU repetido en la cotización.")
        seen_skus.add(sku)
        validated.append((sku, quantity))

    quote_lines = []
    for sku, quantity in validated:
        product = catalog.get(sku)
        if product is None:
            raise _ToolError("NOT_FOUND", f"No existe el SKU {sku} en el catálogo de esta sede.")
        if quantity > product.stock:
            raise _ToolError(
                "INSUFFICIENT_STOCK",
                f"Existencias insuficientes para {sku}: solicitadas {quantity}, disponibles {product.stock}.",
            )
        subtotal = product.price_cop * quantity
        quote_lines.append({
            "sku": product.sku,
            "name": product.name,
            "variant": product.variant,
            "unit": product.unit,
            "quantity": quantity,
            "unit_price_cop": product.price_cop,
            "subtotal_cop": subtotal,
        })

    return _ok({
        "lines": quote_lines,
        "total_cop": sum(item["subtotal_cop"] for item in quote_lines),
        "currency": "COP",
        "reservation_created": False,
    })


def local_now() -> datetime:
    """Hora local de la tienda; las pruebas la reemplazan para fijar el día y la hora."""
    return datetime.now(BOGOTA)


def _store_info(arguments: dict, catalog: MockCatalog) -> dict:
    topic = arguments.get("tema")
    if set(arguments) != {"tema"} or topic not in STORE_TOPICS:
        raise _ToolError("INVALID_ARGUMENT", f"tema debe ser uno de: {', '.join(STORE_TOPICS)}.")
    content = catalog.store_info(topic)
    if content is None:
        raise _ToolError("NOT_FOUND", "La tienda no tiene información registrada sobre ese tema.")
    data = {"tema": topic, **content}
    if topic == "horario":
        # Abierto o cerrado lo calcula el servidor con su reloj: Grok no sabe qué hora es.
        now = local_now()
        day = WEEKDAYS[now.weekday()]
        hours = content["dias"].get(day)
        data.update(
            ahora=now.strftime("%Y-%m-%d %H:%M"),
            dia_actual=day,
            abierto_ahora=bool(hours) and hours[0] <= now.strftime("%H:%M") < hours[1],
        )
    return _ok(data)


def _stems(text: str) -> set[str]:
    # «tornillos» debe encontrar «Tornillería y fijación»: se comparan las primeras seis letras.
    return {word[:6] for word in tokens(text) if len(word) >= 4}


def _explore_category(arguments: dict, catalog: MockCatalog) -> dict:
    if not set(arguments) <= {"categoria"}:
        raise _ToolError("INVALID_ARGUMENT", "explorar_categoria solo acepta el campo categoria.")
    available = catalog.categories()
    requested = arguments.get("categoria")
    if requested is None:
        return _ok({"categorias": available})
    if not isinstance(requested, str) or not requested.strip() or len(requested) > MAX_CATEGORY_CHARS:
        raise _ToolError("INVALID_ARGUMENT", "categoria debe ser un texto breve.")
    wanted = _stems(requested)
    scores = {item["categoria"]: len(wanted & _stems(item["categoria"])) for item in available}
    best = max(scores.values(), default=0)
    chosen = [name for name, score in scores.items() if score == best]
    if best == 0 or len(chosen) != 1:
        names = ", ".join(item["categoria"] for item in available)
        raise _ToolError("NOT_FOUND", f"No hay una categoría con ese nombre. Categorías: {names}.")
    return _ok({"categoria": chosen[0], "productos": catalog.category_overview(chosen[0])})


def execute_tool(name: str, arguments: dict, *, catalog: MockCatalog) -> dict:
    """Ejecuta una herramienta validada contra el catálogo de la sede del servidor."""
    if not isinstance(catalog, MockCatalog):
        return error_envelope("error", "INVALID_ARGUMENT", "Se requiere un catálogo válido del servidor.", SOURCE)
    if name not in TOOL_NAMES:
        return error_envelope("error", "UNKNOWN_TOOL", "Herramienta fuera de la lista permitida.", SOURCE)
    if not isinstance(arguments, dict):
        return error_envelope("error", "INVALID_ARGUMENT", "Los argumentos deben ser un objeto.", SOURCE)
    try:
        serialized = json.dumps(arguments, ensure_ascii=False)
    except (TypeError, ValueError):
        return error_envelope("error", "INVALID_ARGUMENT", "Los argumentos deben ser serializables en JSON.", SOURCE)
    if len(serialized) > MAX_ARGUMENT_CHARS:
        return error_envelope("error", "INVALID_ARGUMENT", "Los argumentos superan el límite de longitud.", SOURCE)

    try:
        if name == "buscar_productos":
            return _search_products(arguments, catalog)
        if name == "consultar_disponibilidad":
            return _check_availability(arguments, catalog)
        if name == "consultar_info_tienda":
            return _store_info(arguments, catalog)
        if name == "explorar_categoria":
            return _explore_category(arguments, catalog)
        return _calculate_quote(arguments, catalog)
    except _ToolError as exc:
        return error_envelope("error", exc.code, str(exc), SOURCE)
    except (FileNotFoundError, sqlite3.Error, OSError):
        # No exponer rutas locales ni detalles internos del motor SQLite.
        return error_envelope(
            "error",
            "CATALOG_UNAVAILABLE",
            "No fue posible consultar el catálogo de demostración en este momento.",
            SOURCE,
        )
