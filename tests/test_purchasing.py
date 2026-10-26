"""Abastecimiento flexible: órdenes de compra, recepciones parciales y adicionales, y el surtido que ve el agente."""

from datetime import datetime, timedelta
import json
import sqlite3

import pytest

from asistendero.catalog import MockCatalog
from asistendero.inventory import Inventory
from asistendero.orders import BOGOTA
from asistendero.purchasing import Purchasing, PurchasingError
from asistendero.purchasing_rules import MAX_LINES
from asistendero.seed import create_mock_db
from asistendero.tools import execute_tool


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 21, 10, 0, tzinfo=BOGOTA)

    def __call__(self):
        return self.now


@pytest.fixture
def db(tmp_path):
    return create_mock_db(tmp_path / "catalog.sqlite3")


@pytest.fixture
def buying(db):
    purchasing = Purchasing(db, clock=Clock())
    purchasing.add_supplier("Distribuidora El Bulto", "cemento y pegantes")
    return purchasing


def _stock(db, sku):
    return MockCatalog(db).get(sku).stock


def _restock(db, sku):
    return Inventory(db).products(sku)[0]["surtido"]


CEMENT = {"sku": "CEM-050", "cantidad": 20, "costo_unitario": 32000}


def test_partial_receipt_with_extra_items_raises_stock_only_when_it_arrives(db, buying):
    order = buying.create_order("Distribuidora El Bulto", [CEMENT], "2026-10-24", "pedido por teléfono")
    assert order["oc"] == "OC-0001" and order["estado"] == "pedido" and order["pendiente"] == 20
    # Pedir no es recibir: el stock sigue igual y lo pedido queda como mercancía pendiente.
    assert _stock(db, "CEM-050") == 9
    assert buying.pending_by_sku() == {"CEM-050": {"pendiente": 20, "llega": "2026-10-24"}}

    receipt = buying.receive("distribuidora el bulto", [{"sku": "CEM-050", "cantidad": 12},
                                                        {"sku": "BRO-2", "cantidad": 5, "costo_unitario": 3000}],
                             oc="OC-0001", nota="faltaron 8")
    cement, brush = receipt["lineas"]
    assert receipt["recepcion"] == "R-0001" and receipt["estado_oc"] == "parcial" and not receipt["vista_previa"]
    assert receipt["proveedor"] == "Distribuidora El Bulto" and receipt["unidades"] == 17
    assert (cement["stock_antes"], cement["recibido"], cement["stock_despues"], cement["pendiente"]) == (9, 12, 21, 8)
    assert cement["adicional"] is False and cement["costo_unitario_cop"] == 32000 and cement["costo_cop"] == 384000
    assert (brush["stock_antes"], brush["stock_despues"], brush["pendiente"]) == (35, 40, 0)
    assert brush["adicional"] is True and brush["cantidad_adicional"] == 5
    assert _stock(db, "CEM-050") == 21 and _stock(db, "BRO-2") == 40
    assert buying.pending_by_sku() == {"CEM-050": {"pendiente": 8, "llega": "2026-10-24"}}
    [line] = buying.orders("parcial")[0]["lineas"]
    assert (line["pedido"], line["recibido"], line["pendiente"]) == (20, 12, 8)

    inventory = Inventory(db)
    for sku, before, after in (("CEM-050", "9", "21"), ("BRO-2", "35", "40")):
        [event] = [item for item in inventory.history(sku=sku) if item["campo"] == "existencias"]
        assert (event["antes"], event["despues"], event["origen"]) == (before, after, "recepción R-0001")
    assert {item["sku"] for item in inventory.history(sku="BRO-2")} == {"BRO-2"}
    assert buying.receipts()[0]["lineas"] == receipt["lineas"]

    # Llega lo que faltaba y 2 de más: la OC se cierra y el excedente cuenta como adicional.
    final = buying.receive(None, [{"sku": "CEM-050", "cantidad": 10}], oc="OC-0001")
    assert final["estado_oc"] == "recibida" and final["lineas"][0]["cantidad_adicional"] == 2
    assert _stock(db, "CEM-050") == 31 and buying.pending_by_sku() == {}
    # Ya llegó: la fecha de la OC deja de prometerse como surtido.
    assert _restock(db, "CEM-050") == ""


def test_preview_returns_the_same_summary_without_writing_anything(db, buying):
    buying.create_order("PV-001", [CEMENT])
    history = Inventory(db).history()
    preview = buying.receive("PV-001", [{"sku": "CEM-050", "cantidad": 12}, {"sku": "BRO-2", "cantidad": 5}],
                             oc="OC-0001", apply=False)
    assert preview["vista_previa"] is True and preview["recepcion"] is None and preview["estado_oc"] == "parcial"
    assert _stock(db, "CEM-050") == 9 and _stock(db, "BRO-2") == 35
    assert Inventory(db).history() == history and buying.receipts() == []
    assert buying.orders()[0]["estado"] == "pedido" and buying.orders()[0]["pendiente"] == 20
    applied = buying.receive("PV-001", [{"sku": "CEM-050", "cantidad": 12}, {"sku": "BRO-2", "cantidad": 5}],
                             oc="OC-0001")
    assert applied["lineas"] == preview["lineas"] and applied["recepcion"] == "R-0001"


