"""Pedidos para recoger en tienda: apartado, confirmación, recogida, vencimiento y competencia entre clientes."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import threading

import pytest

from asistendero.catalog import MockCatalog
from asistendero.orders import BOGOTA, HOLD_MINUTES, OrderBook, OrderError
from asistendero.sales import order_board
from asistendero.seed import create_mock_db


class Clock:
    """Reloj de la tienda que avanza a mano: miércoles 21-10-2026, 10:00 en Bogotá."""

    def __init__(self):
        self.now = datetime(2026, 10, 21, 10, 0, tzinfo=BOGOTA)

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta)


@pytest.fixture
def store(tmp_path):
    path = create_mock_db(tmp_path / "catalog.sqlite3")
    clock = Clock()
    return OrderBook(path, clock=clock), MockCatalog(path), clock


def test_pending_order_holds_stock_and_expires_after_five_minutes(store):
    book, catalog, clock = store
    assert catalog.get("PVC-050").stock == 12
    order = book.create("sesion-a", [("PVC-050", 3)])
    assert order["estado"] == "pendiente" and order["total_cop"] == 25500
    assert order["aparta_hasta"] == "2026-10-21 10:05"
    # Lo apartado no lo ve otro cliente ni el agente.
    assert catalog.get("PVC-050").stock == 9
    clock.advance(minutes=HOLD_MINUTES - 1)
    assert book.expire_due() == []
    clock.advance(minutes=1)
    assert book.expire_due() == [{"pedido": order["pedido"], "session_id": "sesion-a", "antes": "pendiente"}]
    assert catalog.get("PVC-050").stock == 12
    with pytest.raises(OrderError) as error:
        book.confirm("sesion-a", order["pedido"])
    assert error.value.code == "ORDER_EXPIRED"


def test_confirmed_order_is_kept_until_pickup_plus_grace(store):
    book, catalog, clock = store
    order = book.create("sesion-a", [("CEM-050", 2), ("PVC-050", 1)])
    confirmed = book.confirm("sesion-a", order["pedido"])
    assert confirmed["estado"] == "confirmado"
    scheduled = book.schedule("sesion-a", order["pedido"], datetime(2026, 10, 21, 16, 0, tzinfo=BOGOTA), "Lo recoge mi hermano")
    assert scheduled["recogida"] == "2026-10-21 16:00" and scheduled["aparta_hasta"] == "2026-10-21 18:00"
    assert scheduled["nota"] == "Lo recoge mi hermano"
    clock.advance(hours=7, minutes=59)
    assert book.expire_due() == []
    assert catalog.get("CEM-050").stock == 7
    clock.advance(minutes=1)
    assert [item["antes"] for item in book.expire_due()] == ["confirmado"]
    assert catalog.get("CEM-050").stock == 9


@pytest.mark.parametrize(("moment", "code"), [
    (datetime(2026, 10, 21, 10, 5, tzinfo=BOGOTA), "PICKUP_IN_PAST"),
    (datetime(2026, 10, 21, 19, 0, tzinfo=BOGOTA), "PICKUP_OUTSIDE_HOURS"),
    (datetime(2026, 10, 25, 10, 0, tzinfo=BOGOTA), "PICKUP_OUTSIDE_HOURS"),  # domingo cerrado
    (datetime(2026, 10, 24, 15, 0, tzinfo=BOGOTA), "PICKUP_OUTSIDE_HOURS"),  # sábado cierra a las 14:00
    (datetime(2026, 11, 3, 10, 0, tzinfo=BOGOTA), "PICKUP_TOO_FAR"),
])
def test_pickup_must_be_soon_and_inside_store_hours(store, moment, code):
    book, _, _ = store
    order = book.create("sesion-a", [("PVC-050", 1)])
    with pytest.raises(OrderError) as error:
        book.schedule("sesion-a", order["pedido"], moment, None)
    assert error.value.code == code


def test_a_customer_only_sees_and_changes_their_own_orders(store):
    book, _, _ = store
    order = book.create("sesion-a", [("PVC-050", 1)])
    for action in (lambda: book.confirm("sesion-b", order["pedido"]), lambda: book.get(order["pedido"], "sesion-b"),
                   lambda: book.cancel(order["pedido"], "sesion-b")):
        with pytest.raises(OrderError) as error:
            action()
        assert error.value.code == "ORDER_NOT_FOUND"
    assert book.session_orders("sesion-b") == []
    assert [item["pedido"] for item in book.session_orders("sesion-a")] == [order["pedido"]]


def test_insufficient_stock_and_active_order_limit(store):
    book, _, _ = store
    with pytest.raises(OrderError) as error:
        book.create("sesion-a", [("PVC-050", 13)])
    assert error.value.code == "INSUFFICIENT_STOCK" and "12" in str(error.value)
    for _ in range(3):
        book.create("sesion-a", [("CEM-050", 1)])
    with pytest.raises(OrderError) as error:
        book.create("sesion-a", [("CEM-050", 1)])
    assert error.value.code == "TOO_MANY_ORDERS"


def test_cancel_releases_and_deliver_discounts_physical_stock(store):
    book, catalog, _ = store
    cancelled = book.create("sesion-a", [("PVC-050", 4)])
    assert book.cancel(cancelled["pedido"], "sesion-a")["estado"] == "cancelado"
    assert catalog.get("PVC-050").stock == 12
    sold = book.create("sesion-a", [("PVC-050", 5)])
    book.confirm("sesion-a", sold["pedido"])
    assert book.deliver(sold["pedido"])["estado"] == "entregado"
    assert catalog.get("PVC-050").stock == 7
    with pytest.raises(OrderError) as error:
        book.deliver(sold["pedido"])
    assert error.value.code == "ORDER_CLOSED"
    history = [event["estado"] for event in order_board(book)[0]["historial"]]
    assert history == ["pendiente", "confirmado", "entregado"]


def test_two_customers_cannot_hold_the_last_units_at_the_same_time(store):
    book, catalog, _ = store
    stock = catalog.get("CEM-050").stock
    barrier = threading.Barrier(6)

    def attempt(index):
        barrier.wait()
        try:
            return book.create(f"sesion-{index}", [("CEM-050", stock // 2 + 1)])["pedido"]
        except OrderError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(attempt, range(6)))
    won = [result for result in results if result.startswith("P-")]
    assert len(won) == 1
    assert results.count("INSUFFICIENT_STOCK") == 5
    assert catalog.get("CEM-050").stock == stock - (stock // 2 + 1)


# --- El flujo de pedidos dentro de una conversación, con un Grok falso -------------------------------------

from asistendero.chat import run_turn  # noqa: E402
from asistendero.executor import catalog_executor  # noqa: E402
from asistendero.grok import Decision  # noqa: E402
from asistendero.graph import build_graph  # noqa: E402
from asistendero.order_watch import WARN_BEFORE, Watcher, sweep  # noqa: E402
from asistendero.sessions import SessionStore  # noqa: E402


PVC_HALF = {"text": "tubo PVC de 1/2 para agua", "product": "tubo", "material": "PVC", "measure": "1/2 pulgada", "use": "agua"}


def tool(name, **arguments):
    return Decision("call_tool", "pedido", name, arguments, "")


def say(reply="", intent="pedido"):
    return Decision("respond", intent, None, None, reply)


class Script:
    """Grok falso: devuelve las decisiones en orden y guarda lo que recibió en cada paso."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.seen = []

    def __call__(self, message, observations, remaining, context=None):
        self.seen.append({"observaciones": observations, "contexto": context})
        step = self.steps.pop(0)
        # Un paso puede depender de lo observado, como el código del pedido que acaba de registrarse.
        return step(observations) if callable(step) else step


