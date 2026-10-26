"""Asistente de bodega: Grok interpreta, el servidor arma la propuesta y nada cambia hasta que el tendero confirma.

Ninguna prueba llama a Grok: ``interpret`` es un interpretador falso que devuelve lo que habría dicho Grok, y
``interpret_text`` se prueba con un ``complete`` falso que guarda el payload.
"""

from datetime import datetime, timedelta
import json
import sqlite3

import pytest

from asistendero.grok import ModelError
from asistendero.inventory import Inventory
from asistendero.orders import BOGOTA, OrderBook
from asistendero.seed import create_mock_db
from asistendero.stock_assistant import (MAX_OPERATIONS, MAX_TEXT_CHARS, STOCK_PROMPT, STOCK_PROMPT_VERSION,
                                         StockAssistantError, interpret_text)
from asistendero.stock_proposal import VALID_MINUTES, StockAssistant

EXAMPLE = ("ya llegaron los 20 bultos de cemento, de los 15 galones de pintura blanca solo llegaron 10 y el "
           "proveedor mandó 6 brochas de 2 pulgadas de más")
PROPOSAL_KEYS = {"id", "texto", "creada", "vence", "aplicable", "advertencias", "dudas", "operaciones"}
RECEPTION_LINE_KEYS = {"sku", "nombre", "variante", "unidad", "stock_antes", "recibido", "stock_despues", "pendiente",
                       "adicional", "cantidad_adicional"}


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 21, 10, 0, tzinfo=BOGOTA)

    def __call__(self):
        return self.now


class FakeGrok:
    """Lo que habría interpretado Grok; guarda cada texto y contexto que recibió."""

    def __init__(self, *operations: dict, dudas: list[str] | None = None):
        self.reply = {"operaciones": list(operations), "dudas": dudas or []}
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, text: str, context: dict) -> dict:
        self.calls.append((text, context))
        return self.reply


def op(tipo: str, producto: str, **fields) -> dict:
    return {"tipo": tipo, "producto": producto, **fields}


@pytest.fixture
def db(tmp_path):
    return create_mock_db(tmp_path / "catalog.sqlite3")


@pytest.fixture
def clock():
    return Clock()


def assistant(db, clock, grok: FakeGrok, with_order: bool = True) -> StockAssistant:
    helper = StockAssistant(db, clock=clock, interpret=grok)
    if not helper.purchasing.suppliers():
        helper.purchasing.add_supplier("Distribuidora El Bulto")
    if with_order:
        helper.purchasing.create_order("PV-001", [{"sku": "CEM-050", "cantidad": 20},
                                                  {"sku": "PIN-BLA", "cantidad": 15}], "2026-10-21")
    return helper


def stock(db, sku: str) -> dict:
    return next(item for item in Inventory(db).products(sku) if item["sku"] == sku)


def snapshot(helper: StockAssistant) -> tuple:
    """Todo lo que una propuesta no debe tocar: bodega, precios, pedidos, recepciones e historial."""
    return (helper.purchasing.inventory.products(), helper.purchasing.orders(), helper.purchasing.receipts(),
            helper.purchasing.inventory.history(limit=500))


EXAMPLE_GROK = (op("recepcion", "bultos de cemento", cantidad=20),
                op("recepcion", "galones de pintura blanca", sku="PIN-BLA", cantidad=10),
                op("recepcion", "brochas de 2 pulgadas", cantidad=6))


