"""El mapa del harness del visor describe el flujo real: mismas constantes, códigos y estados."""

import http.client
import json
from pathlib import Path
import re
from threading import Thread

import pytest

from asistendero.agente.conversacion.sessions import SessionStore
from asistendero.agente.flujo.graph import MAX_MESSAGE_CHARS, MAX_TOOL_CALLS
from asistendero.agente.modelo.grok import AGENT_PROMPT, PROMPT_VERSION, TOOL_NAMES
from asistendero.entregas.estaticos import web_file
from asistendero.entregas.visor import visual
from asistendero.observabilidad.harness_info import describe_harness


SRC = Path(__file__).resolve().parents[1] / "src" / "asistendero"


def module_file(name: str) -> Path:
    """Un módulo del paquete, en el subpaquete donde viva."""
    (path,) = SRC.rglob(name)
    return path


def test_description_comes_from_the_code_constants():
    info = describe_harness()
    assert info["prompt_version"] == PROMPT_VERSION
    assert info["instructions"] == AGENT_PROMPT
    assert [tool["name"] for tool in info["tools"]] == list(TOOL_NAMES)
    assert info["limits"]["max_tool_calls"] == MAX_TOOL_CALLS
    assert info["limits"]["max_message_chars"] == MAX_MESSAGE_CHARS
    assert [item["code"] for item in info["reminders"]] == ["SEARCH_REQUIRED", "QUOTE_REQUIRED", "INFO_REQUIRED",
                                                            "LIST_QUOTE_REQUIRED", "RESTOCK_REQUIRED", "CATALOG_REQUIRED",
                                                            "ORDER_REQUIRED"]
    assert set(info["guardrails"]) == {"PROMPT_DISCLOSURE", "CREDENTIALS", "INTERNAL_DATA", "THIRD_PARTY_DATA",
                                       "BUSINESS_PRIVATE"}


def test_every_rejection_code_in_the_flow_is_on_the_map():
    source = "".join(module_file(name).read_text(encoding="utf-8") for name in ("validation.py", "graph.py", "order_rules.py"))
    codes = set(re.findall(r'Rejected\("([A-Z_]+)"', source))
    assert codes, "no se encontraron rechazos en el código"
    assert codes <= set(describe_harness()["rejections"])


def test_every_final_state_in_the_flow_is_classified():
    source = "".join(module_file(name).read_text(encoding="utf-8") for name in ("answers.py", "graph.py", "order_replies.py", "chat.py"))
    patterns = [
        r'_(?:pedido|recogida)": "([a-z_]+)"',  # STATUS_BY_TOOL de order_replies
        r'if results else "([a-z_]+)"',  # estado de order_reply sin pedidos válidos
        r'return "([a-z_]+)", ',  # (estado, respuesta) de render_answer
        r'statuses\.append\("([a-z_]+)"\)',
        r'status = "([a-z_]+)"',
        r'\{\*\*common, "estado": "([a-z_]+)"',  # salida del nodo respond
        r'"[A-Z_]+": "([a-z_]+)"',  # código de error → estado en respond
        r'\.get\(error\["code"\], "([a-z_]+)"\)',
        r'_without_grok\(store, session_id, text, "([a-z_]+)"',  # turnos que atiende el tendero (chat.py)
    ]
    states = {state for pattern in patterns for state in re.findall(pattern, source)}
    classified = {state for group in describe_harness()["outcomes"].values() for state in group["states"]}
    assert {"quoted", "insufficient_stock", "model_error", "limit_reached", "order_confirmed", "order_issue",
            "handoff", "staff"} <= states
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
    page = web_file("index.html").decode("utf-8")
    match = re.search(rf'data-{name}="([^"]+)"', page)
    assert match, f"el castillo no trae data-{name}"
    return json.loads(match.group(1).replace("&quot;", '"').replace("&amp;", "&"))


def test_the_castle_animates_every_node_of_the_graph():
    source = module_file("graph.py").read_text(encoding="utf-8")
    nodes = set(re.findall(r'add_node\("([a-z_]+)"', source))
    script = web_file("castillo.js").decode("utf-8")
    assert nodes == {"validate", "interpret", "retrieve", "respond"}
    for node in nodes:
        assert f"event.node === '{node}'" in script, f"el castillo no muestra el nodo {node}"