@pytest.fixture
def chat(tmp_path):
    path = create_mock_db(tmp_path / "catalog.sqlite3")
    clock = Clock()
    book = OrderBook(path, clock=clock)
    sessions = SessionStore(tmp_path / "sessions.sqlite3")

    def turn(session, message, *steps):
        planner = Script(*steps)
        result = run_turn(sessions, session, message, planner=planner, orders=book)
        result["planner"] = planner
        return result

    return turn, sessions, book, MockCatalog(path), clock


def _quote_turn(turn, session):
    return turn(session, "Necesito 3 metros de tubo PVC de 1/2 para agua",
                tool("buscar_productos", items=[PVC_HALF]),
                tool("calcular_cotizacion_informativa", lines=[{"sku": "PVC-050", "quantity": 3}]), say())


def test_full_order_flow_quote_register_confirm_and_schedule_pickup(chat):
    turn, sessions, book, catalog, _ = chat
    session = sessions.create()
    assert _quote_turn(turn, session)["estado"] == "quoted"

    # El SKU sale de los productos de la sesión y la cantidad, de lo que el cliente dijo antes.
    registered = turn(session, "listo, me los llevo", tool("registrar_pedido", lines=[{"sku": "PVC-050", "quantity": 3}]), say())
    assert registered["estado"] == "order_pending"
    code = registered["tool_calls"][0]["response"]["data"]["pedido"]
    assert code in registered["respuesta"] and "$25.500" in registered["respuesta"]
    assert "¿Confirmas el pedido?" in registered["respuesta"] and "mostrador al recoger" in registered["respuesta"]
    assert catalog.get("PVC-050").stock == 9

    confirmed = turn(session, "sí, confirmo", tool("confirmar_pedido", pedido=code), say())
    assert confirmed["estado"] == "order_confirmed"
    context = confirmed["planner"].seen[0]["contexto"]
    assert context["ahora"] == "2026-10-21 10:00 (miercoles)"
    assert context["pedidos"][0]["pedido"] == code and context["pedidos"][0]["estado"] == "pendiente"
    assert "precio_unitario_cop" not in str(context["pedidos"]) and "total_cop" not in str(context["pedidos"])

    scheduled = turn(session, "paso mañana a las 4, lo recoge mi hermano",
                     tool("agendar_recogida", pedido=code, fecha="2026-10-22", hora="16:00", nota="Lo recoge el hermano"), say())
    assert scheduled["estado"] == "pickup_scheduled"
    order = book.get(code)
    assert order["estado"] == "confirmado" and order["recogida"] == "2026-10-22 16:00"
    assert order["nota"] == "Lo recoge el hermano" and order["aparta_hasta"] == "2026-10-22 18:00"


