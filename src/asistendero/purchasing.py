"""Abastecimiento flexible: órdenes de compra a proveedores ficticios y recepción de mercancía, sin ciclos fijos.

Ciclo de una orden de compra (OC):

- ``pedido``: el tendero la registró. **No suma existencias**: es mercancía pendiente (``pending_by_sku``).
- ``parcial``: llegó una parte y queda algo pendiente.
- ``recibida``: llegó todo lo pedido. ``cancelada``: el tendero canceló lo que faltaba (lo recibido se queda).

Una recepción (``R-0001``) es lo que de verdad llegó, con o sin OC. Con OC, cada línea abona a lo pendiente de esa
OC; lo que excede lo pedido, un SKU que no estaba en la OC o una recepción sin OC es **adicional**. Solo la
recepción sube el stock, y lo hace ``Inventory.receive_stock`` dentro de la misma transacción (el stock solo se
escribe en ``inventory.py``), con origen «recepción R-…» en el historial.

Coherencia con el asistente de clientes: el surtido (``restocks``) es lo que el agente dice cuando un cliente
pregunta «¿cuándo le llega?». Al crear, reprogramar, recibir o cancelar una OC, el surtido de cada SKU afectado pasa
a la fecha estimada más próxima (de hoy en adelante) entre las OC abiertas con ese SKU pendiente, si era otra cosa:
vacío, otra fecha o un día de la semana (la OC fechada es más precisa que el ciclo semanal). Si ya no queda OC
pendiente con fecha y el surtido era la fecha de esta OC, se borra: el agente no debe prometer una llegada que ya
no viene. «Descontinuado» nunca se pisa. Cada cambio de surtido queda en el historial con origen «compra OC-…».

Los costos de compra viven en tablas propias y nunca llegan a las herramientas del agente, que leen solo
``products``. Cada cambio corre en ``BEGIN IMMEDIATE``; las horas se guardan en UTC y se muestran en Bogotá.
"""

from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from datetime import date, datetime
from pathlib import Path
import sqlite3

from asistendero.inventory import ACTOR, Inventory, InventoryError
from asistendero.orders import BOGOTA, _store_now, utc_text
from asistendero.purchasing_lookup import (current_restock, earliest_arrival, find_order, find_product,
                                           find_supplier, next_id, pending_skus)
from asistendero.purchasing_rules import (MAX_LISTED, MAX_NAME_CHARS, MAX_NOTE_CHARS, MAX_SUPPLIERS, OPEN,
                                          PURCHASING_SCHEMA, STATUSES, SUPPLIER_ID, PurchasingError, clean_lines,
                                          expected_date, short_text, whole)
from asistendero.purchasing_views import order_view, receipt_view
from asistendero.restock import DISCONTINUED
from asistendero.seed import DEFAULT_DB_PATH, DEMO_BUSINESS_ID, DEMO_STORE_ID

__all__ = ["Purchasing", "PurchasingError"]