def test_the_castle_route_only_joins_stations_that_exist():
    route = _castle_data("route")
    points = set(route["points"])
    assert {"cliente", "puerta", "torre", "cruce", "aduana", "bodega", "balanza", "mostrador", "salida"} <= points
    assert route["edges"] and all(a in points and b in points for a, b in route["edges"])
    script = web_file("castillo.js").decode("utf-8")
    walked = set(re.findall(r"go\('([a-z]+)'", script)) | set(re.findall(r"live\('([a-z]+)'", script))
    assert walked and walked <= points, walked - points
    page = web_file("index.html").decode("utf-8")
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
    page = web_file("index.html").decode("utf-8")
    script = web_file("app.js").decode("utf-8")
    used = set(re.findall(r"querySelector\('#([\w-]+)'\)", script))
    assert {"chat-scroll", "chat-thread", "jump-latest", "query", "run", "form"} <= used
    missing = [name for name in sorted(used) if f'id="{name}"' not in page]
    assert missing == [], f"app.js busca ids que index.html no tiene: {missing}"
    assert "innerHTML" not in script and not re.search(r"\b(?:alert|confirm|prompt)\(", script)


def test_the_decision_map_is_the_real_graph():
    # El mapa separa la ruta (arista condicional de interpret) y la aduana y la bodega (dentro de retrieve); sin las
    # conexiones internas, cada conexión del mapa debe ser una arista del grafo compilado, y ninguna puede faltar.
    from asistendero.agente.flujo.graph import build_graph

    flow = describe_harness()["flow"]
    graph = build_graph(lambda name, arguments: {}, lambda *args, **kwargs: None).get_graph()
    real = {(edge.source, edge.target) for edge in graph.edges}
    owner = {node["id"]: node["graph"] for node in flow["nodes"]}
    assert set(owner.values()) == set(graph.nodes)
    mapped = {(owner[edge["from"]], owner[edge["to"]]) for edge in flow["edges"] if not edge.get("internal")}
    assert mapped == real
    ids = [node["id"] for node in flow["nodes"]]
    assert len(ids) == len(set(ids))
    for node in flow["nodes"]:
        exits = [edge for edge in flow["edges"] if edge["from"] == node["id"]]
        # Cada nodo dice a dónde sigue; solo el estado final cierra la corrida.
        assert bool(exits) == (node["graph"] != "__end__"), node["id"]
        assert node["does"] and node["receives"] and node["decides"] and set(node["layers"]) <= {"prompt", "model", "rule", "data"}
    assert all(edge["from"] in owner and edge["to"] in owner and edge["label"] and edge["when"] for edge in flow["edges"])


def _visor_files() -> dict[str, str]:
    served = {name for name, _ in visual.TraceHandler._assets.values()}
    return {name: web_file(name).decode("utf-8") for name in sorted(served)
            if name.endswith((".js", ".css"))}


def test_the_visor_page_loads_only_served_files_and_its_scripts_find_their_elements():
    page = web_file("index.html").decode("utf-8")
    files = _visor_files()
    served = set(visual.TraceHandler._assets)
    assert set(re.findall(r'(?:href|src)="(/assets/[\w.-]+)"', page)) <= served
    ids = set(re.findall(r'\bid="([\w-]+)"', page))
    scripts = {name: text for name, text in files.items() if name.endswith(".js")}
    for name, script in scripts.items():
        used = set(re.findall(r"querySelector\('#([\w-]+)'\)", script)) | set(re.findall(r"getElementById\('([\w-]+)'\)", script))
        # Los ids que el mapa crea al vuelo (el título del detalle) no están en la página.
        assert used - {"flow-detail-title"} <= ids, (name, used - ids)
        for module in re.findall(r"from '\./([\w.-]+\.js)'", script):
            assert module in scripts, (name, module)
        assert "innerHTML" not in script and "insertAdjacentHTML" not in script, name
        assert not re.search(r"\b(?:alert|confirm|prompt)\(", script), name


def test_the_inspection_keeps_the_original_json_and_the_download():
    script = web_file("traza.js").decode("utf-8")
    assert "JSON.stringify(event, null, 2)" in script and "JSON original del evento" in script
    assert "JSON.stringify(events, null, 2)" in script and "'#download'" in script


