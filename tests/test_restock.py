"""Surtido: «veci, ¿cuándo le llegan más?» se responde con lo que anotó el tendero, y nunca con una fecha inventada."""

from datetime import date, datetime, timedelta
import sqlite3

import pytest

from asistendero.catalog import MockCatalog
from asistendero.chat import run_turn
from asistendero.executor import catalog_executor
from asistendero.graph import build_graph
from asistendero.grok import Decision
from asistendero.inventory import Inventory, InventoryError
from asistendero.orders import BOGOTA, OrderBook
from asistendero.restock import asks_restock, plan_of, restock_reply_ok, restock_sentence, valid_plan
from asistendero.seed import create_mock_db, upgrade_db
from asistendero.sessions import SessionStore
from asistendero.validation import normalize_text


HAMMER = {"text": "martillo de uña de 16 oz", "product": "martillo", "measure": "16 oz"}
PVC_HALF = {"text": "tubo PVC de 1/2 para agua", "product": "tubo", "material": "PVC", "measure": "1/2 pulgada", "use": "agua"}
LEVEL = {"text": "nivel de burbuja de 24 pulgadas", "product": "nivel", "measure": "24 pulgadas"}
SAW = {"text": "serrucho de 20 pulgadas", "product": "serrucho", "measure": "20 pulgadas"}
TODAY = date(2026, 10, 23)


def tool(name, **arguments):
    return Decision("call_tool", "productos", name, arguments, "")


def say(reply="", intent="productos"):
    return Decision("respond", intent, None, None, reply)


class Script:
    def __init__(self, *steps):
        self.steps = list(steps)
        self.seen = []

    def __call__(self, message, observations, remaining, context=None):
        self.seen.append(observations)
        return self.steps.pop(0)


@pytest.fixture
def db(tmp_path):
    return create_mock_db(tmp_path / "catalog.sqlite3")


def ask(db, message, *steps):
    planner = Script(*steps)
    result = build_graph(catalog_executor(MockCatalog(db)), planner).invoke({"consulta": message})
    result["avisos"] = [item["error"]["code"] for item in planner.seen[-1] if item.get("estado") == "aviso"]
    return result


@pytest.mark.parametrize(("message", "expected"), [
    ("veci, ¿cuándo le llegan más martillos?", True), ("¿ya no van a traer más de ese?", True),
    ("¿lo siguen trayendo?", True), ("¿cuándo vuelve a llegar el serrucho?", True),
    ("¿cuánto vale el martillo?", False), ("cuando llegue a la tienda te pago", False),
    ("¿a qué hora llega el pedido?", False), ("necesito 3 metros de tubo", False),
])
def test_what_asks_about_the_restock(message, expected):
    assert asks_restock(normalize_text(message)) is expected


def test_the_shopkeeper_writes_a_day_a_date_or_discontinued():
    assert valid_plan(" Miércoles ") == "miercoles" and valid_plan("DESCONTINUADO") == "descontinuado"
    assert valid_plan("") == ""
    soon = (datetime.now(BOGOTA).date() + timedelta(days=3)).isoformat()
    assert valid_plan(soon) == soon
    for wrong in ("pronto", "2020-01-01", (datetime.now(BOGOTA).date() + timedelta(days=400)).isoformat(), 5):
        with pytest.raises(ValueError):
            valid_plan(wrong)
    # Una fecha que ya pasó no dice nada: no se promete una llegada vencida.
    assert plan_of("2026-10-20", TODAY) == ("", "") and plan_of("2026-10-27", TODAY) == ("fecha", "2026-10-27")


