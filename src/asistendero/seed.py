"""Crea un catálogo SQLite 100 % ficticio para las pruebas locales."""

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
    "contacto": {"texto": "Para pedidos, reservas o reclamos atiende el personal del mostrador en el horario de la tienda."},
}


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
    return path


def main() -> None:
    print(f"Catálogo ficticio de {len(PRODUCTS)} variantes creado en {create_mock_db()}")


if __name__ == "__main__":
    main()