def test_the_visor_colors_are_tokens_with_the_same_dark_palette_twice():
    sheet = web_file("conversacion.css").decode("utf-8")
    media = re.search(r':root:not\(\[data-theme="light"\]\) \{(.*?)\n  \}', sheet, re.S).group(1)
    chosen = re.search(r':root\[data-theme="dark"\] \{(.*?)\n\}', sheet, re.S).group(1)
    tokens = lambda block: dict(re.findall(r"(--[\w-]+):\s*([^;]+);", block))
    assert tokens(media) == tokens(chosen) and tokens(media)
    light = tokens(re.search(r"^:root \{(.*?)\n\}", sheet, re.S | re.M).group(1))
    assert set(tokens(media)) <= set(light)
    # Fuera de las paletas no hay colores fijos: con uno suelto, el modo oscuro deja una caja clara.
    for name in ("conversacion.css", "visor-panels.css", "harness-map.css"):
        text = web_file(name).decode("utf-8")
        outside = re.sub(r":root[^{]*\{.*?\n\s*\}", "", text, flags=re.S)
        assert len(outside) > len(text) / 2, name  # quitar las paletas no puede borrar la hoja entera
        assert not re.findall(r"#[0-9A-Fa-f]{3,8}\b", outside), name
    castle = web_file("castillo.css").decode("utf-8")
    assert '.castle-stage.iso[data-theme="dark"]' in castle
    assert 'id="castle-stage"' in web_file("index.html").decode("utf-8").split("data-follow-theme")[0][-200:]


# ---------------------------------------------------------------- recorrido de una foto


def test_the_photo_diagram_names_real_functions_and_real_limits():
    from importlib import import_module

    from asistendero.agente.vision import photo
    from asistendero.observabilidad.photo_flow import BROWSER_SIDE, REJECTIONS
    from asistendero.tienda.catalogo import product_photos

    flow = describe_harness()["photo_flow"]
    lanes = {lane["id"] for lane in flow["lanes"]}
    stores = {store["id"] for store in flow["stores"]}
    stages = {stage["id"]: stage for stage in flow["stages"]}
    for stage in flow["stages"]:
        assert stage["lane"] in lanes and stage["title"] and stage["does"]
        assert {access["store"] for access in stage["data"]} <= stores
        assert all(access["mode"] in {"lee", "escribe"} for access in stage["data"])
        if ":" in stage["code"]:
            module, name = stage["code"].split(":")
            assert hasattr(import_module(module), name), stage["code"]
    # Los códigos de rechazo son los que lanza read_photo, ni uno más ni uno menos.
    raised = set(re.findall(r'PhotoRejected\("(PHOTO_\w+)"', module_file("photo.py").read_text(encoding="utf-8")))
    assert set(REJECTIONS) == raised == set(stages["limpieza"]["exit"]["codes"])
    # El navegador reduce a lo que dice el diagrama, y el servidor a lo que dice read_photo.
    assert f"const maxDim = {BROWSER_SIDE};" in web_file("app.js").decode("utf-8")
    assert f"{photo.VISION_SIDE} px" in stages["limpieza"]["does"]
    assert flow["limits"]["photos"] == len(product_photos.manifest())
    # Las conexiones unen etapas que existen, y la huella tiene las dos salidas: atajo sin Grok y visión.
    assert all(edge["from"] in stages and edge["to"] in stages and edge["label"] for edge in flow["edges"])
    assert {edge["to"] for edge in flow["edges"] if edge["from"] == "huella"} == {"vision", "respaldo"}
    # Grok solo aparece en una etapa: mirar la foto. Nada de lo que escribe en la sesión es la foto.
    assert [stage["id"] for stage in flow["stages"] if stage["lane"] == "grok"] == ["vision"]
    assert any(access == {"store": "sesion", "mode": "escribe"} for access in stages["memoria"]["data"])


def test_the_photo_diagram_is_on_the_visor_page_and_reads_the_trace():
    page = web_file("index.html").decode("utf-8")
    assert '<script type="module" src="/assets/foto-flujo.js"></script>' in page
    assert 'href="/assets/foto-flujo.css"' in page
    script = web_file("foto-flujo.js").decode("utf-8")
    # Las piezas de la traza que lo mueven: la visión, la ruta que detiene la foto, la bodega y la sesión.
    for piece in ("'vision'", "details.foto", "'retrieve'", "'session'", "details.limpieza", "details.cotejo",
                  "details.descartados"):
        assert piece in script, piece