def test_confirmation_needs_a_yes_in_this_message_and_a_previous_summary(chat):
    turn, sessions, book, _, _ = chat
    session = sessions.create()
    _quote_turn(turn, session)
    # Registrar y confirmar en el mismo turno: el cliente no vio el resumen.
    same_turn = turn(session, "sí, me los llevo",
                     tool("registrar_pedido", lines=[{"sku": "PVC-050", "quantity": 3}]),
                     lambda seen: tool("confirmar_pedido", pedido=seen[-1]["datos"]["pedido"]),
                     say("Listo, tu pedido quedó confirmado. Datos simulados."))
    code = same_turn["tool_calls"][0]["response"]["data"]["pedido"]
    assert same_turn["tool_calls"][1]["response"]["error"]["code"] == "CONFIRMATION_NOT_STATED"
    assert same_turn["estado"] == "order_pending" and "quedó confirmado" not in same_turn["respuesta"]
    # En otro turno, una pregunta que no confirma tampoco sirve.
    later = turn(session, "y el cemento cuánto vale?", tool("confirmar_pedido", pedido=code),
                 say("Tu pedido quedó confirmado. Datos simulados."))
    rejected = later["tool_calls"][0]
    assert not rejected["executed"] and rejected["response"]["error"]["code"] == "CONFIRMATION_NOT_STATED"
    assert "quedó confirmado" not in later["respuesta"]
    assert book.get(code)["estado"] == "pendiente"


