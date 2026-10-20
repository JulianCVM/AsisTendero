import json

import httpx
import openai
import pytest

from asistendero import grok


def fake_complete(payload):
    return lambda *_: (json.dumps(payload) if not isinstance(payload, str) else payload,
                       "modelo-prueba", 20, 30, None, None)


def test_grok_tool_request_is_parsed_with_its_arguments(monkeypatch):
    payload = {
        "action": "call_tool", "intent": "productos", "tool": "buscar_productos", "reply": "",
        "arguments": {"items": [
            {"text": "tubo PVC de 1/2 para agua", "product": "tubo", "material": "PVC", "measure": "1/2 pulgada"},
            {"text": "bulto de cemento gris de 50 kg", "product": "cemento", "presentation": "bulto"},
        ]},
    }
    monkeypatch.setattr(grok, "_complete", fake_complete(payload))
    decision = grok.decide_with_grok("Busco tubo PVC de 1/2 para agua y un bulto de cemento gris de 50 kg", [], 6)
    assert decision.valid_json
    assert decision.action == "call_tool"
    assert decision.tool == "buscar_productos"
    assert decision.arguments["items"][1]["presentation"] == "bulto"
    assert decision.input_tokens == 20


@pytest.mark.parametrize("tool", grok.TOOL_NAMES)
def test_each_of_the_three_tools_is_accepted(monkeypatch, tool):
    payload = {"action": "call_tool", "intent": "productos", "tool": tool, "arguments": {"x": 1}, "reply": ""}
    monkeypatch.setattr(grok, "_complete", fake_complete(payload))
    assert grok.decide_with_grok("mensaje", [], 6).tool == tool


@pytest.mark.parametrize("payload", [
    {"action": "call_tool", "intent": "productos", "tool": "crear_pedido", "arguments": {}, "reply": ""},
    {"action": "call_tool", "intent": "productos", "tool": "buscar_productos", "arguments": ["PVC"], "reply": ""},
    {"action": "call_tool", "intent": "productos", "tool": "buscar_productos",
     "arguments": {"items": [{"text": "x" * 2000}]}, "reply": ""},
    {"action": "respond", "intent": "otro", "tool": "buscar_productos", "arguments": {"items": []}, "reply": "hola"},
    {"action": "borrar", "intent": "otro", "reply": ""},
    {"action": "respond", "intent": "venta", "reply": "hola"},
    "esto no es JSON",
    "[]",
])
def test_unknown_tool_or_malformed_decision_fails_closed(monkeypatch, payload):
    monkeypatch.setattr(grok, "_complete", fake_complete(payload))
    decision = grok.decide_with_grok("Crea el pedido", [], 6)
    assert not decision.valid_json
    assert decision.action == "respond"
    assert decision.tool is None and decision.arguments is None


def test_direct_reply_is_parsed(monkeypatch):
    payload = {"action": "respond", "intent": "saludo", "tool": None, "arguments": None, "reply": " Hola, ¿qué buscas? "}
    monkeypatch.setattr(grok, "_complete", fake_complete(payload))
    decision = grok.decide_with_grok("Hola", [], 6)
    assert decision.valid_json and decision.reply == "Hola, ¿qué buscas?"


def test_grok_receives_message_observations_and_remaining_calls(monkeypatch):
    seen = {}

    def complete(system, payload):
        seen.update(payload)
        return json.dumps({"action": "respond", "intent": "otro", "reply": "ok"}), "m", 1, 1, None, None

    monkeypatch.setattr(grok, "_complete", complete)
    grok.decide_with_grok("Hola", [{"herramienta": "buscar_productos"}], 4)
    assert seen == {"mensaje": "Hola", "observaciones": [{"herramienta": "buscar_productos"}], "llamadas_disponibles": 4}


def _request():
    return httpx.Request("POST", "https://api.example/v1/chat/completions")


@pytest.mark.parametrize(("error", "code"), [
    (openai.APITimeoutError(request=_request()), "MODEL_TIMEOUT"),
    (openai.RateLimitError("cuota agotada clave=sk-secreta", response=httpx.Response(429, request=_request()), body=None), "MODEL_QUOTA"),
    (openai.AuthenticationError("clave inválida", response=httpx.Response(401, request=_request()), body=None), "MODEL_AUTH"),
    (openai.APIStatusError("sin créditos", response=httpx.Response(402, request=_request()), body=None), "MODEL_QUOTA"),
    (openai.InternalServerError("fallo", response=httpx.Response(500, request=_request()), body=None), "MODEL_UNAVAILABLE"),
    (openai.APIConnectionError(request=_request()), "MODEL_UNAVAILABLE"),
])
def test_sdk_errors_become_safe_model_errors(monkeypatch, error, code):
    monkeypatch.setenv("GROK_API_KEY", "clave-de-prueba")

    class FailingClient:
        def __init__(self, **_):
            self.chat = self
            self.completions = self

        def create(self, **_):
            raise error

    monkeypatch.setattr(grok, "OpenAI", FailingClient)
    with pytest.raises(grok.ModelError) as raised:
        grok.decide_with_grok("Hola", [], 6)
    assert raised.value.code == code
    assert "sk-secreta" not in str(raised.value)
    assert raised.value.__cause__ is None


def test_missing_key_is_a_model_error(monkeypatch):
    monkeypatch.delenv("GROK_API_KEY", raising=False)
    with pytest.raises(grok.ModelError) as raised:
        grok.decide_with_grok("Hola", [], 6)
    assert raised.value.code == "MODEL_NOT_CONFIGURED"