@pytest.mark.parametrize(("restock", "asked", "stock", "expected"), [
    ("martes", False, 12, ""),
    ("martes", True, 12, "El martillo me llega los martes, cuando viene el proveedor."),
    ("2026-10-27", True, 12, "El martillo me llega el martes 27/10."),
    ("martes", False, 0, "El martillo está agotado por ahora, pero me llega los martes, cuando viene el proveedor."),
    ("descontinuado", False, 0, "El martillo está agotado y ya no lo vamos a volver a traer."),
    ("descontinuado", True, 4, "El martillo ya no lo vamos a volver a traer; lo que queda es lo último."),
    ("", False, 0, "El martillo está agotado por ahora."),
    ("", True, 0, "El martillo está agotado y no tengo fecha de cuándo vuelve a llegar; en el mostrador te pueden "
                  "averiguar."),
    ("", False, 12, ""),
])
def test_the_restock_is_said_only_when_asked_or_out_of_stock(restock, asked, stock, expected):
    assert restock_sentence("martillo", restock, asked, stock, TODAY) == expected


@pytest.mark.parametrize(("name", "restock", "asked", "stock", "expected"), [
    # Suite surtido (U-04, U-08): decía «El cinta aislante … está agotado».
    ("cinta aislante negra 18 m", "", True, 0, "La cinta aislante negra 18 m está agotada y no tengo fecha de cuándo "
                                               "vuelve a llegar; en el mostrador te pueden averiguar."),
    ("esmalte sintético gris en galón", "descontinuado", False, 0,
     "El esmalte sintético gris en galón está agotado y ya no lo vamos a volver a traer."),
    ("llave expansiva de 12 pulgadas", "jueves", True, 3, "La llave expansiva de 12 pulgadas me llega los jueves, "
                                                          "cuando viene el proveedor."),
    ("guantes de carnaza talla L", "martes", False, 0,
     "Los guantes de carnaza talla L están agotados por ahora, pero me llegan los martes, cuando viene el proveedor."),
    ("pintura vinilo marfil", "descontinuado", True, 2,
     "La pintura vinilo marfil ya no la vamos a volver a traer; lo que queda es lo último."),
])
def test_the_restock_sentence_agrees_with_the_product(name, restock, asked, stock, expected):
    assert restock_sentence(name, restock, asked, stock, TODAY) == expected


@pytest.mark.parametrize(("reply", "restocks", "ok"), [
    ("Te llegan los martes, cuando viene el proveedor.", ["martes"], True),
    ("Te llegan el jueves.", ["martes"], False),
    ("Pronto me llegan más.", ["martes"], False),
    ("Me llegan la otra semana.", [""], False),
    ("Ese ya no lo vamos a traer.", ["martes"], False),
    ("Ese ya no lo vamos a volver a traer.", ["descontinuado"], True),
    ("No tengo fecha de cuándo llega; pregúntale al tendero.", [""], True),
    ("Me llega el martes 27/10.", ["2026-10-27"], True),
    ("Me llega el martes 28/10.", ["2026-10-27"], False),
    # Sin hablar de surtido, un día de la semana es otra cosa (el horario, la recogida).
    ("Te esperamos el jueves a las 4.", [""], True),
])
def test_grok_never_promises_a_restock_the_shopkeeper_did_not_write(reply, restocks, ok):
    assert restock_reply_ok(normalize_text(reply), restocks, TODAY) is ok


def test_an_out_of_stock_hammer_says_when_it_arrives(db):
    result = ask(db, "veci, ¿cuándo le llegan más martillos de uña de 16 oz?", tool("buscar_productos", items=[HAMMER]),
                 say())
    answer = result["respuesta"]
    assert "está agotado por ahora, pero me llega los martes, cuando viene el proveedor." in answer
    assert "$" not in answer and "¿Cuántos" not in answer


def test_an_invented_restock_date_falls_back_to_what_the_shopkeeper_wrote(db):
    invented = ask(db, "veci, ¿cuándo le llegan más martillos de uña de 16 oz?", tool("buscar_productos", items=[HAMMER]),
                   say("Se me acabó, pero me llegan el jueves. Precios de demostración."))
    assert "jueves" not in invented["respuesta"] and "los martes" in invented["respuesta"]
    true = ask(db, "veci, ¿cuándo le llegan más martillos de uña de 16 oz?", tool("buscar_productos", items=[HAMMER]),
               say("Se me acabó, pero me llegan los martes. Precios de demostración."))
    assert true["respuesta"].startswith("Se me acabó, pero me llegan los martes.")


