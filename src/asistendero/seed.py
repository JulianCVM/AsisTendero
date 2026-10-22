"""Crea un catálogo SQLite 100 % ficticio para las pruebas locales."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3

from asistendero.catalog_data import build_products


DEMO_BUSINESS_ID = "demo-ferreteria"
DEMO_STORE_ID = "sede-unica"
# Ruta nueva para el catálogo ampliado de S3: la base de seis productos de S2 (.local/mock_catalog.sqlite3)
# se conserva para poder repetir la evidencia de ese corte con los mismos datos.
DEFAULT_DB_PATH = Path(".local/mock_catalog_s3.sqlite3")
UPDATED_AT = "2026-10-15T00:00:00-05:00"

_ROWS = build_products()
# SKU, nombre, variante, unidad, precio COP, stock, términos de búsqueda.
PRODUCTS = [row[:7] for row in _ROWS]
CATEGORIES = {row[0]: row[7] for row in _ROWS}

# Información de la tienda de demostración que lee consultar_info_tienda. Todo es ficticio.
STORE_INFO = {
    "nombre": {"texto": "Ferretería La Esquina (tienda de demostración)"},
    "horario": {
        "zona_horaria": "America/Bogota",
        "dias": {
            "lunes": ["07:00", "18:00"], "martes": ["07:00", "18:00"], "miercoles": ["07:00", "18:00"],
            "jueves": ["07:00", "18:00"], "viernes": ["07:00", "18:00"], "sabado": ["07:00", "14:00"],
            "domingo": None,
        },
        "festivos": "Cerrado los festivos.",
    },
    "ubicacion": {"texto": "Calle 10 # 5-23, barrio Centro (dirección ficticia de demostración)."},
    "medios_pago": {"texto": "En el mostrador se recibe efectivo, transferencia y tarjeta débito o crédito. "
                             "Este asistente no cobra ni recibe pagos."},
    "domicilios": {"texto": "Domicilio en el barrio por $5.000 COP para compras desde $50.000 COP, "
                            "coordinado por el mostrador. Este asistente no programa entregas."},
    "garantias": {"texto": "Cambios con factura dentro de los 30 días siguientes, con el producto sin uso y en su "
                           "empaque. Los materiales cortados a la medida (tubo, cable, cadena) no tienen cambio."},
    "contacto": {"texto": "Reclamos, domicilios y pedidos especiales los atiende el personal del mostrador en el horario "
                          "de la tienda."},
    "pedidos": {"texto": "Por este chat se registran pedidos para recoger en la tienda. El pedido se aparta 5 minutos "
                         "mientras lo confirmas; ya confirmado, se guarda hasta 2 horas después de la hora de recogida "
                         "acordada (o 24 horas si no acuerdas hora). El pago se hace en el mostrador al recoger: este "
                         "chat no cobra, no recibe pagos ni fía."},
}
# Temas agregados después de crear una base: upgrade_db los escribe en bases existentes.
UPGRADED_TOPICS = ("contacto", "pedidos")

# Pedidos para recoger en tienda (orders.py). Lo apartado se descuenta de las existencias que ve el agente.
ORDER_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL,
    store_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pendiente', 'confirmado', 'entregado', 'cancelado', 'vencido')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    hold_until TEXT NOT NULL,
    pickup_at TEXT,
    note TEXT,
    total_cop INTEGER NOT NULL CHECK (total_cop >= 0)
);
CREATE TABLE IF NOT EXISTS order_lines (
    order_id TEXT NOT NULL REFERENCES orders(id),
    sku TEXT NOT NULL,
    name TEXT NOT NULL,
    variant TEXT NOT NULL,
    unit TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_cop INTEGER NOT NULL,
    subtotal_cop INTEGER NOT NULL,
    PRIMARY KEY (order_id, sku)
);
CREATE TABLE IF NOT EXISTS order_events (
    order_id TEXT NOT NULL REFERENCES orders(id),
    at TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS orders_by_status ON orders (business_id, store_id, status);
CREATE INDEX IF NOT EXISTS orders_by_session ON orders (session_id);
"""


def upgrade_db(path: Path = DEFAULT_DB_PATH) -> Path:
    """Agrega a una base existente las tablas de pedidos y los temas nuevos de la tienda; es idempotente."""
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError("No existe la base mock. Ejecuta: python -m asistendero.seed")
    connection = sqlite3.connect(path)
    try:
        with connection:
            connection.executescript(ORDER_SCHEMA)
            connection.executemany(
                "INSERT OR REPLACE INTO store_info VALUES (?, ?, ?, ?)",
                [(DEMO_BUSINESS_ID, DEMO_STORE_ID, topic, json.dumps(STORE_INFO[topic], ensure_ascii=False))
                 for topic in UPGRADED_TOPICS],
            )
    finally:
        connection.close()
    return path


def create_mock_db(path: Path = DEFAULT_DB_PATH) -> Path:
    """Crea la base una sola vez; nunca sobreescribe cambios locales."""
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"La base ya existe: {path}. Bórrala manualmente para regenerar datos ficticios.")

    try:
        # «with connect()» solo confirma: closing() suelta el archivo, que en Windows quedaba tomado y hacía
        # fallar el borrado de una base a medio crear.
        with closing(sqlite3.connect(path)) as connection, connection:
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
                    category TEXT NOT NULL,
                    PRIMARY KEY (business_id, store_id, sku)
                )"""
            )
            connection.execute(
                """CREATE TABLE store_info (
                    business_id TEXT NOT NULL,
                    store_id TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    content TEXT NOT NULL,
                    PRIMARY KEY (business_id, store_id, topic)
                )"""
            )
            connection.executemany(
                "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (DEMO_BUSINESS_ID, DEMO_STORE_ID, *product, UPDATED_AT, CATEGORIES[product[0]])
                    for product in PRODUCTS
                ],
            )
            connection.executemany(
                "INSERT INTO store_info VALUES (?, ?, ?, ?)",
                [
                    (DEMO_BUSINESS_ID, DEMO_STORE_ID, topic, json.dumps(content, ensure_ascii=False))
                    for topic, content in STORE_INFO.items()
                ],
            )
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return upgrade_db(path)


def main() -> None:
    print(f"Catálogo ficticio de {len(PRODUCTS)} variantes creado en {create_mock_db()}")


if __name__ == "__main__":
    main()
