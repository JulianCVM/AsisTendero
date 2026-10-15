"""Lectura acotada del catálogo mock; el modelo no construye SQL."""

from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3
import unicodedata

from asistendero.seed import DEFAULT_DB_PATH, DEMO_BUSINESS_ID, DEMO_STORE_ID


STOPWORDS = {"a", "de", "el", "en", "la", "las", "lo", "los", "me", "necesito", "para", "por", "que", "quiero", "un", "una", "y"}


def tokens(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    return {word for word in re.findall(r"[a-z0-9]+(?:/[0-9]+)?", ascii_text) if word not in STOPWORDS}


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    variant: str
    unit: str
    price_cop: int
    stock: int
    updated_at: str

    def facts_for_model(self) -> dict[str, str]:
        # Grok identifica una variante; precio y stock solo salen del renderizador.
        return {"sku": self.sku, "name": self.name, "variant": self.variant, "unit": self.unit}


class MockCatalog:
    def __init__(self, path: Path = DEFAULT_DB_PATH):
        self.path = path.resolve()

    def search(self, query: str, limit: int = 5) -> list[Product]:
        if not self.path.is_file():
            raise FileNotFoundError("No existe la base mock. Ejecuta: python -m asistendero.seed")
        query_words = tokens(query)
        if not query_words:
            return []

        connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """SELECT sku, name, variant, unit, price_cop, stock, search_terms, updated_at
                   FROM products WHERE business_id = ? AND store_id = ?""",
                (DEMO_BUSINESS_ID, DEMO_STORE_ID),
            ).fetchall()
        finally:
            connection.close()

        ranked = []
        for row in rows:
            name_words = tokens(f"{row['name']} {row['variant']} {row['sku']}")
            alias_words = tokens(row["search_terms"].replace("|", " "))
            score = 2 * len(query_words & name_words) + len(query_words & alias_words)
            if score:
                ranked.append((score, Product(**{key: row[key] for key in Product.__dataclass_fields__})))
        ranked.sort(key=lambda item: (-item[0], item[1].sku))
        return [product for _, product in ranked[:limit]]

    def get(self, sku: str) -> Product | None:
        if not self.path.is_file():
            raise FileNotFoundError("No existe la base mock. Ejecuta: python -m asistendero.seed")
        connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute(
                """SELECT sku, name, variant, unit, price_cop, stock, updated_at
                   FROM products WHERE business_id = ? AND store_id = ? AND sku = ?""",
                (DEMO_BUSINESS_ID, DEMO_STORE_ID, sku),
            ).fetchone()
        finally:
            connection.close()
        return Product(**dict(row)) if row else None
