"""Búsquedas de las compras dentro de la transacción de quien llama (``purchasing.py``).

Cada consulta va filtrada por negocio y sede (``scope``) y parametrizada: lo de otra sede responde igual que lo que
no existe.
"""

import sqlite3

from asistendero.purchasing_rules import MAX_NAME_CHARS, OPEN, SUPPLIER_ID, PurchasingError, purchase_id, short_text

Scope = tuple[str, str]
_OPEN_IN = ", ".join("?" * len(OPEN))


def next_id(connection: sqlite3.Connection, scope: Scope, table: str, prefix: str, width: int) -> str:
    """Código secuencial por sede (OC-0001, R-0001, PV-001); corre dentro de BEGIN IMMEDIATE, sin carreras."""
    # ``table`` y ``prefix`` son constantes de purchasing.py, nunca texto de quien llama.
    last = connection.execute(f"SELECT COALESCE(MAX(CAST(substr(id, {len(prefix) + 1}) AS INTEGER)), 0) "
                              f"FROM {table} WHERE business_id = ? AND store_id = ?", scope).fetchone()[0]
    return f"{prefix}{last + 1:0{width}d}"


def find_supplier(connection: sqlite3.Connection, scope: Scope, value: object) -> sqlite3.Row:
    """Proveedor por su código (PV-001) o por su nombre exacto, sin importar mayúsculas."""
    if isinstance(value, str) and SUPPLIER_ID.match(value.strip()):
        row = connection.execute("SELECT * FROM purchase_suppliers WHERE business_id = ? AND store_id = ? AND id = ?",
                                 (*scope, value.strip())).fetchone()
    else:
        name = short_text(value, "El proveedor", MAX_NAME_CHARS, required=True)
        row = connection.execute("SELECT * FROM purchase_suppliers WHERE business_id = ? AND store_id = ? "
                                 "AND name_key = ?", (*scope, name.casefold())).fetchone()
    if row is None:
        raise PurchasingError("SUPPLIER_NOT_FOUND", "No existe ese proveedor en esta sede; agrégalo primero.")
    return row


def find_product(connection: sqlite3.Connection, scope: Scope, sku: str) -> sqlite3.Row:
    row = connection.execute("SELECT sku FROM products WHERE business_id = ? AND store_id = ? AND sku = ?",
                             (*scope, sku)).fetchone()
    if row is None:
        raise PurchasingError("NOT_FOUND", f"No existe el SKU {sku} en esta sede.")
    return row


def find_order(connection: sqlite3.Connection, scope: Scope, order_id: object, open_only: bool = True) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM purchase_orders WHERE business_id = ? AND store_id = ? AND id = ?",
                             (*scope, purchase_id(order_id))).fetchone()
    if row is None:
        raise PurchasingError("PURCHASE_NOT_FOUND", f"No encuentro la orden {order_id} en esta sede.")
    if open_only and row["status"] not in OPEN:
        raise PurchasingError("PURCHASE_CLOSED", f"La orden {order_id} ya está {row['status']}; si llegó algo, "
                                                 "regístralo como recepción sin OC.")
    return row


def pending_skus(connection: sqlite3.Connection, scope: Scope, order_id: str) -> list[str]:
    return [row[0] for row in connection.execute(
        "SELECT sku FROM purchase_order_lines WHERE business_id = ? AND store_id = ? AND order_id = ? "
        "AND received < ordered", (*scope, order_id))]


def earliest_arrival(connection: sqlite3.Connection, scope: Scope, sku: str, today: str) -> str | None:
    """Fecha estimada más próxima, de hoy en adelante, entre las OC abiertas con ese SKU pendiente."""
    return connection.execute(
        "SELECT MIN(o.expected_date) FROM purchase_orders o JOIN purchase_order_lines l ON l.business_id = "
        "o.business_id AND l.store_id = o.store_id AND l.order_id = o.id WHERE o.business_id = ? AND o.store_id = ? "
        f"AND l.sku = ? AND o.status IN ({_OPEN_IN}) AND l.received < l.ordered AND o.expected_date >= ?",
        (*scope, sku, *OPEN, today)).fetchone()[0]


def current_restock(connection: sqlite3.Connection, scope: Scope, sku: str) -> str:
    row = connection.execute("SELECT plan FROM restocks WHERE business_id = ? AND store_id = ? AND sku = ?",
                             (*scope, sku)).fetchone()
    return row[0] if row else ""
