"""Lo que el tendero ve de los pedidos del chat: el tablero por estado y el resumen de ventas del día.

Una venta es un pedido entregado: solo al entregarlo se descuentan las existencias físicas (``OrderBook.deliver``).
Los pedidos llevan la conversación abreviada (8 caracteres) para ubicarla en el visor, nunca datos del cliente.
Con ``Payments``, cada pedido del tablero lleva su pago y los motivos por los que el tendero debe revisarlo: una venta
entregada no es un pago confirmado.
"""

from collections import Counter
from datetime import datetime, timedelta
import sqlite3

from asistendero.orders import ACTIVE, BOGOTA, OrderBook, local_text
from asistendero.payments import Payments


STATUSES = ("pendiente", "confirmado", "entregado", "cancelado", "vencido")
MAX_BOARD = 200
TOP_PRODUCTS = 5
EXPIRY_WARNING = timedelta(minutes=2)


def review_reasons(row: sqlite3.Row, payment: dict | None, now: datetime) -> list[str]:
    """Motivos legibles por los que el tendero debe intervenir en el pedido; vacía si no hay nada que hacer.

    Los motivos de pago solo aparecen si se conoce el pago (``payment``): sin registro de pagos no se sabe.
    """
    reasons = []
    status = row["status"]
    if status == "pendiente" and datetime.fromisoformat(row["hold_until"]) - now <= EXPIRY_WARNING:
        reasons.append("Vence en 2 minutos o menos sin que el cliente confirme.")
    if status == "confirmado" and row["pickup_at"] and datetime.fromisoformat(row["pickup_at"]) < now:
        reasons.append("Ya pasó la hora de recogida y no se ha entregado.")
    if payment is None:
        return reasons
    if payment["estado"] == "comprobante_recibido" and status not in ("cancelado", "vencido"):
        reasons.append("Hay un comprobante sin verificar: revisa tu app o extracto antes de darlo por pagado.")
    if status == "entregado" and payment["estado"] != "confirmado":
        reasons.append("Entregado sin pago confirmado: está vendido, pero no cobrado.")
    if status in ("cancelado", "vencido") and payment["estado"] == "confirmado":
        reasons.append(f"Pedido {status} con pago confirmado: hay que devolver el dinero.")
    return reasons


def order_board(book: OrderBook, status: str | None = None, limit: int = MAX_BOARD,
                payments: Payments | None = None) -> list[dict]:
    """Pedidos de la sede, del más reciente al más antiguo, con su historial de estados y lo que hay que revisar.

    Con ``payments``, ``pago`` deja de ser el aviso para el cliente y pasa a ser el registro del pago
    (``Payments.of``: método, estado, fuente, referencia; ``pendiente`` si no hay ninguno).
    """
    if status is not None and status not in STATUSES:
        raise ValueError(f"Estado desconocido: usa uno de {', '.join(STATUSES)}.")
    book.expire_due()
    with book.transaction() as connection:
        rows = connection.execute(
            "SELECT * FROM orders WHERE business_id = ? AND store_id = ? AND (? IS NULL OR status = ?) "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (book.business_id, book.store_id, status, status, limit),
        ).fetchall()
        board = []
        for row in rows:
            events = connection.execute("SELECT at, status, detail FROM order_events WHERE order_id = ? ORDER BY rowid",
                                        (row["id"],)).fetchall()
            board.append({**book.view(connection, row), "conversacion": row["session_id"][:8],
                          "historial": [{"hora": local_text(event["at"]), "estado": event["status"],
                                         "detalle": event["detail"]} for event in events]})
    # Los pagos se leen fuera de la transacción del libro: son otra conexión a la misma base.
    paid = payments.of_many([order["pedido"] for order in board]) if payments is not None else {}
    now = book.clock()
    for row, order in zip(rows, board):
        if payments is not None:
            order["pago"] = paid[order["pedido"]]
        order["revisar"] = review_reasons(row, paid.get(order["pedido"]), now)
    return board


def day_summary(book: OrderBook, day: str | None = None) -> dict:
    """Ventas entregadas en el día (hora de Bogotá), pedidos por estado y productos más vendidos."""
    day = day or book.clock().astimezone(BOGOTA).strftime("%Y-%m-%d")
    datetime.strptime(day, "%Y-%m-%d")  # Un día mal escrito falla aquí con ValueError, no en la consulta.
    board = order_board(book, limit=10_000)
    delivered = [order for order in board if order["estado"] == "entregado"
                 and any(event["estado"] == "entregado" and (event["hora"] or "").startswith(day)
                         for event in order["historial"])]
    units = Counter()
    for order in delivered:
        for line in order["lineas"]:
            units[(line["sku"], line["nombre"], line["variante"], line["unidad"])] += line["cantidad"]
    return {
        "dia": day,
        "ventas": len(delivered),
        "total_cop": sum(order["total_cop"] for order in delivered),
        "por_estado": {status: sum(order["estado"] == status for order in board) for status in STATUSES},
        "por_recoger": [order for order in board if order["estado"] in ACTIVE][:20],
        "mas_vendidos": [{"sku": sku, "nombre": name, "variante": variant, "unidad": unit, "cantidad": amount}
                         for (sku, name, variant, unit), amount in units.most_common(TOP_PRODUCTS)],
    }