class Purchasing:
    def __init__(self, path: Path = DEFAULT_DB_PATH, clock: Callable[[], datetime] = _store_now,
                 business_id: str = DEMO_BUSINESS_ID, store_id: str = DEMO_STORE_ID):
        self.inventory = Inventory(path, business_id, store_id)
        self.path = self.inventory.path
        self.clock = clock
        self.business_id = business_id
        self.store_id = store_id
        # executescript confirma lo pendiente, así que el esquema va fuera de la transacción explícita.
        with closing(sqlite3.connect(self.path, timeout=10)) as connection, connection:
            connection.executescript(PURCHASING_SCHEMA)

    @contextmanager
    def _transaction(self, commit: bool = True) -> Iterator[sqlite3.Connection]:
        """Con ``commit=False`` todo se deshace al final: la vista previa corre el mismo código que la recepción."""
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            connection.execute("COMMIT" if commit else "ROLLBACK")
        finally:
            connection.close()

    def _now(self) -> str:
        return utc_text(self.clock())

    def _today(self) -> date:
        return self.clock().astimezone(BOGOTA).date()

    def _scope(self) -> tuple[str, str]:
        return self.business_id, self.store_id

    def _event(self, connection: sqlite3.Connection, order_id: str, action: str, detail: str) -> None:
        connection.execute("INSERT INTO purchase_order_events VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (*self._scope(), order_id, self._now(), action, detail, ACTOR))

    def _sync_restock(self, connection: sqlite3.Connection, skus: list[str], origin: str,
                      stale: str | None = None) -> None:
        """Lleva el surtido de cada SKU a la llegada más próxima de las OC abiertas (regla en el docstring)."""
        today = self._today().isoformat()
        for sku in skus:
            earliest = earliest_arrival(connection, self._scope(), sku, today)
            current = current_restock(connection, self._scope(), sku)
            if current == DISCONTINUED:
                continue
            if earliest and earliest != current:
                self.inventory.set_restock(connection, sku, earliest, ACTOR, origin, self._now())
            elif not earliest and stale and current == stale:
                self.inventory.set_restock(connection, sku, "", ACTOR, origin, self._now())

    def add_supplier(self, nombre: str, nota: str = "") -> dict:
        name = short_text(nombre, "El nombre del proveedor", MAX_NAME_CHARS, required=True)
        note = short_text(nota, "La nota", MAX_NOTE_CHARS)
        if SUPPLIER_ID.match(name):
            raise PurchasingError("INVALID_ARGUMENT", "El nombre no puede tener la forma de un código PV-001.")
        with self._transaction() as connection:
            count = connection.execute("SELECT COUNT(*) FROM purchase_suppliers WHERE business_id = ? AND "
                                       "store_id = ?", self._scope()).fetchone()[0]
            if count >= MAX_SUPPLIERS:
                raise PurchasingError("TOO_MANY_SUPPLIERS", f"La sede ya tiene {MAX_SUPPLIERS} proveedores.")
            supplier_id = next_id(connection, self._scope(), "purchase_suppliers", "PV-", 3)
            try:
                connection.execute("INSERT INTO purchase_suppliers VALUES (?, ?, ?, ?, ?, ?, ?)",
                                   (*self._scope(), supplier_id, name, name.casefold(), note, self._now()))
            except sqlite3.IntegrityError:
                raise PurchasingError("DUPLICATE_SUPPLIER", f"Ya existe el proveedor {name}.") from None
        return {"proveedor": supplier_id, "nombre": name, "nota": note, "ocs_abiertas": 0}

    def suppliers(self) -> list[dict]:
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT s.id, s.name, s.note, (SELECT COUNT(*) FROM purchase_orders o WHERE o.business_id = "
                "s.business_id AND o.store_id = s.store_id AND o.supplier_id = s.id AND o.status IN (?, ?)) AS open "
                "FROM purchase_suppliers s WHERE s.business_id = ? AND s.store_id = ? ORDER BY s.name_key",
                (*OPEN, *self._scope())).fetchall()
        return [{"proveedor": row["id"], "nombre": row["name"], "nota": row["note"], "ocs_abiertas": row["open"]}
                for row in rows]

    def create_order(self, proveedor: str, lineas: list[dict], fecha_estimada: str | None = None,
                     nota: str = "") -> dict:
        """Registra lo pedido al proveedor como mercancía pendiente; no cambia las existencias."""
        lines = clean_lines(lineas)
        day = expected_date(fecha_estimada, self._today())
        note = short_text(nota, "La nota", MAX_NOTE_CHARS)
        with self._transaction() as connection:
            supplier = find_supplier(connection, self._scope(), proveedor)
            for sku, _, _ in lines:
                find_product(connection, self._scope(), sku)
            order_id = next_id(connection, self._scope(), "purchase_orders", "OC-", 4)
            connection.execute("INSERT INTO purchase_orders VALUES (?, ?, ?, ?, 'pedido', ?, ?, ?, ?)",
                               (*self._scope(), order_id, supplier["id"], day, note, self._now(), self._now()))
            connection.executemany("INSERT INTO purchase_order_lines VALUES (?, ?, ?, ?, ?, 0, ?)",
                                   [(*self._scope(), order_id, sku, quantity, cost) for sku, quantity, cost in lines])
            when = f"; llega {day}" if day else "; sin fecha acordada"
            self._event(connection, order_id, "pedido", f"{len(lines)} líneas a {supplier['name']}{when}")
            if day:
                self._sync_restock(connection, [sku for sku, _, _ in lines], f"compra {order_id}")
            return self._view(connection, find_order(connection, self._scope(), order_id, open_only=False))

    def reschedule(self, oc: str, fecha_estimada: str, motivo: str = "") -> dict:
        """Cambia la fecha acordada con el proveedor y lleva el surtido de lo pendiente a la nueva fecha."""
        day = expected_date(fecha_estimada, self._today())
        if day is None:
            raise PurchasingError("INVALID_ARGUMENT", "Indica la nueva fecha estimada como AAAA-MM-DD.")
        reason = short_text(motivo, "El motivo", MAX_NOTE_CHARS)
        with self._transaction() as connection:
            row = find_order(connection, self._scope(), oc)
            if row["expected_date"] != day:
                connection.execute("UPDATE purchase_orders SET expected_date = ?, updated_at = ? WHERE business_id "
                                   "= ? AND store_id = ? AND id = ?", (day, self._now(), *self._scope(), row["id"]))
                detail = f"{row['expected_date'] or 'sin fecha'} -> {day}" + (f": {reason}" if reason else "")
                self._event(connection, row["id"], "reprogramada", detail)
                pending = pending_skus(connection, self._scope(), row["id"])
                self._sync_restock(connection, pending, f"compra {row['id']}", stale=row["expected_date"])
            return self._view(connection, find_order(connection, self._scope(), row["id"], open_only=False))

    def cancel_order(self, oc: str, motivo: str) -> dict:
        """Cancela lo que faltaba por llegar; lo ya recibido y las existencias no cambian."""
        reason = short_text(motivo, "El motivo", MAX_NOTE_CHARS, required=True)
        with self._transaction() as connection:
            row = find_order(connection, self._scope(), oc)
            pending = pending_skus(connection, self._scope(), row["id"])
            connection.execute("UPDATE purchase_orders SET status = 'cancelada', updated_at = ? WHERE business_id = ? "
                               "AND store_id = ? AND id = ?", (self._now(), *self._scope(), row["id"]))
            self._event(connection, row["id"], "cancelada", reason)
            self._sync_restock(connection, pending, f"compra {row['id']}", stale=row["expected_date"])
            return self._view(connection, find_order(connection, self._scope(), row["id"], open_only=False))

    def receive(self, proveedor: str | None, lineas: list[dict], oc: str | None = None, nota: str = "",
                apply: bool = True) -> dict:
        """Registra lo que llegó y suma existencias; con ``apply=False`` devuelve el mismo resumen sin escribir."""
        lines = clean_lines(lineas)
        note = short_text(nota, "La nota", MAX_NOTE_CHARS)
        with self._transaction(commit=apply) as connection:
            order = find_order(connection, self._scope(), oc) if oc is not None else None
            if order is None or proveedor is not None:
                supplier = find_supplier(connection, self._scope(), proveedor)
                if order is not None and supplier["id"] != order["supplier_id"]:
                    raise PurchasingError("SUPPLIER_MISMATCH", f"La orden {oc} es de otro proveedor.")
            receipt_id = next_id(connection, self._scope(), "purchase_receipts", "R-", 4)
            ordered = {} if order is None else {row["sku"]: row for row in connection.execute(
                "SELECT * FROM purchase_order_lines WHERE business_id = ? AND store_id = ? AND order_id = ?",
                (*self._scope(), order["id"]))}
            stored = []
            for sku, quantity, cost in lines:
                find_product(connection, self._scope(), sku)
                line = ordered.get(sku)
                pending = line["ordered"] - line["received"] if line else 0
                toward = min(quantity, pending)
                if toward:
                    connection.execute("UPDATE purchase_order_lines SET received = received + ? WHERE business_id "
                                       "= ? AND store_id = ? AND order_id = ? AND sku = ?",
                                       (toward, *self._scope(), order["id"], sku))
                try:
                    before, after = self.inventory.receive_stock(connection, sku, quantity, ACTOR,
                                                                 f"recepción {receipt_id}", self._now())
                except InventoryError as error:
                    raise PurchasingError(error.code, str(error)) from None
                unit_cost = cost if cost is not None else (line["unit_cost_cop"] if line else None)
                stored.append((*self._scope(), receipt_id, sku, quantity, quantity - toward, before, after,
                               pending - toward, unit_cost))
            connection.execute("INSERT INTO purchase_receipts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                               (*self._scope(), receipt_id, order["supplier_id"] if order else supplier["id"],
                                order["id"] if order else None, note, self._now(), ACTOR))
            connection.executemany("INSERT INTO purchase_receipt_lines VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", stored)
            if order is not None:
                self._close_if_complete(connection, order, receipt_id, [line[3] for line in stored])
            result = self._receipt_view(connection, receipt_id)
        return {**result, "recepcion": None, "vista_previa": True} if not apply else result

    def _close_if_complete(self, connection: sqlite3.Connection, order: sqlite3.Row, receipt_id: str,
                           skus: list[str]) -> None:
        left = len(pending_skus(connection, self._scope(), order["id"]))
        status = "parcial" if left else "recibida"
        connection.execute("UPDATE purchase_orders SET status = ?, updated_at = ? WHERE business_id = ? AND "
                           "store_id = ? AND id = ?", (status, self._now(), *self._scope(), order["id"]))
        self._event(connection, order["id"], status, f"recepción {receipt_id}")
        self._sync_restock(connection, skus, f"compra {order['id']}", stale=order["expected_date"])

    def _view(self, connection: sqlite3.Connection, row: sqlite3.Row) -> dict:
        return order_view(connection, row, self._today())

    def _receipt_view(self, connection: sqlite3.Connection, receipt_id: str) -> dict:
        return receipt_view(connection, self._scope(), receipt_id)

    def orders(self, estado: str | None = None) -> list[dict]:
        """OCs más recientes primero, con líneas, atraso e historial; ``estado`` filtra por uno de STATUSES."""
        if estado is not None and estado not in STATUSES:
            raise PurchasingError("INVALID_ARGUMENT", f"El estado es uno de: {', '.join(STATUSES)}.")
        sql = "SELECT * FROM purchase_orders WHERE business_id = ? AND store_id = ?"
        params: list[object] = list(self._scope())
        if estado is not None:
            sql += " AND status = ?"
            params.append(estado)
        with self._transaction() as connection:
            rows = connection.execute(sql + " ORDER BY created_at DESC, id DESC LIMIT ?", (*params, MAX_LISTED))
            return [self._view(connection, row) for row in rows.fetchall()]

    def receipts(self, limit: int = 20) -> list[dict]:
        limit = whole(limit, "El límite", 1, MAX_LISTED)
        with self._transaction() as connection:
            ids = [row[0] for row in connection.execute(
                "SELECT id FROM purchase_receipts WHERE business_id = ? AND store_id = ? ORDER BY received_at DESC, "
                "id DESC LIMIT ?", (*self._scope(), limit))]
            return [self._receipt_view(connection, receipt_id) for receipt_id in ids]

    def pending_by_sku(self) -> dict[str, dict]:
        """{sku: {"pendiente": unidades por llegar, "llega": fecha más próxima o None}} de las OC abiertas."""
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT l.sku, SUM(l.ordered - l.received) AS pending, MIN(o.expected_date) AS arrives FROM "
                "purchase_order_lines l JOIN purchase_orders o ON o.business_id = l.business_id AND o.store_id = "
                "l.store_id AND o.id = l.order_id WHERE l.business_id = ? AND l.store_id = ? AND o.status IN (?, ?) "
                "AND l.received < l.ordered GROUP BY l.sku ORDER BY l.sku", (*self._scope(), *OPEN)).fetchall()
        return {row["sku"]: {"pendiente": row["pending"], "llega": row["arrives"]} for row in rows}
