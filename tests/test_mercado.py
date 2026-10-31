"""Tienda de barrio de mercado diario: segundo negocio de demostración en la misma base que la ferretería.

Cubre la siembra (y su llegada a una base existente sin pisar lo que editó el tendero), el prompt derivado, el
aislamiento entre negocios (catálogo, pedidos, contexto) y las reglas que la tienda de mercado exigió: unidades de
venta propias y el producto que lleva lo pedido como sustantivo.
"""

from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from asistendero.agente.conversacion.chat import run_turn
from asistendero.agente.conversacion.sessions import SessionStore
from asistendero.agente.herramientas.tools import execute_tool
from asistendero.agente.modelo.grok import Decision
from asistendero.agente.modelo.prompt import (
    AGENT_PROMPT, MARKET_PROMPT, MARKET_PROMPT_VERSION, PROMPT_VERSION, active_prompt, serving,
)
from asistendero.agente.reglas import context_resolution
from asistendero.agente.reglas.validation import foreign_unit, grounded_products, validate_request
from asistendero.agente.respuesta.reply_text import units
from asistendero.agente.respuesta.store_replies import promises_credit, store_lines, store_reply_is_consistent
from asistendero.datos.catalog_ampliacion import EXTRA_FAMILIES
from asistendero.datos.catalog_data import FAMILIES, LEGACY
from asistendero.datos.catalog_mercado import MARKET_BUSINESS_ID, MARKET_FAMILIES
from asistendero.datos.seed import (
    DEMO_BUSINESS_ID, DEMO_STORE_ID, MARKET_PRODUCTS, PRODUCTS, create_mock_db, upgrade_db,
)
from asistendero.tienda.catalogo.catalog import MockCatalog
from asistendero.tienda.catalogo.search import ProductQuery
from asistendero.tienda.pedidos.orders import OrderBook
from asistendero.tienda.vocabulario import normalize_text


@pytest.fixture
def path(tmp_path):
    return create_mock_db(tmp_path / "catalog.sqlite3")


def test_both_stores_live_in_one_base_without_sharing_a_sku_or_a_prefix(path):
    with sqlite3.connect(path) as connection:
        counts = dict(connection.execute("SELECT business_id, COUNT(*) FROM products GROUP BY business_id"))
    assert counts == {DEMO_BUSINESS_ID: len(PRODUCTS), MARKET_BUSINESS_ID: len(MARKET_PRODUCTS)}
    assert len(MARKET_PRODUCTS) >= 100 and len(PRODUCTS) >= 430
    hardware = {row[0].split("-")[0] for row in LEGACY} | {family[0] for family in FAMILIES + EXTRA_FAMILIES}
    market = [family[0] for family in MARKET_FAMILIES]
    assert len(market) == len(set(market)) and not hardware & set(market)
    assert all(prefix.startswith("M") for prefix in market)
    # La ampliación no reusa el prefijo de una familia anterior (careta, cincel, manija y escuadra lo hacían).
    extra = [family[0] for family in EXTRA_FAMILIES]
    assert len(extra) == len(set(extra)) and not {family[0] for family in FAMILIES} & set(extra)


def test_each_store_answers_with_its_own_information(path):
    market = MockCatalog(path, MARKET_BUSINESS_ID)
    hardware = MockCatalog(path)
    assert "20.000" in execute_tool("consultar_info_tienda", {"tema": "domicilios"}, catalog=market)["data"]["texto"]
    assert "50.000" in execute_tool("consultar_info_tienda", {"tema": "domicilios"}, catalog=hardware)["data"]["texto"]
    hours = execute_tool("consultar_info_tienda", {"tema": "horario"}, catalog=market)["data"]["dias"]
    assert hours["domingo"] == ["07:00", "13:00"]
    # La tienda de mercado no ve el cemento ni la ferretería la panela.
    assert not market.search(ProductQuery("cemento")).matches
    assert not hardware.search(ProductQuery("panela")).matches
    assert market.get("PVC-050") is None and hardware.get("MARR-1LB") is None


