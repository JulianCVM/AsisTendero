"""El mapa del harness del visor describe el flujo real: mismas constantes, códigos y estados."""

import http.client
import json
from pathlib import Path
import re
from threading import Thread

import pytest

from asistendero import visual
from asistendero.graph import MAX_MESSAGE_CHARS, MAX_TOOL_CALLS
from asistendero.grok import AGENT_PROMPT, PROMPT_VERSION, TOOL_NAMES
from asistendero.harness_info import describe_harness
from asistendero.sessions import SessionStore


SRC = Path(__file__).resolve().parents[1] / "src" / "asistendero"


def test_description_comes_from_the_code_constants():
    info = describe_harness()
    assert info["prompt_version"] == PROMPT_VERSION
    assert info["instructions"] == AGENT_PROMPT
    assert [tool["name"] for tool in info["tools"]] == list(TOOL_NAMES)
    assert info["limits"]["max_tool_calls"] == MAX_TOOL_CALLS
    assert info["limits"]["max_message_chars"] == MAX_MESSAGE_CHARS
    assert [item["code"] for item in info["reminders"]] == ["SEARCH_REQUIRED", "QUOTE_REQUIRED", "INFO_REQUIRED",
                                                            "LIST_QUOTE_REQUIRED", "RESTOCK_REQUIRED", "ORDER_REQUIRED"]
    assert set(info["guardrails"]) == {"PROMPT_DISCLOSURE", "CREDENTIALS", "INTERNAL_DATA", "THIRD_PARTY_DATA",
                                       "BUSINESS_PRIVATE"}


def test_every_rejection_code_in_the_flow_is_on_the_map():
    source = "".join((SRC / name).read_text(encoding="utf-8") for name in ("validation.py", "graph.py", "order_rules.py"))
    codes = set(re.findall(r'Rejected\("([A-Z_]+)"', source))
    assert codes, "no se encontraron rechazos en el código"
    assert codes <= set(describe_harness()["rejections"])


def test_every_final_state_in_the_flow_is_classified():
    source = "".join((SRC / name).read_text(encoding="utf-8") for name in ("answers.py", "graph.py", "order_replies.py"))
    patterns = [
        r'_(?:pedido|recogida)": "([a-z_]+)"',  # STATUS_BY_TOOL de order_replies
        r'if results else "([a-z_]+)"',  # estado de order_reply sin pedidos válidos
        r'return "([a-z_]+)", ',  # (estado, respuesta) de render_answer
        r'statuses\.append\("([a-z_]+)"\)',
        r'status = "([a-z_]+)"',
        r'\{\*\*common, "estado": "([a-z_]+)"',  # salida del nodo respond
        r'"[A-Z_]+": "([a-z_]+)"',  # código de error → estado en respond
        r'\.get\(error\["code"\], "([a-z_]+)"\)',
    ]
    states = {state for pattern in patterns for state in re.findall(pattern, source)}
    classified = {state for group in describe_harness()["outcomes"].values() for state in group["states"]}
    assert {"quoted", "insufficient_stock", "model_error", "limit_reached", "order_confirmed", "order_issue"} <= states
    assert states <= classified
    # Ningún estado puede estar en dos grupos: el veredicto de la corrida sería ambiguo.
    total = sum(len(group["states"]) for group in describe_harness()["outcomes"].values())
    assert total == len(classified)


def test_description_never_includes_the_key_or_gateway(monkeypatch):
    monkeypatch.setenv("GROK_API_KEY", "xai-clave-que-no-debe-salir")
    monkeypatch.setenv("GROK_BASE_URL", "https://pasarela.example/v1")
    serialized = json.dumps(describe_harness(), ensure_ascii=False)
    assert "xai-clave-que-no-debe-salir" not in serialized
    assert "pasarela.example" not in serialized