def test_a_yes_answered_without_the_tool_gets_the_order_reminder_and_never_a_false_claim(chat):
    turn, sessions, book, _, _ = chat
    session = sessions.create()
    _quote_turn(turn, session)
    registered = turn(session, "me los llevo", tool("registrar_pedido", lines=[{"sku": "PVC-050", "quantity": 3}]), say())
    code = registered["tool_calls"][0]["response"]["data"]["pedido"]
    lazy = turn(session, "dale", say("¡Listo! Tu pedido quedó confirmado. Datos simulados."),
                say("¡Listo! Tu pedido quedó confirmado. Datos simulados."))
    assert lazy["planner"].seen[1]["observaciones"][-1]["error"]["code"] == "ORDER_REQUIRED"
    assert "quedó confirmado" not in lazy["respuesta"]
    assert book.get(code)["estado"] == "pendiente"


def test_order_reminder_names_the_missing_tool(chat):
    # Primera corrida S4: con un aviso genérico Grok confirmó un pedido vencido en vez de registrarlo de nuevo.
    turn, sessions, book, _, clock = chat
    session = sessions.create()
    _quote_turn(turn, session)
    turn(session, "me los llevo", tool("registrar_pedido", lines=[{"sku": "PVC-050", "quantity": 3}]), say())
    clock.advance(minutes=6)
    again = turn(session, "sí, me los llevo de nuevo", say("¿Quieres que lo registre? Datos simulados."), say())
    reminder = again["planner"].seen[1]["observaciones"][-1]["error"]
    assert reminder["code"] == "ORDER_REQUIRED" and "registrar_pedido" in reminder["message"]
    assert [order["estado"] for order in book.session_orders(session)] == ["vencido"]


def test_question_about_the_total_needs_the_order_tool(chat):
    # Primera corrida S4 (L-02): «¿cuánto me toca pagar?» se respondió sin consultar el pedido.
    turn, sessions, _, _, _ = chat
    session = sessions.create()
    _quote_turn(turn, session)
    turn(session, "me los llevo", tool("registrar_pedido", lines=[{"sku": "PVC-050", "quantity": 3}]), say())
    asked = turn(session, "¿cuánto me toca pagar al recoger?", say("Pagas en caja. Datos simulados."),
                 tool("consultar_pedido"), say())
    reminder = asked["planner"].seen[1]["observaciones"][-1]["error"]
    assert reminder["code"] == "ORDER_REQUIRED" and "consultar_pedido" in reminder["message"]
    assert asked["estado"] == "order_status" and "$25.500" in asked["respuesta"]
    # Una pregunta de precio sin pedidos no pide la herramienta de pedidos.
    other = sessions.create()
    plain = turn(other, "¿cuánto vale el total de 3 metros de tubo PVC de 1/2 para agua?",
                 tool("buscar_productos", items=[PVC_HALF]),
                 tool("calcular_cotizacion_informativa", lines=[{"sku": "PVC-050", "quantity": 3}]), say())
    assert all(item.get("error", {}).get("code") != "ORDER_REQUIRED" for item in plain["planner"].seen[-1]["observaciones"])


def test_an_invented_order_code_gets_an_order_answer(chat):
    # Primera corrida S4 (P-03): «sí, confirmo» sin pedido y con «P-XXXXXX» terminaba en «No pude verificar ese producto».
    turn, sessions, _, _, _ = chat
    session = sessions.create()
    result = turn(session, "sí, confirmo", tool("confirmar_pedido", pedido="P-XXXXXX"), say())
    assert result["estado"] == "order_issue"
    assert "No encuentro ese pedido" in result["respuesta"] and "producto en el catálogo" not in result["respuesta"]


