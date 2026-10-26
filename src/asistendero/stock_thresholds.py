"""Umbrales de existencias bajas del tendero y la base que comparte con las categorías (``catalog_admin.py``).

El umbral dice desde cuántas unidades disponibles un producto pide surtido: uno global y, si el tendero quiere, uno
propio por SKU. Cada cambio de umbral o de categoría queda en ``catalog_admin_events`` con la hora UTC, el antes, el
después y el actor («tendero» en el prototipo). Todo es ficticio y queda filtrado por negocio y sede.
"""

from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from asistendero.seed import DEFAULT_DB_PATH, DEMO_BUSINESS_ID, DEMO_STORE_ID, upgrade_db
from asistendero.validation import SKU_PATTERN


# Igual a inventory.LOW_STOCK, pero sin importarlo: inventory.py es quien pinta las existencias y es natural que
# llegue a leer estos umbrales; el import cruzado haría un ciclo. tests/test_catalog_admin.py comprueba que coincidan.
DEFAULT_LOW_STOCK = 5
MAX_THRESHOLD = 100_000
MAX_HISTORY = 200
ACTOR = "tendero"
SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    business_id TEXT NOT NULL, store_id TEXT NOT NULL, name TEXT NOT NULL, position INTEGER NOT NULL,
    PRIMARY KEY (business_id, store_id, name)
);
CREATE TABLE IF NOT EXISTS stock_alert_settings (
    business_id TEXT NOT NULL, store_id TEXT NOT NULL, low_stock INTEGER NOT NULL CHECK (low_stock >= 0),
    PRIMARY KEY (business_id, store_id)
);
CREATE TABLE IF NOT EXISTS stock_thresholds (
    business_id TEXT NOT NULL, store_id TEXT NOT NULL, sku TEXT NOT NULL, minimum INTEGER NOT NULL CHECK (minimum >= 0),
    PRIMARY KEY (business_id, store_id, sku)
);
CREATE TABLE IF NOT EXISTS catalog_admin_events (
    business_id TEXT NOT NULL, store_id TEXT NOT NULL, at TEXT NOT NULL, action TEXT NOT NULL,
    before TEXT, after TEXT, actor TEXT NOT NULL
);
"""


class CatalogError(Exception):
    """Cambio rechazado con un código estable y un mensaje que dice qué corregir."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _threshold(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= MAX_THRESHOLD:
        raise CatalogError("INVALID_ARGUMENT", "El mínimo debe ser un entero de 0 a 100.000.")
    return value


class StockThresholds:
    """Conexión, bitácora y umbrales; ``CatalogAdmin`` le suma las categorías."""

    def __init__(self, path: Path = DEFAULT_DB_PATH, business_id: str = DEMO_BUSINESS_ID,
                 store_id: str = DEMO_STORE_ID):
        self.path = upgrade_db(path)
        self.business_id = business_id
        self.store_id = store_id
        self._run(lambda connection: connection.executescript(SCHEMA))

    def _run(self, action):
        # «with connection» confirma o deshace todo junto; el cierre explícito suelta el archivo en Windows.
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                return action(connection)
        finally:
            connection.close()

    @property
    def _scope(self) -> tuple[str, str]:
        return self.business_id, self.store_id

    def _log(self, connection: sqlite3.Connection, action: str, before: object, after: object) -> None:
        connection.execute("INSERT INTO catalog_admin_events VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (*self._scope, _now(), action, None if before is None else str(before),
                            None if after is None else str(after), ACTOR))

    # Umbrales de existencias bajas

    def _global(self, connection: sqlite3.Connection) -> int:
        row = connection.execute("SELECT low_stock FROM stock_alert_settings WHERE business_id = ? AND store_id = ?",
                                 self._scope).fetchone()
        return row[0] if row else DEFAULT_LOW_STOCK

    def _known_sku(self, connection: sqlite3.Connection, sku: object) -> str:
        if not isinstance(sku, str) or not SKU_PATTERN.match(sku):
            raise CatalogError("INVALID_ARGUMENT", "El SKU va en mayúsculas, números y guiones (por ejemplo TUB-099).")
        if not connection.execute("SELECT 1 FROM products WHERE business_id = ? AND store_id = ? AND sku = ?",
                                  (*self._scope, sku)).fetchone():
            raise CatalogError("SKU_NOT_FOUND", f"No existe el SKU {sku} en esta sede.")
        return sku

    def thresholds(self) -> dict:
        """{"global": n, "productos": {sku: n}}; solo aparecen los SKU con mínimo propio."""
        def read(connection: sqlite3.Connection) -> dict:
            own = connection.execute("SELECT sku, minimum FROM stock_thresholds WHERE business_id = ? AND store_id = ? "
                                     "ORDER BY sku", self._scope).fetchall()
            return {"global": self._global(connection), "productos": {row["sku"]: row["minimum"] for row in own}}
        return self._run(read)

    def set_global(self, n: int) -> dict:
        value = _threshold(n)

        def apply(connection: sqlite3.Connection) -> None:
            before = self._global(connection)
            connection.execute("INSERT OR REPLACE INTO stock_alert_settings VALUES (?, ?, ?)", (*self._scope, value))
            if before != value:
                self._log(connection, "umbral_global", before, value)

        self._run(apply)
        return self.thresholds()

    def set_threshold(self, sku: str, n: int | None) -> dict:
        """Mínimo propio de un producto; ``None`` lo quita y el producto vuelve al global."""
        value = None if n is None else _threshold(n)

        def apply(connection: sqlite3.Connection) -> None:
            known = self._known_sku(connection, sku)
            row = connection.execute("SELECT minimum FROM stock_thresholds WHERE business_id = ? AND store_id = ? "
                                     "AND sku = ?", (*self._scope, known)).fetchone()
            before = row[0] if row else None
            if value is None:
                connection.execute("DELETE FROM stock_thresholds WHERE business_id = ? AND store_id = ? AND sku = ?",
                                   (*self._scope, known))
            else:
                connection.execute("INSERT OR REPLACE INTO stock_thresholds VALUES (?, ?, ?, ?)",
                                   (*self._scope, known, value))
            if before != value:
                self._log(connection, "umbral_producto",
                          f"{known}: {'global' if before is None else before}",
                          f"{known}: {'global' if value is None else value}")

        self._run(apply)
        return self.thresholds()

    def threshold_for(self, sku: str) -> int:
        """Mínimo que rige para el producto: el propio si lo tiene, si no el global."""
        def read(connection: sqlite3.Connection) -> int:
            known = self._known_sku(connection, sku)
            row = connection.execute("SELECT minimum FROM stock_thresholds WHERE business_id = ? AND store_id = ? "
                                     "AND sku = ?", (*self._scope, known)).fetchone()
            return row[0] if row else self._global(connection)
        return self._run(read)

    def history(self, limit: int = 50) -> list[dict]:
        limit = max(1, min(int(limit), MAX_HISTORY))
        rows = self._run(lambda connection: connection.execute(
            "SELECT at, action, before, after, actor FROM catalog_admin_events WHERE business_id = ? AND store_id = ? "
            "ORDER BY rowid DESC LIMIT ?", (*self._scope, limit)).fetchall())
        return [{"hora": row["at"], "accion": row["action"], "antes": row["before"], "despues": row["after"],
                 "quien": row["actor"]} for row in rows]
