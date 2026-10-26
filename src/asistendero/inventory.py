"""Inventario que administra el tendero: consultar, corregir precio, existencias y surtido y agregar productos.

Es la única vía que escribe precio o stock; las herramientas del agente siguen en solo lectura. Cada cambio queda
en ``inventory_events`` con el valor anterior y el nuevo, para que el tendero sepa quién movió qué y cuándo
(en el prototipo el único actor es «tendero») y de dónde vino el movimiento (``origin``: «panel» si lo corrigió
a mano, «recepción R-0001» si llegó mercancía de un proveedor por ``purchasing.py``). Las compras suman existencias
con ``receive_stock`` dentro de su propia transacción, así que el stock solo se escribe aquí. Todo es ficticio: no
hay datos de un piloto real.
"""

from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3

from asistendero.catalog import RESERVED_SQL, RESTOCK_SQL
from asistendero.orders import local_text
from asistendero.restock import valid_plan
from asistendero.seed import DEFAULT_DB_PATH, DEMO_BUSINESS_ID, DEMO_STORE_ID, upgrade_db
from asistendero.validation import SKU_PATTERN


MAX_PRICE_COP = 50_000_000
MAX_STOCK = 100_000
MAX_TEXT_CHARS = 80
MAX_TERMS_CHARS = 300
MAX_LISTED = 500
LOW_STOCK = 5
UNITS = ("unidad", "metro", "bulto", "galón", "libra", "rollo", "par", "pliego", "bolsa", "caja")
INVENTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS inventory_events (
    business_id TEXT NOT NULL, store_id TEXT NOT NULL, sku TEXT NOT NULL, at TEXT NOT NULL,
    field TEXT NOT NULL, before TEXT, after TEXT NOT NULL, actor TEXT NOT NULL, origin TEXT
);
"""
PANEL = "panel"
ACTOR = "tendero"


class InventoryError(Exception):
    """Cambio rechazado con un código estable y un mensaje que dice qué corregir."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _int(value: object, field: str, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= maximum:
        raise InventoryError("INVALID_ARGUMENT", f"{field} debe ser un entero de 0 a {maximum:,}.".replace(",", "."))
    return value


def _text(value: object, field: str, maximum: int = MAX_TEXT_CHARS) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise InventoryError("INVALID_ARGUMENT", f"{field} es un texto de 1 a {maximum} caracteres.")
    return re.sub(r"\s+", " ", value.strip())