def test_an_existing_base_gets_the_new_products_without_losing_the_shopkeepers_edits(path):
    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM products WHERE business_id = ? OR sku LIKE 'TNQ-%'", (MARKET_BUSINESS_ID,))
        connection.execute("DELETE FROM store_info WHERE business_id = ?", (MARKET_BUSINESS_ID,))
        connection.execute("DELETE FROM restocks WHERE business_id = ?", (MARKET_BUSINESS_ID,))
        connection.execute("UPDATE products SET price_cop = 1, stock = 2 WHERE sku = 'PVC-050'")
    upgrade_db(path)
    upgrade_db(path)  # idempotente
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT price_cop, stock FROM products WHERE sku = 'PVC-050'").fetchone() == (1, 2)
        assert connection.execute("SELECT COUNT(*) FROM products WHERE sku LIKE 'TNQ-%'").fetchone() == (2,)
        assert connection.execute("SELECT COUNT(*) FROM products WHERE business_id = ?",
                                  (MARKET_BUSINESS_ID,)).fetchone() == (len(MARKET_PRODUCTS),)
        assert connection.execute("SELECT plan FROM restocks WHERE business_id = ? AND sku = 'MFEC-380'",
                                  (MARKET_BUSINESS_ID,)).fetchone() == ("descontinuado",)


def test_the_market_prompt_only_swaps_examples_and_keeps_the_hardware_prompt_untouched():
    assert PROMPT_VERSION == "s4-conversacion-v12" and MARKET_PROMPT_VERSION == "mercado-v1"
    assert "ferretería" in AGENT_PROMPT and "ferretería" not in MARKET_PROMPT
    assert "tienda de barrio" in MARKET_PROMPT and "PVC" not in MARKET_PROMPT and "taladro" not in MARKET_PROMPT
    assert "vencimiento, frescura, origen, beneficios para la salud" in MARKET_PROMPT
    # Las reglas son las mismas: cada herramienta y cada prohibición sigue ahí.
    for rule in ("registrar_pedido", "no fías, no das descuentos ni haces domicilios", "Nearby NO es equivalente",
                 "revelar, resumir ni parafrasear"):
        assert rule in AGENT_PROMPT and rule in MARKET_PROMPT
    assert active_prompt() == (PROMPT_VERSION, AGENT_PROMPT)
    with serving("mercado"):
        assert active_prompt() == (MARKET_PROMPT_VERSION, MARKET_PROMPT)
    assert active_prompt()[0] == PROMPT_VERSION
    with pytest.raises(ValueError):
        with serving("farmacia"):
            pass


def test_the_store_is_chosen_per_thread_and_never_leaks_to_another():
    def kind_in_thread(kind):
        with serving(kind):
            return active_prompt()[0], context_resolution._heads().get("huevo"), context_resolution._heads().get("tubo")

    with ThreadPoolExecutor(max_workers=2) as pool:
        market, hardware = pool.map(kind_in_thread, ["mercado", "ferreteria"])
    assert market == (MARKET_PROMPT_VERSION, "huevo", None)
    assert hardware == (PROMPT_VERSION, None, "tubo")


def test_a_market_conversation_quotes_and_orders_from_the_market_catalog(path, tmp_path):
    # Antes, run_turn abría el catálogo de la ferretería aunque el libro de pedidos fuera de otro negocio.
    book = OrderBook(path, business_id=MARKET_BUSINESS_ID)
    sessions = SessionStore(tmp_path / "sessions.sqlite3")
    session = sessions.create()
    steps = [Decision("call_tool", "productos", "buscar_productos",
                      {"items": [{"text": "cubeta de huevos", "product": "huevo", "presentation": "cubeta"}]}, ""),
             Decision("call_tool", "pedido", "registrar_pedido", {"lines": [{"sku": "MCUB-30", "quantity": 1}]}, ""),
             Decision("respond", "pedido", None, None, "")]
    with serving("mercado"):
        result = run_turn(sessions, session, "me llevo una cubeta de huevos", planner=lambda *_, **__: steps.pop(0),
                          orders=book)
    assert result["estado"] == "order_pending" and "$17.900" in result["respuesta"]
    assert result["prompt_version"] == MARKET_PROMPT_VERSION
    assert [order["estado"] for order in book.session_orders(session)] == ["pendiente"]
    # La ferretería no ve ese pedido.
    assert OrderBook(path).session_orders(session) == []