def test_an_order_with_a_date_tells_the_agent_when_it_arrives_and_reschedules_with_it(db, buying):
    assert _restock(db, "CEM-050") == "lunes"
    buying.create_order("PV-001", [CEMENT], "2026-10-24")
    assert _restock(db, "CEM-050") == "2026-10-24" and MockCatalog(db).get("CEM-050").restock == "2026-10-24"
    order = buying.reschedule("OC-0001", "2026-10-28", "el proveedor no tiene camión")
    assert order["fecha_estimada"] == "2026-10-28" and _restock(db, "CEM-050") == "2026-10-28"
    assert order["eventos"][-1]["accion"] == "reprogramada"
    assert "2026-10-24 -> 2026-10-28" in order["eventos"][-1]["detalle"] and order["eventos"][-1]["quien"] == "tendero"
    [change] = [item for item in Inventory(db).history(sku="CEM-050") if item["despues"] == "2026-10-28"]
    assert change["campo"] == "surtido" and change["origen"] == "compra OC-0001"
    assert not order["atrasada"]
    buying.clock.now += timedelta(days=8)
    assert buying.orders()[0]["atrasada"] is True
    with pytest.raises(PurchasingError) as error:
        buying.reschedule("OC-0001", "2026-10-28")
    assert error.value.code == "DATE_IN_PAST"


def test_the_earliest_open_order_wins_and_a_cancelled_date_is_not_promised(db, buying):
    buying.create_order("PV-001", [CEMENT], "2026-10-24")
    buying.create_order("PV-001", [{"sku": "CEM-050", "cantidad": 5}], "2026-10-30")
    assert _restock(db, "CEM-050") == "2026-10-24"
    cancelled = buying.cancel_order("OC-0001", "el proveedor no despacha")
    assert cancelled["estado"] == "cancelada" and cancelled["pendiente"] == 0
    assert _restock(db, "CEM-050") == "2026-10-30" and _stock(db, "CEM-050") == 9
    buying.cancel_order("OC-0002", "se consiguió en otro lado")
    # Sin OC pendiente, la fecha de la compra cancelada ya no se le promete a ningún cliente.
    assert _restock(db, "CEM-050") == "" and buying.pending_by_sku() == {}
    with pytest.raises(PurchasingError) as error:
        buying.receive(None, [{"sku": "CEM-050", "cantidad": 1}], oc="OC-0001")
    assert error.value.code == "PURCHASE_CLOSED"


def test_a_partial_order_cancels_only_what_was_pending(db, buying):
    buying.create_order("PV-001", [CEMENT])
    buying.receive("PV-001", [{"sku": "CEM-050", "cantidad": 12}], oc="OC-0001")
    order = buying.cancel_order("OC-0001", "no llegó el resto")
    [line] = order["lineas"]
    assert (line["recibido"], line["pendiente"], order["estado"]) == (12, 0, "cancelada")
    assert _stock(db, "CEM-050") == 21 and buying.pending_by_sku() == {}


def test_discontinued_restock_is_never_overwritten(db, buying):
    assert _restock(db, "NIV-24") == "descontinuado"
    buying.create_order("PV-001", [{"sku": "NIV-24", "cantidad": 3}], "2026-10-24")
    buying.reschedule("OC-0001", "2026-10-25")
    assert _restock(db, "NIV-24") == "descontinuado"
    assert [item for item in Inventory(db).history(sku="NIV-24") if item["campo"] == "surtido"] == []


@pytest.mark.parametrize("lines, date, code", [
    ([{"sku": "NOX-999", "cantidad": 1}], None, "NOT_FOUND"),
    ([{"sku": "CEM-050", "cantidad": 0}], None, "INVALID_ARGUMENT"),
    ([{"sku": "CEM-050", "cantidad": True}], None, "INVALID_ARGUMENT"),
    ([{"sku": "CEM-050", "cantidad": 100_001}], None, "INVALID_ARGUMENT"),
    ([{"sku": "CEM-050", "cantidad": 2, "costo_unitario": -1}], None, "INVALID_ARGUMENT"),
    ([{"sku": "CEM-050", "cantidad": 2, "precio": 1}], None, "INVALID_ARGUMENT"),
    ([{"sku": "CEM-050", "cantidad": 2}, {"sku": "CEM-050", "cantidad": 1}], None, "DUPLICATE_LINE"),
    ([{"sku": "CEM-050", "cantidad": 1}] * (MAX_LINES + 1), None, "INVALID_ARGUMENT"),
    ([], None, "INVALID_ARGUMENT"),
    ([CEMENT], "2026-10-20", "DATE_IN_PAST"),
    ([CEMENT], "24/10/2026", "INVALID_ARGUMENT"),
    ([CEMENT], "2027-10-24", "DATE_TOO_FAR"),
])
def test_invalid_orders_are_rejected_without_writing(db, buying, lines, date, code):
    with pytest.raises(PurchasingError) as error:
        buying.create_order("PV-001", lines, date)
    assert error.value.code == code
    assert buying.orders() == [] and _stock(db, "CEM-050") == 9 and _restock(db, "CEM-050") == "lunes"


