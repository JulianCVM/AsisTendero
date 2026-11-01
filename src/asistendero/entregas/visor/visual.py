"""Visor de pruebas local. Ejecutar: python -m asistendero.entregas.visor"""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from urllib.parse import parse_qs, urlsplit

from dotenv import load_dotenv

from asistendero.agente.conversacion.chat import run_turn
from asistendero.agente.conversacion.order_watch import Watcher
from asistendero.agente.conversacion.sessions import SESSION_ID, SessionError, SessionStore
from asistendero.agente.modelo.grok import ModelError
from asistendero.agente.vision.photo import MAX_PHOTO_CHARS
from asistendero.entregas.estaticos import web_file
from asistendero.observabilidad.harness_info import describe_harness
from asistendero.observabilidad.tracing import run_traced
from asistendero.tienda.catalogo.product_photos import PHOTO_ROUTE, photo_file
from asistendero.tienda.pedidos.orders import OrderBook


MAX_QUERY_CHARS = 2000
# El texto y una foto en base64 (el navegador la reduce a 1024 px antes de mandarla), con margen para el JSON.
MAX_BODY_BYTES = MAX_PHOTO_CHARS + 4096
BAD_REQUEST = "Envía una consulta de texto de máximo 2000 caracteres o una foto de menos de 1,5 MB."


