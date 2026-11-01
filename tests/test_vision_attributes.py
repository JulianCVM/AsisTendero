"""Pruebas unitarias para reconocimiento de imágenes mediante extracción estructurada de atributos.

Valida:
1. Esquema estructurado tipado (ImageAttributePayload).
2. Principio «Grok Visión extrae, el servidor gobierna».
3. Mapeo preciso a SQLite vía MockCatalog sin que la visión consulte la base ni decida SKUs.
4. Salto determinista cuando hay 1 único match que cumple is_distinguished y cantidad dicha.
5. Respeto estricto a QUANTITY_NOT_GROUNDED (no cotizar sin cantidad explícita).
6. Respeto estricto a SKU_NOT_GROUNDED y desambiguación guiada ante variantes ambiguas.
7. Tope de 2 preguntas de aclaración y Fallo seguro (R2: muestra física al mostrador).
8. Fallo seguro (R2) ante confianza visual baja.
9. Preservación de atributos en sesión para turnos posteriores sin reprocesar imágenes.
10. Aislamiento de payload, inmutabilidad de AGENT_PROMPT y Prompt Caching sin base64 en SessionStore.
"""

from pathlib import Path
import pytest

from asistendero.catalog import MockCatalog
from asistendero.chat import run_turn
from asistendero.grok import AGENT_PROMPT, Decision, PROMPT_VERSION, TOOL_NAMES
from asistendero.observations import ToolCall
from asistendero.orders import OrderBook
from asistendero.prompt import AGENT_PROMPT as PROMPT_FROM_MODULE
from asistendero.search import ProductQuery
from asistendero.seed import DEFAULT_DB_PATH, create_mock_db
from asistendero.sessions import SessionStore
from asistendero.validation import Rejected, validate_request
from asistendero.vision import (
    MAX_VISION_CLARIFICATIONS,
    SAMPLE_COUNTER_TEMPLATE,
    SCREW_SAFEGUARD_TEMPLATE,
    VISION_EXTRACTOR_OVERRIDE,
    ImageAttributePayload,
    extract_vision_attributes,
    handle_vision_turn,
    payload_to_product_query,
    sanitize_image_text,
    search_catalog_with_vision,
)


@pytest.fixture
def catalog_path(tmp_path):
    return create_mock_db(tmp_path / "catalog.sqlite3")


@pytest.fixture
def catalog(catalog_path):
    return MockCatalog(catalog_path)


@pytest.fixture
def orders(catalog_path):
    return OrderBook(path=catalog_path)


@pytest.fixture
def session_store(tmp_path):
    db_file = tmp_path / "sessions_test.sqlite3"
    return SessionStore(path=db_file)


