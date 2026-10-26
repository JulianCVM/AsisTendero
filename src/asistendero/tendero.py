"""Plataforma local del tendero: pedidos, ventas y pagos, inventario y abastecimiento, catálogo, asistente de bodega
y supervisión de las conversaciones del chat.

Ejecutar: python -m asistendero.tendero            (la tienda que usa el chat)
          python -m asistendero.tendero --demo     (una copia con pedidos, ventas y chats simulados; ver demo.py)

Mismas barreras que el visor: escucha solo en 127.0.0.1, rechaza otro ``Host`` u ``Origin``, recibe JSON de
máximo 16 KB y no muestra errores internos. Solo el asistente de bodega llama a Grok, y únicamente cuando el tendero
pide interpretar un mensaje. En el prototipo no hay inicio de sesión: quien abre la página en el equipo es el
tendero, y por eso nunca se expone a la red. Las rutas viven en ``tendero_views.py`` (lectura) y
``tendero_actions.py`` (cambios).
"""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
import re
import sqlite3
from urllib.parse import parse_qs, urlsplit

from asistendero.catalog_admin import CatalogAdmin, CatalogError
from asistendero.demo import build_demo
from asistendero.grok import ModelError
from asistendero.injection import INJECTION_CODES
from asistendero.inventory import Inventory, InventoryError
from asistendero.orders import OrderBook, OrderError
from asistendero.payments import PaymentError, Payments
from asistendero.product_art import product_svg
from asistendero.purchasing import Purchasing
from asistendero.purchasing_rules import PurchasingError
from asistendero.sessions import SessionError, SessionStore
from asistendero.stock_assistant import StockAssistantError
from asistendero.stock_proposal import StockAssistant
from asistendero.tendero_actions import PanelActions
from asistendero.tendero_views import PanelViews


MAX_BODY = 16_384
JS = "text/javascript; charset=utf-8"
CSS = "text/css; charset=utf-8"
MODULES = ("tendero", "tendero-core", "tendero-theme", "tendero-today", "tendero-orders", "tendero-payments",
           "tendero-sales", "tendero-inventory", "tendero-product-editor", "tendero-supply", "tendero-categories",
           "tendero-catalog", "tendero-assistant", "tendero-chats")
ASSETS = {
    **{f"/assets/{name}.js": (f"{name}.js", JS) for name in MODULES},
    "/assets/tendero.css": ("tendero.css", CSS),
    "/assets/tendero-views.css": ("tendero-views.css", CSS),
    "/assets/inicio.css": ("inicio.css", CSS),
    "/assets/cercania-mark.png": ("cercania-mark.png", "image/png"),
    "/assets/NunitoSans.ttf": ("NunitoSans.ttf", "font/ttf"),
    "/assets/Inter.ttf": ("Inter.ttf", "font/ttf"),
}
IMAGE_SENT = object()  # _image ya respondió con el SVG; _dispatch no envía JSON.
PAGES = {"/": "tendero.html", "/inicio": "inicio.html"}
PRODUCT_IMAGE = re.compile(r"^/img/producto/([A-Z0-9-]{2,40})\.svg$")
KNOWN_ERRORS = (InventoryError, OrderError, PaymentError, PurchasingError, CatalogError, SessionError,
                StockAssistantError)
CONFLICTS = {"ORDER_CLOSED", "ORDER_EXPIRED", "DUPLICATE_SKU", "STOCK_BELOW_RESERVED", "INSUFFICIENT_STOCK",
             "PAYMENT_ORDER_CLOSED", "PAYMENT_ALREADY_CONFIRMED", "PURCHASE_CLOSED", "DUPLICATE_CATEGORY",
             "CATEGORY_NOT_EMPTY", "DUPLICATE_SUPPLIER", "ATTENTION_INVALID_CHANGE", "ATTENTION_NOT_TAKEN",
             "ATTENTION_BANNED", "PROPOSAL_STALE", "PROPOSAL_CLOSED", "PROPOSAL_EXPIRED"}
