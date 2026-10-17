"""Lectura acotada del catálogo mock; el modelo no construye SQL."""

from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3
import unicodedata

from asistendero.seed import DEFAULT_DB_PATH, DEMO_BUSINESS_ID, DEMO_STORE_ID
from asistendero.search import ProductQuery


STOPWORDS = {
    "a", "al", "busco", "como", "con", "cual", "cuales", "cuanto", "cuantos",
    "cuesta", "cuestan", "de", "del", "disponible", "disponibles", "el", "en",
    "es", "esta", "estan", "este", "favor", "hay", "hola", "la", "las", "le",
    "les", "lo", "los", "mas", "me", "mi", "necesito", "o", "para", "por",
    "precio", "precios", "que", "quedan", "quiero", "recomienda", "recomiendas",
    "se", "si", "stock", "su", "te", "tienen", "tienes", "un", "una", "unas",
    "uno", "unos", "vale", "valen", "valor", "vende", "venden", "y",
}

SYNONYMS = {
    "tubos": "tubo",
    "tuberia": "tubo",
    "tuberias": "tubo",
    "cano": "tubo",
    "canos": "tubo",
    "tornillos": "tornillo",
    "tirafondos": "tirafondo",
    "chazo": "tornillo",
    "chazos": "tornillo",
    "goloso": "tornillo",
    "golosos": "tornillo",
    "bultos": "bulto",
    "saco": "bulto",
    "sacos": "bulto",
    "paca": "bulto",
    "cementos": "cemento",
    "pinturas": "pintura",
    "blanco": "blanca",
    "galones": "galon",
    "tarro": "galon",
    "cunete": "galon",
    "caneca": "galon",
    "pulgadas": "pulgada",
    "kilo": "kg",
    "kilos": "kg",
}


def tokens(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    # Normalizar expresiones de medidas habituales en ferretería.
    ascii_text = re.sub(r"\bmedia\s+pulgada\b", "1/2 pulgada", ascii_text)
    ascii_text = re.sub(r"\bmedio\s+pulgada\b", "1/2 pulgada", ascii_text)
    ascii_text = re.sub(r"\bde\s+media\b", "de 1/2 pulgada", ascii_text)
    ascii_text = re.sub(r"\btres\s+cuartos(?:\s+de\s+pulgada)?\b", "3/4 pulgada", ascii_text)
    ascii_text = re.sub(r"\btres\s+cuarto(?:\s+de\s+pulgada)?\b", "3/4 pulgada", ascii_text)
    ascii_text = re.sub(r"\bun\s+cuarto(?:\s+de\s+pulgada)?\b", "1/4 pulgada", ascii_text)
    ascii_text = re.sub(r"\bcuarto\s+de\s+pulgada\b", "1/4 pulgada", ascii_text)
    ascii_text = re.sub(r"\buna\s+pulgada\b", "1 pulgada", ascii_text)
    ascii_text = re.sub(r"\bdos\s+pulgadas?\b", "2 pulgada", ascii_text)
    ascii_text = re.sub(r"\bcincuenta\s+kilos?\b", "50 kg", ascii_text)
    ascii_text = re.sub(r"\b([0-9]+(?:/[0-9]+)?)\s*\"", r"\1 pulgada", ascii_text)
    ascii_text = re.sub(r"\b(\d+(?:/\d+)?)(kg|cm|mm)\b", r"\1 \2", ascii_text)

    raw_words = [
        word
        for word in re.findall(r"[a-z0-9]+(?:/[0-9]+)?", ascii_text)
        if word not in STOPWORDS
    ]
    result = set(raw_words)
    for word in raw_words:
        if word in SYNONYMS:
            result.add(SYNONYMS[word])
    return result


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


@dataclass(frozen=True)
class SearchResult:
    matches: tuple[Product, ...]
    nearby: tuple[Product, ...]


class MockCatalog:
    def __init__(
        self,
        path: Path = DEFAULT_DB_PATH,
        business_id: str = DEMO_BUSINESS_ID,
        store_id: str = DEMO_STORE_ID,
    ):
        self.path = path.resolve()
        self.business_id = business_id
        self.store_id = store_id

    def search(self, request: ProductQuery, limit: int = 3) -> SearchResult:
        if not self.path.is_file():
            raise FileNotFoundError("No existe la base mock. Ejecuta: python -m asistendero.seed")
        query_words = tokens(request.text)
        if not query_words:
            return SearchResult((), ())

        connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """SELECT sku, name, variant, unit, price_cop, stock, search_terms, updated_at
                   FROM products WHERE business_id = ? AND store_id = ?""",
                (self.business_id, self.store_id),
            ).fetchall()
        finally:
            connection.close()

        type_words = tokens(request.product or "")
        for field in (request.material, request.measure, request.presentation, request.color, request.brand):
            type_words -= tokens(field or "")
        # Cuando el modelo no nombra el tipo, la frase aún debe anclar la búsqueda.
        anchor_words = type_words or tokens(request.use or "") or query_words
        exact = []
        nearby = []
        for row in rows:
            name_words = tokens(f"{row['name']} {row['variant']} {row['unit']}")
            alias_words = tokens(row["search_terms"].replace("|", " "))
            product_words = name_words | alias_words
            if not (anchor_words & product_words):
                continue
            constraints = {
                "use": (request.use, product_words),
                "material": (request.material, product_words),
                "measure": (request.measure, tokens(row["variant"])),
                "presentation": (request.presentation, product_words),
                "color": (request.color, product_words),
                "brand": (request.brand, product_words),
            }
            missing = [
                field for field, (value, words) in constraints.items()
                if value and not tokens(value) <= words
            ]
            score = 3 * len(query_words & name_words) + len(query_words & alias_words)
            score += 4 * (sum(bool(value) for value, _ in constraints.values()) - len(missing))
            product = Product(**{key: row[key] for key in Product.__dataclass_fields__})
            entry = (score, product)
            if missing:
                # Mostrar otras presentaciones de la misma categoría solo si no hubo exactos.
                nearby.append(entry)
            else:
                exact.append(entry)

        sort_key = lambda item: (-item[0], item[1].stock == 0, item[1].sku)
        exact.sort(key=sort_key)
        nearby.sort(key=sort_key)
        return SearchResult(
            tuple(product for _, product in exact[:limit]),
            tuple(product for _, product in nearby[:2]) if not exact else (),
        )

    def get(self, sku: str) -> Product | None:
        if not self.path.is_file():
            raise FileNotFoundError("No existe la base mock. Ejecuta: python -m asistendero.seed")
        connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute(
                """SELECT sku, name, variant, unit, price_cop, stock, updated_at
                   FROM products WHERE business_id = ? AND store_id = ? AND sku = ?""",
                (self.business_id, self.store_id, sku),
            ).fetchone()
        finally:
            connection.close()
        return Product(**dict(row)) if row else None
