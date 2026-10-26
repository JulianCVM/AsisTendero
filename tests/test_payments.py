"""Pagos y ventas del tendero: lo vendido no es lo cobrado y nadie confirma un pago que no verificó."""

from datetime import datetime, timedelta

import pytest

from asistendero.inventory import Inventory
from asistendero.orders import BOGOTA, OrderBook
from asistendero.payments import MAX_REFERENCE_CHARS, PaymentError, Payments
from asistendero.sales import order_board
from asistendero.sales_history import sales_history, sales_summary
from asistendero.seed import create_mock_db


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 21, 10, 0, tzinfo=BOGOTA)

    def __call__(self):
        return self.now


@pytest.fixture
def shop(tmp_path):
    path = create_mock_db(tmp_path / "catalog.sqlite3")
    clock = Clock()
    return OrderBook(path, clock=clock), Payments(path, clock=clock), Inventory(path)


def _sold(book, session="sesion-a", lines=(("PVC-050", 2),)):
    order = book.create(session, list(lines))
    book.confirm(session, order["pedido"])
    book.deliver(order["pedido"])
    return order


def _board_item(book, payments, order_id):
    return next(item for item in order_board(book, payments=payments) if item["pedido"] == order_id)


def test_a_delivered_order_without_payment_is_sold_but_not_collected(shop):
    book, payments, _ = shop
    order = _sold(book)
    summary = sales_summary(book, payments)
    assert summary["desde"] == summary["hasta"] == "2026-10-21"
    assert summary["ventas_registradas"] == {"pedidos": 1, "total_cop": order["total_cop"]}
    assert summary["ingresos_confirmados"] == {"pagos": 0, "total_cop": 0}
    assert summary["por_cobrar"] == {"pedidos": 1, "total_cop": order["total_cop"]}
    assert "no es cobrado" in summary["nota"]
    assert payments.of(order["pedido"])["estado"] == "pendiente" and payments.history(order["pedido"]) == []
    assert _board_item(book, payments, order["pedido"])["revisar"] == [
        "Entregado sin pago confirmado: está vendido, pero no cobrado."]


def test_a_received_receipt_is_not_income_until_the_shopkeeper_checks_the_money(shop):
    book, payments, _ = shop
    order = _sold(book)
    payments.register(order["pedido"], "nequi", "comprobante_recibido", "M123456", actor="agente")
    summary = sales_summary(book, payments)
    assert summary["ingresos_confirmados"]["total_cop"] == 0
    assert summary["por_verificar"] == {"pagos": 1, "total_cop": order["total_cop"]}
    assert summary["por_cobrar"]["total_cop"] == order["total_cop"]
    assert summary["por_metodo"]["nequi"]["por_verificar_cop"] == order["total_cop"]
    assert any("comprobante sin verificar" in reason for reason in _board_item(book, payments, order["pedido"])["revisar"])
    confirmed = payments.register(order["pedido"], "nequi", "confirmado", "M123456", fuente="revision_tendero")
    assert (confirmed["estado"], confirmed["fuente"]) == ("confirmado", "revision_tendero")
    summary = sales_summary(book, payments)
    assert summary["ingresos_confirmados"] == {"pagos": 1, "total_cop": order["total_cop"]}
    assert summary["por_verificar"]["pagos"] == 0 and summary["por_cobrar"]["pedidos"] == 0
    assert summary["por_metodo"]["nequi"]["confirmado_cop"] == order["total_cop"]
    assert summary["por_metodo"]["efectivo"]["confirmado_cop"] == 0
    assert _board_item(book, payments, order["pedido"])["revisar"] == []
    events = payments.history(order["pedido"])
    assert [(event["estado"], event["actor"], event["fuente"]) for event in events] == [
        ("comprobante_recibido", "agente", None), ("confirmado", "tendero", "revision_tendero")]
    assert all(event["hora"] == "2026-10-21 10:00" and event["metodo"] == "nequi" for event in events)


def test_a_gateway_confirmation_is_rejected_because_there_is_no_integration(shop):
    book, payments, _ = shop
    order = _sold(book)
    with pytest.raises(PaymentError) as error:
        payments.register(order["pedido"], "nequi", "confirmado", fuente="pasarela")
    assert error.value.code == "PAYMENT_SOURCE_UNAVAILABLE" and "webhook firmado" in str(error.value)
    assert payments.of(order["pedido"])["estado"] == "pendiente" and payments.history(order["pedido"]) == []


