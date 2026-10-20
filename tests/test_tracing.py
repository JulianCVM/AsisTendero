import http.client
import json
from threading import Thread

import pytest

from asistendero.grok import Decision, ModelError
from asistendero.tracing import run_traced
from asistendero import visual


PVC = {"sku": "PVC-050", "name": "Tubo PVC presión para agua", "variant": "1/2 pulgada", "unit": "metro",
       "price_cop": 8500, "stock": 12, "updated_at": "2026-10-15T00:00:00-05:00"}


def executor(name, arguments):
    data = {
        "buscar_productos": {"results": [{"matches": [PVC], "nearby": []}]},
        "consultar_disponibilidad": {"sku": "PVC-050", "stock": 12, "unit": "metro"},
    }[name]
    return {"status": "ok", "data": data, "error": None, "source": "mock_sqlite",
            "observed_at": "2026-10-20T12:00:00+00:00"}


def test_trace_separates_grok_requests_from_server_execution(monkeypatch):
    monkeypatch.setenv("GROK_API_KEY", "clave-de-prueba-no-publicar")
    steps = iter([
        Decision("call_tool", "productos", "buscar_productos",
                 {"items": [{"text": "tubo PVC de 1/2", "material": "PVC", "measure": "1/2"}]}, "",
                 "grok-4.20-0309-non-reasoning", 30, 5, reported_cost_usd_ticks=500_000),
        Decision("call_tool", "productos", "consultar_disponibilidad", {"sku": "PVC-050"}, "",
                 "grok-4.20-0309-non-reasoning", 40, 5),
        Decision("respond", "productos", None, None, "", "grok-4.20-0309-non-reasoning", 50, 20),
    ])
    events = []
    result = run_traced("Busco tubo PVC de 1/2", events.append, executor, lambda *_: next(steps))

    assert result["estado"] == "found"
    completed = [event["node"] for event in events if event["type"] == "node" and event["status"] == "complete"]
    assert completed == ["validate", "interpret", "retrieve", "interpret", "retrieve", "interpret", "respond"]
    tool_events = [event["details"]["tool_call"] for event in events
                   if event.get("node") == "retrieve" and event.get("status") == "complete"]
    assert [call["requested_tool"] for call in tool_events] == ["buscar_productos", "consultar_disponibilidad"]
    assert tool_events[0]["requested_arguments"]["items"][0]["measure"] == "1/2"
    assert tool_events[0]["executed"] and tool_events[0]["response"]["data"]["results"][0]["matches"][0]["price_cop"] == 8500
    requests = [event for event in events if event["type"] == "model_request"]
    assert [item["details"]["phase"] for item in requests] == ["interpret", "resolve", "resolve"]
    assert requests[0]["details"]["observaciones"] == []
    assert requests[2]["details"]["observaciones"][1]["datos"]["stock"] == 12
    assert "clave-de-prueba-no-publicar" not in json.dumps(events)
    assert events[-1]["type"] == "final"
    assert events[-1]["details"]["tool_calls"] == 2
    responses = [event for event in events if event["type"] == "model_response"]
    assert [event["details"]["cost"]["basis"] for event in responses] == [
        "api_reported", "xai_public_estimate", "xai_public_estimate",
    ]
    assert events[-1]["details"]["cost"]["basis"] == "mixed"
    assert events[-1]["details"]["cost"]["calls"] == 3


def test_trace_records_direct_response_without_tools():
    events = []
    result = run_traced(
        "¿Están atendiendo?", events.append,
        lambda *_: pytest.fail("No debe ejecutar herramientas"),
        lambda *_: Decision("respond", "horario", None, None, "No sé."),
    )
    assert result["estado"] == "answered"
    assert any(event["type"] == "route" and "sin herramientas" in event["details"]["motivo"] for event in events)
    assert len([event for event in events if event["type"] == "model_request"]) == 1


def test_trace_records_model_failure_with_code_and_unknown_cost():
    events = []

    def planner(*_):
        raise ModelError("MODEL_TIMEOUT", "Grok no respondió a tiempo.")

    result = run_traced("Busco PVC", events.append, lambda *_: pytest.fail("Sin herramientas"), planner)
    assert result["estado"] == "model_error"
    assert events[-1]["details"]["error"]["code"] == "MODEL_TIMEOUT"
    assert events[-1]["details"]["cost"] is None
    response = next(event for event in events if event["type"] == "model_response")
    assert response["details"]["error"]["code"] == "MODEL_TIMEOUT"


def test_visual_server_streams_local_events_and_rejects_other_origins(monkeypatch):
    def fake_run(query, emit):
        emit({"type": "input", "details": {"consulta": query}})
        emit({"type": "final", "details": {"estado": "ok", "respuesta": "Prueba", "model_called": False}})

    monkeypatch.setattr(visual, "run_traced", fake_run)
    server = visual.make_server(0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        try:
            connection.request("GET", "/")
        except PermissionError:
            pytest.skip("Este entorno restringe conexiones a sockets locales")
        page = connection.getresponse()
        assert page.status == 200
        assert "Centro de pruebas" in page.read().decode("utf-8")

        headers = {"Content-Type": "application/json", "Origin": "https://sitio-externo.example"}
        connection.request("POST", "/api/trace", json.dumps({"consulta": "PVC"}), headers)
        denied = connection.getresponse()
        assert denied.status == 403
        denied.read()

        headers["Origin"] = f"http://127.0.0.1:{server.server_port}"
        connection.request("POST", "/api/trace", json.dumps({"consulta": "PVC"}), headers)
        response = connection.getresponse()
        assert response.status == 200
        events = [json.loads(line) for line in response.read().decode("utf-8").splitlines()]
        assert [event["type"] for event in events] == ["input", "final"]
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
