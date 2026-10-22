"""Plataforma local del tendero: inventario y pedidos del chat. Ejecutar: python -m asistendero.tendero

Mismas barreras que el visor: escucha solo en 127.0.0.1, rechaza otro ``Host`` u ``Origin``, recibe JSON de
máximo 4 KB y no muestra errores internos. No llama a Grok ni gasta créditos. En el prototipo no hay inicio de
sesión: quien abre la página en el equipo es el tendero, y por eso nunca se expone a la red.
"""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
import sqlite3
from urllib.parse import parse_qs, urlsplit

from asistendero.inventory import Inventory, InventoryError
from asistendero.orders import OrderBook, OrderError
from asistendero.sales import STATUSES, day_summary, order_board


MAX_BODY = 4096
ASSETS = {
    "/assets/tendero.js": ("tendero.js", "text/javascript; charset=utf-8"),
    "/assets/tendero.css": ("tendero.css", "text/css; charset=utf-8"),
    "/assets/cercania-mark.png": ("cercania-mark.png", "image/png"),
    "/assets/NunitoSans.ttf": ("NunitoSans.ttf", "font/ttf"),
    "/assets/Inter.ttf": ("Inter.ttf", "font/ttf"),
}


class TenderoHandler(BaseHTTPRequestHandler):
    def _local(self) -> bool:
        return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data: dict) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, status: int, message: str, code: str | None = None) -> None:
        self._json(status, {"error": message, **({"code": code} if code else {})})

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        if url.path in ASSETS:
            name, content_type = ASSETS[url.path]
            self._send(200, files("asistendero").joinpath("ui", name).read_bytes(), content_type)
            return
        if url.path == "/":
            self._send(200, files("asistendero").joinpath("ui", "tendero.html").read_bytes(), "text/html; charset=utf-8")
            return
        if not self._local():
            self._error(403, "Origen local no permitido.")
            return
        params = {key: values[0] for key, values in parse_qs(url.query).items()}
        self._dispatch(lambda: self._read(url.path, params))

    def _read(self, path: str, params: dict) -> dict | None:
        inventory, orders = self.server.inventory, self.server.orders
        if path == "/api/inventario":
            return {"productos": inventory.products(params.get("q", "")[:60], params.get("categoria", "")[:60],
                                                    params.get("bajo") == "1"),
                    "categorias": inventory.categories()}
        if path == "/api/pedidos":
            return {"pedidos": order_board(orders, params.get("estado") or None), "estados": list(STATUSES)}
        if path == "/api/resumen":
            return day_summary(orders)
        if path == "/api/movimientos":
            return {"movimientos": inventory.history()}
        return None

    def do_POST(self) -> None:
        origin = f"http://127.0.0.1:{self.server.server_port}"
        if not self._local() or self.headers.get("Origin") not in (None, origin):
            self._error(403, "Origen local no permitido.")
            return
        if self.headers.get_content_type() != "application/json":
            self._error(415, "Se requiere application/json.")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= MAX_BODY:
                raise ValueError
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError
        except (ValueError, json.JSONDecodeError):
            self._error(400, f"Envía un objeto JSON de máximo {MAX_BODY} bytes.")
            return
        self._dispatch(lambda: self._write(urlsplit(self.path).path, body))

    def _write(self, path: str, body: dict) -> dict | None:
        inventory, orders = self.server.inventory, self.server.orders
        if path == "/api/inventario/actualizar":
            sku = body.pop("sku", None)
            if not isinstance(sku, str):
                raise InventoryError("INVALID_ARGUMENT", "Falta el SKU.")
            return {"producto": inventory.update(sku, body)}
        if path == "/api/inventario/nuevo":
            return {"producto": inventory.add(body)}
        if path in ("/api/pedidos/entregar", "/api/pedidos/cancelar"):
            order_id = body.get("pedido")
            if set(body) != {"pedido"} or not isinstance(order_id, str):
                raise OrderError("INVALID_ARGUMENT", "Envía solo el código del pedido.")
            order = orders.deliver(order_id) if path.endswith("entregar") else orders.cancel(order_id, by="tendero")
            return {"pedido": order}
        return None

    def _dispatch(self, action) -> None:
        try:
            result = action()
        except (InventoryError, OrderError) as exc:
            self._error(409 if exc.code in {"ORDER_CLOSED", "ORDER_EXPIRED", "DUPLICATE_SKU", "STOCK_BELOW_RESERVED",
                                            "INSUFFICIENT_STOCK"} else 400, str(exc), exc.code)
            return
        except ValueError as exc:
            self._error(400, str(exc))
            return
        except (sqlite3.Error, OSError):
            # Sin rutas ni detalles del motor: el tendero solo necesita saber que debe reintentar.
            self._error(503, "No se pudo leer la base de la tienda. Intenta de nuevo.")
            return
        if result is None:
            self._error(404, "Ruta no encontrada.")
            return
        self._json(200, result)

    def log_message(self, format: str, *args: object) -> None:
        pass


def make_server(port: int, inventory: Inventory | None = None, orders: OrderBook | None = None) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), TenderoHandler)
    server.inventory = inventory or Inventory()
    server.orders = orders or OrderBook(server.inventory.path)
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Plataforma local del tendero: inventario y pedidos del chat")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port debe estar entre 1 y 65535")
    with make_server(args.port) as server:
        print(f"Plataforma del tendero: http://127.0.0.1:{server.server_port}/")
        print("Ctrl+C para detenerla. No llama a Grok.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
