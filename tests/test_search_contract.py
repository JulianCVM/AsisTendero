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


@pytest.mark.parametrize("model", ["grok-3", "grok-4.3", "gpt-4o"])
def test_models_outside_the_challenge_rules_are_rejected_before_the_gateway(monkeypatch, model):
    monkeypatch.setenv("GROK_API_KEY", "clave-de-prueba")
    monkeypatch.setenv("GROK_MODEL", model)
    monkeypatch.setattr(grok, "OpenAI", lambda **_: pytest.fail("No debía crear el cliente"))
    with pytest.raises(grok.ModelError) as raised:
        grok.decide_with_grok("Hola", [], 6)
    assert raised.value.code == "MODEL_NOT_ALLOWED"


def test_conversation_context_is_sent_only_in_a_session(monkeypatch):
    seen = {}

    def complete(system, payload):
        seen.clear()
        seen.update(payload)
        return json.dumps({"action": "respond", "intent": "otro", "reply": "ok"}), "m", 1, 1, None, None

    monkeypatch.setattr(grok, "_complete", complete)
    context = {"turnos": [{"cliente": "Busco tubo PVC de 1/2", "asistente": "Cuesta [precio]"}], "productos": []}
    grok.decide_with_grok("Dame 3", [], 6, context=context)
    assert seen["conversacion"] == {"turnos": [{"cliente": "Busco tubo PVC de 1/2", "asistente": "Cuesta [precio]"}]}
    grok.decide_with_grok("Hola", [], 6)
    assert "conversacion" not in seen


def test_system_prompt_prefix_is_immutable_and_dynamic_state_stays_in_user_payload(monkeypatch):
    from asistendero.prompt import AGENT_PROMPT

    monkeypatch.setenv("GROK_API_KEY", "clave-de-prueba")
    captured = []

    class RecordingClient:
        def __init__(self, **_):
            self.chat = self
            self.completions = self

        def create(self, **kwargs):
            captured.append(kwargs)
            msg = type("Msg", (), {"content": '{"action":"respond","intent":"saludo","reply":"Hola"}'})()
            choice = type("Choice", (), {"message": msg})()
            usage = type("Usage", (), {"prompt_tokens": 100, "completion_tokens": 10,
                                       "prompt_tokens_details": None, "cost_in_usd_ticks": None})()
            return type("Resp", (), {"choices": [choice], "model": "grok-4.20-0309-non-reasoning", "usage": usage})()

    monkeypatch.setattr(grok, "OpenAI", RecordingClient)
    grok.decide_with_grok("Hola", [], 6)
    grok.decide_with_grok(
        "Confirmo", [{"herramienta": "buscar_productos", "estado": "ok"}], 4,
        context={"ahora": "2026-10-28 14:00 (miércoles)", "turnos": [{"cliente": "Hola", "asistente": "Buenas"}],
                 "productos": [], "pedidos": [{"pedido": "P-123456", "estado": "pendiente", "nota": None}]},
    )
    assert len(captured) == 2
    first_msgs, second_msgs = captured[0]["messages"], captured[1]["messages"]
    assert first_msgs[0] == {"role": "system", "content": AGENT_PROMPT}
    assert second_msgs[0] == first_msgs[0]
    assert "2026-10-28" not in second_msgs[0]["content"] and "P-123456" not in second_msgs[0]["content"]
    assert second_msgs[1]["role"] == "user" and "\n" not in second_msgs[1]["content"]
    user_payload = json.loads(second_msgs[1]["content"])
    assert user_payload["conversacion"]["ahora"] == "2026-10-28 14:00 (miércoles)"
    assert "productos" not in user_payload["conversacion"]
    assert "nota" not in user_payload["conversacion"]["pedidos"][0]


def test_s2_hours_intent_is_still_accepted_as_store_intent(monkeypatch):
    payload = {"action": "respond", "intent": "horario", "tool": None, "arguments": None, "reply": "Consulto."}
    monkeypatch.setattr(grok, "_complete", fake_complete(payload))
    decision = grok.decide_with_grok("¿Abren hoy?", [], 6)
    assert decision.valid_json and decision.intent == "tienda"
