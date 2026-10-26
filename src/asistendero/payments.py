"""Registro de pagos de los pedidos para recoger: quién dijo qué y quién lo verificó.

Aquí no se verifica nada con un banco. Un pago solo queda ``confirmado`` cuando el tendero lo vio: recibió el
efectivo o el voucher del datáfono en el mostrador, o revisó su app o su extracto y encontró el dinero. Un pantallazo
o un número de comprobante es ``comprobante_recibido``: un soporte por revisar, nunca un pago confirmado.

Estados del pago:

- ``pendiente``: no hay pago (se puede anotar el método que el cliente dijo que usaría).
- ``comprobante_recibido``: el cliente mostró o envió un soporte de un pago digital; falta que el tendero lo verifique.
- ``confirmado``: el tendero verificó el dinero. Es final: devolver o corregir un cobro queda fuera de este prototipo.
- ``rechazado``: el soporte no coincide con lo que llegó.

Reglas (cada una con su código estable):

- El monto es siempre el ``total_cop`` del pedido leído de la base; ningún valor del cliente ni del modelo entra.
- No se registra pago de un pedido ``cancelado`` o ``vencido`` (``PAYMENT_ORDER_CLOSED``).
- Efectivo y datáfono se reciben en persona: solo ``pendiente`` o ``confirmado`` con fuente ``mostrador``; no tienen
  comprobante que revisar (``PAYMENT_STATUS_NOT_ALLOWED``, ``PAYMENT_SOURCE_MISMATCH``).
- Nequi, Daviplata, transferencia y Bre-B solo se confirman con ``revision_tendero``: un soporte mostrado en el
  mostrador no prueba que el dinero llegó (``PAYMENT_SOURCE_MISMATCH``).
- Confirmar exige fuente (``PAYMENT_SOURCE_REQUIRED``) y la fuente solo acompaña a ``confirmado``
  (``PAYMENT_SOURCE_NOT_ALLOWED``). ``pasarela`` existe pero se rechaza (``PAYMENT_SOURCE_UNAVAILABLE``): exige integrar
  un proveedor con webhook firmado, y no hay ninguno.
- Solo el tendero confirma o rechaza (``PAYMENT_FORBIDDEN``): el chat a lo sumo anota un comprobante recibido.
- La referencia es texto breve (``MAX_REFERENCE_CHARS``); más larga se rechaza y los datos personales se tapan.

Cada cambio deja un evento con hora UTC, estado, método, fuente, actor, referencia y detalle.
"""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
import sqlite3

from asistendero.guardrails import redact_personal_data
from asistendero.orders import ORDER_ID, OrderBook, local_text, utc_text
from asistendero.seed import DEFAULT_DB_PATH, DEMO_BUSINESS_ID, DEMO_STORE_ID


METHODS = {
    "efectivo": "Efectivo",
    "datafono": "Datáfono (tarjeta en el mostrador)",
    "nequi": "Nequi",
    "daviplata": "Daviplata",
    "transferencia": "Transferencia bancaria",
    "bre_b": "Bre-B",
}
IN_PERSON = ("efectivo", "datafono")
PAYMENT_STATUSES = ("pendiente", "comprobante_recibido", "confirmado", "rechazado")
SOURCES = {
    "mostrador": "Recibido en el mostrador",
    "revision_tendero": "El tendero revisó su app o extracto",
    "pasarela": "Pasarela de pagos",
}
UNAVAILABLE_SOURCES = ("pasarela",)
ACTORS = ("tendero", "agente")
MAX_REFERENCE_CHARS = 60
MAX_MANY = 10_000
DETAILS = {
    "pendiente": "sin pago registrado",
    "comprobante_recibido": "comprobante recibido; falta verificar el dinero",
    "confirmado": "pago verificado por el tendero",
    "rechazado": "el soporte no coincide con lo recibido",
}

PAYMENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS payments (
    order_id TEXT PRIMARY KEY REFERENCES orders(id),
    business_id TEXT NOT NULL,
    store_id TEXT NOT NULL,
    method TEXT,
    status TEXT NOT NULL CHECK (status IN ('pendiente', 'comprobante_recibido', 'confirmado', 'rechazado')),
    source TEXT,
    reference TEXT NOT NULL DEFAULT '',
    amount_cop INTEGER NOT NULL CHECK (amount_cop >= 0),
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payment_events (
    order_id TEXT NOT NULL REFERENCES orders(id),
    at TEXT NOT NULL,
    status TEXT NOT NULL,
    method TEXT,
    source TEXT,
    actor TEXT NOT NULL,
    reference TEXT NOT NULL,
    detail TEXT NOT NULL
);
"""


class PaymentError(Exception):
    """Regla que impide registrar el pago, con un código estable y un mensaje seguro."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _check_choice(value: object, options, code: str, what: str) -> None:
    if not isinstance(value, str) or value not in options:
        raise PaymentError(code, f"{what} desconocido: usa uno de {', '.join(options)}.")


def _clean_reference(reference: object) -> str:
    if not isinstance(reference, str):
        raise PaymentError("PAYMENT_INVALID_REFERENCE", "La referencia debe ser texto.")
    reference = " ".join(reference.split())
    if len(reference) > MAX_REFERENCE_CHARS:
        # Se rechaza en vez de recortar: una referencia cortada no sirve para cuadrar el pago.
        raise PaymentError("PAYMENT_INVALID_REFERENCE",
                           f"La referencia admite hasta {MAX_REFERENCE_CHARS} caracteres.")
    return redact_personal_data(reference)[0]


def check_payment(method: str, status: str, source: str | None, actor: str) -> None:
    """Valida método, estado, fuente y actor antes de tocar la base."""
    _check_choice(method, tuple(METHODS), "PAYMENT_INVALID_METHOD", "Método")
    _check_choice(status, PAYMENT_STATUSES, "PAYMENT_INVALID_STATUS", "Estado de pago")
    _check_choice(actor, ACTORS, "PAYMENT_INVALID_ACTOR", "Actor")
    if source is not None:
        _check_choice(source, tuple(SOURCES), "PAYMENT_INVALID_SOURCE", "Fuente")
    if source in UNAVAILABLE_SOURCES:
        raise PaymentError("PAYMENT_SOURCE_UNAVAILABLE", "No hay pasarela de pagos: confirmarla exigiría integrar "
                                                          "un proveedor con webhook firmado. Verifica el dinero tú mismo.")
    if status in ("confirmado", "rechazado") and actor != "tendero":
        raise PaymentError("PAYMENT_FORBIDDEN", "Solo el tendero confirma o rechaza un pago.")
    if status == "confirmado" and source is None:
        raise PaymentError("PAYMENT_SOURCE_REQUIRED", "Para confirmar di cómo lo verificaste: mostrador o revisión.")
    if status != "confirmado" and source is not None:
        raise PaymentError("PAYMENT_SOURCE_NOT_ALLOWED", "La fuente solo se indica al confirmar el pago.")
    if method in IN_PERSON and status in ("comprobante_recibido", "rechazado"):
        raise PaymentError("PAYMENT_STATUS_NOT_ALLOWED",
                           f"{METHODS[method]} se recibe en persona: queda pendiente o confirmado en el mostrador.")
    if status == "confirmado" and (source == "mostrador") != (method in IN_PERSON):
        raise PaymentError("PAYMENT_SOURCE_MISMATCH",
                           "Efectivo y datáfono se confirman en el mostrador; un pago digital, revisando tu app o "
                           "extracto (un pantallazo no prueba que llegó el dinero).")


class Payments:
    def __init__(self, path: Path = DEFAULT_DB_PATH, clock: Callable[[], datetime] | None = None,
                 business_id: str = DEMO_BUSINESS_ID, store_id: str = DEMO_STORE_ID):
        # El libro de pedidos aporta la conexión, el reloj de la tienda y el vencimiento de lo apartado.
        self.book = OrderBook(path, business_id=business_id, store_id=store_id,
                              **({"clock": clock} if clock is not None else {}))
        self.business_id = business_id
        self.store_id = store_id
        with self.book.transaction() as connection:
            for statement in filter(str.strip, PAYMENT_SCHEMA.split(";")):
                connection.execute(statement)

    def _order(self, connection: sqlite3.Connection, order_id: object) -> sqlite3.Row:
        if not isinstance(order_id, str) or not ORDER_ID.match(order_id):
            raise PaymentError("PAYMENT_ORDER_NOT_FOUND", "No encuentro ese pedido.")
        row = connection.execute("SELECT id, status, total_cop FROM orders WHERE id = ? AND business_id = ? AND "
                                 "store_id = ?", (order_id, self.business_id, self.store_id)).fetchone()
        if row is None:
            raise PaymentError("PAYMENT_ORDER_NOT_FOUND", "No encuentro ese pedido.")
        return row

    @staticmethod
    def _view(order: sqlite3.Row, payment: sqlite3.Row | None) -> dict:
        method = payment["method"] if payment else None
        return {
            "pedido": order["id"],
            "metodo": method,
            "metodo_texto": METHODS.get(method) if method else None,
            "estado": payment["status"] if payment else "pendiente",
            "fuente": payment["source"] if payment else None,
            "referencia": payment["reference"] if payment else "",
            "monto_cop": payment["amount_cop"] if payment else order["total_cop"],
            "actualizado": local_text(payment["updated_at"]) if payment else None,
        }

    def register(self, pedido: str, metodo: str, estado: str, referencia: str = "", fuente: str | None = None,
                 actor: str = "tendero") -> dict:
        """Registra el estado del pago del pedido con el monto del pedido y deja su evento."""
        check_payment(metodo, estado, fuente, actor)
        reference = _clean_reference(referencia)
        self.book.expire_due()  # Un pedido que ya pasó su plazo cuenta como vencido, no como activo.
        now = utc_text(self.book.clock())
        with self.book.transaction() as connection:
            order = self._order(connection, pedido)
            if order["status"] in ("cancelado", "vencido"):
                raise PaymentError("PAYMENT_ORDER_CLOSED", f"Ese pedido está {order['status']}: no recibe pagos.")
            current = connection.execute("SELECT status FROM payments WHERE order_id = ?", (pedido,)).fetchone()
            if current is not None and current["status"] == "confirmado":
                raise PaymentError("PAYMENT_ALREADY_CONFIRMED", "Ese pago ya está confirmado; no se cambia.")
            connection.execute("INSERT OR REPLACE INTO payments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                               (pedido, self.business_id, self.store_id, metodo, estado, fuente, reference,
                                order["total_cop"], now))
            connection.execute("INSERT INTO payment_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                               (pedido, now, estado, metodo, fuente, actor, reference, DETAILS[estado]))
            return self._view(order, connection.execute("SELECT * FROM payments WHERE order_id = ?",
                                                        (pedido,)).fetchone())

    def of(self, pedido: str) -> dict:
        """El pago del pedido; sin registro es ``pendiente`` sin método."""
        with self.book.transaction() as connection:
            order = self._order(connection, pedido)
            return self._view(order, connection.execute("SELECT * FROM payments WHERE order_id = ?",
                                                        (pedido,)).fetchone())

    def of_many(self, ids: list[str]) -> dict[str, dict]:
        """Pagos de varios pedidos de la sede por identificador; los que no existen se omiten."""
        wanted = [order_id for order_id in dict.fromkeys(ids) if isinstance(order_id, str) and ORDER_ID.match(order_id)]
        if len(wanted) > MAX_MANY:
            raise PaymentError("PAYMENT_TOO_MANY", f"Pide a lo sumo {MAX_MANY} pedidos a la vez.")
        found: dict[str, dict] = {}
        with self.book.transaction() as connection:
            for start in range(0, len(wanted), 500):  # SQLite limita los parámetros por consulta.
                chunk = wanted[start:start + 500]
                marks = ", ".join("?" * len(chunk))
                rows = connection.execute(
                    f"SELECT orders.id, orders.total_cop, payments.* FROM orders LEFT JOIN payments "
                    f"ON payments.order_id = orders.id WHERE orders.business_id = ? AND orders.store_id = ? "
                    f"AND orders.id IN ({marks})", (self.business_id, self.store_id, *chunk)).fetchall()
                for row in rows:
                    found[row["id"]] = self._view(row, row if row["status"] is not None else None)
        return found

    def history(self, pedido: str) -> list[dict]:
        """Eventos del pago del pedido, del más antiguo al más reciente, en hora de Bogotá."""
        with self.book.transaction() as connection:
            self._order(connection, pedido)
            events = connection.execute("SELECT * FROM payment_events WHERE order_id = ? ORDER BY rowid",
                                        (pedido,)).fetchall()
        return [{"hora": local_text(event["at"]), "estado": event["status"], "metodo": event["method"],
                 "fuente": event["source"], "actor": event["actor"], "referencia": event["reference"],
                 "detalle": event["detail"]} for event in events]