def test_a_failing_line_rolls_back_the_whole_receipt(db, buying):
    buying.create_order("PV-001", [CEMENT])
    history = Inventory(db).history()
    for lines, code in (([{"sku": "CEM-050", "cantidad": 12}, {"sku": "NOX-999", "cantidad": 1}], "NOT_FOUND"),
                        ([{"sku": "BRO-2", "cantidad": 5}, {"sku": "CEM-050", "cantidad": 100_000}], "STOCK_LIMIT")):
        with pytest.raises(PurchasingError) as error:
            buying.receive("PV-001", lines, oc="OC-0001")
        assert error.value.code == code
    assert _stock(db, "CEM-050") == 9 and _stock(db, "BRO-2") == 35 and Inventory(db).history() == history
    assert buying.receipts() == [] and buying.orders()[0]["lineas"][0]["recibido"] == 0


def test_suppliers_and_orders_stay_inside_their_store(db, buying):
    assert buying.suppliers() == [{"proveedor": "PV-001", "nombre": "Distribuidora El Bulto",
                                   "nota": "cemento y pegantes", "ocs_abiertas": 0}]
    with pytest.raises(PurchasingError) as error:
        buying.add_supplier("  distribuidora   EL BULTO ")
    assert error.value.code == "DUPLICATE_SUPPLIER"
    buying.add_supplier("Pinturas del Norte")
    buying.create_order("PV-001", [CEMENT])
    for call, code in ((lambda: buying.create_order("Proveedor fantasma", [CEMENT]), "SUPPLIER_NOT_FOUND"),
                       (lambda: buying.receive("Pinturas del Norte", [{"sku": "CEM-050", "cantidad": 1}],
                                               oc="OC-0001"), "SUPPLIER_MISMATCH"),
                       (lambda: buying.receive(None, [{"sku": "CEM-050", "cantidad": 1}]), "INVALID_ARGUMENT"),
                       (lambda: buying.reschedule("OC-1; DROP", "2026-10-24"), "PURCHASE_NOT_FOUND")):
        with pytest.raises(PurchasingError) as error:
            call()
        assert error.value.code == code
    other = Purchasing(db, clock=Clock(), store_id="otra-sede")
    assert other.orders() == [] and other.suppliers() == [] and other.pending_by_sku() == {}
    for call in (lambda: other.reschedule("OC-0001", "2026-10-24"), lambda: other.cancel_order("OC-0001", "x"),
                 lambda: other.receive(None, [{"sku": "CEM-050", "cantidad": 1}], oc="OC-0001")):
        with pytest.raises(PurchasingError) as error:
            call()
        assert error.value.code == "PURCHASE_NOT_FOUND"
    assert buying.orders()[0]["estado"] == "pedido" and _stock(db, "CEM-050") == 9


def test_a_receipt_without_order_is_all_extra_and_costs_never_reach_the_agent(db, buying):
    receipt = buying.receive("PV-001", [{"sku": "CEM-025", "cantidad": 4, "costo_unitario": 17777}])
    assert receipt["oc"] is None and receipt["estado_oc"] is None
    assert receipt["lineas"][0]["adicional"] is True and receipt["lineas"][0]["stock_despues"] == 32
    catalog = MockCatalog(db)
    answers = [execute_tool("consultar_disponibilidad", {"sku": "CEM-025"}, catalog=catalog),
               execute_tool("buscar_productos", {"items": [{"text": "cemento gris de 25 kg", "product": "cemento",
                                                            "measure": "25 kg"}]}, catalog=catalog)]
    assert answers[0]["data"]["stock"] == 32 and answers[1]["status"] == "ok"
    assert answers[1]["data"]["results"][0]["matches"][0]["sku"] == "CEM-025"
    assert all("17777" not in json.dumps(answer) and "cost" not in json.dumps(answer) for answer in answers)


def test_inventory_events_gain_an_origin_without_losing_old_rows(tmp_path):
    db = create_mock_db(tmp_path / "old.sqlite3")
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE inventory_events (business_id TEXT NOT NULL, store_id TEXT NOT NULL, "
                           "sku TEXT NOT NULL, at TEXT NOT NULL, field TEXT NOT NULL, before TEXT, after TEXT NOT "
                           "NULL, actor TEXT NOT NULL)")
        connection.execute("INSERT INTO inventory_events VALUES ('demo-ferreteria', 'sede-unica', 'PVC-050', "
                           "'2026-10-20T15:00:00+00:00', 'price_cop', '8000', '8500', 'tendero')")
    connection.close()
    inventory = Inventory(db)
    Inventory(db)  # La migración se puede repetir.
    inventory.update("CEM-050", {"stock": 10})
    history = inventory.history()
    assert [(item["sku"], item["origen"]) for item in history] == [("CEM-050", "panel"), ("PVC-050", "panel")]
    assert [item["sku"] for item in inventory.history(sku="PVC-050")] == ["PVC-050"]
    assert inventory.history(limit=1)[0]["sku"] == "CEM-050"