def test_the_example_proposes_before_and_after_and_changes_nothing_until_confirmed(db, clock):
    helper = assistant(db, clock, FakeGrok(*EXAMPLE_GROK))
    before = snapshot(helper)
    proposal = helper.propose(EXAMPLE)

    assert set(proposal) == PROPOSAL_KEYS and proposal["id"].startswith("AS-") and proposal["aplicable"] is True
    assert (proposal["creada"], proposal["vence"]) == ("2026-10-21 10:00", "2026-10-21 10:15")
    assert proposal["advertencias"] == [] and proposal["texto"] == EXAMPLE
    [arrival] = proposal["operaciones"]
    assert set(arrival) == {"tipo", "titulo", "aplicable", "oc", "proveedor", "lineas"}
    assert (arrival["tipo"], arrival["oc"], arrival["proveedor"]) == ("recepcion", "OC-0001", "Distribuidora El Bulto")
    cement, paint, brush = arrival["lineas"]
    assert all(set(line) == RECEPTION_LINE_KEYS for line in arrival["lineas"])
    assert (cement["sku"], cement["stock_antes"], cement["recibido"], cement["stock_despues"],
            cement["pendiente"]) == ("CEM-050", 9, 20, 29, 0)
    assert (paint["sku"], paint["stock_antes"], paint["stock_despues"], paint["pendiente"]) == ("PIN-BLA", 4, 14, 5)
    assert (brush["sku"], brush["adicional"], brush["cantidad_adicional"], brush["stock_despues"]) == (
        "BRO-2", True, 6, 41)
    assert not cement["adicional"] and not paint["adicional"]
    # Proponer no escribe nada: ni bodega, ni pedido, ni recepción, ni historial.
    assert snapshot(helper) == before

    result = helper.apply(proposal["id"])
    assert result["id"] == proposal["id"] and result["aplicada"] is True
    assert result["resultados"] == ["Llegada R-0001 (pedido OC-0001): +20 Cemento gris bulto de 50 kg, +10 Pintura "
                                    "blanca vinilo galón, +6 Brocha de cerda 2 pulgadas (6 adicionales)."]
    assert (stock(db, "CEM-050")["stock"], stock(db, "PIN-BLA")["stock"], stock(db, "BRO-2")["stock"]) == (29, 14, 41)
    [receipt] = helper.purchasing.receipts()
    assert receipt["nota"] == f"asistente {proposal['id']}" and receipt["estado_oc"] == "parcial"
    assert helper.purchasing.pending_by_sku()["PIN-BLA"]["pendiente"] == 5

    # Un doble clic devuelve el mismo resultado y no repite la llegada.
    after = snapshot(helper)
    assert helper.apply(proposal["id"]) == result
    assert snapshot(helper) == after and len(helper.purchasing.receipts()) == 1
    [entry] = helper.history()
    assert entry["estado"] == "aplicada" and entry["texto"] == EXAMPLE and entry["id"] == proposal["id"]
    assert entry["resumen"].startswith("Llegada del pedido OC-0001")
    with pytest.raises(StockAssistantError) as error:
        helper.discard(proposal["id"])
    assert error.value.code == "PROPOSAL_APPLIED"


@pytest.mark.parametrize("operation", [
    op("recepcion", "galones de pintura blanca", cantidad=30, fecha="2026-10-22"),
    # Grok no puso fecha, pero el texto dice «mañana»: la defensa está en el código, no en el prompt.
    op("recepcion", "galones de pintura blanca", cantidad=30),
])
def test_a_future_arrival_never_adds_stock_even_if_grok_calls_it_a_reception(db, clock, operation):
    helper = assistant(db, clock, FakeGrok(operation))
    before = snapshot(helper)
    proposal = helper.propose("mañana llegan 30 galones de pintura blanca")
    assert proposal["aplicable"] is False and proposal["operaciones"] == []
    assert "entrega futura" in proposal["advertencias"][0]
    with pytest.raises(StockAssistantError) as error:
        helper.apply(proposal["id"])
    assert error.value.code == "PROPOSAL_NOT_APPLICABLE"
    assert snapshot(helper) == before and stock(db, "PIN-BLA")["stock"] == 4


def test_ambiguous_or_unknown_products_are_asked_never_guessed(db, clock):
    helper = assistant(db, clock, FakeGrok(op("recepcion", "brochas", cantidad=6),
                                           op("cambio_precio", "tornillos de oro", precio_cop=5000)), with_order=False)
    before = snapshot(helper)
    proposal = helper.propose("llegaron 6 brochas y los tornillos de oro ahora valen 5000")
    assert proposal["aplicable"] is False
    assert [(item["tipo"], item["aplicable"], item["lineas"]) for item in proposal["operaciones"]] == [
        ("recepcion", False, []), ("cambio_precio", False, [])]
    ambiguous, unknown = proposal["advertencias"]
    assert ambiguous.startswith("¿Cuál de estos es «brochas»?") and ambiguous.count("Brocha de cerda") == 3
    assert unknown.startswith("No identifiqué «tornillos de oro»")
    with pytest.raises(StockAssistantError) as error:
        helper.apply(proposal["id"])
    assert error.value.code == "PROPOSAL_NOT_APPLICABLE" and snapshot(helper) == before