class Script:
    """Grok falso para pruebas deterministas sin llamadas de red."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.seen = []

    def __call__(self, message, observations, remaining, context=None):
        self.seen.append({"observaciones": observations, "contexto": context})
        return self.steps.pop(0)


def tool(name, **arguments):
    return Decision("call_tool", "productos", name, arguments, "")


def say(reply="", intent="productos"):
    return Decision("respond", intent, None, None, reply)


# -------------------------------------------------------------------------
# 1. Esquema estructurado ImageAttributePayload
# -------------------------------------------------------------------------

def test_image_attribute_payload_schema():
    payload = ImageAttributePayload(
        tipo_producto="tubo",
        material="pvc",
        medidas_visibles=["1/2 pulgada"],
        presentacion_uso="presion agua",
        color_acabado="blanco",
        confianza_visual="alta",
    )
    assert payload.tipo_producto == "tubo"
    assert payload.material == "pvc"
    assert payload.medidas_visibles == ["1/2 pulgada"]
    assert payload.presentacion_uso == "presion agua"
    assert payload.color_acabado == "blanco"
    assert payload.confianza_visual == "alta"

    as_dict = payload.to_dict()
    assert as_dict["tipo_producto"] == "tubo"
    assert as_dict["confianza_visual"] == "alta"

    rebuilt = ImageAttributePayload.from_dict(as_dict)
    assert rebuilt == payload

    summary = payload.semantic_summary()
    assert "tubo pvc 1/2 pulgada presion agua blanco" in summary
    assert "confianza: alta" in summary


def test_image_attribute_payload_defaults_and_normalization():
    empty_payload = ImageAttributePayload.from_dict({})
    assert empty_payload.tipo_producto is None
    assert empty_payload.material is None
    assert empty_payload.medidas_visibles == []
    assert empty_payload.confianza_visual == "media"

    # Medidas como string individual se normalizan a lista
    single_measure = ImageAttributePayload.from_dict({
        "tipo_producto": "tornillo",
        "medidas_visibles": "1 pulgada",
        "confianza_visual": "invalid_value",
    })
    assert single_measure.medidas_visibles == ["1 pulgada"]
    assert single_measure.confianza_visual == "media"


# -------------------------------------------------------------------------
# 2. Extracción simulada («Grok Visión extrae, el servidor gobierna»)
# -------------------------------------------------------------------------

def test_simulated_vision_extraction():
    simulated = ImageAttributePayload(
        tipo_producto="cemento",
        material=None,
        medidas_visibles=["50 kg"],
        presentacion_uso="obra gris",
        color_acabado="gris",
        confianza_visual="alta",
    )
    token = VISION_EXTRACTOR_OVERRIDE.set(lambda _: simulated)
    try:
        extracted = extract_vision_attributes("dummy_base64_data")
        assert extracted == simulated
        # El payload de visión NO contiene SKUs ni interactúa con la base de datos
        assert not hasattr(extracted, "sku")
    finally:
        VISION_EXTRACTOR_OVERRIDE.reset(token)


# -------------------------------------------------------------------------
# 3. Mapeo de búsqueda en SQLite
# -------------------------------------------------------------------------

def test_vision_search_mapping_to_sqlite(catalog):
    payload = ImageAttributePayload(
        tipo_producto="tubo",
        material="pvc",
        medidas_visibles=["1/2 pulgada"],
        presentacion_uso="agua",
        color_acabado=None,
        confianza_visual="alta",
    )
    query = payload_to_product_query(payload, "necesito cotizar")
    assert isinstance(query, ProductQuery)
    assert query.product == "tubo"
    assert query.material == "pvc"
    assert query.measure == "1/2 pulgada"

    search_res = search_catalog_with_vision(catalog, payload)
    assert len(search_res.matches) >= 1
    skus = [p.sku for p in search_res.matches]
    assert "PVC-050" in skus


# -------------------------------------------------------------------------
# 4. Salto determinista: match único distinguido con cantidad dicha
# -------------------------------------------------------------------------

def test_deterministic_quote_jump_single_match_with_quantity(session_store, orders):
    session_id = session_store.create()
    payload = ImageAttributePayload(
        tipo_producto="tubo",
        material="pvc",
        medidas_visibles=["1/2 pulgada"],
        presentacion_uso="agua",
        color_acabado=None,
        confianza_visual="alta",
    )

    # El usuario pide explícitamente 5 metros con imagen
    result = run_turn(
        store=session_store,
        session_id=session_id,
        message="¿Cuánto me valen 5 metros de este?",
        orders=orders,
        image=payload,
    )

    # Verificación de salto determinista: sin quemar llamadas al modelo Grok
    assert result["model_called"] is False
    assert result["model_calls"] == 0
    assert result["estado"] == "answered"
    assert "5 metro" in result["respuesta"] or "5" in result["respuesta"]
    assert "COP" in result["respuesta"]

    # Se ejecutó búsqueda y cotización informativa en tool_calls
    tools_called = [c["requested_tool"] for c in result["tool_calls"]]
    assert "buscar_productos" in tools_called
    assert "calcular_cotizacion_informativa" in tools_called

    # Se guardó en la lista de compras y productos recordados
    ctx = session_store.context(session_id)
    assert any(p["sku"] == "PVC-050" for p in ctx["productos"])
    assert any(item["sku"] == "PVC-050" and item["cantidad"] == 5 for item in ctx["lista"])


# -------------------------------------------------------------------------
# 5. Respeto estricto a QUANTITY_NOT_GROUNDED
# -------------------------------------------------------------------------

def test_respects_quantity_not_grounded(session_store, orders):
    session_id = session_store.create()
    payload = ImageAttributePayload(
        tipo_producto="tubo",
        material="pvc",
        medidas_visibles=["1/2 pulgada"],
        presentacion_uso="agua",
        color_acabado=None,
        confianza_visual="alta",
    )

    # El usuario envía la imagen sin especificar cantidad
    result = run_turn(
        store=session_store,
        session_id=session_id,
        message="¿Tienen de este tubo?",
        orders=orders,
        image=payload,
    )

    # El servidor NO inventa cantidad ni cotiza sin autorización
    assert result["model_called"] is False
    assert result["model_calls"] == 0
    tools_called = [c["requested_tool"] for c in result["tool_calls"]]
    assert "calcular_cotizacion_informativa" not in tools_called
    assert "¿Cuántas unidades" in result["respuesta"] or "necesitas" in result["respuesta"]

    # Si se intentara forzar calcular_cotizacion_informativa sin cantidad dicha, se rechaza
    with pytest.raises(Rejected) as exc_info:
        validate_request(
            "calcular_cotizacion_informativa",
            {"lines": [{"sku": "PVC-050", "quantity": 10}]},
            "¿Tienen de este tubo?",
            [],
            quantities=set(),  # Ninguna cantidad en el mensaje
            remembered={"PVC-050": "Tubo PVC 1/2 pulgada metro"},
            listed={},
            current="¿Tienen de este tubo?",
        )
    assert exc_info.value.code == "QUANTITY_NOT_GROUNDED"


# -------------------------------------------------------------------------
# 6. Respeto estricto a SKU_NOT_GROUNDED y Desambiguación Guiada
# -------------------------------------------------------------------------

def test_respects_sku_not_grounded_on_ambiguity(session_store, orders):
    session_id = session_store.create()
    # Atributos ambiguos: codo PVC sin especificar medida
    payload = ImageAttributePayload(
        tipo_producto="codo",
        material="pvc",
        medidas_visibles=[],  # Sin medida visible
        presentacion_uso="presion",
        color_acabado=None,
        confianza_visual="alta",
    )

    result = run_turn(
        store=session_store,
        session_id=session_id,
        message="Necesito este codo",
        orders=orders,
        image=payload,
    )

    # Abre desambiguación guiada sin adivinar el SKU
    assert result["model_called"] is False
    assert result["model_calls"] == 0
    assert "1." in result["respuesta"]
    assert "2." in result["respuesta"]
    assert "¿Cuál de estas medidas" in result["respuesta"]

    # El servidor guardó las opciones en session_options
    ctx = session_store.context(session_id)
    assert len(ctx["opciones"]) >= 1

    # Intentar cotizar un SKU arbitrario que no fue seleccionado arroja SKU_NOT_GROUNDED
    with pytest.raises(Rejected) as exc_info:
        validate_request(
            "calcular_cotizacion_informativa",
            {"lines": [{"sku": "COD-050", "quantity": 1}]},
            "Necesito este codo",
            [],
            quantities={1},
            remembered={},
            listed={},
            current="Necesito este codo",
        )
    assert exc_info.value.code == "SKU_NOT_GROUNDED"


# -------------------------------------------------------------------------
# 7. Tope de 2 preguntas de aclaración y Fallo Seguro R2
# -------------------------------------------------------------------------

def test_clarification_cap_and_counter_failsafe(session_store, orders):
    session_id = session_store.create()
    ambiguous_payload = ImageAttributePayload(
        tipo_producto="tornillo",
        material="acero",
        medidas_visibles=[],
        presentacion_uso=None,
        color_acabado=None,
        confianza_visual="alta",
    )

    # Intento 1 de aclaración
    turn1 = run_turn(
        store=session_store,
        session_id=session_id,
        message="¿Tienen este tornillo?",
        orders=orders,
        image=ambiguous_payload,
    )
    assert "¿Cuál de estas" in turn1["respuesta"]

    # Intento 2 de aclaración
    turn2 = run_turn(
        store=session_store,
        session_id=session_id,
        message="No sé bien, es como mediano",
        orders=orders,
        image=ambiguous_payload,
    )
    assert "¿Cuál de estas" in turn2["respuesta"]

    # Intento 3: Supera el tope de 2 aclaraciones -> Fallo seguro R2 al mostrador
    turn3 = run_turn(
        store=session_store,
        session_id=session_id,
        message="Sigo con dudas",
        orders=orders,
        image=ambiguous_payload,
    )
    assert SAMPLE_COUNTER_TEMPLATE in turn3["respuesta"]
    assert "muestra física al mostrador" in turn3["respuesta"]


# -------------------------------------------------------------------------
# 8. Fallo seguro directo si la confianza es baja
# -------------------------------------------------------------------------

def test_low_confidence_triggers_counter_failsafe(session_store, orders):
    session_id = session_store.create()
    low_conf_payload = ImageAttributePayload(
        tipo_producto="pieza metalica",
        material="desconocido",
        medidas_visibles=[],
        confianza_visual="baja",
    )

    result = run_turn(
        store=session_store,
        session_id=session_id,
        message="¿Tienen esto?",
        orders=orders,
        image=low_conf_payload,
    )
    assert result["model_called"] is False
    assert result["model_calls"] == 0
    assert result["respuesta"] == SAMPLE_COUNTER_TEMPLATE
    assert "muestra física al mostrador" in result["respuesta"]


# -------------------------------------------------------------------------
# 9. Preservación de atributos en sesión para turnos posteriores
# -------------------------------------------------------------------------

def test_session_remembers_confirmed_specs_without_reprocessing_image(session_store, orders):
    session_id = session_store.create()
    # Turno 1: el usuario envía foto de tubo PVC sin medida
    turn1_payload = ImageAttributePayload(
        tipo_producto="tubo",
        material="pvc",
        medidas_visibles=[],
        presentacion_uso="agua",
        color_acabado=None,
        confianza_visual="alta",
    )
    res1 = run_turn(
        store=session_store,
        session_id=session_id,
        message="Busco este tubo",
        orders=orders,
        image=turn1_payload,
    )
    assert "¿Cuál de estas" in res1["respuesta"]

    # Verificar que las especificaciones fijadas quedaron guardadas en sesión
    ctx = session_store.context(session_id)
    assert "tubo" in ctx["especificaciones"]
    assert ctx["especificaciones"]["tubo"]["material"] == "pvc"

    # Turno 2: el usuario responde solo texto «el de 1/2 pulgada, cotízame 4»
    # NO se envía imagen; el bot debe recordar que hablaban de tubo PVC
    script = Script(
        tool("buscar_productos", items=[{"text": "tubo de 1/2 pulgada", "product": "tubo", "measure": "1/2 pulgada"}]),
        say("Te cotizo 4 metros de tubo PVC de 1/2 pulgada para agua."),
    )
    res2 = run_turn(
        store=session_store,
        session_id=session_id,
        message="el de 1/2 pulgada, cotízame 4 metros",
        orders=orders,
        planner=script,
    )
    assert res2["estado"] in ("quoted", "answered")
    assert "4 metro" in res2["respuesta"] or "PVC-050" in [line.get("sku") for line in (session_store.context(session_id).get("lista") or [])]


# -------------------------------------------------------------------------
# 10. Aislamiento de Payload, Prompt Caching y Sanitización en SQLite
# -------------------------------------------------------------------------

def test_prompt_caching_prefix_remains_static():
    # AGENT_PROMPT en prompt.py debe ser 100% inmutable para garantizar 85%+ hit rate
    assert PROMPT_FROM_MODULE == AGENT_PROMPT
    assert "ImageAttributePayload" not in AGENT_PROMPT
    assert "base64" not in AGENT_PROMPT
    assert "foto" not in AGENT_PROMPT.lower()

    # Las 10 herramientas del harness se mantienen intactas en idéntico orden
    assert len(TOOL_NAMES) == 10
    assert TOOL_NAMES == (
        "buscar_productos", "consultar_disponibilidad", "calcular_cotizacion_informativa",
        "consultar_info_tienda", "explorar_categoria",
        "registrar_pedido", "confirmar_pedido", "agendar_recogida", "consultar_pedido", "cancelar_pedido",
    )


def test_session_store_never_persists_raw_base64(session_store, orders):
    session_id = session_store.create()
    heavy_base64 = "data:image/jpeg;base64," + "A" * 5000

    payload = ImageAttributePayload(
        tipo_producto="tornillo",
        material="acero",
        medidas_visibles=["1 pulgada"],
        presentacion_uso="madera",
        confianza_visual="alta",
    )

    # Mensaje con payload base64 pesado
    run_turn(
        store=session_store,
        session_id=session_id,
        message=f"{heavy_base64} necesito 10 de estos",
        orders=orders,
        image=payload,
    )

    ctx = session_store.context(session_id)
    stored_customer = ctx["turnos"][0]["cliente"]

    # Jamás debe persistirse el base64 pesado en SQLite
    assert "data:image/jpeg;base64" not in stored_customer
    assert "AAAAA" not in stored_customer
    assert "[Foto: tornillo acero 1 pulgada madera" in stored_customer


def test_sanitize_image_text():
    raw = "Consulta normal data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg== con texto"
    sanitized = sanitize_image_text(raw)
    assert "base64" not in sanitized
    assert "[imagen]" in sanitized
    assert "Consulta normal [imagen] con texto" == sanitized


def test_visual_server_handles_image_payload_and_emits_vision_events(monkeypatch, tmp_path, session_store, orders):
    from threading import Thread
    import http.client
    import json
    from asistendero import visual

    mock_payload = ImageAttributePayload(
        tipo_producto="tubo",
        material="pvc",
        medidas_visibles=["1/2 pulgada"],
        presentacion_uso="agua",
        confianza_visual="alta",
    )
    monkeypatch.setattr(visual, "run_turn", lambda store, session_id, message, emit, orders=None, image=None: run_turn(
        store=store, session_id=session_id, message=message, emit=emit, orders=orders, image=mock_payload,
    ))

    server = visual.make_server(0, session_store, orders)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    headers = {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{server.server_port}"}

    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        body = {
            "consulta": "Necesito 3 de estos",
            "image_data": "data:image/jpeg;base64,abc123mockdata",
            "sesion": True,
        }
        connection.request("POST", "/api/trace", json.dumps(body), headers)
        response = connection.getresponse()
        assert response.status == 200
        events = [json.loads(line) for line in response.read().decode("utf-8").splitlines()]
        connection.close()

        types = [e["type"] for e in events]
        assert "input" in types
        assert "vision" in types
        assert "node" in types
        assert "final" in types
        assert "session" in types

        vision_event = next(e for e in events if e["type"] == "vision")
        assert vision_event["details"]["tipo_producto"] == "tubo"
        assert vision_event["details"]["confianza"] == "alta"

        final_event = next(e for e in events if e["type"] == "final")
        assert final_event["vision_confidence"] == "alta"
        assert final_event["estado"] == "answered"
        assert "Tubo PVC" in final_event["respuesta"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_visual_server_allows_sending_image_without_accompanying_text(monkeypatch, tmp_path, session_store, orders):
    from threading import Thread
    import http.client
    import json
    from asistendero import visual

    mock_payload = ImageAttributePayload(
        tipo_producto="codo",
        material="pvc",
        medidas_visibles=[],
        presentacion_uso="agua",
        confianza_visual="alta",
    )
    monkeypatch.setattr(visual, "run_turn", lambda store, session_id, message, emit, orders=None, image=None: run_turn(
        store=store, session_id=session_id, message=message, emit=emit, orders=orders, image=mock_payload,
    ))

    server = visual.make_server(0, session_store, orders)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    headers = {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{server.server_port}"}

    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        # Consulta vacía con solo imagen adjunta
        body = {
            "consulta": "",
            "image_data": "data:image/jpeg;base64,soloimagen",
            "sesion": True,
        }
        connection.request("POST", "/api/trace", json.dumps(body), headers)
        response = connection.getresponse()
        assert response.status == 200
        events = [json.loads(line) for line in response.read().decode("utf-8").splitlines()]
        connection.close()

        final_event = next(e for e in events if e["type"] == "final")
        assert final_event["estado"] == "answered"
        assert "codo" in final_event["respuesta"].lower()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_screw_query_triggers_screw_safeguard_template_when_unclassified_or_low_confidence(session_store, orders):
    session_id = session_store.create()
    unclassified_payload = ImageAttributePayload(
        tipo_producto=None,
        material=None,
        medidas_visibles=[],
        confianza_visual="baja",
    )

    result = run_turn(
        store=session_store,
        session_id=session_id,
        message="necesito un tornillo asi",
        orders=orders,
        image=unclassified_payload,
    )
    assert result["respuesta"] == SCREW_SAFEGUARD_TEMPLATE
    assert len(result["respuesta"].strip()) > 0
    assert "madera, lámina, drywall" in result["respuesta"]


def test_vision_trace_emits_all_langgraph_nodes_and_final_details(session_store, orders):
    session_id = session_store.create()
    payload = ImageAttributePayload(
        tipo_producto="tubo",
        material="pvc",
        medidas_visibles=["1/2 pulgada"],
        presentacion_uso="agua",
        confianza_visual="alta",
    )

    events = []
    result = run_turn(
        store=session_store,
        session_id=session_id,
        message="Necesito 2 tubos",
        orders=orders,
        image=payload,
        emit=events.append,
    )

    # Validar que los 4 nodos de LangGraph se emiten completos
    completed_nodes = [e["node"] for e in events if e.get("type") == "node" and e.get("status") == "complete"]
    assert "validate" in completed_nodes
    assert "interpret" in completed_nodes
    assert "retrieve" in completed_nodes
    assert "respond" in completed_nodes

    # Validar que el nodo interpret incluye el payload de visión estructurado
    interpret_event = next(e for e in events if e.get("node") == "interpret" and e.get("status") == "complete")
    assert "vision_payload" in interpret_event["details"]
    assert interpret_event["details"]["vision_payload"]["tipo_producto"] == "tubo"

    # Validar evento final con campo details poblado y respuesta no vacía
    final_event = next(e for e in events if e.get("type") == "final")
    assert "details" in final_event
    assert final_event["details"]["respuesta"] == result["respuesta"]
    assert len(final_event["details"]["respuesta"].strip()) > 0
    assert final_event["details"]["estado"] == "answered"

    # Verificar que no hay evento route que fuerce a omitir retrieve cuando hay herramientas
    assert not any(e.get("type") == "route" for e in events)


def test_visual_server_emits_visible_error_on_exception(monkeypatch, session_store, orders):
    from threading import Thread
    import http.client
    import json
    from asistendero import visual

    def crashing_turn(*args, **kwargs):
        raise RuntimeError("Fallo simulado en modelo multimodal")

    monkeypatch.setattr(visual, "run_turn", crashing_turn)

    server = visual.make_server(0, session_store, orders)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    headers = {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{server.server_port}"}

    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        body = {
            "consulta": "necesito un tornillo asi",
            "image_data": "data:image/jpeg;base64,fototornillo",
            "sesion": True,
        }
        connection.request("POST", "/api/trace", json.dumps(body), headers)
        response = connection.getresponse()
        assert response.status == 200
        events = [json.loads(line) for line in response.read().decode("utf-8").splitlines()]
        connection.close()

        error_event = next(e for e in events if e["type"] == "error")
        assert "Fallo simulado en modelo multimodal" in error_event["message"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_vision_propagates_usage_tokens_cost_and_model_calls(session_store, orders):
    session_id = session_store.create()
    usage_info = {
        "model": "grok-4.20-0309-non-reasoning",
        "input_tokens": 1100,
        "output_tokens": 50,
        "cached_input_tokens": 0,
        "duration_ms": 1200,
        "cost": {"usd": "0.0015000000", "basis": "xai_public_estimate", "calls": 1},
    }
    payload_with_usage = ImageAttributePayload(
        tipo_producto="tubo",
        material="pvc",
        medidas_visibles=["1/2 pulgada"],
        presentacion_uso="agua",
        confianza_visual="alta",
        usage=usage_info,
    )

    events = []
    res = run_turn(
        store=session_store,
        session_id=session_id,
        message="necesito 2 tubos",
        orders=orders,
        image=payload_with_usage,
        emit=events.append,
    )

    assert res["model_called"] is True
    assert res["model_calls"] == 1
    assert res["input_tokens"] == 1100
    assert res["output_tokens"] == 50
    assert res["total_tokens"] == 1150
    assert res["cost"]["usd"] == "0.0015000000"

    model_resp_event = next(
        e for e in events if e.get("type") == "model_response" and e.get("details", {}).get("phase") == "vision"
    )
    assert model_resp_event["details"]["input_tokens"] == 1100
    assert model_resp_event["details"]["cost"]["usd"] == "0.0015000000"

    final_event = next(e for e in events if e.get("type") == "final")
    assert final_event["details"]["model_calls"] == 1
    assert final_event["details"]["input_tokens"] == 1100
    assert final_event["details"]["cost"]["usd"] == "0.0015000000"



