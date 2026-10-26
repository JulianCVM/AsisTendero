"""Límites, tablas y validaciones de las compras a proveedores (``purchasing.py``).

Todo lo que escribe el tendero (o, más adelante, otro canal) se valida aquí con sus límites en constantes antes de
tocar la base: pasado el máximo se rechaza, nunca se recorta en silencio. Los costos de compra viven en tablas
propias; las herramientas del agente leen solo ``products`` y nunca los ven.
"""

from datetime import date, timedelta
import re

from asistendero.restock import MAX_DAYS_AHEAD
from asistendero.validation import SKU_PATTERN


MAX_QUANTITY = 100_000
MAX_UNIT_COST_COP = 50_000_000
MAX_LINES = 40
MAX_NAME_CHARS = 60
MAX_NOTE_CHARS = 140
MAX_SUPPLIERS = 200
MAX_LISTED = 200
OPEN = ("pedido", "parcial")
STATUSES = (*OPEN, "recibida", "cancelada")
PURCHASE_ID = re.compile(r"^OC-\d{4,6}$")
SUPPLIER_ID = re.compile(r"^PV-\d{3,5}$")
LINE_FIELDS = {"sku", "cantidad", "costo_unitario"}

PURCHASING_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS purchase_suppliers (
    business_id TEXT NOT NULL, store_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL,
    name_key TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY (business_id, store_id, id), UNIQUE (business_id, store_id, name_key)
);
CREATE TABLE IF NOT EXISTS purchase_orders (
    business_id TEXT NOT NULL, store_id TEXT NOT NULL, id TEXT NOT NULL, supplier_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ({", ".join(f"'{status}'" for status in STATUSES)})),
    expected_date TEXT, note TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY (business_id, store_id, id)
);
CREATE TABLE IF NOT EXISTS purchase_order_lines (
    business_id TEXT NOT NULL, store_id TEXT NOT NULL, order_id TEXT NOT NULL, sku TEXT NOT NULL,
    ordered INTEGER NOT NULL CHECK (ordered > 0), received INTEGER NOT NULL DEFAULT 0 CHECK (received >= 0),
    unit_cost_cop INTEGER CHECK (unit_cost_cop >= 0),
    PRIMARY KEY (business_id, store_id, order_id, sku)
);
CREATE TABLE IF NOT EXISTS purchase_order_events (
    business_id TEXT NOT NULL, store_id TEXT NOT NULL, order_id TEXT NOT NULL, at TEXT NOT NULL,
    action TEXT NOT NULL, detail TEXT NOT NULL, actor TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS purchase_receipts (
    business_id TEXT NOT NULL, store_id TEXT NOT NULL, id TEXT NOT NULL, supplier_id TEXT NOT NULL,
    order_id TEXT, note TEXT NOT NULL, received_at TEXT NOT NULL, actor TEXT NOT NULL,
    PRIMARY KEY (business_id, store_id, id)
);
CREATE TABLE IF NOT EXISTS purchase_receipt_lines (
    business_id TEXT NOT NULL, store_id TEXT NOT NULL, receipt_id TEXT NOT NULL, sku TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0), extra INTEGER NOT NULL CHECK (extra >= 0),
    stock_before INTEGER NOT NULL, stock_after INTEGER NOT NULL, pending_after INTEGER NOT NULL,
    unit_cost_cop INTEGER CHECK (unit_cost_cop >= 0),
    PRIMARY KEY (business_id, store_id, receipt_id, sku)
);
CREATE INDEX IF NOT EXISTS purchase_orders_by_status ON purchase_orders (business_id, store_id, status);
"""


class PurchasingError(Exception):
    """Compra o recepción rechazada con un código estable y un mensaje que dice qué corregir."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def short_text(value: object, field: str, maximum: int, required: bool = False) -> str:
    """Texto limpio de espacios repetidos; vacío solo si no es obligatorio."""
    if value is None and not required:
        return ""
    if not isinstance(value, str) or len(value.strip()) > maximum or (required and not value.strip()):
        need = "de 1" if required else "de 0"
        raise PurchasingError("INVALID_ARGUMENT", f"{field} es un texto {need} a {maximum} caracteres.")
    return re.sub(r"\s+", " ", value.strip())


def whole(value: object, field: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise PurchasingError("INVALID_ARGUMENT",
                              f"{field} debe ser un entero de {minimum} a {maximum:,}.".replace(",", "."))
    return value


def clean_lines(lines: object) -> list[tuple[str, int, int | None]]:
    """(sku, cantidad, costo unitario o None) de cada línea; un SKU repetido se rechaza en vez de sumarse."""
    if not isinstance(lines, list) or not 1 <= len(lines) <= MAX_LINES:
        raise PurchasingError("INVALID_ARGUMENT", f"Indica de 1 a {MAX_LINES} líneas.")
    result = []
    for line in lines:
        if not isinstance(line, dict) or not {"sku", "cantidad"} <= set(line) <= LINE_FIELDS:
            raise PurchasingError("INVALID_ARGUMENT", "Cada línea lleva sku, cantidad y, si quieres, costo_unitario.")
        sku = line["sku"]
        if not isinstance(sku, str) or not SKU_PATTERN.match(sku):
            raise PurchasingError("INVALID_ARGUMENT", "El SKU va en mayúsculas, números y guiones (ej.: CEM-050).")
        if any(sku == seen for seen, _, _ in result):
            raise PurchasingError("DUPLICATE_LINE", f"El SKU {sku} está dos veces; súmalo en una sola línea.")
        quantity = whole(line["cantidad"], f"La cantidad de {sku}", 1, MAX_QUANTITY)
        cost = line.get("costo_unitario")
        if cost is not None:
            cost = whole(cost, f"El costo unitario de {sku}", 0, MAX_UNIT_COST_COP)
        result.append((sku, quantity, cost))
    return result


def expected_date(value: object, today: date) -> str | None:
    """Fecha acordada con el proveedor: AAAA-MM-DD de hoy a ``MAX_DAYS_AHEAD`` días; None si no hay."""
    if value is None or value == "":
        return None
    try:
        day = date.fromisoformat(value) if isinstance(value, str) and len(value) == 10 else None
    except ValueError:
        day = None
    if day is None:
        raise PurchasingError("INVALID_ARGUMENT", "La fecha estimada va como AAAA-MM-DD.")
    if day < today:
        raise PurchasingError("DATE_IN_PAST", "La fecha estimada no puede ser anterior a hoy.")
    if day > today + timedelta(days=MAX_DAYS_AHEAD):
        raise PurchasingError("DATE_TOO_FAR", f"La fecha estimada va hasta {MAX_DAYS_AHEAD} días adelante.")
    return day.isoformat()


def purchase_id(value: object) -> str:
    if not isinstance(value, str) or not PURCHASE_ID.match(value):
        raise PurchasingError("PURCHASE_NOT_FOUND", "No encuentro esa orden de compra (va como OC-0001).")
    return value