@pytest.mark.parametrize(("message", "hour"), [
    ("paso mañana", "08:00"),            # no dijo la hora: se pregunta
    ("paso mañana a las 4", "10:00"),    # dijo las 4, no las 10
])
def test_pickup_hour_must_be_the_one_the_customer_said(chat, message, hour):
    turn, sessions, book, _, _ = chat
    session = sessions.create()
    _quote_turn(turn, session)
    code = turn(session, "me los llevo", tool("registrar_pedido", lines=[{"sku": "PVC-050", "quantity": 3}]),
                say())["tool_calls"][0]["response"]["data"]["pedido"]
    result = turn(session, message, tool("agendar_recogida", pedido=code, fecha="2026-10-22", hora=hour), say())
    assert result["tool_calls"][0]["response"]["error"]["code"] == "TIME_NOT_GROUNDED"
    assert book.get(code)["recogida"] is None
    assert "¿Qué día y a qué hora pasas a recoger?" in result["respuesta"]


def test_pickup_note_never_keeps_personal_data(chat):
    turn, sessions, book, _, _ = chat
    session = sessions.create()
    _quote_turn(turn, session)
    code = turn(session, "me los llevo", tool("registrar_pedido", lines=[{"sku": "PVC-050", "quantity": 3}]),
                say())["tool_calls"][0]["response"]["data"]["pedido"]
    turn(session, "lo recoge mi hermano", tool("agendar_recogida", pedido=code, nota="Hermano, cel 300 123 4567"), say())
    assert "300" not in book.get(code)["nota"] and "[dato personal omitido]" in book.get(code)["nota"]


def test_purchase_needs_intent_and_unsaid_quantities_are_rejected(chat):
    turn, sessions, book, _, _ = chat
    session = sessions.create()
    _quote_turn(turn, session)
    browsing = turn(session, "¿y tienen de 3/4?", tool("registrar_pedido", lines=[{"sku": "PVC-050", "quantity": 3}]), say())
    assert browsing["tool_calls"][0]["response"]["error"]["code"] == "PURCHASE_NOT_STATED"
    more = turn(session, "me los llevo", tool("registrar_pedido", lines=[{"sku": "PVC-050", "quantity": 10}]), say())
    assert more["tool_calls"][0]["response"]["error"]["code"] == "QUANTITY_NOT_GROUNDED"
    assert book.session_orders(session) == []


def test_another_customer_cannot_confirm_or_see_my_order(chat):
    turn, sessions, book, _, _ = chat
    mine, theirs = sessions.create(), sessions.create()
    _quote_turn(turn, mine)
    code = turn(mine, "me los llevo", tool("registrar_pedido", lines=[{"sku": "PVC-050", "quantity": 3}]),
                say())["tool_calls"][0]["response"]["data"]["pedido"]
    stolen = turn(theirs, f"sí, confirmo el {code}", tool("confirmar_pedido", pedido=code), say())
    assert stolen["tool_calls"][0]["response"]["error"]["code"] == "ORDER_NOT_FOUND"
    peek = turn(theirs, "qué pedidos tengo?", tool("consultar_pedido"), say())
    assert code not in peek["respuesta"] and "No tienes pedidos" in peek["respuesta"]
    assert book.get(code)["estado"] == "pendiente"


def test_reply_with_an_invented_order_code_or_total_is_discarded(chat):
    turn, sessions, _, _, _ = chat
    session = sessions.create()
    _quote_turn(turn, session)
    result = turn(session, "me los llevo", tool("registrar_pedido", lines=[{"sku": "PVC-050", "quantity": 3}]),
                  say("Registré el pedido P-ABCDEF por $20.000 COP, apartado 5 minutos. Datos simulados."))
    code = result["tool_calls"][0]["response"]["data"]["pedido"]
    assert "P-ABCDEF" not in result["respuesta"] and "$20.000" not in result["respuesta"]
    assert code in result["respuesta"]


