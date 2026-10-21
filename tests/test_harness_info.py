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


SRC = Path(__file__).resolve().parents[1] / "src" / "asistendero"


def test_description_comes_from_the_code_constants():
    info = describe_harness()
    assert info["prompt_version"] == PROMPT_VERSION
    assert info["instructions"] == AGENT_PROMPT
    assert [tool["name"] for tool in info["tools"]] == list(TOOL_NAMES)
    assert info["limits"]["max_tool_calls"] == MAX_TOOL_CALLS
    assert info["limits"]["max_message_chars"] == MAX_MESSAGE_CHARS
    assert info["reminder"]["code"] == "QUOTE_REQUIRED"


def test_every_rejection_code_in_the_flow_is_on_the_map():
    source = (SRC / "validation.py").read_text(encoding="utf-8") + (SRC / "graph.py").read_text(encoding="utf-8")
    codes = set(re.findall(r'Rejected\("([A-Z_]+)"', source))
    assert codes, "no se encontraron rechazos en el código"
    assert codes <= set(describe_harness()["rejections"])


def test_every_final_state_in_the_flow_is_classified():
    source = (SRC / "answers.py").read_text(encoding="utf-8") + (SRC / "graph.py").read_text(encoding="utf-8")
    patterns = [
        r'return "([a-z_]+)", ',  # (estado, respuesta) de render_answer
        r'statuses\.append\("([a-z_]+)"\)',
        r'status = "([a-z_]+)"',
        r'\{\*\*common, "estado": "([a-z_]+)"',  # salida del nodo respond
        r'"[A-Z_]+": "([a-z_]+)"',  # código de error → estado en respond
        r'\.get\(error\["code"\], "([a-z_]+)"\)',
    ]
    states = {state for pattern in patterns for state in re.findall(pattern, source)}
    classified = {state for group in describe_harness()["outcomes"].values() for state in group["states"]}
    assert {"quoted", "insufficient_stock", "model_error", "limit_reached"} <= states
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


def test_visual_server_serves_harness_map_only_to_local_host(monkeypatch):
    monkeypatch.setenv("GROK_API_KEY", "xai-clave-que-no-debe-salir")
    server = visual.make_server(0)
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
