"""Crea un catálogo SQLite 100 % ficticio para las pruebas locales."""

from pathlib import Path
import sqlite3


DEMO_BUSINESS_ID = "demo-ferreteria"
DEMO_STORE_ID = "sede-unica"
DEFAULT_DB_PATH = Path(".local/mock_catalog.sqlite3")

# SKU, nombre, variante, unidad, precio COP, stock, términos de búsqueda.
PRODUCTS = [
    ("PVC-050", "Tubo PVC presión para agua", "1/2 pulgada", "metro", 8500, 12, "tubo|tuberia|pvc|agua|media pulgada"),
    ("PVC-075", "Tubo PVC presión para agua", "3/4 pulgada", "metro", 11500, 7, "tubo|tuberia|pvc|agua|tres cuartos"),
    ("TOR-025-1", "Tornillo para madera", "1/4 x 1 pulgada", "unidad", 350, 80, "tornillo|madera|tirafondo"),
    ("TOR-025-2", "Tornillo para madera", "1/4 x 2 pulgadas", "unidad", 520, 0, "tornillo|madera|tirafondo"),
    ("CEM-050", "Cemento gris", "bulto de 50 kg", "bulto", 39500, 9, "cemento|gris|mezcla|bulto"),
    ("PIN-BLA", "Pintura blanca vinilo", "galón", "galón", 56000, 4, "pintura|blanca|vinilo|galon"),
]


def create_mock_db(path: Path = DEFAULT_DB_PATH) -> Path:
    """Crea la base una sola vez; nunca sobreescribe cambios locales."""
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"La base ya existe: {path}. Bórrala manualmente para regenerar datos ficticios.")

    try:
        with sqlite3.connect(path) as connection:
            connection.execute(
                """CREATE TABLE products (
                    business_id TEXT NOT NULL,
                    store_id TEXT NOT NULL,
                    sku TEXT NOT NULL,
                    name TEXT NOT NULL,
                    variant TEXT NOT NULL,
                    unit TEXT NOT NULL,
                    price_cop INTEGER NOT NULL CHECK (price_cop >= 0),
                    stock INTEGER NOT NULL CHECK (stock >= 0),
                    search_terms TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (business_id, store_id, sku)
                )"""
            )
            connection.executemany(
                "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (DEMO_BUSINESS_ID, DEMO_STORE_ID, *product, "2026-10-15T00:00:00-05:00")
                    for product in PRODUCTS
                ],
            )
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def main() -> None:
    print(f"Catálogo ficticio creado en {create_mock_db()}")


if __name__ == "__main__":
    main()
