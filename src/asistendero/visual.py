"""Visor de pruebas local. Ejecutar: python -m asistendero.visual"""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json

from dotenv import load_dotenv

from asistendero.tracing import run_traced


class TraceHandler(BaseHTTPRequestHandler):
    _assets = {
        "/assets/cercania-mark.png": ("cercania-mark.png", "image/png"),
        "/assets/NunitoSans.ttf": ("NunitoSans.ttf", "font/ttf"),
        "/assets/Inter.ttf": ("Inter.ttf", "font/ttf"),
        "/assets/conversacion.css": ("conversacion.css", "text/css; charset=utf-8"),
        "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
    }

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

    def do_GET(self) -> None:
        asset = self._assets.get(self.path)
        if asset is not None:
            filename, content_type = asset
            body = files("asistendero").joinpath("ui", filename).read_bytes()
            self._headers(200, content_type, len(body))
            self.wfile.write(body)
            return
        if self.path != "/":
            self._json_error(404, "Ruta no encontrada.")
            return
        body = files("asistendero").joinpath("ui/index.html").read_bytes()
        self._headers(200, "text/html; charset=utf-8", len(body))
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path != "/api/trace":
            self._json_error(404, "Ruta no encontrada.")
            return
        expected_origin = f"http://127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}" or self.headers.get("Origin") not in (None, expected_origin):
            self._json_error(403, "Origen local no permitido.")
            return
        if self.headers.get_content_type() != "application/json":
            self._json_error(415, "Se requiere application/json.")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= 4096:
                raise ValueError
            request = json.loads(self.rfile.read(length))
            query = request["consulta"]
            if not isinstance(query, str) or len(query) > 2000:
                raise ValueError
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            self._json_error(400, "Envía una consulta de texto de máximo 2000 caracteres.")
            return

        self._headers(200, "application/x-ndjson; charset=utf-8")

        def emit(event: dict) -> None:
            line = json.dumps(event, ensure_ascii=False, default=str).encode("utf-8") + b"\n"
            self.wfile.write(line)
            self.wfile.flush()

        try:
            run_traced(query, emit)
        except (ValueError, RuntimeError, FileNotFoundError) as exc:
            emit({"type": "error", "message": str(exc)})
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            # El SDK podría incluir datos de la solicitud en su excepción.
            emit({"type": "error", "message": f"Fallo en Grok o en el flujo ({type(exc).__name__}). Revisa red, clave, modelo y créditos."})

    def log_message(self, format: str, *args: object) -> None:
        # No registrar texto de consultas ni detalles de las llamadas en consola.
        pass


def make_server(port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), TraceHandler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Visor local del flujo LangGraph de AsisTendero")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port debe estar entre 1 y 65535")
    load_dotenv()
    with make_server(args.port) as server:
        print(f"Visor local: http://127.0.0.1:{server.server_port}/")
        print("Ctrl+C para detenerlo. Cada mensaje llama a Grok y puede consumir cupo.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
