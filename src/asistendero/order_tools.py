"""Herramientas de pedidos que Grok puede solicitar dentro de una sesión.

El servidor fija la sesión: Grok solo da el código del pedido y nunca puede tocar el de otro cliente. Los
argumentos llegan ya limpios de ``order_rules``; aquí se vuelven a comprobar porque el ejecutor también se
puede llamar fuera del grafo. Precio y existencias se releen al registrar y al confirmar.
"""

from datetime import date, datetime, time
import sqlite3

from asistendero.observations import error_envelope
from asistendero.orders import BOGOTA, MAX_NOTE_CHARS, ORDER_ID, OrderBook, OrderError
from asistendero.tools import SOURCE, _ok
from asistendero.validation import MAX_ITEMS, MAX_QUANTITY, SKU_PATTERN


def _order_id(arguments: dict) -> str:
    order_id = arguments.get("pedido")
    if not isinstance(order_id, str) or not ORDER_ID.match(order_id):
        raise OrderError("INVALID_ARGUMENT", "Se requiere el código del pedido (P-XXXXXX).")
    return order_id


def _lines(arguments: dict) -> list[tuple[str, int]]:
    lines = arguments.get("lines")
    if set(arguments) != {"lines"} or not isinstance(lines, list) or not 1 <= len(lines) <= MAX_ITEMS:
        raise OrderError("INVALID_ARGUMENT", f"Se requieren de 1 a {MAX_ITEMS} líneas.")
    clean: list[tuple[str, int]] = []
    for line in lines:
        if not isinstance(line, dict) or set(line) != {"sku", "quantity"}:
            raise OrderError("INVALID_ARGUMENT", "Cada línea lleva solo sku y quantity.")
        sku, quantity = line["sku"], line["quantity"]
        if not isinstance(sku, str) or not SKU_PATTERN.match(sku) or sku in {item[0] for item in clean}:
            raise OrderError("INVALID_ARGUMENT", "SKU inválido o repetido.")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= MAX_QUANTITY:
            raise OrderError("INVALID_QUANTITY", f"La cantidad debe ser un entero de 1 a {MAX_QUANTITY}.")
        clean.append((sku, quantity))
    return clean


def _pickup(arguments: dict) -> tuple[datetime | None, str | None]:
    if not set(arguments) <= {"pedido", "fecha", "hora", "nota"}:
        raise OrderError("INVALID_ARGUMENT", "agendar_recogida acepta pedido, fecha, hora y nota.")
    moment = None
    if arguments.get("fecha") is not None or arguments.get("hora") is not None:
        try:
            moment = datetime.combine(date.fromisoformat(arguments["fecha"]), time.fromisoformat(arguments["hora"]),
                                      tzinfo=BOGOTA)
        except (KeyError, TypeError, ValueError):
            raise OrderError("INVALID_ARGUMENT", "fecha va como AAAA-MM-DD y hora como HH:MM.") from None
    note = arguments.get("nota")
    if note is not None and (not isinstance(note, str) or len(note) > MAX_NOTE_CHARS):
        raise OrderError("INVALID_ARGUMENT", f"La nota es un texto de hasta {MAX_NOTE_CHARS} caracteres.")
    return moment, note


def execute_order_tool(name: str, arguments: dict, *, book: OrderBook, session_id: str) -> dict:
    """Ejecuta una herramienta de pedidos para la sesión que fija el servidor."""
    if not isinstance(arguments, dict):
        return error_envelope("error", "INVALID_ARGUMENT", "Los argumentos deben ser un objeto.", SOURCE)
    try:
        if name == "registrar_pedido":
            return _ok(book.create(session_id, _lines(arguments)))
        if name == "consultar_pedido":
            if not set(arguments) <= {"pedido"}:
                raise OrderError("INVALID_ARGUMENT", "consultar_pedido acepta solo pedido.")
            if "pedido" in arguments:
                return _ok({"pedidos": [book.get(_order_id(arguments), session_id)]})
            return _ok({"pedidos": book.session_orders(session_id)})
        if name == "agendar_recogida":
            moment, note = _pickup(arguments)
            return _ok(book.schedule(session_id, _order_id(arguments), moment, note))
        if set(arguments) != {"pedido"}:
            raise OrderError("INVALID_ARGUMENT", f"{name} acepta solo pedido.")
        if name == "confirmar_pedido":
            return _ok(book.confirm(session_id, _order_id(arguments)))
        if name == "cancelar_pedido":
            return _ok(book.cancel(_order_id(arguments), session_id))
        return error_envelope("error", "UNKNOWN_TOOL", "Herramienta fuera de la lista permitida.", SOURCE)
    except OrderError as exc:
        return error_envelope("error", exc.code, str(exc), SOURCE)
    except (FileNotFoundError, sqlite3.Error, OSError):
        # Igual que el catálogo: no se exponen rutas ni detalles del motor.
        return error_envelope("error", "CATALOG_UNAVAILABLE",
                              "No fue posible registrar el pedido en este momento.", SOURCE)
