"""Pedidos para recoger en la tienda: se apartan, se confirman, se agendan y vencen solos.

Ciclo de un pedido:

- ``pendiente``: lo registró el agente con lo que el cliente pidió. Aparta las unidades ``HOLD_MINUTES``
  mientras el cliente confirma; si no confirma a tiempo, el barrido lo deja ``vencido`` y las libera.
- ``confirmado``: el cliente dijo que sí. Queda apartado hasta ``PICKUP_GRACE`` después de la hora de
  recogida acordada, o ``CONFIRMED_HOLD`` si no hay hora. Después también vence.
- ``entregado``: lo marca el tendero al entregar; solo ahí se descuentan las existencias físicas.
- ``cancelado``: lo cancela el cliente o el tendero.

Lo apartado se descuenta de las existencias que ven las herramientas del agente (``catalog.RESERVED_SQL``).
Cada cambio corre en una transacción ``BEGIN IMMEDIATE``: dos clientes no pueden apartar la última unidad a la
vez. Las horas se guardan en UTC y se muestran en hora de Bogotá. Este chat no cobra ni fía.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from asistendero.catalog import RESERVED_SQL
from asistendero.seed import DEFAULT_DB_PATH, DEMO_BUSINESS_ID, DEMO_STORE_ID, upgrade_db


HOLD_MINUTES = 5
CONFIRMED_HOLD = timedelta(hours=24)
PICKUP_GRACE = timedelta(hours=2)
MIN_PICKUP_LEAD = timedelta(minutes=10)
MAX_PICKUP_DAYS = 7
MAX_ACTIVE_PER_SESSION = 3
MAX_NOTE_CHARS = 140
ORDER_ID = re.compile(r"^P-[0-9A-F]{6}$")
ACTIVE = ("pendiente", "confirmado")
WEEKDAYS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")
BOGOTA = timezone(timedelta(hours=-5), "America/Bogota")
PAYMENT = "Lo pagas en el mostrador al recoger; por aquí no cobro ni fío."


class OrderError(Exception):
    """Regla de negocio que impide el cambio, con un código estable y un mensaje seguro."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _store_now() -> datetime:
    # Importación tardía: las pruebas fijan la hora reemplazando tools.local_now.
    from asistendero import tools
    return tools.local_now()