def test_an_arrival_without_order_or_supplier_is_not_charged_to_anyone(db, clock):
    helper = assistant(db, clock, FakeGrok(op("recepcion", "brochas de 2 pulgadas", cantidad=6)), with_order=False)
    proposal = helper.propose("llegaron 6 brochas de 2 pulgadas")
    assert proposal["aplicable"] is False and "¿Quién trajo" in proposal["advertencias"][0]
    named = assistant(db, clock, FakeGrok(op("recepcion", "brochas de 2 pulgadas", cantidad=6,
                                             proveedor="distribuidora el bulto")), with_order=False)
    [arrival] = named.propose("el bulto trajo 6 brochas de 2 pulgadas")["operaciones"]
    assert arrival["aplicable"] and arrival["oc"] is None and arrival["proveedor"] == "Distribuidora El Bulto"
    assert arrival["lineas"][0]["adicional"] is True


def test_a_sku_grok_did_not_see_in_open_orders_is_ignored(db, clock):
    # THI-GAL no está en ningún pedido abierto: el producto sale del texto, no del SKU que mandó Grok.
    helper = assistant(db, clock, FakeGrok(op("consulta", "brochas de 2 pulgadas", sku="THI-GAL")))
    [query] = helper.propose("¿cuántas brochas de 2 pulgadas quedan?")["operaciones"]
    assert [line["sku"] for line in query["lineas"]] == ["BRO-2"]


def test_expired_or_discarded_proposals_are_never_applied(db, clock):
    helper = assistant(db, clock, FakeGrok(*EXAMPLE_GROK))
    before = snapshot(helper)
    late = helper.propose(EXAMPLE)
    dropped = helper.propose(EXAMPLE)
    assert helper.discard(dropped["id"]) == {"id": dropped["id"], "descartada": True}
    with pytest.raises(StockAssistantError) as error:
        helper.apply(dropped["id"])
    assert error.value.code == "PROPOSAL_DISCARDED"
    clock.now += timedelta(minutes=VALID_MINUTES)
    with pytest.raises(StockAssistantError) as error:
        helper.apply(late["id"])
    assert error.value.code == "PROPOSAL_EXPIRED"
    assert snapshot(helper) == before
    assert {item["id"]: item["estado"] for item in helper.history()} == {late["id"]: "vencida",
                                                                         dropped["id"]: "descartada"}
    with pytest.raises(StockAssistantError) as error:
        helper.apply("AS-NOEXISTE")
    assert error.value.code == "PROPOSAL_NOT_FOUND"


def test_a_proposal_is_stale_if_stock_or_price_changed_and_applies_nothing(db, clock):
    helper = assistant(db, clock, FakeGrok(*EXAMPLE_GROK, op("cambio_precio", "thinner galón", precio_cop=31900)))
    proposal = helper.propose(EXAMPLE + " y sube el thinner galón a 31900")
    assert [item["tipo"] for item in proposal["operaciones"]] == ["recepcion", "cambio_precio"]
    # Entre la propuesta y la confirmación, alguien corrigió la bodega del cemento en el panel.
    Inventory(db).update("CEM-050", {"stock": 12})
    before = snapshot(helper)
    with pytest.raises(StockAssistantError) as error:
        helper.apply(proposal["id"])
    assert error.value.code == "PROPOSAL_STALE" and "Vuelve a contármelo" in str(error.value)
    assert snapshot(helper) == before and stock(db, "THI-GAL")["precio_cop"] == 29900
    assert helper.history()[0]["estado"] == "pendiente"


def test_price_change_shows_before_after_warns_on_big_jumps_and_logs_the_assistant(db, clock):
    helper = assistant(db, clock, FakeGrok(op("cambio_precio", "thinner galón", precio_cop=59900)))
    proposal = helper.propose("sube el thinner galón a 59.900")
    [change] = proposal["operaciones"]
    assert change["aplicable"] and change["lineas"] == [{"sku": "THI-GAL", "nombre": "Thinner", "variante": "galón",
                                                         "unidad": "unidad", "precio_antes": 29900,
                                                         "precio_nuevo": 59900}]
    assert "más del 50 %" in proposal["advertencias"][0]
    assert stock(db, "THI-GAL")["precio_cop"] == 29900
    assert helper.apply(proposal["id"])["resultados"] == ["Precio de Thinner galón: $29.900 → $59.900."]
    assert stock(db, "THI-GAL")["precio_cop"] == 59900
    [event] = Inventory(db).history(sku="THI-GAL")
    assert (event["campo"], event["antes"], event["despues"], event["origen"]) == (
        "precio", "29900", "59900", f"asistente {proposal['id']}")


