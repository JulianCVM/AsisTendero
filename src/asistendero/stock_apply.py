"""Aplica una operación confirmada del asistente de bodega, después de comprobar que sigue valiendo.

``stale`` compara la operación con el estado actual (lo que mostró la propuesta tiene que seguir siendo verdad) y
``run`` la escribe con los métodos de ``Purchasing`` e ``Inventory``, cada uno en su propia transacción. Nada aquí
escribe precio ni stock por su cuenta: las existencias suben solo con ``Purchasing.receive`` y se corrigen solo con
``Inventory.update``, que dejan el historial con el origen «asistente AS-…» (en la recepción, en su nota).
"""

from datetime import date

from asistendero.purchasing import Purchasing, PurchasingError
from asistendero.purchasing_rules import OPEN, expected_date
from asistendero.reply_text import format_cop
from asistendero.stock_arrivals import reception_lines
from asistendero.stock_operations import stock_row

APPLICABLE = ("recepcion", "pedido_proveedor", "programar_entrega", "cambio_precio", "correccion_stock")


def _receive_args(operation: dict) -> tuple[str | None, list[dict]]:
    lines = [{"sku": line["sku"], "cantidad": line["recibido"]} for line in operation["lineas"]]
    return (None if operation["oc"] else operation["proveedor"]), lines


def _name(line: dict) -> str:
    return f"{line['nombre']} {line['variante']}"


def stale(purchasing: Purchasing, operation: dict, today: date) -> str | None:
    """Por qué la operación ya no vale contra el estado actual, o None si sigue igual que en la propuesta."""
    tipo = operation["tipo"]
    try:
        if tipo == "recepcion":
            supplier, lines = _receive_args(operation)
            preview = purchasing.receive(supplier, lines, oc=operation["oc"], apply=False)
            if reception_lines(preview) != operation["lineas"]:
                return "la bodega o el pedido cambiaron desde la propuesta"
        elif tipo == "programar_entrega":
            order = next((item for item in purchasing.orders() if item["oc"] == operation["oc"]), None)
            if order is None or order["estado"] not in OPEN or order["fecha_estimada"] != operation["fecha_antes"]:
                return f"el pedido {operation['oc']} cambió desde la propuesta"
            expected_date(operation["fecha_nueva"], today)
        elif tipo == "pedido_proveedor":
            if not any(item["nombre"] == operation["proveedor"] for item in purchasing.suppliers()):
                return f"ya no existe el proveedor {operation['proveedor']}"
            expected_date(operation["fecha_estimada"], today)
        else:
            [line] = operation["lineas"]
            row = stock_row(purchasing, line["sku"])
            if tipo == "cambio_precio" and (row is None or row["precio_cop"] != line["precio_antes"]):
                return f"el precio de {_name(line)} cambió desde la propuesta"
            if tipo == "correccion_stock" and (row is None or row["stock"] != line["stock_antes"]
                                               or row["apartado"] > line["stock_nuevo"]):
                return f"la bodega de {_name(line)} cambió desde la propuesta"
    except PurchasingError as error:
        return str(error)
    return None


def run(purchasing: Purchasing, operation: dict, origin: str) -> str:
    """Escribe la operación y devuelve una frase para el tendero; un rechazo del negocio sale como excepción."""
    tipo = operation["tipo"]
    if tipo == "recepcion":
        supplier, lines = _receive_args(operation)
        receipt = purchasing.receive(supplier, lines, oc=operation["oc"], nota=origin)
        parts = [f"+{line['recibido']} {_name(line)}" + (f" ({line['cantidad_adicional']} adicionales)"
                                                        if line["adicional"] else "") for line in receipt["lineas"]]
        where = f"pedido {operation['oc']}" if operation["oc"] else operation["proveedor"]
        return f"Llegada {receipt['recepcion']} ({where}): {', '.join(parts)}."
    if tipo == "programar_entrega":
        order = purchasing.reschedule(operation["oc"], operation["fecha_nueva"], origin)
        return f"El pedido {order['oc']} ahora llega el {order['fecha_estimada']}."
    if tipo == "pedido_proveedor":
        lines = [{"sku": line["sku"], "cantidad": line["cantidad"]} for line in operation["lineas"]]
        order = purchasing.create_order(operation["proveedor"], lines, operation["fecha_estimada"], origin)
        when = f" para el {order['fecha_estimada']}" if order["fecha_estimada"] else " sin fecha acordada"
        count = "1 producto" if len(lines) == 1 else f"{len(lines)} productos"
        return f"Pedido {order['oc']} a {order['proveedor']}{when}: {count} por llegar."
    [line] = operation["lineas"]
    if tipo == "cambio_precio":
        purchasing.inventory.update(line["sku"], {"precio_cop": line["precio_nuevo"]}, origin=origin)
        return f"Precio de {_name(line)}: {format_cop(line['precio_antes'])} → {format_cop(line['precio_nuevo'])}."
    purchasing.inventory.update(line["sku"], {"stock": line["stock_nuevo"]}, origin=origin)
    return f"Bodega de {_name(line)}: {line['stock_antes']} → {line['stock_nuevo']}."