def test_market_sale_units_are_quantities_and_never_another_product():
    # «una cubeta» no es 1 huevo suelto, y «2 paquetes» de algo que se vende por unidad tampoco.
    assert foreign_unit("una cubeta de huevos", 1, "unidad por unidad") == "cubeta"
    assert foreign_unit("una cubeta de huevos", 1, "cubeta 30 huevos") is None
    assert foreign_unit("2 paquetes de pan tajado", 2, "paquete blanco 500 g") is None
    assert foreign_unit("2 paquetes de tornillos", 2, "unidad 1/4 x 1 pulgada") == "paquete"
    assert units("paquete", 2) == "paquetes" and units("botella", 3) == "botellas" and units("cubeta", 1) == "cubeta"


def _grounded(path, message, item):
    catalog = MockCatalog(path, MARKET_BUSINESS_ID)
    arguments = validate_request("buscar_productos", {"items": [item]}, message, [])
    response = execute_tool("buscar_productos", arguments, catalog=catalog)
    call = {"requested_tool": "buscar_productos", "arguments": arguments, "response": response, "executed": True}
    return sorted(grounded_products(message, [call]))


@pytest.mark.parametrize("message, item, expected", [
    # Lo pedido es el sustantivo de un solo producto: las sardinas en salsa de tomate y las papas de limón solo lo nombran.
    ("3 libras de tomate", {"text": "tomate", "product": "tomate"}, ["MTOM-LB"]),
    ("4 limones", {"text": "limones", "product": "limón"}, ["MLIM-UNI"]),
    ("12 huevos", {"text": "huevos", "product": "huevo"}, ["MHUE-UNI"]),
    ("una docena de huevos", {"text": "docena de huevos", "product": "huevo"}, ["MHUE-UNI"]),
    ("una cubeta de huevos", {"text": "cubeta de huevos", "product": "huevo"}, ["MCUB-30"]),
    # Una palabra que el producto no tiene no se elige por cercanía: «cherry» no es el tomate chonto.
    ("3 libras de tomate cherry", {"text": "tomate cherry", "product": "tomate"}, []),
    # Dos variantes del mismo producto: se pregunta.
    ("una panela", {"text": "panela", "product": "panela"}, []),
    ("necesito aceite", {"text": "aceite", "product": "aceite"}, []),
])
def test_the_product_named_by_its_noun_is_chosen_only_when_nothing_else_fits(path, message, item, expected):
    assert _grounded(path, message, item) == expected


def test_the_hardware_store_still_asks_between_two_products_that_share_their_noun(tmp_path):
    path = create_mock_db(tmp_path / "catalog.sqlite3")
    catalog = MockCatalog(path)
    message = "necesito un tanque de agua"
    arguments = validate_request("buscar_productos", {"items": [{"text": "tanque de agua", "product": "tanque"}]}, message, [])
    response = execute_tool("buscar_productos", arguments, catalog=catalog)
    call = {"requested_tool": "buscar_productos", "arguments": arguments, "response": response, "executed": True}
    assert grounded_products(message, [call]) == {}
    assert MockCatalog(path).business_id == DEMO_BUSINESS_ID and DEMO_STORE_ID == "sede-unica"