def test_the_restock_is_not_announced_when_nobody_asked(db):
    result = ask(db, "¿tienen tubo PVC de 1/2 para agua?", tool("buscar_productos", items=[PVC_HALF]), say())
    assert "viernes" not in result["respuesta"] and "proveedor" not in result["respuesta"]
    asked = ask(db, "¿cuándo les llega más tubo PVC de 1/2 para agua?", tool("buscar_productos", items=[PVC_HALF]), say())
    assert "me llega los viernes" in asked["respuesta"]


def test_discontinued_and_unknown_are_said_as_they_are(db):
    level = ask(db, "¿ya no van a traer el nivel de burbuja de 24 pulgadas?", tool("buscar_productos", items=[LEVEL]), say())
    assert "ya no lo vamos a volver a traer" in level["respuesta"]
    saw = ask(db, "¿cuándo vuelve a llegar el serrucho de 20 pulgadas?", tool("buscar_productos", items=[SAW]), say())
    assert "no tengo fecha" in saw["respuesta"] and "llega los" not in saw["respuesta"]


def test_a_restock_question_answered_without_looking_gets_one_reminder(db):
    result = ask(db, "veci, ¿cuándo le llegan más martillos de uña de 16 oz?",
                 say("Uy, eso llega la otra semana."), tool("buscar_productos", items=[HAMMER]), say())
    assert result["avisos"] == ["RESTOCK_REQUIRED"]
    assert "otra semana" not in result["respuesta"] and "los martes" in result["respuesta"]


def test_in_a_conversation_the_remembered_product_can_be_checked_again(tmp_path):
    db = create_mock_db(tmp_path / "catalog.sqlite3")
    book = OrderBook(db, clock=lambda: datetime(2026, 10, 21, 10, 0, tzinfo=BOGOTA))
    sessions = SessionStore(tmp_path / "sessions.sqlite3")
    session = sessions.create()
    run_turn(sessions, session, "¿tienen martillo de uña de 16 oz?",
             planner=Script(tool("buscar_productos", items=[HAMMER]), say()), orders=book)
    later = run_turn(sessions, session, "y veci, ¿cuándo le llegan más?",
                     planner=Script(tool("consultar_disponibilidad", sku="MAR-16"), say()), orders=book)
    assert later["tool_calls"][0]["executed"] and "me llega los martes" in later["respuesta"]


def test_a_restock_question_does_not_carry_over_to_the_next_turn(tmp_path):
    # Suite natural (H-04): tras «¿y cuándo le llega más?», «¿y el de 20 onzas cuánto vale?» seguía diciendo cuándo
    # llega: la pregunta se leía de los turnos anteriores, no del mensaje de ahora.
    db = create_mock_db(tmp_path / "catalog.sqlite3")
    book = OrderBook(db, clock=lambda: datetime(2026, 10, 21, 10, 0, tzinfo=BOGOTA))
    sessions = SessionStore(tmp_path / "sessions.sqlite3")
    session = sessions.create()
    run_turn(sessions, session, "veci, ¿cuándo le llegan más martillos de 16 oz?",
             planner=Script(tool("buscar_productos", items=[HAMMER]), say()), orders=book)
    price = run_turn(sessions, session, "y el de 20 onzas cuanto vale?",
                     planner=Script(tool("buscar_productos", items=[{"text": "martillo de uña de 20 oz",
                                                                     "product": "martillo", "measure": "20 oz"}]),
                                    say()), orders=book)
    assert "$32.900" in price["respuesta"] and "martes" not in price["respuesta"]


def test_out_of_stock_is_not_said_twice_when_the_quote_fails(db):
    # Suite surtido (U-10): tras «está agotado … me llega los martes» venía «solo me quedan 0 unidades».
    result = ask(db, "dame 2 martillos de uña de 16 oz", tool("buscar_productos", items=[HAMMER]),
                 tool("calcular_cotizacion_informativa", lines=[{"sku": "MAR-16", "quantity": 2}]), say())
    assert result["estado"] == "insufficient_stock" and "me llega los martes" in result["respuesta"]
    assert "0 unidades" not in result["respuesta"] and "Total" not in result["respuesta"]