def test_cancelled_or_expired_orders_take_no_payment(shop):
    book, payments, _ = shop
    cancelled = book.create("sesion-a", [("PVC-050", 1)])
    book.cancel(cancelled["pedido"], "sesion-a")
    expired = book.create("sesion-b", [("PVC-050", 1)])
    book.clock.now += timedelta(minutes=6)
    for order_id, state in ((cancelled["pedido"], "cancelado"), (expired["pedido"], "vencido")):
        with pytest.raises(PaymentError) as error:
            payments.register(order_id, "efectivo", "confirmado", fuente="mostrador")
        assert error.value.code == "PAYMENT_ORDER_CLOSED" and state in str(error.value)
        assert payments.history(order_id) == []
    with pytest.raises(PaymentError) as error:
        payments.register("P-000000", "efectivo", "pendiente")
    assert error.value.code == "PAYMENT_ORDER_NOT_FOUND"


def test_the_amount_is_always_the_order_total_read_from_the_database(shop):
    book, payments, inventory = shop
    order = book.create("sesion-a", [("PVC-050", 3)])
    # Un cambio de precio posterior no toca lo que vale el pedido ni lo que se cobra.
    inventory.update("PVC-050", {"precio_cop": 1})
    registered = payments.register(order["pedido"], "efectivo", "confirmado", fuente="mostrador")
    assert registered["monto_cop"] == order["total_cop"] == 3 * 8500
    with pytest.raises(TypeError):
        payments.register(order["pedido"], "efectivo", "confirmado", fuente="mostrador", monto_cop=1)
    assert payments.of_many([order["pedido"], "P-000000", "x"]) == {order["pedido"]: registered}


@pytest.mark.parametrize(("method", "status", "source", "actor", "code"), [
    ("efectivo", "comprobante_recibido", None, "tendero", "PAYMENT_STATUS_NOT_ALLOWED"),
    ("datafono", "rechazado", None, "tendero", "PAYMENT_STATUS_NOT_ALLOWED"),
    ("nequi", "confirmado", "mostrador", "tendero", "PAYMENT_SOURCE_MISMATCH"),
    ("efectivo", "confirmado", "revision_tendero", "tendero", "PAYMENT_SOURCE_MISMATCH"),
    ("bre_b", "confirmado", None, "tendero", "PAYMENT_SOURCE_REQUIRED"),
    ("daviplata", "comprobante_recibido", "revision_tendero", "tendero", "PAYMENT_SOURCE_NOT_ALLOWED"),
    ("transferencia", "confirmado", "revision_tendero", "agente", "PAYMENT_FORBIDDEN"),
    ("nequi", "rechazado", None, "agente", "PAYMENT_FORBIDDEN"),
    ("bitcoin", "pendiente", None, "tendero", "PAYMENT_INVALID_METHOD"),
    ("nequi", "pagado", None, "tendero", "PAYMENT_INVALID_STATUS"),
    ("nequi", "confirmado", "banco", "tendero", "PAYMENT_INVALID_SOURCE"),
    ("nequi", "pendiente", None, "cliente", "PAYMENT_INVALID_ACTOR"),
])
def test_payment_rules_reject_without_writing(shop, method, status, source, actor, code):
    book, payments, _ = shop
    order = book.create("sesion-a", [("PVC-050", 1)])
    with pytest.raises(PaymentError) as error:
        payments.register(order["pedido"], method, status, fuente=source, actor=actor)
    assert error.value.code == code
    assert payments.of(order["pedido"])["metodo"] is None and payments.history(order["pedido"]) == []


def test_references_are_short_free_of_personal_data_and_confirmed_payments_are_final(shop):
    book, payments, _ = shop
    order = book.create("sesion-a", [("PVC-050", 1)])
    with pytest.raises(PaymentError) as error:
        payments.register(order["pedido"], "nequi", "comprobante_recibido", "x" * (MAX_REFERENCE_CHARS + 1))
    assert error.value.code == "PAYMENT_INVALID_REFERENCE"
    saved = payments.register(order["pedido"], "nequi", "comprobante_recibido", "envió desde el 300 123 4567")
    assert "4567" not in saved["referencia"] and "[dato personal omitido]" in saved["referencia"]
    assert "4567" not in payments.history(order["pedido"])[0]["referencia"]
    payments.register(order["pedido"], "nequi", "rechazado", "no llegó")
    payments.register(order["pedido"], "nequi", "confirmado", fuente="revision_tendero")
    with pytest.raises(PaymentError) as error:
        payments.register(order["pedido"], "nequi", "rechazado")
    assert error.value.code == "PAYMENT_ALREADY_CONFIRMED"
    assert [event["estado"] for event in payments.history(order["pedido"])] == [
        "comprobante_recibido", "rechazado", "confirmado"]


