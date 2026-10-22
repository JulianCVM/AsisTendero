"""Plataforma del tendero: inventario con historial, ventas del chat y barreras del servidor local."""

from datetime import datetime, timedelta
import http.client
import json
from pathlib import Path
import re
import shutil
from threading import Thread

import pytest

from asistendero import tendero
from asistendero.catalog import MockCatalog
from asistendero.inventory import Inventory, InventoryError
from asistendero.orders import BOGOTA, OrderBook
from asistendero.sales import day_summary, order_board
from asistendero.seed import create_mock_db


UI = Path(__file__).resolve().parents[1] / "src" / "asistendero" / "ui"


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 21, 10, 0, tzinfo=BOGOTA)

    def __call__(self):
        return self.now


@pytest.fixture
def shop(tmp_path):
    path = create_mock_db(tmp_path / "catalog.sqlite3")
    return Inventory(path), OrderBook(path, clock=Clock()), MockCatalog(path)


def test_price_and_stock_edits_reach_the_agent_and_leave_an_audit_trail(shop):
    inventory, _, catalog = shop
    updated = inventory.update("PVC-050", {"precio_cop": 9000, "stock": 20})
    assert updated["precio_cop"] == 9000 and updated["stock"] == 20 and updated["disponible"] == 20
    assert catalog.get("PVC-050").price_cop == 9000 and catalog.get("PVC-050").stock == 20
    history = inventory.history()
    assert {(item["campo"], item["antes"], item["despues"]) for item in history} == {
        ("precio", "8500", "9000"), ("existencias", "12", "20")}


@pytest.mark.parametrize("changes", [
    {"precio_cop": -1}, {"stock": 1.5}, {"stock": True}, {"precio_cop": "9000"}, {"nombre": "otro"}, {},
])
def test_invalid_edits_are_rejected_without_touching_the_product(shop, changes):
    inventory, _, catalog = shop
    with pytest.raises(InventoryError) as error:
        inventory.update("PVC-050", changes)
    assert error.value.code == "INVALID_ARGUMENT"
    assert catalog.get("PVC-050").price_cop == 8500 and inventory.history() == []


def test_stock_cannot_drop_below_what_customers_have_on_hold(shop):
    inventory, book, _ = shop
    book.create("sesion-a", [("PVC-050", 5)])
    product = inventory.products("PVC-050")[0]
    assert (product["stock"], product["apartado"], product["disponible"]) == (12, 5, 7)
    with pytest.raises(InventoryError) as error:
        inventory.update("PVC-050", {"stock": 4})
    assert error.value.code == "STOCK_BELOW_RESERVED"
    assert inventory.update("PVC-050", {"stock": 5})["disponible"] == 0


def test_new_products_are_searchable_by_the_agent_and_skus_never_repeat(shop):
    inventory, _, catalog = shop
    added = inventory.add({"sku": "TUB-099", "nombre": "Tubo PVC sanitario", "variante": "3 pulgadas",
                           "unidad": "metro", "precio_cop": 21000, "stock": 6, "categoria": "Plomería"})
    assert added["sku"] == "TUB-099" and catalog.get("TUB-099").price_cop == 21000
    with pytest.raises(InventoryError) as error:
        inventory.add({"sku": "TUB-099", "nombre": "Otro", "variante": "x", "unidad": "metro", "precio_cop": 1,
                       "stock": 1, "categoria": "Plomería"})
    assert error.value.code == "DUPLICATE_SKU"
    for bad in ({"sku": "tub 1"}, {"unidad": "kilo"}, {"precio_cop": 10**9}, {"nombre": ""}):
        product = {"sku": "TUB-100", "nombre": "Tubo", "variante": "1", "unidad": "metro", "precio_cop": 1,
                   "stock": 1, "categoria": "Plomería", **bad}
        with pytest.raises(InventoryError):
            inventory.add(product)
    assert catalog.get("TUB-100") is None


def test_delivered_orders_become_the_day_sales(shop):
    inventory, book, _ = shop
    sold = book.create("sesion-a", [("PVC-050", 3), ("CEM-050", 1)])
    book.confirm("sesion-a", sold["pedido"])
    book.deliver(sold["pedido"])
    waiting = book.create("sesion-b", [("PVC-050", 2)])
    summary = day_summary(book)
    assert summary["dia"] == "2026-10-21" and summary["ventas"] == 1
    assert summary["total_cop"] == sold["total_cop"]
    assert summary["por_estado"]["entregado"] == 1 and summary["por_estado"]["pendiente"] == 1
    assert [order["pedido"] for order in summary["por_recoger"]] == [waiting["pedido"]]
    assert summary["mas_vendidos"][0]["sku"] == "PVC-050" and summary["mas_vendidos"][0]["cantidad"] == 3
    assert inventory.products("PVC-050")[0]["stock"] == 9
    # El tablero muestra la conversación abreviada, nunca el identificador completo.
    assert all(len(order["conversacion"]) == 8 for order in order_board(book))