def test_the_panel_writes_the_restock_with_history(db):
    inventory = Inventory(db)
    soon = (datetime.now(BOGOTA).date() + timedelta(days=2)).isoformat()
    assert inventory.update("SER-20", {"surtido": "Jueves"})["surtido"] == "jueves"
    assert MockCatalog(db).get("SER-20").restock == "jueves"
    assert inventory.update("SER-20", {"surtido": soon})["surtido"] == soon
    assert inventory.update("SER-20", {"surtido": ""})["surtido"] == ""
    assert [(item["campo"], item["despues"]) for item in inventory.history()[:3]] == [
        ("surtido", "sin dato"), ("surtido", soon), ("surtido", "jueves")]
    with pytest.raises(InventoryError):
        inventory.update("SER-20", {"surtido": "la otra semana"})
    # El agente solo lee: nada de esto cambia precio ni existencias.
    assert MockCatalog(db).get("SER-20").stock == 0


def _old_base(tmp_path):
    db = create_mock_db(tmp_path / "old.sqlite3")
    with sqlite3.connect(db) as connection:
        connection.execute("DROP TABLE restocks")
    return db


def test_the_cli_and_the_evaluator_upgrade_an_old_base(tmp_path, monkeypatch, capsys):
    # Corrida 26 con Grok real: los casos de un turno decían «no tengo fecha» del martillo que llega los martes; la
    # base compartida era de antes del surtido y solo el libro de pedidos la actualizaba.
    from asistendero import cli, evaluate

    db = _old_base(tmp_path)
    monkeypatch.setattr(cli, "DEFAULT_DB_PATH", db)
    monkeypatch.setattr(cli, "decide_with_grok", Script(tool("buscar_productos", items=[HAMMER]), say()))
    monkeypatch.setattr("sys.argv", ["asistendero", "veci, ¿cuándo le llegan más martillos de uña de 16 oz?"])
    cli.main()
    assert "me llega los martes" in capsys.readouterr().out

    seen = {}

    def stop(cases, *, catalog, **options):
        seen["restock"] = catalog.get("FLX-8").restock
        raise SystemExit(0)

    other = _old_base(tmp_path / "otra")
    monkeypatch.setattr(evaluate, "DEFAULT_DB_PATH", other)
    monkeypatch.setattr(evaluate, "evaluate_cases", stop)
    monkeypatch.setattr(evaluate, "load_dotenv", lambda: None)
    monkeypatch.setattr("sys.argv", ["evaluate", "--live", "--suite", "surtido"])
    with pytest.raises(SystemExit):
        evaluate.main()
    assert seen == {"restock": "viernes"}


def test_the_demo_restocks_are_seeded_once(db):
    with sqlite3.connect(db) as connection:
        connection.execute("DELETE FROM restocks WHERE sku = 'MAR-16'")
    upgrade_db(db)
    assert MockCatalog(db).get("MAR-16").restock == "" and MockCatalog(db).get("FLX-8").restock == "viernes"


def test_the_restock_question_is_about_the_product_it_names(db):
    # Z-25 (suite fallas): «¿tienen candado…, cuándo les llega el martillo…?» decía «no tengo fecha» también del candado.
    lock = {"text": "candado de 40 mm", "product": "candado", "measure": "40 mm"}
    result = ask(db, "¿tienen candado de 40 mm, cuándo les llega el martillo de uña de 16 oz?",
                 tool("buscar_productos", items=[lock, HAMMER]), say())
    assert "martillo de uña de 16 oz está agotado por ahora, pero me llega los martes" in result["respuesta"]
    assert "no tengo fecha" not in result["respuesta"].casefold()
    from asistendero.restock import restock_subjects
    # Sin producto en la parte que pregunta, vale para todos.
    assert restock_subjects("¿y cuando le llegan mas?", ["candado", "martillo"]) == {0, 1}
