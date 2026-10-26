"""Historial de ventas y resumen de caja del tendero: lo vendido y lo cobrado se cuentan por separado.

- **Vendido** (``ventas_registradas``): pedidos entregados. Entregar descuenta la bodega, pero no prueba que se pagó.
- **Cobrado** (``ingresos_confirmados``): pagos que el tendero verificó (``Payments``, estado ``confirmado``). Un
  comprobante recibido todavía no es dinero: va aparte, en ``por_verificar``.

Las fechas se filtran como AAAA-MM-DD en hora de Bogotá. Cada transacción lleva la conversación abreviada
(8 caracteres), nunca datos del cliente. No se consulta ningún banco: solo lo que el tendero registró.
"""

from datetime import datetime
import re

from asistendero.orders import BOGOTA, OrderBook
from asistendero.payments import METHODS, PAYMENT_STATUSES, Payments
from asistendero.sales import STATUSES, order_board


MAX_HISTORY = 500
ALL_ORDERS = 10_000
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
NOTE = ("Vendido no es cobrado: una venta registrada es un pedido entregado; solo es ingreso el pago que el tendero "
        "verificó en el mostrador o en su app o extracto. Un comprobante sin verificar no cuenta como ingreso.")


def _day(value: object, name: str) -> str:
    if not isinstance(value, str) or not DAY.fullmatch(value):
        raise ValueError(f"{name} debe ser una fecha AAAA-MM-DD.")
    datetime.strptime(value, "%Y-%m-%d")  # «2026-02-30» falla aquí con ValueError, no en la comparación.
    return value


def _range(desde: str | None, hasta: str | None) -> tuple[str | None, str | None]:
    desde = _day(desde, "desde") if desde is not None else None
    hasta = _day(hasta, "hasta") if hasta is not None else None
    if desde and hasta and desde > hasta:
        raise ValueError("«desde» no puede ser posterior a «hasta».")
    return desde, hasta


def _within(moment: str | None, desde: str | None, hasta: str | None) -> bool:
    day = (moment or "")[:10]
    return bool(day) and (desde is None or day >= desde) and (hasta is None or day <= hasta)


def _delivered_at(order: dict) -> str | None:
    return next((event["hora"] for event in reversed(order["historial"]) if event["estado"] == "entregado"), None)


def _transaction(order: dict) -> dict:
    delivered = _delivered_at(order) if order["estado"] == "entregado" else None
    payment = order["pago"]
    return {
        "pedido": order["pedido"],
        "fecha": delivered or order["creado"],
        "creado": order["creado"],
        "entregado": delivered,
        "productos": [{"sku": line["sku"], "nombre": line["nombre"], "variante": line["variante"],
                       "unidad": line["unidad"], "cantidad": line["cantidad"]} for line in order["lineas"]],
        "total_cop": order["total_cop"],
        "estado_pedido": order["estado"],
        "metodo_pago": payment["metodo"],
        "metodo_texto": payment["metodo_texto"],
        "estado_pago": payment["estado"],
        "fuente_pago": payment["fuente"],
        "referencia": payment["referencia"],
        "conversacion": order["conversacion"],
    }


def sales_history(book: OrderBook, payments: Payments, desde: str | None = None, hasta: str | None = None,
                  metodo: str | None = None, estado_pago: str | None = None, estado_pedido: str | None = None,
                  limit: int = MAX_HISTORY) -> list[dict]:
    """Transacciones de la sede, de la más reciente a la más antigua, filtradas por fecha, método y estados.

    ``fecha`` es la hora de entrega si el pedido se entregó y, si no, la de creación; ``desde`` y ``hasta`` (incluidos)
    se comparan con ella. Un filtro inválido lanza ``ValueError`` con un mensaje que dice qué usar.
    """
    desde, hasta = _range(desde, hasta)
    if metodo is not None and metodo not in METHODS:
        raise ValueError(f"Método desconocido: usa uno de {', '.join(METHODS)}.")
    if estado_pago is not None and estado_pago not in PAYMENT_STATUSES:
        raise ValueError(f"Estado de pago desconocido: usa uno de {', '.join(PAYMENT_STATUSES)}.")
    if estado_pedido is not None and estado_pedido not in STATUSES:
        raise ValueError(f"Estado de pedido desconocido: usa uno de {', '.join(STATUSES)}.")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_HISTORY:
        raise ValueError(f"El límite debe ser un entero entre 1 y {MAX_HISTORY}.")
    transactions = [_transaction(order) for order in order_board(book, estado_pedido, ALL_ORDERS, payments)]
    chosen = [item for item in transactions if _within(item["fecha"], desde, hasta)
              and (metodo is None or item["metodo_pago"] == metodo)
              and (estado_pago is None or item["estado_pago"] == estado_pago)]
    return sorted(chosen, key=lambda item: item["fecha"], reverse=True)[:limit]


def _amounts(orders: list[dict]) -> dict:
    return {"pedidos": len(orders), "total_cop": sum(order["total_cop"] for order in orders)}


def sales_summary(book: OrderBook, payments: Payments, desde: str | None = None, hasta: str | None = None) -> dict:
    """Caja del día o de un rango (hora de Bogotá), separando lo vendido de lo cobrado.

    Sin fechas es el día de hoy; con una sola, ese día. Cuenta:

    - ``ventas_registradas``: pedidos entregados en el rango (vendido, con o sin pago).
    - ``ingresos_confirmados``: pagos confirmados por el tendero en el rango, de cualquier pedido (puede incluir un pago
      anticipado de un pedido aún por recoger).
    - ``por_verificar``: comprobantes recibidos en el rango que el tendero no ha verificado (no son ingreso).
    - ``por_cobrar``: ventas registradas del rango cuyo pago no está confirmado (incluye las de ``por_verificar``).
    - ``por_metodo``: confirmados y por verificar de cada método.
    """
    if desde is None and hasta is None:
        desde = book.clock().astimezone(BOGOTA).strftime("%Y-%m-%d")
    desde, hasta = _range(desde or hasta, hasta or desde)
    board = order_board(book, limit=ALL_ORDERS, payments=payments)
    sold = [order for order in board if order["estado"] == "entregado" and _within(_delivered_at(order), desde, hasta)]
    confirmed = [order for order in board if order["pago"]["estado"] == "confirmado"
                 and _within(order["pago"]["actualizado"], desde, hasta)]
    to_verify = [order for order in board if order["pago"]["estado"] == "comprobante_recibido"
                 and order["estado"] not in ("cancelado", "vencido") and _within(order["pago"]["actualizado"], desde, hasta)]
    by_method = {
        method: {"etiqueta": label,
                 "confirmados": sum(order["pago"]["metodo"] == method for order in confirmed),
                 "confirmado_cop": sum(order["pago"]["monto_cop"] for order in confirmed if order["pago"]["metodo"] == method),
                 "por_verificar": sum(order["pago"]["metodo"] == method for order in to_verify),
                 "por_verificar_cop": sum(order["pago"]["monto_cop"] for order in to_verify
                                          if order["pago"]["metodo"] == method)}
        for method, label in METHODS.items()
    }
    return {
        "desde": desde,
        "hasta": hasta,
        "ventas_registradas": _amounts(sold),
        "ingresos_confirmados": {"pagos": len(confirmed), "total_cop": sum(order["pago"]["monto_cop"] for order in confirmed)},
        "por_verificar": {"pagos": len(to_verify), "total_cop": sum(order["pago"]["monto_cop"] for order in to_verify)},
        "por_cobrar": _amounts([order for order in sold if order["pago"]["estado"] != "confirmado"]),
        "por_metodo": by_method,
        "nota": NOTE,
    }
