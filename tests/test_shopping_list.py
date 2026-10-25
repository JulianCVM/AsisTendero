"""La lista de la conversación: lo cotizado se recuerda con su cantidad y «¿cuánto es todo?» lo suma entero."""

from datetime import datetime

import pytest

from asistendero.chat import run_turn
from asistendero.grok import Decision
from asistendero.orders import BOGOTA, OrderBook
from asistendero.seed import create_mock_db
from asistendero.sessions import SessionStore
from asistendero.shopping_list import MAX_LIST_LINES, asks_whole_list, missing_from_quote, updated_list


CONDUIT = {"text": "tubo conduit eléctrico de media pulgada", "product": "tubo", "use": "eléctrico", "measure": "1/2 pulgada"}
HOSES = {"text": "mangueras", "product": "manguera"}
HOSE_40 = {"text": "manguera de abasto de 40 cm", "product": "manguera", "measure": "40 cm"}
PVC_HALF = {"text": "tubo PVC de 1/2 para agua", "product": "tubo", "material": "PVC", "measure": "1/2 pulgada", "use": "agua"}
BRUSH = {"text": "brochas de 3 pulgadas", "product": "brocha", "measure": "3 pulgadas"}


def tool(name, **arguments):
    return Decision("call_tool", "productos", name, arguments, "")


def say(reply="", intent="productos"):
    return Decision("respond", intent, None, None, reply)


def quote(*lines):
    return tool("calcular_cotizacion_informativa", lines=[{"sku": sku, "quantity": quantity} for sku, quantity in lines])


