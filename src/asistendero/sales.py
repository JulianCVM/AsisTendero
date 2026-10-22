"""Lo que el tendero ve de los pedidos del chat: el tablero por estado y el resumen de ventas del día.

Una venta es un pedido entregado: solo al entregarlo se descuentan las existencias físicas (``OrderBook.deliver``).
Los pedidos llevan la conversación abreviada (8 caracteres) para ubicarla en el visor, nunca datos del cliente.
"""

from collections import Counter
from datetime import datetime

from asistendero.orders import ACTIVE, BOGOTA, OrderBook, local_text


STATUSES = ("pendiente", "confirmado", "entregado", "cancelado", "vencido")
MAX_BOARD = 200
TOP_PRODUCTS = 5


def order_board(book: OrderBook, status: str | None = None, limit: int = MAX_BOARD) -> list[dict]:
    """Pedidos de la sede, del más reciente al más antiguo, con su historial de estados."""
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