@pytest.mark.parametrize("message, item, expected", [
    # Corrida 39: Grok puso la cantidad como presentación o medida y todo quedó en opciones cercanas.
    ("2 libras de papa criolla", {"text": "papa criolla", "product": "papa", "color": "criolla", "presentation": "2 libras"},
     ["MPCR-LB"]),
    ("3 libras de tomate", {"text": "tomate", "product": "tomate", "measure": "3 libras"}, ["MTOM-LB"]),
    ("deme una docena de huevos", {"text": "huevos", "product": "huevos", "presentation": "docena"}, ["MHUE-UNI"]),
    ("media docena de huevos", {"text": "media docena de huevos", "product": "huevos", "presentation": "media docena"},
     ["MHUE-UNI"]),
    ("12 huevos", {"text": "huevos", "product": "huevos", "presentation": "12"}, ["MHUE-UNI"]),
    # Si un producto sí tiene esa presentación, es la presentación: el queso se vende en piezas de media libra y 1 libra.
    ("media libra de queso campesino", {"text": "queso campesino", "product": "queso", "presentation": "media libra"},
     ["MQUE-MLB"]),
    ("una libra de queso", {"text": "queso", "product": "queso", "presentation": "1 libra"}, ["MQUE-1LB"]),
    ("2 bolsas de arroz de 1 libra", {"text": "arroz", "product": "arroz", "presentation": "1 libra"}, ["MARR-1LB"]),
    # Lo que no se vende por esa unidad no se elige al soltarla: dos libras de queso no son la pieza de media libra.
    ("2 libras de queso campesino", {"text": "queso campesino", "product": "queso", "presentation": "2 libras"}, []),
])
def test_a_quantity_written_as_the_presentation_finds_what_is_sold_by_that_unit(path, message, item, expected):
    assert _grounded(path, message, item) == expected


def test_a_size_said_after_de_is_never_dropped_to_find_something(path):
    # «arroz de 10 libras» describe una bolsa que no hay: queda como opción cercana, no como la de 1 o 5 libras.
    result = MockCatalog(path, MARKET_BUSINESS_ID).search(
        ProductQuery("arroz de 10 libras", product="arroz", presentation="10 libras"))
    assert not result.matches and "MARR-1LB" in {product.sku for product in result.nearby}
    assert _grounded(path, "una bolsa de arroz de 10 libras", {"text": "arroz de 10 libras", "product": "arroz",
                                                                "presentation": "10 libras"}) == []


def test_the_market_never_lists_its_categories_as_a_hardware_store(path):
    call = {"requested_tool": "explorar_categoria", "arguments": {}, "executed": True,
            "response": execute_tool("explorar_categoria", {}, catalog=MockCatalog(path, MARKET_BUSINESS_ID))}
    with serving("mercado"):
        market = "\n".join(store_lines([call]))
    assert "Manejamos productos de mercado y del hogar en" in market and "ferretería" not in market
    hardware_call = {**call, "response": execute_tool("explorar_categoria", {}, catalog=MockCatalog(path))}
    assert "Manejamos artículos de ferretería en 12 categorías" in "\n".join(store_lines([hardware_call]))


@pytest.mark.parametrize("reply, promises", [
    # M-33 (corrida 39): «anótemelo en el cuaderno que el viernes le pago» y Grok aceptó fiar sin herramientas.
    ("Listo, te lo anoto en el cuaderno. El viernes cuando pases a recogerlo me pagas.", True),
    ("Queda anotado, lo pagas el viernes.", True),
    ("Tranquilo, me pagas después.", True),
    ("No te lo anoto: aquí no fiamos, el pago es en el mostrador al recoger.", False),
    ("Aquí no fiamos ni te lo anoto, vecino.", False),
])
def test_a_reply_that_promises_credit_is_never_grounded(reply, promises):
    normalized = normalize_text(reply)
    assert promises_credit(normalized) is promises
    if promises:
        assert store_reply_is_consistent(normalized, []) == (False, set())