def test_visual_server_serves_harness_map_only_to_local_host(monkeypatch, tmp_path):
    monkeypatch.setenv("GROK_API_KEY", "xai-clave-que-no-debe-salir")
    server = visual.make_server(0, SessionStore(tmp_path / "sessions.sqlite3"))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        try:
            connection.request("GET", "/api/harness")
        except PermissionError:
            pytest.skip("Este entorno restringe conexiones a sockets locales")
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        assert response.status == 200
        assert json.loads(body)["prompt_version"] == PROMPT_VERSION
        assert "xai-clave-que-no-debe-salir" not in body

        connection.request("GET", "/api/harness", headers={"Host": "sitio-externo.example"})
        denied = connection.getresponse()
        denied.read()
        assert denied.status == 403

        connection.request("GET", "/assets/harness.js")
        script = connection.getresponse()
        assert script.status == 200
        assert "innerHTML" not in script.read().decode("utf-8")
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _castle_data(name: str) -> dict:
    page = (SRC / "ui" / "index.html").read_text(encoding="utf-8")
    match = re.search(rf'data-{name}="([^"]+)"', page)
    assert match, f"el castillo no trae data-{name}"
    return json.loads(match.group(1).replace("&quot;", '"').replace("&amp;", "&"))


def test_the_castle_animates_every_node_of_the_graph():
    source = (SRC / "graph.py").read_text(encoding="utf-8")
    nodes = set(re.findall(r'add_node\("([a-z_]+)"', source))
    script = (SRC / "ui" / "castillo.js").read_text(encoding="utf-8")
    assert nodes == {"validate", "interpret", "retrieve", "respond"}
    for node in nodes:
        assert f"event.node === '{node}'" in script, f"el castillo no muestra el nodo {node}"


def test_the_castle_route_only_joins_stations_that_exist():
    route = _castle_data("route")
    points = set(route["points"])
    assert {"cliente", "puerta", "torre", "cruce", "aduana", "bodega", "balanza", "mostrador", "salida"} <= points
    assert route["edges"] and all(a in points and b in points for a, b in route["edges"])
    script = (SRC / "ui" / "castillo.js").read_text(encoding="utf-8")
    walked = set(re.findall(r"go\('([a-z]+)'", script)) | set(re.findall(r"live\('([a-z]+)'", script))
    assert walked and walked <= points, walked - points
    page = (SRC / "ui" / "index.html").read_text(encoding="utf-8")
    for name in ("token", "portcullis", "barrier", "sign", "beam", "pan-left", "pan-right", "strings", "flag",
                 "lantern", "crates", "lock"):
        assert f'data-part="{name}"' in page, f"falta la pieza {name} que mueve castillo.js"


def test_visual_server_serves_the_castle_without_unsafe_html(tmp_path):
    server = visual.make_server(0, SessionStore(tmp_path / "sessions.sqlite3"))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        try:
            connection.request("GET", "/assets/castillo.js")
        except PermissionError:
            pytest.skip("Este entorno restringe conexiones a sockets locales")
        response = connection.getresponse()
        script = response.read().decode("utf-8")
        assert response.status == 200
        assert "innerHTML" not in script and not re.search(r"\b(?:alert|confirm|prompt)\(", script)
        for path in ("/assets/castillo.css", "/assets/iso.css"):
            connection.request("GET", path)
            sheet = connection.getresponse()
            assert sheet.status == 200 and "text/css" in sheet.getheader("Content-Type")
            sheet.read()
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_the_chat_script_finds_every_element_it_uses():
    # El chat se rearmó (hilo con desplazamiento propio, Enter para enviar): un id que app.js busca y la página ya
    # no tiene rompe el visor sin que ninguna otra prueba lo note.
    page = (SRC / "ui" / "index.html").read_text(encoding="utf-8")
    script = (SRC / "ui" / "app.js").read_text(encoding="utf-8")
    used = set(re.findall(r"querySelector\('#([\w-]+)'\)", script))
    assert {"chat-scroll", "chat-thread", "jump-latest", "query", "run", "form"} <= used
    missing = [name for name in sorted(used) if f'id="{name}"' not in page]
    assert missing == [], f"app.js busca ids que index.html no tiene: {missing}"
    assert "innerHTML" not in script and not re.search(r"\b(?:alert|confirm|prompt)\(", script)