def test_expired_holds_show_up_as_expired_for_the_shopkeeper(shop):
    _, book, _ = shop
    order = book.create("sesion-a", [("PVC-050", 3)])
    book.clock.now += timedelta(minutes=6)
    assert order_board(book, "vencido")[0]["pedido"] == order["pedido"]
    with pytest.raises(ValueError):
        order_board(book, "robado")


@pytest.fixture
def server(shop):
    inventory, book, _ = shop
    instance = tendero.make_server(0, inventory, book)
    thread = Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    yield instance
    instance.shutdown()
    instance.server_close()
    thread.join(timeout=5)


def _request(server, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    payload = json.dumps(body) if body is not None else None
    base = {"Content-Type": "application/json"} if body is not None else {}
    try:
        connection.request(method, path, payload, {**base, **(headers or {})})
    except PermissionError:
        pytest.skip("Este entorno restringe conexiones a sockets locales")
    response = connection.getresponse()
    data = response.read().decode("utf-8")
    connection.close()
    return response.status, data


def test_server_only_answers_the_local_host_and_origin(server):
    origin = {"Origin": f"http://127.0.0.1:{server.server_port}"}
    assert _request(server, "GET", "/api/inventario", headers={"Host": "tienda.example"})[0] == 403
    assert _request(server, "POST", "/api/pedidos/cancelar", {"pedido": "P-000000"},
                    {"Origin": "http://sitio-externo.example"})[0] == 403
    status, _ = _request(server, "POST", "/api/inventario/actualizar", None, {**origin, "Content-Type": "text/plain"})
    assert status == 415
    status, body = _request(server, "POST", "/api/inventario/actualizar", {"sku": "PVC-050", "precio_cop": "gratis"}, origin)
    assert status == 400 and "precio" in json.loads(body)["error"].casefold()
    assert _request(server, "GET", "/api/secretos")[0] == 404


def test_server_flow_edit_stock_deliver_and_summary(server, shop):
    _, book, _ = shop
    origin = {"Origin": f"http://127.0.0.1:{server.server_port}"}
    status, body = _request(server, "POST", "/api/inventario/actualizar", {"sku": "PVC-050", "stock": 30}, origin)
    assert status == 200 and json.loads(body)["producto"]["stock"] == 30
    order = book.create("sesion-a", [("PVC-050", 4)])
    status, body = _request(server, "POST", "/api/pedidos/entregar", {"pedido": order["pedido"]}, origin)
    assert status == 200 and json.loads(body)["pedido"]["estado"] == "entregado"
    status, body = _request(server, "POST", "/api/pedidos/cancelar", {"pedido": order["pedido"]}, origin)
    assert status == 409 and json.loads(body)["code"] == "ORDER_CLOSED"
    summary = json.loads(_request(server, "GET", "/api/resumen")[1])
    assert summary["ventas"] == 1 and summary["total_cop"] == order["total_cop"]
    pedidos = json.loads(_request(server, "GET", "/api/pedidos?estado=entregado")[1])["pedidos"]
    assert [item["pedido"] for item in pedidos] == [order["pedido"]]


def test_ui_never_uses_inline_code_html_injection_or_blocking_dialogs():
    html = (UI / "tendero.html").read_text(encoding="utf-8")
    script = (UI / "tendero.js").read_text(encoding="utf-8")
    assert not re.search(r"<script>(?!\s*</script>)|\son\w+=|style=", html)
    assert "innerHTML" not in script and not re.search(r"\b(?:alert|confirm|prompt)\(", script)


def test_inventory_releases_the_database_file(tmp_path):
    # Abrir el inventario dejaba una conexión sin cerrar: en Windows la copia de la evaluación no se podía borrar.
    copy = tmp_path / "copia.sqlite3"
    shutil.copy(create_mock_db(tmp_path / "catalog.sqlite3"), copy)
    Inventory(copy).products()
    copy.unlink()
    assert not copy.exists()