def test_orders_need_a_session(tmp_path):
    executor = catalog_executor(MockCatalog(create_mock_db(tmp_path / "catalog.sqlite3")))
    planner = Script(tool("registrar_pedido", lines=[{"sku": "PVC-050", "quantity": 3}]), say())
    result = build_graph(executor, planner).invoke({"consulta": "me llevo 3 metros de tubo PVC de 1/2"})
    assert result["tool_calls"][0]["response"]["error"]["code"] == "SESSION_REQUIRED"
    assert not result["tool_calls"][0]["executed"]
    assert executor("registrar_pedido", {"lines": [{"sku": "PVC-050", "quantity": 3}]})["error"]["code"] == "SESSION_REQUIRED"



def test_without_a_session_the_rejected_order_keeps_the_quote_answer(tmp_path):
    # G-07, corridas S4: fuera de una conversación Grok intentó registrar; la respuesta es la cotización.
    executor = catalog_executor(MockCatalog(create_mock_db(tmp_path / "catalog.sqlite3")))
    cement = {"text": "cemento gris de 50 kg", "product": "cemento", "measure": "50 kg", "presentation": "bulto"}
    planner = Script(tool("buscar_productos", items=[cement]),
                     tool("registrar_pedido", lines=[{"sku": "CEM-050", "quantity": 3}]),
                     tool("calcular_cotizacion_informativa", lines=[{"sku": "CEM-050", "quantity": 3}]),
                     say("Te aparté 3 bultos. Datos simulados."))
    result = build_graph(executor, planner).invoke({"consulta": "Apártame 3 bultos de cemento gris de 50 kg, pago mañana"})
    assert result["tool_calls"][1]["response"]["error"]["code"] == "SESSION_REQUIRED"
    assert result["estado"] == "quoted"
    assert "No es un pedido ni una reserva" in result["respuesta"] and "aparté" not in result["respuesta"]


def test_a_remembered_product_is_quoted_without_searching_again(chat):
    # M-01, segunda corrida S4: «dame 3 metros de ese» cotizó el SKU recordado sin buscar y se rechazaba.
    turn, sessions, _, _, _ = chat
    session = sessions.create()
    turn(session, "Busco tubo PVC de 1/2 para agua", tool("buscar_productos", items=[PVC_HALF]), say())
    result = turn(session, "Dame 3 metros de ese",
                  tool("calcular_cotizacion_informativa", lines=[{"sku": "PVC-050", "quantity": 3}]), say())
    assert result["tool_calls"][0]["executed"] and result["estado"] == "quoted"
    assert "$25.500" in result["respuesta"] and "Tubo PVC" in result["respuesta"]
    # Un SKU que la sesión no identificó sigue rechazado, y la cantidad debe estar dicha.
    other = turn(session, "y 2 de cemento", tool("calcular_cotizacion_informativa", lines=[{"sku": "CEM-050", "quantity": 2}]),
                 say())
    assert other["tool_calls"][0]["response"]["error"]["code"] == "SKU_NOT_GROUNDED" and "$" not in other["respuesta"]
    unsaid = turn(session, "cotízamelo", tool("calcular_cotizacion_informativa", lines=[{"sku": "PVC-050", "quantity": 7}]),
                  say())
    assert unsaid["tool_calls"][0]["response"]["error"]["code"] == "QUANTITY_NOT_GROUNDED"


def test_a_registered_order_does_not_ask_for_a_separate_quote(chat):
    # P-02, corridas S4: tras registrar, el aviso QUOTE_REQUIRED pedía cotizar lo mismo (dos llamadas más).
    turn, sessions, book, _, _ = chat
    session = sessions.create()
    cement = {"text": "bultos de cemento gris de 50 kg", "product": "cemento", "measure": "50 kg", "presentation": "bulto"}
    result = turn(session, "me llevo 2 bultos de cemento gris de 50 kg", tool("buscar_productos", items=[cement]),
                  tool("registrar_pedido", lines=[{"sku": "CEM-050", "quantity": 2}]), say())
    assert len(result["planner"].seen) == 3 and result["estado"] == "order_pending"
    assert "$79.000" in result["respuesta"] and [o["estado"] for o in book.session_orders(session)] == ["pendiente"]
    # Sin pedido registrado el aviso sigue: una cantidad con producto distinguido se cotiza.
    plain = turn(sessions.create(), "Necesito 3 metros de tubo PVC de 1/2 para agua",
                 tool("buscar_productos", items=[PVC_HALF]), say(), say())
    assert plain["planner"].seen[-1]["observaciones"][-1]["error"]["code"] == "QUOTE_REQUIRED"