READS = {
    "/api/inventario": lambda views, params: views.inventory_page(params),
    "/api/movimientos": lambda views, params: {"movimientos": views.inventory.history(
        100, (params.get("sku") or "")[:40] or None)},
    "/api/pedidos": lambda views, params: views.board(params),
    "/api/resumen": lambda views, params: views.summary(),
    "/api/alertas": lambda views, params: views.badges(),
    "/api/ventas": lambda views, params: views.sales(params),
    "/api/abastecimiento": lambda views, params: views.supply(),
    "/api/categorias": lambda views, params: views.categories(),
    "/api/catalogo": lambda views, params: views.catalog(),
    "/api/conversaciones": lambda views, params: views.chats(params),
    "/api/conversacion": lambda views, params: views.chat(params),
    "/api/bloqueos": lambda views, params: {"bloqueos": views.sessions.bans(), "codigos": INJECTION_CODES},
    "/api/asistente/historial": lambda views, params: {"historial": views.assistant.history()},
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
        if url.path in PAGES:
            page = files("asistendero").joinpath("ui", PAGES[url.path]).read_bytes()
            self._send(200, page, "text/html; charset=utf-8")
            return
        if not self._local():
            self._error(403, "Origen local no permitido.")
            return
        image = PRODUCT_IMAGE.match(url.path)
        if image:
            self._dispatch(lambda: self._image(image.group(1)))
            return
        params = {key: values[0] for key, values in parse_qs(url.query).items()}
        read = READS.get(url.path)
        self._dispatch(lambda: None if read is None else read(self.server.views, params))

    def _image(self, sku: str) -> dict | None:
        # La imagen es un dibujo generado (product_art.py) sin el texto del producto: no hay nada que escapar.
        found = [product for product in self.server.inventory.products(sku) if product["sku"] == sku]
        if not found:
            return None
        product = found[0]
        svg = product_svg(product["nombre"], product["variante"], product["categoria"])
        self._send(200, svg.encode("utf-8"), "image/svg+xml; charset=utf-8")
        return IMAGE_SENT

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
        return PanelActions(self.server).run(path, body)

    def _dispatch(self, action) -> None:
        try:
            result = action()
        except KNOWN_ERRORS as exc:
            self._error(409 if exc.code in CONFLICTS else 400, str(exc), exc.code)
            return
        except ModelError as exc:
            # ModelError ya trae un mensaje propio y seguro; el detalle del SDK nunca llega al panel.
            self._error(502, str(exc), exc.code)
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
        if result is not IMAGE_SENT:
            self._json(200, result)

    def log_message(self, format: str, *args: object) -> None:
        pass


def make_server(port: int, inventory: Inventory | None = None, orders: OrderBook | None = None,
                sessions: SessionStore | None = None, assistant: StockAssistant | None = None) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), TenderoHandler)
    server.inventory = inventory or Inventory()
    path = server.inventory.path
    server.orders = orders or OrderBook(path)
    server.sessions = sessions or SessionStore()
    server.payments = Payments(path, server.orders.clock)
    server.purchasing = Purchasing(path, server.orders.clock)
    server.admin = CatalogAdmin(path)
    server.assistant = assistant or StockAssistant(path, server.orders.clock)
    server.views = PanelViews(server.inventory, server.orders, server.sessions, server.payments, server.purchasing,
                              server.admin, server.assistant)
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Plataforma local del tendero: pedidos, ventas, inventario y chats")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--demo", action="store_true",
                        help="rehace y abre la tienda de demostración (.local/demo), con datos simulados")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port debe estar entre 1 y 65535")
    stores = {}
    if args.demo:
        database, sessions = build_demo()
        stores = {"inventory": Inventory(database), "sessions": SessionStore(sessions)}
    with make_server(args.port, **stores) as server:
        print(f"Plataforma del tendero: http://127.0.0.1:{server.server_port}/")
        if args.demo:
            print("Tienda de demostración: pedidos, ventas, proveedores y chats simulados.")
        print("Ctrl+C para detenerla. Solo el asistente de bodega llama a Grok, cuando pides interpretar un mensaje.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