class TraceHandler(BaseHTTPRequestHandler):
    # HTTP/1.1 reutiliza la conexión entre los archivos del visor; por eso un cuerpo rechazado se lee o se cierra.
    protocol_version = "HTTP/1.1"

    _assets = {
        "/assets/cercania-mark.png": ("cercania-mark.png", "image/png"),
        "/assets/NunitoSans.ttf": ("NunitoSans.ttf", "font/ttf"),
        "/assets/Inter.ttf": ("Inter.ttf", "font/ttf"),
        "/assets/conversacion.css": ("conversacion.css", "text/css; charset=utf-8"),
        # El tema es el mismo del panel y de la página pública: mismo selector y misma cookie (ver tendero-theme.js).
        "/assets/tendero-theme.js": ("tendero-theme.js", "text/javascript; charset=utf-8"),
        "/assets/tendero-theme.css": ("tendero-theme.css", "text/css; charset=utf-8"),
        "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
        "/assets/harness.js": ("harness.js", "text/javascript; charset=utf-8"),
        "/assets/harness-map.js": ("harness-map.js", "text/javascript; charset=utf-8"),
        "/assets/harness-extras.js": ("harness-extras.js", "text/javascript; charset=utf-8"),
        "/assets/resultado.js": ("resultado.js", "text/javascript; charset=utf-8"),
        "/assets/traza.js": ("traza.js", "text/javascript; charset=utf-8"),
        "/assets/traza-lectura.js": ("traza-lectura.js", "text/javascript; charset=utf-8"),
        "/assets/visor-comun.js": ("visor-comun.js", "text/javascript; charset=utf-8"),
        "/assets/visor-panels.css": ("visor-panels.css", "text/css; charset=utf-8"),
        "/assets/harness-map.css": ("harness-map.css", "text/css; charset=utf-8"),
        "/assets/foto-flujo.js": ("foto-flujo.js", "text/javascript; charset=utf-8"),
        "/assets/foto-flujo.css": ("foto-flujo.css", "text/css; charset=utf-8"),
        "/assets/iso.css": ("iso.css", "text/css; charset=utf-8"),
        "/assets/castillo.css": ("castillo.css", "text/css; charset=utf-8"),
        "/assets/castillo.js": ("castillo.js", "text/javascript; charset=utf-8"),
    }

    def _is_local_host(self) -> bool:
        return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

    def _headers(self, status: int, content_type: str, length: int | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.end_headers()

    def _json_error(self, status: int, message: str) -> None:
        body = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def _reject_post(self, status: int, message: str) -> None:
        """Responde un error sin dejar el cuerpo en el socket: se leería como la siguiente solicitud."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if 0 <= length <= MAX_BODY_BYTES:
            self.rfile.read(length)
            self.close_connection = False
        else:
            self.close_connection = True
        body = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Length", str(len(body)))
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        asset = self._assets.get(self.path)
        if asset is not None:
            filename, content_type = asset
            body = web_file(filename)
            self._headers(200, content_type, len(body))
            self.wfile.write(body)
            self.close_connection = False
            return
        if self.path == "/api/harness":
            if not self._is_local_host():
                self._json_error(403, "Origen local no permitido.")
                self.close_connection = False
                return
            body = json.dumps(describe_harness(), ensure_ascii=False).encode("utf-8")
            self._headers(200, "application/json; charset=utf-8", len(body))
            self.wfile.write(body)
            self.close_connection = False
            return
        url = urlsplit(self.path)
        if url.path.startswith(PHOTO_ROUTE):
            # Solo los archivos del manifiesto: el nombre se busca en una lista, nunca se arma una ruta con él.
            photo = photo_file(url.path.removeprefix(PHOTO_ROUTE))
            if photo is None:
                self._json_error(404, "Foto no encontrada.")
            else:
                body = photo.read_bytes()
                self._headers(200, "image/jpeg", len(body))
                self.wfile.write(body)
            self.close_connection = False
            return
        if url.path == "/api/avisos":
            # Avisos del servidor para una conversación (pedido por vencer o vencido); se entregan una vez.
            if not self._is_local_host():
                self._json_error(403, "Origen local no permitido.")
                self.close_connection = False
                return
            session_id = (parse_qs(url.query).get("sesion") or [""])[0]
            if not SESSION_ID.match(session_id):
                self._json_error(400, "Sesión inválida.")
                self.close_connection = False
                return
            body = json.dumps({"avisos": self.server.sessions.take_notices(session_id)}, ensure_ascii=False).encode("utf-8")
            self._headers(200, "application/json; charset=utf-8", len(body))
            self.wfile.write(body)
            self.close_connection = False
            return
        if self.path != "/":
            self._json_error(404, "Ruta no encontrada.")
            self.close_connection = False
            return
        body = web_file("index.html")
        self._headers(200, "text/html; charset=utf-8", len(body))
        for offset in range(0, len(body), 32768):
            self.wfile.write(body[offset:offset + 32768])
        self.close_connection = False

    def do_POST(self) -> None:
        if self.path != "/api/trace":
            self._reject_post(404, "Ruta no encontrada.")
            return
        expected_origin = f"http://127.0.0.1:{self.server.server_port}"
        if not self._is_local_host() or self.headers.get("Origin") not in (None, expected_origin):
            self._reject_post(403, "Origen local no permitido.")
            return
        if self.headers.get_content_type() != "application/json":
            self._reject_post(415, "Se requiere application/json.")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= MAX_BODY_BYTES:
                self._reject_post(400, BAD_REQUEST)
                return
            request = json.loads(self.rfile.read(length))
            query = request.get("consulta", "")
            if not isinstance(query, str) or len(query) > MAX_QUERY_CHARS:
                raise ValueError
            image_data = request.get("image_data")
            if image_data is not None and (not isinstance(image_data, str) or len(image_data) > MAX_PHOTO_CHARS):
                raise ValueError
            if not query.strip() and not image_data:
                raise ValueError
            in_session = request.get("sesion") is True
            session_id = request.get("session_id")
            if session_id is not None and not isinstance(session_id, str):
                raise ValueError
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            # Si el largo no era un número, el cuerpo quedó sin leer: la conexión se cierra.
            self.close_connection = True
            self._json_error(400, BAD_REQUEST)
            return

        self._headers(200, "application/x-ndjson; charset=utf-8")

        def emit(event: dict) -> None:
            line = json.dumps(event, ensure_ascii=False, default=str).encode("utf-8") + b"\n"
            self.wfile.write(line)
            self.wfile.flush()

        try:
            # Una foto siempre va en una conversación: la sesión recuerda qué se vio para el turno siguiente.
            if in_session or image_data:
                store = self.server.sessions
                photo = {"image": image_data} if image_data else {}
                run_turn(store, session_id or store.create(), query, emit, orders=self.server.orders, **photo)
            else:
                run_traced(query, emit)
        except (SessionError, ModelError) as exc:
            # Los dos traen un código estable y un mensaje propio, nunca el texto del SDK.
            emit({"type": "error", "code": exc.code, "message": str(exc)})
        except (ValueError, RuntimeError, FileNotFoundError) as exc:
            emit({"type": "error", "message": str(exc)})
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            # El SDK podría incluir datos de la solicitud en su excepción.
            emit({"type": "error", "message": f"Fallo en Grok o en el flujo ({type(exc).__name__}). Revisa red, clave, modelo y créditos."})
        finally:
            self.close_connection = True

    def log_message(self, format: str, *args: object) -> None:
        # No registrar texto de consultas ni detalles de las llamadas en consola.
        pass


def make_server(port: int, sessions: SessionStore | None = None, orders: OrderBook | None = None) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), TraceHandler)
    # La sesión vive en el servidor; el visor solo guarda el identificador que este le entrega.
    server.sessions = sessions or SessionStore()
    server.orders = orders
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Visor local del flujo LangGraph de AsisTendero")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port debe estar entre 1 y 65535")
    load_dotenv()
    with make_server(args.port, orders=OrderBook()) as server:
        # Vence los pedidos sin confirmar a los 5 minutos y deja el aviso para cada cliente, sin llamar a Grok.
        watcher = Watcher(server.orders, server.sessions).start()
        print(f"Visor local: http://127.0.0.1:{server.server_port}/")
        print("Ctrl+C para detenerlo. Cada mensaje llama a Grok y puede consumir cupo.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            watcher.stop()


if __name__ == "__main__":
    main()
