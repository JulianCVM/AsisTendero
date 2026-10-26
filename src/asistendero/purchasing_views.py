"""Cómo se le muestran al tendero una orden de compra y una recepción (``purchasing.py``).

Solo lectura dentro de la transacción de quien llama; las horas salen en hora de Bogotá. Son vistas del panel
local del tendero: los costos de compra no pasan nunca por las herramientas del agente.
"""

from datetime import date
import sqlite3

from asistendero.orders import local_text
from asistendero.purchasing_rules import OPEN

_PRODUCT = ("LEFT JOIN products p ON p.business_id = l.business_id AND p.store_id = l.store_id AND p.sku = l.sku")


def _cost(quantity: int, unit_cost: int | None) -> int | None:
    return None if unit_cost is None else quantity * unit_cost


def order_view(connection: sqlite3.Connection, row: sqlite3.Row, today: date) -> dict:
    """Una OC con su proveedor, sus líneas (pedido, recibido, pendiente, costo), su atraso y su historial."""
    scope = (row["business_id"], row["store_id"], row["id"])
    is_open = row["status"] in OPEN
    supplier = connection.execute("SELECT name FROM purchase_suppliers WHERE business_id = ? AND store_id = ? "
                                  "AND id = ?", (*scope[:2], row["supplier_id"])).fetchone()
    lines = connection.execute(f"SELECT l.*, p.name, p.variant, p.unit FROM purchase_order_lines l {_PRODUCT} "
                               "WHERE l.business_id = ? AND l.store_id = ? AND l.order_id = ? ORDER BY l.rowid",
                               scope).fetchall()
    shown = [{"sku": line["sku"], "nombre": line["name"], "variante": line["variant"], "unidad": line["unit"],
              "pedido": line["ordered"], "recibido": line["received"],
              "pendiente": line["ordered"] - line["received"] if is_open else 0,
              "costo_unitario_cop": line["unit_cost_cop"], "costo_cop": _cost(line["ordered"], line["unit_cost_cop"])}
             for line in lines]
    events = connection.execute("SELECT at, action, detail, actor FROM purchase_order_events WHERE business_id = ? "
                                "AND store_id = ? AND order_id = ? ORDER BY rowid", scope).fetchall()
    pending = sum(line["pendiente"] for line in shown)
    expected = row["expected_date"]
    return {
        "oc": row["id"], "proveedor": supplier["name"] if supplier else None, "proveedor_id": row["supplier_id"],
        "estado": row["status"], "fecha_estimada": expected,
        "atrasada": bool(is_open and pending and expected and expected < today.isoformat()),
        "nota": row["note"], "creada": local_text(row["created_at"]), "actualizada": local_text(row["updated_at"]),
        "lineas": shown, "pendiente": pending,
        "costo_cop": sum(line["costo_cop"] for line in shown if line["costo_cop"] is not None),
        "eventos": [{"hora": local_text(event["at"]), "accion": event["action"], "detalle": event["detail"],
                     "quien": event["actor"]} for event in events],
    }


def receipt_view(connection: sqlite3.Connection, scope: tuple[str, str], receipt_id: str) -> dict:
    """Una recepción con lo que subió cada SKU, lo que queda pendiente de su OC y lo que llegó de más."""
    row = connection.execute("SELECT r.*, s.name AS supplier, o.status AS order_status FROM purchase_receipts r "
                             "LEFT JOIN purchase_suppliers s ON s.business_id = r.business_id AND s.store_id = "
                             "r.store_id AND s.id = r.supplier_id LEFT JOIN purchase_orders o ON o.business_id = "
                             "r.business_id AND o.store_id = r.store_id AND o.id = r.order_id WHERE r.business_id = ? "
                             "AND r.store_id = ? AND r.id = ?", (*scope, receipt_id)).fetchone()
    lines = connection.execute(f"SELECT l.*, p.name, p.variant, p.unit FROM purchase_receipt_lines l {_PRODUCT} "
                               "WHERE l.business_id = ? AND l.store_id = ? AND l.receipt_id = ? ORDER BY l.rowid",
                               (*scope, receipt_id)).fetchall()
    shown = [{"sku": line["sku"], "nombre": line["name"], "variante": line["variant"], "unidad": line["unit"],
              "stock_antes": line["stock_before"], "recibido": line["quantity"], "stock_despues": line["stock_after"],
              "pendiente": line["pending_after"], "adicional": line["extra"] > 0,
              "cantidad_adicional": line["extra"], "costo_unitario_cop": line["unit_cost_cop"],
              "costo_cop": _cost(line["quantity"], line["unit_cost_cop"])} for line in lines]
    return {
        "recepcion": row["id"], "proveedor": row["supplier"], "proveedor_id": row["supplier_id"],
        "oc": row["order_id"], "estado_oc": row["order_status"], "hora": local_text(row["received_at"]),
        "nota": row["note"], "vista_previa": False, "lineas": shown,
        "unidades": sum(line["recibido"] for line in shown),
        "costo_cop": sum(line["costo_cop"] for line in shown if line["costo_cop"] is not None),
    }
