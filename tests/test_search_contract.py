import json

from asistendero import grok


def test_grok_plan_parses_one_structured_query_per_product(monkeypatch):
    payload = {
        "action": "search_products", "intent": "productos", "reply": "",
        "items": [
            {"text": "tubo PVC de 1/2 para agua", "product": "tubo", "material": "PVC", "measure": "1/2 pulgada", "use": "agua", "quantity": 2},
            {"text": "bulto de cemento gris de 50 kg", "product": "cemento", "measure": "50 kg", "presentation": "bulto"},
        ],
    }
    monkeypatch.setattr(grok, "_complete", lambda *_: (json.dumps(payload), "modelo-prueba", 20, 30, None, None))
    plan = grok.plan_with_grok("Busco dos tubos PVC de 1/2 para agua y un bulto de cemento gris de 50 kg")
    assert plan.valid_json
    assert plan.items[0].measure == "1/2 pulgada"
    assert plan.items[0].quantity == 2
    assert plan.items[1].presentation == "bulto"


def test_invalid_structured_plan_fails_closed(monkeypatch):
    payload = {"action": "search_products", "intent": "productos", "reply": "", "items": [
        {"text": "tubo", "product": "tubo", "quantity": -3}
    ]}
    monkeypatch.setattr(grok, "_complete", lambda *_: (json.dumps(payload), "modelo-prueba", 20, 30, None, None))
    plan = grok.plan_with_grok("Busco tubo")
    assert not plan.valid_json
    assert plan.action == "respond"
