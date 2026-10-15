import http.client
import json
from threading import Thread

from asistendero.catalog import MockCatalog
from asistendero.grok import Decision
from asistendero.seed import create_mock_db
from asistendero.tracing import run_traced
from asistendero import visual


def test_trace_shows_real_node_data_without_configured_key(tmp_path, monkeypatch):
    monkeypatch.setenv("GROK_API_KEY", "clave-de-prueba-no-publicar")
    catalog = MockCatalog(create_mock_db(tmp_path / "catalog.sqlite3"))
    events = []
    result = run_traced(
        "Busco tubo PVC de 1/2",
        events.append,
        catalog,
        lambda *_: Decision("PVC-050", "modelo-falso", 30, 5, True, '{"selected_sku":"PVC-050"}'),
    )

    assert result["estado"] == "found"
    assert [event["node"] for event in events if event["type"] == "node" and event["status"] == "complete"] == ["validate", "retrieve", "decide", "render"]
    retrieval = next(event for event in events if event.get("node") == "retrieve" and event.get("status") == "complete")
    assert retrieval["details"]["candidatos"][0]["price_cop"] == 8500
    request = next(event for event in events if event["type"] == "model_request")
    user_payload = json.loads(request["details"]["messages"][1]["content"])
    assert user_payload["candidatos"]
    assert "price_cop" not in user_payload["candidatos"][0]
    assert "stock" not in user_payload["candidatos"][0]
    assert "clave-de-prueba-no-publicar" not in json.dumps(events)
    assert events[-1]["type"] == "final"


def test_trace_records_skipped_model_when_catalog_has_no_candidate(tmp_path):
    catalog = MockCatalog(create_mock_db(tmp_path / "catalog.sqlite3"))
    events = []
    result = run_traced("Busco taladro de 20 V", events.append, catalog, lambda *_: (_ for _ in ()).throw(AssertionError("No llamar")))
    assert result["estado"] == "not_found"
    assert any(event["type"] == "route" and "omite Grok" in event["details"]["motivo"] for event in events)
    assert not any(event["type"] == "model_request" for event in events)


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
        connection.request("GET", "/")
        page = connection.getresponse()
        assert page.status == 200
        assert "Visor del harness" in page.read().decode("utf-8")

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