def test_a_count_never_goes_below_what_is_reserved(db, clock):
    OrderBook(db, clock=clock).create("cliente-1", [("BRO-2", 3)])
    helper = assistant(db, clock, FakeGrok(op("correccion_stock", "brochas de 2 pulgadas", cantidad=2)),
                       with_order=False)
    proposal = helper.propose("conté 2 brochas de 2 pulgadas")
    assert proposal["aplicable"] is False and "3 apartadas" in proposal["advertencias"][0]
    fixed = assistant(db, clock, FakeGrok(op("correccion_stock", "brochas de 2 pulgadas", cantidad=30)),
                      with_order=False)
    [count] = fixed.propose("conté 30 brochas de 2 pulgadas")["operaciones"]
    assert count["lineas"][0] == {"sku": "BRO-2", "nombre": "Brocha de cerda", "variante": "2 pulgadas",
                                       "unidad": "unidad", "stock_antes": 35, "stock_nuevo": 30, "apartado": 3}


def test_rescheduling_moves_the_order_date_and_never_adds_stock(db, clock):
    helper = assistant(db, clock, FakeGrok(op("programar_entrega", "galones de pintura blanca", cantidad=5,
                                              fecha="2026-10-23")))
    proposal = helper.propose("los 5 galones de pintura blanca que faltan llegan el viernes")
    [move] = proposal["operaciones"]
    assert (move["tipo"], move["oc"], move["fecha_antes"], move["fecha_nueva"]) == (
        "programar_entrega", "OC-0001", "2026-10-21", "2026-10-23")
    assert [(line["sku"], line["pendiente"]) for line in move["lineas"]] == [("CEM-050", 20), ("PIN-BLA", 15)]
    # La fecha es de todo el pedido: se avisa que también mueve el cemento.
    assert any("también mueve: Cemento gris" in text for text in proposal["advertencias"])
    helper.apply(proposal["id"])
    assert helper.purchasing.orders()[0]["fecha_estimada"] == "2026-10-23"
    assert stock(db, "PIN-BLA")["stock"] == 4 and helper.purchasing.receipts() == []


def test_a_delivery_without_open_order_becomes_a_supplier_order_only_with_a_supplier(db, clock):
    lone = assistant(db, clock, FakeGrok(op("programar_entrega", "thinner galón", cantidad=12, fecha="2026-10-24")),
                     with_order=False)
    proposal = lone.propose("el viernes llegan 12 thinner galón")
    assert proposal["aplicable"] is False and "proveedor" in proposal["advertencias"][-1]
    helper = assistant(db, clock, FakeGrok(op("programar_entrega", "thinner galón", cantidad=12, fecha="2026-10-24",
                                              proveedor="Distribuidora El Bulto")), with_order=False)
    proposal = helper.propose("el viernes el bulto trae 12 thinner galón")
    [order] = proposal["operaciones"]
    assert (order["tipo"], order["proveedor"], order["fecha_estimada"]) == (
        "pedido_proveedor", "Distribuidora El Bulto", "2026-10-24")
    assert order["lineas"] == [{"sku": "THI-GAL", "nombre": "Thinner", "variante": "galón", "unidad": "unidad",
                                "cantidad": 12}]
    helper.apply(proposal["id"])
    assert helper.purchasing.pending_by_sku()["THI-GAL"] == {"pendiente": 12, "llega": "2026-10-24"}
    assert stock(db, "THI-GAL")["stock"] == 6


def test_a_query_only_shows_numbers_and_has_nothing_to_apply(db, clock):
    helper = assistant(db, clock, FakeGrok(op("consulta", "galones de pintura blanca")))
    proposal = helper.propose("¿cuántos galones de pintura blanca hay?")
    [query] = proposal["operaciones"]
    assert query["aplicable"] is False and proposal["aplicable"] is False
    assert query["lineas"] == [{"sku": "PIN-BLA", "nombre": "Pintura blanca vinilo", "variante": "galón",
                                "unidad": "galón", "stock": 4, "apartado": 0, "disponible": 4, "precio_cop": 56000,
                                "en_camino": 15}]
    assert helper.history()[0]["resumen"] == "Consulta"