class Script:
    """Grok falso: devuelve las decisiones en orden y guarda lo que recibió en cada paso."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.seen = []

    def __call__(self, message, observations, remaining, context=None):
        self.seen.append({"observaciones": observations, "contexto": context})
        return self.steps.pop(0)


@pytest.fixture
def chat(tmp_path):
    book = OrderBook(create_mock_db(tmp_path / "catalog.sqlite3"),
                     clock=lambda: datetime(2026, 10, 21, 10, 0, tzinfo=BOGOTA))
    sessions = SessionStore(tmp_path / "sessions.sqlite3")

    def turn(session, message, *steps):
        planner = Script(*steps)
        result = run_turn(sessions, session, message, planner=planner, orders=book)
        result["planner"] = planner
        # Cada paso recibe todas las observaciones anteriores: la última trae los avisos de la ejecución.
        result["avisos_enviados"] = [observation["error"]["code"] for observation in planner.seen[-1]["observaciones"]
                                     if observation.get("estado") == "aviso"]
        return result

    return turn, sessions, book


def _listed(sessions, session):
    return [(item["sku"], item["cantidad"]) for item in sessions.context(session)["lista"]]


def test_the_demo_conversation_quotes_the_tube_and_the_hose_together(chat):
    # Conversación del 23-10 con Grok real. «agrega una manguera…, ¿cuánto sería todo y a qué hora puedo pasar?»
    # cotizó solo la manguera y no dio el horario; «yo quiero la manguera cotizada con el tubo» volvió a preguntar
    # qué manguera. El guion repite lo que hizo Grok; los avisos del servidor lo corrigen.
    turn, sessions, book = chat
    session = sessions.create()
    first = turn(session, "me gustaria comprar un metro de tubo conduit electrico de media pulgada adicional quiero "
                          "saber si tienen mangueras",
                 tool("buscar_productos", items=[CONDUIT, HOSES]), quote(("CON-050", 1)), say())
    answer = first["respuesta"]
    # Un producto cotizado va en una frase y, sin preguntarlo, no se anuncia cuánto queda (visor, 23-10).
    assert "1 metro de tubo PVC conduit eléctrico de 1/2 pulgada te sale en $3.900." in answer and "quedan" not in answer
    assert "Manguera de abasto de 1/2 x 40 cm" in answer and "¿Cuál te sirve?" in answer
    assert "SKU" not in answer and "COP" not in answer and "→" not in answer
    assert "Precios y existencias de demostración." in answer
    assert _listed(sessions, session) == [("CON-050", 1)]

    second = turn(session, "agrega una manguera de abasto de 40 cm, cuanto seria todo y a que hora puedo pasar a "
                           "recogerlo?",
                  tool("buscar_productos", items=[HOSE_40]), quote(("MAB-40", 1)), say(),
                  tool("consultar_info_tienda", tema="horario"), say(),
                  quote(("CON-050", 1), ("MAB-40", 1)), say())
    assert second["avisos_enviados"] == ["INFO_REQUIRED", "LIST_QUOTE_REQUIRED"]
    assert second["planner"].seen[0]["contexto"]["lista"][0]["cantidad"] == 1
    answer = second["respuesta"]
    assert second["estado"] == "quoted"
    assert "Con lo que llevas, te quedaría así:" in answer and "Total: $13.800" in answer
    assert "1 metro de tubo PVC conduit eléctrico de 1/2 pulgada: $3.900" in answer
    assert "Manguera de abasto de 1/2 x 40 cm: $9.900" in answer and "7:00" in answer
    # «agrega» sin pedido activo suma a la lista: no se registra nada ni se repite la aclaración de demostración.
    assert book.session_orders(session) == [] and "demostración" not in answer
    assert _listed(sessions, session) == [("CON-050", 1), ("MAB-40", 1)]

    third = turn(session, "pero yo quiero la manguera cotizada con el tubo que te dije, cuanto es todo",
                 tool("buscar_productos", items=[{"text": "manguera", "product": "manguera"}]), say(),
                 quote(("CON-050", 1), ("MAB-40", 1)), say())
    assert third["avisos_enviados"] == ["LIST_QUOTE_REQUIRED"]
    assert "Total: $13.800" in third["respuesta"] and "¿Qué medida" not in third["respuesta"]


def test_a_quantity_said_many_turns_ago_is_quoted_from_the_list(chat):
    turn, sessions, _ = chat
    session = sessions.create()
    turn(session, "necesito 3 metros de tubo PVC de 1/2 para agua", tool("buscar_productos", items=[PVC_HALF]),
         quote(("PVC-050", 3)), say())
    turn(session, "¿tienen cemento gris?", tool("buscar_productos", items=[{"text": "cemento gris", "product": "cemento",
                                                                           "color": "gris"}]), say())
    turn(session, "¿y lijas?", tool("buscar_productos", items=[{"text": "lijas", "product": "lija"}]), say())
    turn(session, "¿hasta qué hora atienden hoy?", tool("consultar_info_tienda", tema="horario"), say(intent="tienda"))
    turn(session, "¿tienen silicona?", tool("buscar_productos", items=[{"text": "silicona", "product": "silicona"}]), say())
    # El «3» quedó fuera de los turnos recientes: sin la lista, cotizar 3 metros se rechazaba.
    last = turn(session, "agrégale 2 brochas de 3 pulgadas, ¿cuánto es todo?", tool("buscar_productos", items=[BRUSH]),
                quote(("PVC-050", 3), ("BRO-3", 2)), say())
    assert last["tool_calls"][1]["executed"] and last["estado"] == "quoted"
    assert "Total: $39.300" in last["respuesta"]
    assert _listed(sessions, session) == [("PVC-050", 3), ("BRO-3", 2)]


def test_the_list_never_lets_grok_change_a_quantity(chat):
    turn, sessions, _ = chat
    session = sessions.create()
    turn(session, "necesito 3 metros de tubo PVC de 1/2 para agua", tool("buscar_productos", items=[PVC_HALF]),
         quote(("PVC-050", 3)), say())
    for _ in range(3):
        turn(session, "¿tienen lijas?", tool("buscar_productos", items=[{"text": "lijas", "product": "lija"}]), say())
    # Ni la cantidad de la lista cambia sola ni un SKU fuera de ella entra sin respaldo.
    changed = turn(session, "¿cuánto es todo?", quote(("PVC-050", 5)), say(), quote(("PVC-050", 3)), say())
    assert changed["tool_calls"][0]["response"]["error"]["code"] == "QUANTITY_NOT_GROUNDED"
    assert changed["tool_calls"][1]["executed"] and "te salen en $25.500" in changed["respuesta"]
    foreign = turn(session, "¿cuánto es todo?", quote(("PVC-050", 3), ("CEM-050", 3)), say(), quote(("PVC-050", 3)), say())
    assert foreign["tool_calls"][0]["response"]["error"]["code"] == "SKU_NOT_GROUNDED"


def test_taking_everything_registers_the_whole_list_and_empties_it(chat):
    turn, sessions, book = chat
    session = sessions.create()
    turn(session, "necesito 3 metros de tubo PVC de 1/2 para agua", tool("buscar_productos", items=[PVC_HALF]),
         quote(("PVC-050", 3)), say())
    turn(session, "agrega 2 brochas de 3 pulgadas", tool("buscar_productos", items=[BRUSH]),
         quote(("PVC-050", 3), ("BRO-3", 2)), say())
    taken = turn(session, "listo, me llevo todo",
                 tool("registrar_pedido", lines=[{"sku": "PVC-050", "quantity": 3}, {"sku": "BRO-3", "quantity": 2}]),
                 say(intent="pedido"))
    assert taken["estado"] == "order_pending" and "Total: $39.300" in taken["respuesta"]
    assert [order["estado"] for order in book.session_orders(session)] == ["pendiente"]
    assert _listed(sessions, session) == []
    assert "mostrador al recoger" in taken["respuesta"]
    code = book.session_orders(session)[0]["pedido"]
    confirmed = turn(session, "sí, confirmo", tool("confirmar_pedido", pedido=code), say(intent="pedido"))
    scheduled = turn(session, "paso hoy a las 4", tool("agendar_recogida", pedido=code, fecha="2026-10-21", hora="16:00"),
                     say(intent="pedido"))
    # El pago se aclara una vez, al registrar; repetido en cada mensaje se leía como un aviso legal.
    assert "mostrador" not in confirmed["respuesta"] and "mostrador" not in scheduled["respuesta"]
    assert f"te esperamos el miércoles 21/10 a las 16:00 con tu pedido {code}" in scheduled["respuesta"]


def test_a_nearby_option_names_what_it_is_and_shows_no_price(chat):
    turn, sessions, _ = chat
    session = sessions.create()
    asked = turn(session, "¿cuánto vale la brocha de 3 pulgadas?", tool("buscar_productos", items=[BRUSH]), say())
    assert "¿Cuántas unidades necesitas?" in asked["respuesta"]
    nearby = turn(session, "busco llaves para ducha",
                  tool("buscar_productos", items=[{"text": "llaves para ducha", "product": "llave", "use": "ducha"}]), say())
    answer = nearby["respuesta"]
    assert nearby["estado"] == "nearby" and "Lo más parecido que tengo es juego de llaves Allen, aunque no es exactamente lo mismo." in answer
    assert "$" not in answer


def test_without_a_registered_order_adding_is_not_buying(chat):
    from asistendero.order_rules import wants_to_buy

    assert not wants_to_buy("agrega una manguera de abasto de 40 cm, cuanto seria todo", {"pedidos": []})
    assert wants_to_buy("agrega una manguera", {"pedidos": [{"pedido": "P-ABCDEF", "estado": "pendiente"}]})


@pytest.mark.parametrize("message", ["¿a qué hora puedo pasar a recogerlo?", "¿hasta qué hora atienden?",
                                     "y a que horas abren mañana"])
def test_asking_when_to_come_asks_for_the_store_hours(message):
    from asistendero.reminders import pending_reminder

    assert pending_reminder(message, say(intent="pedido"), [], set()) == "INFO_REQUIRED"


def _quote_call(*lines):
    names = {"CON-050": ("Tubo PVC conduit eléctrico", "1/2 pulgada", "metro"),
             "MAB-40": ("Manguera de abasto", "1/2 x 40 cm", "unidad"), "BRO-3": ("Brocha", "3 pulgadas", "unidad")}
    data = {"lines": [{"sku": sku, "name": names[sku][0], "variant": names[sku][1], "unit": names[sku][2],
                       "quantity": quantity, "unit_price_cop": 1000, "subtotal_cop": 1000 * quantity}
                      for sku, quantity in lines],
            "total_cop": 1000 * sum(quantity for _, quantity in lines), "currency": "COP", "reservation_created": False}
    return {"requested_tool": "calcular_cotizacion_informativa", "executed": True,
            "response": {"status": "ok", "data": data, "error": None}}


LISTED = [{"sku": "CON-050", "nombre": "Tubo PVC conduit eléctrico", "variante": "1/2 pulgada", "unidad": "metro",
           "cantidad": 1},
          {"sku": "MAB-40", "nombre": "Manguera de abasto", "variante": "1/2 x 40 cm", "unidad": "unidad", "cantidad": 1}]


def test_the_list_updates_removes_and_restarts():
    assert [item["cantidad"] for item in updated_list(LISTED, "mejor 3 metros de tubo", [_quote_call(("CON-050", 3))])] == [3, 1]
    assert [item["sku"] for item in updated_list(LISTED, "quita la manguera", [])] == ["CON-050"]
    assert updated_list(LISTED, "empecemos de nuevo, necesito una brocha", [_quote_call(("BRO-3", 1))])[0]["sku"] == "BRO-3"
    assert len(updated_list(LISTED, "empecemos de nuevo, necesito una brocha", [_quote_call(("BRO-3", 1))])) == 1
    # Un saco de cemento no es «sacar» nada de la lista, y una pregunta sin cotización no la cambia.
    assert updated_list(LISTED, "¿cuánto vale el saco de cemento?", []) == LISTED


def test_the_list_fits_in_one_quote():
    many = [{**LISTED[0], "sku": f"SKU-{number}"} for number in range(MAX_LIST_LINES)]
    assert [item["sku"] for item in updated_list(many, "y una brocha", [_quote_call(("BRO-3", 1))])][-1] == "BRO-3"
    assert len(updated_list(many, "y una brocha", [_quote_call(("BRO-3", 1))])) == MAX_LIST_LINES


@pytest.mark.parametrize(("message", "expected"), [
    ("¿cuánto es todo?", True), ("agrega una manguera", True), ("y también 2 brochas", True),
    ("¿también tienen cemento?", False), ("¿tienen silicona?", False), ("cuanto me sale todo junto", True),
])
def test_what_asks_for_the_whole_list(message, expected):
    assert asks_whole_list(message) is expected


def test_the_whole_list_is_not_demanded_after_removing_or_ordering():
    context = {"lista": LISTED}
    assert missing_from_quote("¿cuánto es todo?", [_quote_call(("MAB-40", 1))], context) == ["CON-050"]
    assert missing_from_quote("quita el tubo, ¿cuánto es todo?", [_quote_call(("MAB-40", 1))], context) == []
    assert missing_from_quote("¿tienen silicona?", [], context) == []
    assert missing_from_quote("¿cuánto es todo?", [], {"lista": []}) == []


@pytest.mark.parametrize(("quantity", "unit", "name", "variant", "expected"), [
    (3, "metro", "Tubo PVC presión para agua", "1/2 pulgada",
     "• 3 metros de tubo PVC presión para agua de 1/2 pulgada (a $8.500 el metro): $25.500"),
    (2, "unidad", "Brocha", "3 pulgadas", "• 2 unidades de brocha de 3 pulgadas (a $8.500 c/u): $25.500"),
    (1, "bulto", "Cemento gris", "bulto de 50 kg", "• 1 bulto de cemento gris de 50 kg: $25.500"),
    (3, "bulto", "Cemento gris", "bulto de 50 kg", "• 3 bultos de cemento gris de 50 kg (a $8.500 el bulto): $25.500"),
    # La presentación es la unidad que dice el cliente: «10 galones», no «10 unidades de pintura en galón».
    (10, "unidad", "Pintura vinilo beige", "galón", "• 10 galones de pintura vinilo beige (a $8.500 el galón): $25.500"),
    (1, "unidad", "Manguera de abasto", "1/2 x 40 cm", "• Manguera de abasto de 1/2 x 40 cm: $25.500"),
])
def test_a_quote_line_reads_like_the_counter(quantity, unit, name, variant, expected):
    from asistendero.reply_text import item_line

    assert item_line(quantity, unit, name, variant, 8500, 25500) == expected


def test_a_quantity_for_a_new_product_never_quotes_a_remembered_one(chat):
    # Suite memoria con Grok real (23-10): con el cemento consultado antes, «agrégale 2 brochas» cotizó 2 bultos.
    turn, sessions, _ = chat
    session = sessions.create()
    turn(session, "necesito 3 metros de tubo PVC de 1/2 para agua", tool("buscar_productos", items=[PVC_HALF]),
         quote(("PVC-050", 3)), say())
    turn(session, "¿Y tienen cemento gris de 50 kg?",
         tool("buscar_productos", items=[{"text": "cemento gris de 50 kg", "product": "cemento", "color": "gris",
                                          "measure": "50 kg"}]), say())
    added = turn(session, "agrégale 2 brochas de 3 pulgadas, ¿cuánto es todo?",
                 quote(("PVC-050", 3), ("CEM-050", 2)), tool("buscar_productos", items=[BRUSH]),
                 quote(("PVC-050", 3), ("BRO-3", 2)), say())
    rejected = added["tool_calls"][0]["response"]["error"]
    assert rejected["code"] == "QUANTITY_NOT_GROUNDED" and "brochas" in rejected["message"]
    assert "Total: $39.300" in added["respuesta"] and "Cemento" not in added["respuesta"]
    # El cemento se puede seguir cotizando con una cantidad dicha para él.
    cement = turn(session, "y 2 bultos de cemento, ¿cuánto es todo?", quote(("PVC-050", 3), ("BRO-3", 2), ("CEM-050", 2)),
                  say())
    assert cement["tool_calls"][0]["executed"] and "Total: $118.300" in cement["respuesta"]


def test_starting_over_or_removing_stops_backing_the_old_lines(chat):
    # Suite memoria con Grok real (23-10): «empecemos de nuevo: necesito 2 brochas» cotizó también el tubo de antes.
    turn, sessions, _ = chat
    session = sessions.create()
    turn(session, "necesito 3 metros de tubo PVC de 1/2 para agua", tool("buscar_productos", items=[PVC_HALF]),
         quote(("PVC-050", 3)), say())
    restart = turn(session, "empecemos de nuevo: necesito 2 brochas de 3 pulgadas, ¿cuánto es todo?",
                   tool("buscar_productos", items=[BRUSH]), quote(("BRO-3", 2), ("PVC-050", 3)), quote(("BRO-3", 2)),
                   say())
    assert restart["tool_calls"][1]["response"]["error"]["code"] == "SKU_NOT_GROUNDED"
    assert "te salen en $13.800" in restart["respuesta"] and _listed(sessions, session) == [("BRO-3", 2)]
    turn(session, "y 3 metros de tubo PVC de 1/2 para agua", tool("buscar_productos", items=[PVC_HALF]),
         quote(("BRO-3", 2), ("PVC-050", 3)), say())
    removed = turn(session, "quita las brochas, ¿cuánto queda?", quote(("PVC-050", 3), ("BRO-3", 2)),
                   quote(("PVC-050", 3)), say())
    assert removed["tool_calls"][0]["response"]["error"]["code"] == "SKU_NOT_GROUNDED"
    assert "te salen en $25.500" in removed["respuesta"] and _listed(sessions, session) == [("PVC-050", 3)]


TUBES = {"text": "tubos pvc", "product": "tubo", "material": "PVC"}
VISOR_RUSH = ("Listo, te aparté el pedido por 5 minutos. Tienes hasta esa hora para llegar a pagar y recoger. "
              "¡Apúrate que se vence pronto!")


def test_the_visor_conversation_follows_the_options_the_list_and_the_hold(chat):
    # Conversación del visor del 23-10 con Grok real. «dame del primero 3 metros» cotizó el tubo sanitario de 3
    # pulgadas, el «PVC» del tubo llegó a la búsqueda de mangueras («Es de otro material»), «la segunda, la de 60…
    # ¿cuánto queda todo?» cotizó solo el tubo y, con el pedido sin confirmar, Grok le dijo al cliente que vivía a
    # media hora «tienes hasta esa hora para llegar, ¡apúrate!». El guion repite esos pasos de Grok.
    turn, sessions, book = chat
    session = sessions.create()
    first = turn(session, "buenas tubos pbc tiene?", tool("buscar_productos", items=[TUBES]), say())
    assert "De tubos PVC tengo estas opciones:" in first["respuesta"] and "¿Cuál te sirve?" in first["respuesta"]
    assert "quedan" not in first["respuesta"] and "$" not in first["respuesta"]
    assert [item["sku"] for item in sessions.context(session)["opciones"][0]["opciones"]] == ["CON-050", "CON-075", "PVC-050"]

    second = turn(session, "dame del primero 3 metros, de mangueras que tiene?",
                  tool("buscar_productos", items=[{"text": "tubo PVC 3 metros", "product": "tubo", "material": "PVC"},
                                                  {"text": "mangueras PVC", "product": "manguera", "material": "PVC"}]),
                  quote(("SAN-3", 3)), say(), quote(("CON-050", 3)), say())
    assert second["tool_calls"][0]["arguments"]["items"][1] == {"text": "mangueras PVC", "product": "manguera"}
    assert second["tool_calls"][1]["response"]["error"]["code"] == "SKU_NOT_GROUNDED"
    assert second["avisos_enviados"] == ["LIST_QUOTE_REQUIRED"]
    answer = second["respuesta"]
    assert "Los 3 metros de tubo PVC conduit eléctrico de 1/2 pulgada te salen en $11.700" in answer
    assert "De mangueras tengo estas opciones:" in answer and "Manguera de abasto de 1/2 x 60 cm" in answer
    assert "sanitario" not in answer and "otro material" not in answer and "quedan" not in answer

    third = turn(session, "dame de esa manguera la segunda la de 60 dame unas 3 y que precio quedaria todo?",
                 say("Te queda en $11.700 por los 3 metros de tubo."), quote(("CON-050", 3), ("MAB-60", 3)), say())
    assert third["avisos_enviados"] == ["LIST_QUOTE_REQUIRED"]
    assert "3 unidades de manguera de abasto de 1/2 x 60 cm (a $11.900 c/u): $35.700" in third["respuesta"]
    assert "Total: $47.400" in third["respuesta"]

    fifth = turn(session, "apartamelo y ya voy a la tienda a pagar cuanto tiempo tengo para llegar? es que vivo medio "
                          "lejos, a una media hora",
                 tool("registrar_pedido", lines=[{"sku": "CON-050", "quantity": 3}, {"sku": "MAB-60", "quantity": 3}]),
                 say(VISOR_RUSH, intent="pedido"))
    answer = fifth["respuesta"]
    assert fifth["estado"] == "order_pending" and [order["estado"] for order in book.session_orders(session)] == ["pendiente"]
    assert "¿me confirmas con un «sí» antes de las 10:05?" in answer and "te lo guardo hasta 24 horas" in answer
    assert "pú" not in answer.casefold() and "llegar a pagar" not in answer
    # Con el código real del pedido, la misma redacción sin la prisa sí se usaría: lo que la descarta es la prisa.
    from asistendero.answers import reply_is_grounded

    code, context = book.session_orders(session)[0]["pedido"], sessions.context(session)
    calm = f"Listo, registré tu pedido {code} por $47.400. Confírmame con un sí antes de las 10:05."
    assert reply_is_grounded(calm, fifth["consulta"], fifth["tool_calls"], context)
    assert not reply_is_grounded(f"{calm} Tienes hasta esa hora para llegar, ¡apúrate!", fifth["consulta"],
                                 fifth["tool_calls"], context)


def test_an_option_is_chosen_only_by_an_ordinal_with_its_article():
    from asistendero.choices import chosen_options

    tubes = {"grupo": "tubos pvc", "opciones": [{"sku": "CON-050"}, {"sku": "CON-075"}, {"sku": "PVC-050"}]}
    hoses = {"grupo": "mangueras", "opciones": [{"sku": "MAB-40"}, {"sku": "MAB-60"}]}
    assert chosen_options("dame del primero 3 metros", {"opciones": [tubes]}) == [{"sku": "CON-050"}]
    assert chosen_options("la última", {"opciones": [tubes]}) == [{"sku": "PVC-050"}]
    assert chosen_options("de la opción 2, 4 metros", {"opciones": [tubes]}) == [{"sku": "CON-075"}]
    # Sin artículo «primero» no elige nada; con dos grupos y sin decir cuál, no se adivina; fuera de rango, nada.
    assert chosen_options("primero dime el horario", {"opciones": [tubes]}) == []
    assert chosen_options("dame la segunda", {"opciones": [tubes, hoses]}) == []
    assert chosen_options("de la manguera, la segunda", {"opciones": [tubes, hoses]}) == [{"sku": "MAB-60"}]
    assert chosen_options("el quinto", {"opciones": [tubes]}) == [] and chosen_options("el primero", None) == []


def test_a_rejected_quote_names_the_option_the_client_chose_by_its_order(chat):
    # Corrida 26 (H-01) con Grok real: tras «dame del primero 3 metros, de mangueras que tiene?» Grok cotizó la
    # primera manguera; el servidor lo rechazó bien, pero sin decir que «el primero» era el tubo conduit.
    turn, sessions, _ = chat
    session = sessions.create()
    turn(session, "buenas tubos pbc tiene?", tool("buscar_productos", items=[{"text": "tubos PVC", "product": "tubo",
                                                                              "material": "PVC"}]), say())
    result = turn(session, "dame del primero 3 metros, de mangueras que tiene?", tool("buscar_productos", items=[HOSES]),
                  quote(("MAB-40", 3)), quote(("CON-050", 3)), say())
    rejected, quoted = result["tool_calls"][1], result["tool_calls"][2]
    assert not rejected["executed"] and rejected["response"]["error"]["code"] == "SKU_NOT_GROUNDED"
    assert "el cliente eligió: CON-050 (Tubo PVC conduit eléctrico 1/2 pulgada)" in rejected["response"]["error"]["message"]
    assert quoted["executed"] and "$11.700" in result["respuesta"]
    # Sin un orden dicho, el rechazo no sugiere nada.
    plain = turn(session, "¿y de esas cuál es la más barata? dame 3", quote(("MAB-60", 3)), say())
    assert "eligió" not in plain["tool_calls"][0]["response"]["error"]["message"]


def test_an_option_is_chosen_by_the_attribute_only_it_has():
    from asistendero.choices import chosen_options

    # Suite natural (H-02, H-08, H-14): en el mostrador se elige «el de 12» o «la talla L», no solo «el primero».
    bulbs = {"grupo": "bombillos LED de luz blanca", "opciones": [
        {"sku": "BOM-09", "variante": "9 W luz blanca"}, {"sku": "BOM-12", "variante": "12 W luz blanca"},
        {"sku": "BOM-18A", "variante": "ahorrador 18 W luz blanca"}]}
    paints = {"grupo": "pintura beige", "opciones": [
        {"sku": "PIV-BEI-14", "variante": "1/4 de galón"}, {"sku": "PIV-BEI-G", "variante": "galón"},
        {"sku": "PIV-BEI-C5", "variante": "beige cuñete de 5 galones"}]}
    gloves = {"grupo": "guantes de carnaza", "opciones": [
        {"sku": "GUA-L", "variante": "talla L"}, {"sku": "GUA-M", "variante": "talla M"}]}
    tapes = {"grupo": "flexómetro", "opciones": [
        {"sku": "FLX-3", "variante": "3 m"}, {"sku": "FLX-5", "variante": "5 m"}, {"sku": "FLX-8", "variante": "8 m"}]}
    assert [item["sku"] for item in chosen_options("el de 12, deme 4", {"opciones": [bulbs]})] == ["BOM-12"]
    assert [item["sku"] for item in chosen_options("la de galón, deme 2", {"opciones": [paints]})] == ["PIV-BEI-G"]
    assert [item["sku"] for item in chosen_options(
        "de los guantes la talla L y del flexómetro el de 5 metros, uno de cada uno",
        {"opciones": [gloves, tapes]})] == ["GUA-L", "FLX-5"]
    # Lo que comparten varias opciones no elige, y un número suelto sin «el de» tampoco: es la cantidad.
    assert chosen_options("el de luz blanca", {"opciones": [bulbs]}) == []
    assert chosen_options("deme 12", {"opciones": [bulbs]}) == []
    assert chosen_options("el de 7", {"opciones": [bulbs]}) == []
    assert chosen_options("la talla L", {"opciones": [gloves, tapes]}) == []


def _product(stock, unit="metro"):
    from asistendero.catalog import Product

    return Product("PVC-050", "Tubo PVC presión para agua", "1/2 pulgada", unit, 8500, stock, "2026-10-23")


@pytest.mark.parametrize(("stock", "asked", "needed", "expected"), [
    (12, False, 0, "Sí, tenemos tubo PVC presión para agua de 1/2 pulgada, a $8.500 el metro."),
    (12, True, 0, "Sí, tenemos tubo PVC presión para agua de 1/2 pulgada, a $8.500 el metro. Me quedan 12 metros."),
    (3, False, 0, "Sí, tenemos tubo PVC presión para agua de 1/2 pulgada, a $8.500 el metro. Ojo, solo me quedan 3 metros."),
    (12, False, 20, "Sí, tenemos tubo PVC presión para agua de 1/2 pulgada, a $8.500 el metro. Ojo, solo me quedan 12 metros."),
    (0, False, 0, "El tubo PVC presión para agua de 1/2 pulgada está agotado por ahora."),
])
def test_stock_is_said_only_when_asked_low_short_or_out(stock, asked, needed, expected):
    # Visor, 23-10: cada opción decía «quedan 12 metros» aunque el cliente no preguntó cuánto había.
    from asistendero.reply_text import found_sentence

    assert found_sentence(_product(stock), stock, True, asked, needed) == expected


@pytest.mark.parametrize(("message", "expected"), [
    ("¿cuántos bultos de cemento gris de 50 kg les quedan?", True), ("¿hay existencias del tubo?", True),
    ("¿cuánto vale el tubo de 1/2?", False), ("necesito 3 metros de tubo", False),
])
def test_what_asks_how_many_are_left(message, expected):
    from asistendero.reply_text import asks_stock
    from asistendero.validation import normalize_text

    assert asks_stock(normalize_text(message)) is expected


ROLLER = {"text": "rodillo de 9 pulgadas", "product": "rodillo", "measure": "9 pulgadas"}
BRUSH_2 = {"text": "brocha de 2 pulgadas", "product": "brocha", "measure": "2 pulgadas"}


def test_a_bare_ese_after_two_products_asks_which_one(chat):
    # Z-36 (suite fallas): tras «la brocha de 2 pulgadas y el rodillo de 9», «dame 3 de ese» cotizó la brocha.
    turn, sessions, _ = chat
    session = sessions.create()
    turn(session, "¿qué precio tienen la brocha de 2 pulgadas y el rodillo de 9 pulgadas?",
         tool("buscar_productos", items=[BRUSH_2, ROLLER]), say())
    result = turn(session, "dame 3 de ese", quote(("BRO-2", 3)), say("Las 3 brochas te salen en $14.700. Datos simulados."))
    rejected = result["tool_calls"][0]["response"]["error"]
    assert rejected["code"] == "AMBIGUOUS_REFERENCE" and "rodillo" in rejected["message"]
    assert result["estado"] == "clarify" and "$" not in result["respuesta"]
    assert "la brocha de cerda de 2 pulgadas o el rodillo de felpa de 9 pulgadas?" in result["respuesta"]
    # Si dice cuál, se cotiza.
    named = turn(session, "dame 3 de ese rodillo", quote(("ROD-9", 3)), say())
    assert named["tool_calls"][0]["executed"] and "$41.700" in named["respuesta"]
    # Con un solo producto en la respuesta anterior, «ese» no tiene duda.
    single = turn(session, "dame 2 de ese", quote(("ROD-9", 2)), say())
    assert single["tool_calls"][0]["executed"]


def test_the_options_remembered_are_the_ones_shown_without_what_the_client_refused():
    # Z-17: la respuesta quita la pintura blanca; si la sesión la guardara, «la primera» elegiría una que no vio.
    from asistendero.choices import shown_options
    from asistendero.catalog import Product
    paints = [Product(sku, name, "galón", "unidad", 58900, 10, "2026-10-15") for sku, name in
              (("PIN-BLA", "Pintura blanca vinilo"), ("PIV-BEI-G", "Pintura vinilo beige"), ("PIV-GRI-G", "Pintura vinilo gris"))]
    calls = [{"requested_tool": "buscar_productos", "executed": True, "arguments": {"items": [{"text": "pintura en galón"}]},
              "response": {"status": "ok", "data": {"results": [{"matches": [vars(p) for p in paints], "nearby": []}]}}}]
    groups = shown_options("pintura en galón", calls, "la pintura que no es la blanca, en galón")
    assert [option["sku"] for option in groups[0]["opciones"]] == ["PIV-BEI-G", "PIV-GRI-G"]


def test_a_bare_answer_to_which_one_chooses_the_option_it_names(chat):
    # M-03 (corrida 35): tras «¿cuál?» con blanco, negro y rojo, «Negro, 15 metros» no respaldaba el cable negro.
    turn, sessions, _ = chat
    session = sessions.create()
    turn(session, "Necesito cable 12 AWG",
         tool("buscar_productos", items=[{"text": "cable 12 AWG", "product": "cable", "measure": "12 AWG"}]), say())
    result = turn(session, "Negro, 15 metros", quote(("CAB-12-NE", 15)), say())
    assert result["estado"] == "quoted" and "$40.500" in result["respuesta"]
    assert result["tool_calls"][0]["executed"]

    from asistendero.choices import chosen_options
    context = sessions.context(session)
    # Otro número, otro producto, dos colores o solo la cantidad no eligen nada.
    for message in ["necesito cable negro de 14", "negro, y un taladro", "blanco y negro, 5 de cada uno", "15 metros"]:
        assert chosen_options(message, context) == [], message
    assert [item["sku"] for item in chosen_options("pues el rojo mejor, 10 metros", context)] == ["CAB-12-RO"]