def utc_text(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def local_text(value: str | None) -> str | None:
    return datetime.fromisoformat(value).astimezone(BOGOTA).strftime("%Y-%m-%d %H:%M") if value else None


class OrderBook:
    def __init__(self, path: Path = DEFAULT_DB_PATH, clock: Callable[[], datetime] = _store_now,
                 business_id: str = DEMO_BUSINESS_ID, store_id: str = DEMO_STORE_ID):
        self.path = upgrade_db(path)
        self.clock = clock
        self.business_id = business_id
        self.store_id = store_id

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            connection.execute("COMMIT")
        finally:
            connection.close()

    def _event(self, connection: sqlite3.Connection, order_id: str, status: str, detail: str) -> None:
        connection.execute("INSERT INTO order_events VALUES (?, ?, ?, ?)", (order_id, utc_text(self.clock()), status, detail))

    def _expire(self, connection: sqlite3.Connection) -> list[dict]:
        rows = connection.execute(
            "SELECT id, session_id, status FROM orders WHERE business_id = ? AND store_id = ? AND status IN (?, ?) "
            "AND hold_until <= ?", (self.business_id, self.store_id, *ACTIVE, utc_text(self.clock())),
        ).fetchall()
        for row in rows:
            connection.execute("UPDATE orders SET status = 'vencido', updated_at = ? WHERE id = ?",
                               (utc_text(self.clock()), row["id"]))
            reason = "sin confirmar a tiempo" if row["status"] == "pendiente" else "no se recogió a tiempo"
            self._event(connection, row["id"], "vencido", reason)
        return [{"pedido": row["id"], "session_id": row["session_id"], "antes": row["status"]} for row in rows]

    def expire_due(self) -> list[dict]:
        """Vence lo que pasó su plazo y devuelve qué venció, para avisar a cada cliente."""
        with self.transaction() as connection:
            return self._expire(connection)

    def _load(self, connection: sqlite3.Connection, order_id: str, session_id: str | None = None) -> sqlite3.Row:
        if not isinstance(order_id, str) or not ORDER_ID.match(order_id):
            raise OrderError("ORDER_NOT_FOUND", "No encuentro ese pedido.")
        row = connection.execute("SELECT * FROM orders WHERE id = ? AND business_id = ? AND store_id = ?",
                                 (order_id, self.business_id, self.store_id)).fetchone()
        # Un cliente solo ve sus pedidos: el de otra sesión responde igual que uno inexistente.
        if row is None or (session_id is not None and row["session_id"] != session_id):
            raise OrderError("ORDER_NOT_FOUND", "No encuentro ese pedido en esta conversación.")
        return row

    def view(self, connection: sqlite3.Connection, row: sqlite3.Row) -> dict:
        lines = connection.execute("SELECT * FROM order_lines WHERE order_id = ? ORDER BY rowid", (row["id"],)).fetchall()
        return {
            "pedido": row["id"], "estado": row["status"],
            "lineas": [{"sku": line["sku"], "nombre": line["name"], "variante": line["variant"], "unidad": line["unit"],
                        "cantidad": line["quantity"], "precio_unitario_cop": line["unit_price_cop"],
                        "subtotal_cop": line["subtotal_cop"]} for line in lines],
            "total_cop": row["total_cop"],
            "aparta_hasta": local_text(row["hold_until"]) if row["status"] in ACTIVE else None,
            "recogida": local_text(row["pickup_at"]),
            "nota": row["note"],
            "creado": local_text(row["created_at"]),
            "pago": PAYMENT,
        }

    def create(self, session_id: str, lines: list[tuple[str, int]], replaces: str | None = None) -> dict:
        """Aparta las líneas HOLD_MINUTES con el precio vigente; falla si alguna no alcanza.

        Con ``replaces`` el pedido nuevo reemplaza a ese pedido activo de la sesión en la misma transacción: lo que
        tenía apartado cuenta como disponible y, si algo no alcanza, el anterior queda igual. Z-32 (suite fallas):
        con «mejor que sean 20» y 9 en bodega, Grok canceló el pedido de 2 y el cliente se quedó sin nada.
        """
        now = self.clock()
        with self.transaction() as connection:
            self._expire(connection)
            freed: dict[str, int] = {}
            if replaces is not None:
                self._active(connection, replaces, session_id)
                freed = {line["sku"]: line["quantity"] for line in connection.execute(
                    "SELECT sku, quantity FROM order_lines WHERE order_id = ?", (replaces,)).fetchall()}
            active = connection.execute("SELECT COUNT(*) FROM orders WHERE session_id = ? AND status IN (?, ?)",
                                        (session_id, *ACTIVE)).fetchone()[0] - (replaces is not None)
            if active >= MAX_ACTIVE_PER_SESSION:
                raise OrderError("TOO_MANY_ORDERS", f"Ya hay {active} pedidos activos en esta conversación.")
            order_id = f"P-{uuid4().hex[:6].upper()}"
            stored = []
            for sku, quantity in lines:
                product = connection.execute(
                    f"SELECT sku, name, variant, unit, price_cop, products.stock - {RESERVED_SQL} AS available "
                    "FROM products WHERE business_id = ? AND store_id = ? AND sku = ?",
                    (self.business_id, self.store_id, sku),
                ).fetchone()
                if product is None:
                    raise OrderError("NOT_FOUND", f"No existe el SKU {sku} en el catálogo de esta sede.")
                available = product["available"] + freed.get(sku, 0)
                if quantity > available and replaces is not None:
                    raise OrderError("INSUFFICIENT_STOCK", f"De {product['name']} {product['variant']} solo hay "
                                                           f"{max(available, 0)} contando lo de tu pedido {replaces}, y "
                                                           f"pediste {quantity}. Tu pedido {replaces} sigue igual.")
                if quantity > available:
                    raise OrderError("INSUFFICIENT_STOCK", f"Para {sku} hay {max(available, 0)} "
                                                           f"{product['unit']} disponibles; pediste {quantity}.")
                stored.append((order_id, sku, product["name"], product["variant"], product["unit"], quantity,
                               product["price_cop"], product["price_cop"] * quantity))
            connection.execute(
                "INSERT INTO orders VALUES (?, ?, ?, ?, 'pendiente', ?, ?, ?, NULL, NULL, ?)",
                (order_id, self.business_id, self.store_id, session_id, utc_text(now), utc_text(now),
                 utc_text(now + timedelta(minutes=HOLD_MINUTES)), sum(line[-1] for line in stored)),
            )
            connection.executemany("INSERT INTO order_lines VALUES (?, ?, ?, ?, ?, ?, ?, ?)", stored)
            self._event(connection, order_id, "pendiente", "registrado por el agente")
            if replaces is None:
                return self.view(connection, self._load(connection, order_id))
            connection.execute("UPDATE orders SET status = 'cancelado', updated_at = ? WHERE id = ?",
                               (utc_text(now), replaces))
            self._event(connection, replaces, "cancelado", f"reemplazado por {order_id} a pedido del cliente")
            return {**self.view(connection, self._load(connection, order_id)), "reemplaza": replaces}

    def _active(self, connection: sqlite3.Connection, order_id: str, session_id: str | None) -> sqlite3.Row:
        self._expire(connection)
        row = self._load(connection, order_id, session_id)
        if row["status"] == "vencido":
            raise OrderError("ORDER_EXPIRED", "Ese pedido venció y ya liberé lo apartado.")
        if row["status"] not in ACTIVE:
            raise OrderError("ORDER_CLOSED", f"Ese pedido ya está {row['status']}.")
        return row

    def confirm(self, session_id: str, order_id: str) -> dict:
        with self.transaction() as connection:
            row = self._active(connection, order_id, session_id)
            if row["status"] == "confirmado":
                return self.view(connection, row)
            pickup = datetime.fromisoformat(row["pickup_at"]) if row["pickup_at"] else None
            hold = pickup + PICKUP_GRACE if pickup else self.clock() + CONFIRMED_HOLD
            connection.execute("UPDATE orders SET status = 'confirmado', hold_until = ?, updated_at = ? WHERE id = ?",
                               (utc_text(hold), utc_text(self.clock()), order_id))
            self._event(connection, order_id, "confirmado", "confirmado por el cliente")
            return self.view(connection, self._load(connection, order_id))

    def check_pickup(self, connection: sqlite3.Connection, pickup: datetime) -> None:
        now = self.clock()
        if pickup < now + MIN_PICKUP_LEAD:
            raise OrderError("PICKUP_IN_PAST", "La recogida debe ser al menos 10 minutos después de ahora.")
        if pickup > now + timedelta(days=MAX_PICKUP_DAYS):
            raise OrderError("PICKUP_TOO_FAR", f"La recogida puede agendarse hasta {MAX_PICKUP_DAYS} días adelante.")
        row = connection.execute("SELECT content FROM store_info WHERE business_id = ? AND store_id = ? AND topic = 'horario'",
                                 (self.business_id, self.store_id)).fetchone()
        hours = json.loads(row["content"])["dias"].get(WEEKDAYS[pickup.astimezone(BOGOTA).weekday()]) if row else None
        at = pickup.astimezone(BOGOTA).strftime("%H:%M")
        if not hours or not hours[0] <= at < hours[1]:
            raise OrderError("PICKUP_OUTSIDE_HOURS", "La tienda está cerrada a esa hora; revisa el horario.")

    def schedule(self, session_id: str, order_id: str, pickup: datetime | None, note: str | None) -> dict:
        with self.transaction() as connection:
            row = self._active(connection, order_id, session_id)
            changes: dict[str, str] = {}
            if pickup is not None:
                self.check_pickup(connection, pickup)
                changes["pickup_at"] = utc_text(pickup)
                if row["status"] == "confirmado":
                    changes["hold_until"] = utc_text(pickup + PICKUP_GRACE)
            if note:
                changes["note"] = note[:MAX_NOTE_CHARS]
            if not changes:
                raise OrderError("INVALID_ARGUMENT", "Indica la fecha y hora de recogida o una nota.")
            assignments = ", ".join(f"{column} = ?" for column in changes)
            connection.execute(f"UPDATE orders SET {assignments}, updated_at = ? WHERE id = ?",
                               (*changes.values(), utc_text(self.clock()), order_id))
            detail = f"recogida {local_text(changes['pickup_at'])}" if "pickup_at" in changes else "nota del cliente"
            self._event(connection, order_id, row["status"], detail)
            return self.view(connection, self._load(connection, order_id))

    def cancel(self, order_id: str, session_id: str | None = None, by: str = "cliente") -> dict:
        with self.transaction() as connection:
            self._active(connection, order_id, session_id)
            connection.execute("UPDATE orders SET status = 'cancelado', updated_at = ? WHERE id = ?",
                               (utc_text(self.clock()), order_id))
            self._event(connection, order_id, "cancelado", f"cancelado por el {by}")
            return self.view(connection, self._load(connection, order_id))

    def deliver(self, order_id: str) -> dict:
        """El tendero entrega: el pedido pasa a venta y se descuentan las existencias físicas."""
        with self.transaction() as connection:
            self._active(connection, order_id, None)
            lines = connection.execute("SELECT sku, quantity FROM order_lines WHERE order_id = ?", (order_id,)).fetchall()
            for line in lines:
                updated = connection.execute(
                    "UPDATE products SET stock = stock - ? WHERE business_id = ? AND store_id = ? AND sku = ? AND stock >= ?",
                    (line["quantity"], self.business_id, self.store_id, line["sku"], line["quantity"]),
                )
                if updated.rowcount != 1:
                    raise OrderError("INSUFFICIENT_STOCK", f"No hay existencias físicas de {line['sku']} para entregar.")
            connection.execute("UPDATE orders SET status = 'entregado', updated_at = ? WHERE id = ?",
                               (utc_text(self.clock()), order_id))
            self._event(connection, order_id, "entregado", "entregado por el tendero")
            return self.view(connection, self._load(connection, order_id))

    def get(self, order_id: str, session_id: str | None = None) -> dict:
        with self.transaction() as connection:
            self._expire(connection)
            return self.view(connection, self._load(connection, order_id, session_id))

    def session_orders(self, session_id: str, limit: int = 5) -> list[dict]:
        with self.transaction() as connection:
            self._expire(connection)
            rows = connection.execute("SELECT * FROM orders WHERE session_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?",
                                      (session_id, limit)).fetchall()
            return [self.view(connection, row) for row in rows]