@pytest.mark.parametrize("bad", [
    {"operaciones": [{"tipo": "regalar", "producto": "cemento"}]},
    {"operaciones": [{"tipo": "recepcion", "producto": "cemento", "cantidad": "20"}]},
    {"operaciones": [{"tipo": "recepcion", "producto": "cemento", "cantidad": 20, "precio_inventado": 1}]},
    {"operaciones": [{"tipo": "recepcion", "producto": "cemento", "fecha": "mañana"}]},
    {"operaciones": [{"tipo": "consulta", "producto": "cemento"}] * (MAX_OPERATIONS + 1)},
    {"dudas": []},
    ["no", "es", "un", "objeto"],
])
def test_an_invalid_interpretation_is_an_error_never_a_proposal(db, clock, bad):
    helper = StockAssistant(db, clock=clock, interpret=lambda text, context: bad)
    with pytest.raises(StockAssistantError) as error:
        helper.propose("llegaron 20 bultos de cemento")
    assert error.value.code == "ASSISTANT_INVALID_OUTPUT" and helper.history() == []


def test_interpret_text_sends_the_message_and_open_orders_but_never_the_catalog(db, clock):
    helper = assistant(db, clock, FakeGrok())
    context = helper._context()[0]
    sent = []

    def complete(system, payload):
        sent.append((system, payload))
        return json.dumps({"operaciones": [op("recepcion", "bultos de cemento", sku="CEM-050", cantidad=20)],
                           "dudas": []}), "grok-4.20-0309-non-reasoning", 900, 60, 0, None

    result = interpret_text("ya llegaron los 20 bultos", context, complete=complete)
    [(system, payload)] = sent
    assert system == STOCK_PROMPT and set(payload) == {"mensaje", "hoy", "proveedores", "pedidos_abiertos"}
    assert payload["mensaje"] == "ya llegaron los 20 bultos"
    assert payload["hoy"] == {"fecha": "2026-10-21", "dia": "miércoles", "hora": "10:00"}
    assert payload["proveedores"] == [{"proveedor": "PV-001", "nombre": "Distribuidora El Bulto"}]
    [order] = payload["pedidos_abiertos"]
    assert order["lineas"][0] == {"sku": "CEM-050", "nombre": "Cemento gris", "variante": "bulto de 50 kg",
                                  "pendiente": 20}
    # Solo viajan los productos de los pedidos abiertos: ni el resto del catálogo, ni precios, ni costos.
    sent_text = json.dumps(payload, ensure_ascii=False)
    with sqlite3.connect(db) as connection:
        other_skus = [row[0] for row in connection.execute("SELECT sku FROM products WHERE sku NOT IN (?, ?)",
                                                           ("CEM-050", "PIN-BLA"))]
    assert not any(f'"{sku}"' in sent_text for sku in other_skus)
    assert "precio" not in sent_text and "costo" not in sent_text
    assert result["operaciones"][0]["cantidad"] == 20 and result["operaciones"][0]["oc"] is None
    assert result["uso"]["prompt"] == STOCK_PROMPT_VERSION and result["uso"]["tokens_entrada"] == 900


@pytest.mark.parametrize("text", ["", "   ", "x" * (MAX_TEXT_CHARS + 1)])
def test_interpret_text_rejects_empty_or_long_text_before_calling_grok(text):
    calls = []
    with pytest.raises(StockAssistantError) as error:
        interpret_text(text, {}, complete=lambda *args: calls.append(args))
    assert error.value.code == "INVALID_ARGUMENT" and calls == []


@pytest.mark.parametrize("raw", ["no es json", '{"operaciones": "todas"}', '{"operaciones": [], "extra": 1}'])
def test_interpret_text_turns_invalid_json_into_a_stable_code(raw):
    with pytest.raises(StockAssistantError) as error:
        interpret_text("llegaron 20 bultos", {}, complete=lambda *args: (raw, "grok-4.20", 1, 1, 0, None))
    assert error.value.code == "ASSISTANT_INVALID_OUTPUT"


def test_interpret_text_keeps_the_model_error_code_without_its_details():
    def failing(*args):
        raise ModelError("MODEL_TIMEOUT", "Grok no respondió a tiempo.")
    with pytest.raises(StockAssistantError) as error:
        interpret_text("llegaron 20 bultos", {}, complete=failing)
    assert (error.value.code, str(error.value)) == ("MODEL_TIMEOUT", "Grok no respondió a tiempo.")