def test_sales_history_filters_by_date_method_and_status(shop):
    book, payments, _ = shop
    first = _sold(book, "sesion-a", [("PVC-050", 2), ("CEM-050", 1)])
    payments.register(first["pedido"], "efectivo", "confirmado", fuente="mostrador")
    book.clock.now += timedelta(days=1)
    second = _sold(book, "sesion-b", [("PVC-050", 1)])
    payments.register(second["pedido"], "daviplata", "comprobante_recibido", "D-778")
    waiting = book.create("sesion-c", [("PVC-050", 1)])
    everything = sales_history(book, payments)
    assert [item["pedido"] for item in everything] == [waiting["pedido"], second["pedido"], first["pedido"]]
    old = sales_history(book, payments, desde="2026-10-21", hasta="2026-10-21")
    assert [item["pedido"] for item in old] == [first["pedido"]]
    assert old[0] == {
        "pedido": first["pedido"], "fecha": "2026-10-21 10:00", "creado": "2026-10-21 10:00",
        "entregado": "2026-10-21 10:00",
        "productos": [{"sku": line["sku"], "nombre": line["nombre"], "variante": line["variante"],
                       "unidad": line["unidad"], "cantidad": line["cantidad"]} for line in first["lineas"]],
        "total_cop": first["total_cop"], "estado_pedido": "entregado", "metodo_pago": "efectivo",
        "metodo_texto": "Efectivo", "estado_pago": "confirmado", "fuente_pago": "mostrador", "referencia": "",
        "conversacion": "sesion-a",
    }
    assert [item["pedido"] for item in sales_history(book, payments, metodo="daviplata")] == [second["pedido"]]
    assert [item["pedido"] for item in sales_history(book, payments, estado_pago="pendiente")] == [waiting["pedido"]]
    assert [item["pedido"] for item in sales_history(book, payments, estado_pedido="entregado", limit=1)] == [
        second["pedido"]]
    two_days = sales_summary(book, payments, "2026-10-21", "2026-10-22")
    assert two_days["ventas_registradas"]["pedidos"] == 2
    assert two_days["ingresos_confirmados"]["total_cop"] == first["total_cop"]
    assert two_days["por_cobrar"] == {"pedidos": 1, "total_cop": second["total_cop"]}
    assert sales_summary(book, payments)["ventas_registradas"]["pedidos"] == 1  # Hoy es el 22.


@pytest.mark.parametrize("filters", [
    {"desde": "21-10-2026"}, {"desde": "2026-02-30"}, {"hasta": 20261021}, {"desde": "2026-10-22", "hasta": "2026-10-21"},
    {"metodo": "bitcoin"}, {"estado_pago": "pagado"}, {"estado_pedido": "robado"}, {"limit": 0}, {"limit": True},
])
def test_invalid_history_filters_fail_with_a_clear_error(shop, filters):
    book, payments, _ = shop
    with pytest.raises(ValueError):
        sales_history(book, payments, **filters)


def test_the_board_flags_what_the_shopkeeper_must_handle(shop):
    book, payments, _ = shop
    expiring = book.create("sesion-a", [("PVC-050", 1)])
    scheduled = book.create("sesion-b", [("PVC-050", 1)])
    book.confirm("sesion-b", scheduled["pedido"])
    book.schedule("sesion-b", scheduled["pedido"], datetime(2026, 10, 21, 10, 30, tzinfo=BOGOTA), None)
    calm = book.create("sesion-c", [("PVC-050", 1)])
    book.confirm("sesion-c", calm["pedido"])
    book.clock.now += timedelta(minutes=3, seconds=30)
    flags = {item["pedido"]: item["revisar"] for item in order_board(book, payments=payments)}
    assert flags[expiring["pedido"]] == ["Vence en 2 minutos o menos sin que el cliente confirme."]
    assert flags[scheduled["pedido"]] == [] and flags[calm["pedido"]] == []
    book.clock.now = datetime(2026, 10, 21, 10, 45, tzinfo=BOGOTA)
    flags = {item["pedido"]: item["revisar"] for item in order_board(book, payments=payments)}
    assert flags[scheduled["pedido"]] == ["Ya pasó la hora de recogida y no se ha entregado."]
    assert flags[expiring["pedido"]] == [] and flags[calm["pedido"]] == []
    # Un pago confirmado de un pedido que luego se cancela pide devolver el dinero.
    payments.register(calm["pedido"], "efectivo", "confirmado", fuente="mostrador")
    book.cancel(calm["pedido"], by="tendero")
    assert _board_item(book, payments, calm["pedido"])["revisar"] == [
        "Pedido cancelado con pago confirmado: hay que devolver el dinero."]


def test_the_board_keeps_working_for_callers_without_payments(shop):
    book, payments, _ = shop
    order = _sold(book)
    item = order_board(book)[0]
    # Sin registro de pagos no se sabe si se cobró: no se marca, y «pago» sigue siendo el aviso al cliente.
    assert item["pago"] == order["pago"] and item["revisar"] == []
    paid = _board_item(book, payments, order["pedido"])["pago"]
    assert paid == {"pedido": order["pedido"], "metodo": None, "metodo_texto": None, "estado": "pendiente",
                    "fuente": None, "referencia": "", "monto_cop": order["total_cop"], "actualizado": None}