def test_a_question_about_confirming_is_not_a_confirmation(chat):
    # P-02, segunda corrida S4: «¿todavía lo puedo confirmar?» tras vencer el apartado disparó el aviso de
    # registrar y Grok registró un pedido que el cliente no había pedido.
    turn, sessions, book, _, clock = chat
    session = sessions.create()
    _quote_turn(turn, session)
    turn(session, "me los llevo", tool("registrar_pedido", lines=[{"sku": "PVC-050", "quantity": 3}]), say())
    clock.advance(minutes=6)
    book.expire_due()
    asked = turn(session, "uy se me pasó, todavía lo puedo confirmar?",
                 say("Ese pedido venció. Si aún lo quieres, dime y lo registro de nuevo. Datos simulados."))
    assert len(asked["planner"].seen) == 1
    assert [order["estado"] for order in book.session_orders(session)] == ["vencido"]
    # «sí, ¿a qué hora abren?» sigue confirmando: abre con el sí.
    from asistendero.order_rules import confirms
    assert confirms("sí, ¿a qué hora abren?") and not confirms("¿ya quedó confirmado?")


def test_watcher_warns_one_minute_before_and_notifies_expiry_once(chat):
    turn, sessions, book, catalog, clock = chat
    session = sessions.create()
    _quote_turn(turn, session)
    code = turn(session, "me los llevo", tool("registrar_pedido", lines=[{"sku": "PVC-050", "quantity": 3}]),
                say())["tool_calls"][0]["response"]["data"]["pedido"]
    seen = sweep(book, sessions, 0)
    assert sessions.take_notices(session) == []
    clock.advance(seconds=HOLD_MINUTES * 60 - WARN_BEFORE.total_seconds())
    seen = sweep(book, sessions, seen)
    warning = sessions.take_notices(session)
    assert len(warning) == 1 and code in warning[0] and "10:05" in warning[0]
    clock.advance(minutes=1)
    seen = sweep(book, sessions, seen)
    expired = sessions.take_notices(session)
    assert len(expired) == 1 and "Pasaron 5 minutos" in expired[0] and code in expired[0]
    assert catalog.get("PVC-050").stock == 12
    sweep(book, sessions, seen)
    assert sessions.take_notices(session) == []
    # Un visor que arranca después no repite avisos viejos.
    assert Watcher(book, sessions).after == seen


def test_session_notes_follow_the_real_order_state(chat):
    from asistendero.answers import CREDIT_NOTE, NO_ORDER_NOTE

    turn, sessions, _, _, _ = chat
    session = sessions.create()
    _quote_turn(turn, session)
    hold = turn(session, "apártamelos", say("Con gusto. Datos simulados.", intent="otro"),
                say("Con gusto. Datos simulados.", intent="otro"))
    assert NO_ORDER_NOTE in hold["respuesta"]
    turn(session, "me los llevo", tool("registrar_pedido", lines=[{"sku": "PVC-050", "quantity": 3}]), say())
    # Con un pedido activo, «fíame» no puede decir que no hay nada apartado.
    credit = turn(session, "me lo fías hasta el viernes?", say("Eso no lo puedo hacer. Datos simulados.", intent="otro"))
    assert CREDIT_NOTE in credit["respuesta"] and NO_ORDER_NOTE not in credit["respuesta"]