class Inventory:
    def __init__(self, path: Path = DEFAULT_DB_PATH, business_id: str = DEMO_BUSINESS_ID, store_id: str = DEMO_STORE_ID):
        self.path = upgrade_db(path)
        self.business_id = business_id
        self.store_id = store_id
        self._run(self._migrate)

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        connection.executescript(INVENTORY_SCHEMA)
        # Bases creadas antes de las compras no tienen «origin»; sus eventos vinieron todos del panel.
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(inventory_events)")}
        if "origin" not in columns:
            connection.execute("ALTER TABLE inventory_events ADD COLUMN origin TEXT")

    def _log(self, connection: sqlite3.Connection, sku: str, field: str, before: object, after: object,
             actor: str = ACTOR, origin: str = PANEL, at: str | None = None) -> None:
        connection.execute(
            "INSERT INTO inventory_events (business_id, store_id, sku, at, field, before, after, actor, origin) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (self.business_id, self.store_id, sku, at or _now(), field, None if before is None else str(before),
             str(after), actor, origin))

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _run(self, action):
        # «with connection» confirma o deshace; el cierre explícito evita dejar el archivo tomado en Windows.
        connection = self._connect()
        try:
            with connection:
                return action(connection)
        finally:
            connection.close()

    def products(self, query: str = "", category: str = "", low_only: bool = False) -> list[dict]:
        """Productos con existencias físicas, apartadas en pedidos y disponibles para vender por el chat."""
        words = [word for word in re.split(r"\s+", query.strip().casefold()) if word][:6]
        sql = (f"SELECT sku, name, variant, unit, price_cop, stock, category, updated_at, {RESERVED_SQL} AS reserved, "
               f"{RESTOCK_SQL} AS restock FROM products WHERE business_id = ? AND store_id = ?")
        params: list[object] = [self.business_id, self.store_id]
        for word in words:
            sql += " AND lower(sku || ' ' || name || ' ' || variant || ' ' || search_terms) LIKE ?"
            params.append(f"%{word}%")
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY category, name, variant LIMIT ?"
        params.append(MAX_LISTED)
        rows = self._run(lambda connection: connection.execute(sql, params).fetchall())
        result = [{"sku": row["sku"], "nombre": row["name"], "variante": row["variant"], "unidad": row["unit"],
                   "precio_cop": row["price_cop"], "stock": row["stock"], "apartado": row["reserved"],
                   "disponible": max(row["stock"] - row["reserved"], 0), "categoria": row["category"],
                   "actualizado": row["updated_at"], "surtido": row["restock"]} for row in rows]
        return [item for item in result if item["disponible"] <= LOW_STOCK] if low_only else result

    def categories(self) -> list[str]:
        rows = self._run(lambda connection: connection.execute(
            "SELECT DISTINCT category FROM products WHERE business_id = ? AND store_id = ? ORDER BY category",
            (self.business_id, self.store_id)).fetchall())
        return [row[0] for row in rows]

    def update(self, sku: str, changes: dict, origin: str = PANEL) -> dict:
        """Corrige precio, existencias físicas y/o surtido; las existencias no pueden quedar por debajo de lo apartado.

        ``surtido`` es un día de la semana, una fecha AAAA-MM-DD, «descontinuado» o "" para borrarlo (``restock.py``).
        ``origin`` dice de dónde vino el cambio en el historial: «panel» o «asistente AS-…» (``stock_proposal.py``).
        """
        if not isinstance(changes, dict) or not changes or not set(changes) <= {"precio_cop", "stock", "surtido"}:
            raise InventoryError("INVALID_ARGUMENT", "Solo se pueden cambiar precio_cop, stock y surtido.")
        clean = {}
        plan = None
        if "surtido" in changes:
            try:
                plan = valid_plan(changes["surtido"])
            except ValueError as error:
                raise InventoryError("INVALID_ARGUMENT", str(error)) from None
        if "precio_cop" in changes:
            clean["price_cop"] = _int(changes["precio_cop"], "El precio", MAX_PRICE_COP)
        if "stock" in changes:
            clean["stock"] = _int(changes["stock"], "Las existencias", MAX_STOCK)

        def apply(connection: sqlite3.Connection) -> None:
            row = connection.execute(
                f"SELECT price_cop, stock, {RESERVED_SQL} AS reserved FROM products "
                "WHERE business_id = ? AND store_id = ? AND sku = ?", (self.business_id, self.store_id, sku)).fetchone()
            if row is None:
                raise InventoryError("NOT_FOUND", f"No existe el SKU {sku} en esta sede.")
            if "stock" in clean and clean["stock"] < row["reserved"]:
                raise InventoryError("STOCK_BELOW_RESERVED", f"Hay {row['reserved']} unidades apartadas en pedidos; "
                                                             "entrega o cancela esos pedidos antes de bajar tanto.")
            if plan is not None:
                self.set_restock(connection, sku, plan, origin=origin)
            for column, value in clean.items():
                if row[column] == value:
                    continue
                connection.execute(f"UPDATE products SET {column} = ?, updated_at = ? "
                                   "WHERE business_id = ? AND store_id = ? AND sku = ?",
                                   (value, _now(), self.business_id, self.store_id, sku))
                self._log(connection, sku, column, row[column], value, origin=origin)

        self._run(apply)
        return self._one(sku)

    def set_restock(self, connection: sqlite3.Connection, sku: str, plan: str, actor: str = ACTOR,
                    origin: str = PANEL, at: str | None = None) -> None:
        """Escribe el surtido ya validado dentro de la transacción de quien llama, con su evento."""
        before = connection.execute("SELECT plan FROM restocks WHERE business_id = ? AND store_id = ? AND sku = ?",
                                    (self.business_id, self.store_id, sku)).fetchone()
        if (before[0] if before else "") == plan:
            return
        if plan:
            connection.execute("INSERT OR REPLACE INTO restocks VALUES (?, ?, ?, ?, ?)",
                               (self.business_id, self.store_id, sku, plan, at or _now()))
        else:
            connection.execute("DELETE FROM restocks WHERE business_id = ? AND store_id = ? AND sku = ?",
                               (self.business_id, self.store_id, sku))
        self._log(connection, sku, "surtido", before[0] if before else None, plan or "sin dato", actor, origin, at)

    def receive_stock(self, connection: sqlite3.Connection, sku: str, quantity: int, actor: str, origin: str,
                      at: str | None = None) -> tuple[int, int]:
        """Suma mercancía recibida dentro de la transacción de quien llama y devuelve (antes, después).

        No confirma ni deshace: si la recepción falla en otra línea, quien llama deshace todo junto.
        """
        quantity = _int(quantity, "La cantidad recibida", MAX_STOCK)
        row = connection.execute("SELECT stock FROM products WHERE business_id = ? AND store_id = ? AND sku = ?",
                                 (self.business_id, self.store_id, sku)).fetchone()
        if row is None:
            raise InventoryError("NOT_FOUND", f"No existe el SKU {sku} en esta sede.")
        after = row["stock"] + quantity
        if quantity == 0 or after > MAX_STOCK:
            raise InventoryError("STOCK_LIMIT", f"Las existencias de {sku} quedarían en {after:,}; el máximo es "
                                                f"{MAX_STOCK:,} y se recibe al menos 1.".replace(",", "."))
        connection.execute("UPDATE products SET stock = ?, updated_at = ? WHERE business_id = ? AND store_id = ? "
                           "AND sku = ?", (after, at or _now(), self.business_id, self.store_id, sku))
        self._log(connection, sku, "stock", row["stock"], after, actor, origin, at)
        return row["stock"], after

    def add(self, product: dict) -> dict:
        """Agrega un producto ficticio nuevo; el SKU no puede repetirse en la sede."""
        if not isinstance(product, dict) or not set(product) <= {"sku", "nombre", "variante", "unidad", "precio_cop",
                                                                 "stock", "categoria", "terminos"}:
            raise InventoryError("INVALID_ARGUMENT", "Campos permitidos: sku, nombre, variante, unidad, precio_cop, "
                                                     "stock, categoria y terminos.")
        sku = product.get("sku")
        if not isinstance(sku, str) or not SKU_PATTERN.match(sku):
            raise InventoryError("INVALID_ARGUMENT", "El SKU va en mayúsculas, números y guiones (por ejemplo TUB-099).")
        unit = product.get("unidad")
        if unit not in UNITS:
            raise InventoryError("INVALID_ARGUMENT", f"La unidad debe ser una de: {', '.join(UNITS)}.")
        name, variant = _text(product.get("nombre"), "El nombre"), _text(product.get("variante"), "La variante")
        category = _text(product.get("categoria"), "La categoría")
        terms = _text(product.get("terminos") or f"{name} {variant}", "Los términos de búsqueda", MAX_TERMS_CHARS)
        price = _int(product.get("precio_cop"), "El precio", MAX_PRICE_COP)
        stock = _int(product.get("stock"), "Las existencias", MAX_STOCK)

        def insert(connection: sqlite3.Connection) -> None:
            try:
                connection.execute("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                   (self.business_id, self.store_id, sku, name, variant, unit, price, stock,
                                    terms.casefold(), _now(), category))
            except sqlite3.IntegrityError:
                raise InventoryError("DUPLICATE_SKU", f"Ya existe el SKU {sku}.") from None
            self._log(connection, sku, "alta", None, f"{price} COP, {stock} {unit}")

        self._run(insert)
        return self._one(sku)

    def _one(self, sku: str) -> dict:
        return next(item for item in self.products(sku) if item["sku"] == sku)

    def history(self, limit: int = 50, sku: str | None = None) -> list[dict]:
        """Movimientos más recientes primero; con ``sku``, solo los de ese producto."""
        limit = _int(limit, "El límite", MAX_LISTED)
        sql = ("SELECT sku, at, field, before, after, actor, origin FROM inventory_events "
               "WHERE business_id = ? AND store_id = ?")
        params: list[object] = [self.business_id, self.store_id]
        if sku is not None:
            sql += " AND sku = ?"
            params.append(sku)
        rows = self._run(lambda connection: connection.execute(sql + " ORDER BY rowid DESC LIMIT ?",
                                                               (*params, limit)).fetchall())
        names = {"price_cop": "precio", "stock": "existencias", "alta": "alta", "surtido": "surtido"}
        return [{"sku": row["sku"], "hora": local_text(row["at"]), "campo": names.get(row["field"], row["field"]),
                 "antes": row["before"], "despues": row["after"], "quien": row["actor"],
                 "origen": row["origin"] or PANEL} for row in rows]
