import http.client
import json
from threading import Thread

import pytest

from asistendero.catalog import MockCatalog
from asistendero.grok import Plan, Resolution
from asistendero.search import ProductQuery
from asistendero.seed import create_mock_db
from asistendero.tracing import run_traced
from asistendero import visual


def test_trace_shows_agent_first_tool_call_without_configured_key(tmp_path, monkeypatch):
    monkeypatch.setenv("GROK_API_KEY", "clave-de-prueba-no-publicar")
    catalog = MockCatalog(create_mock_db(tmp_path / "catalog.sqlite3"))
    events = []
    result = run_traced(
        "Busco tubo PVC de 1/2",
        events.append,
        catalog,
        lambda *_: Plan("search_products", (ProductQuery("tubo PVC de 1/2", product="tubo", material="PVC", measure="1/2"),), "productos", "",
                        "grok-4.20-0309-non-reasoning", 30, 5,
                        reported_cost_usd_ticks=500_000),
        lambda *_: Resolution(("PVC-050",), "Revisé el catálogo:",
                              "grok-4.20-0309-non-reasoning", 20, 4),
    )

    assert result["estado"] == "found"
    assert [event["node"] for event in events if event["type"] == "node" and event["status"] == "complete"] == ["validate", "interpret", "retrieve", "respond"]
    retrieval = next(event for event in events if event.get("node") == "retrieve" and event.get("status") == "complete")
    assert retrieval["details"]["hallazgos"][0]["candidates"][0]["price_cop"] == 8500
    requests = [event for event in events if event["type"] == "model_request"]
    assert [item["details"]["phase"] for item in requests] == ["interpret", "resolve"]
    assert "hallazgos" not in requests[0]["details"]
    assert requests[1]["details"]["hallazgos"][0]["candidates"][0]["stock"] == 12
    assert "clave-de-prueba-no-publicar" not in json.dumps(events)
    assert events[-1]["type"] == "final"
    responses = [event for event in events if event["type"] == "model_response"]
    assert [event["details"]["cost"]["basis"] for event in responses] == [
        "api_reported", "xai_public_estimate",
    ]
    assert events[-1]["details"]["cost"]["basis"] == "mixed"
    assert events[-1]["details"]["cost"]["calls"] == 2


def test_trace_records_direct_response_without_catalog(tmp_path):
    catalog = MockCatalog(create_mock_db(tmp_path / "catalog.sqlite3"))
    events = []
    result = run_traced(
        "¿Están atendiendo?", events.append, catalog,
        lambda *_: Plan("respond", (), "horario", "No sé."),
        lambda *_: (_ for _ in ()).throw(AssertionError("No hacer segunda llamada")),
    )
    assert result["estado"] == "answered"
    assert any(event["type"] == "route" and "sin consultar catálogo" in event["details"]["motivo"] for event in events)
    assert len([event for event in events if event["type"] == "model_request"]) == 1


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
