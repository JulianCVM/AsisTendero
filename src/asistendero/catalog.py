"""Lectura acotada del catálogo mock; el modelo no construye SQL."""

from dataclasses import dataclass
import json
from pathlib import Path
import re
import sqlite3

from asistendero.measures import canonical_text, measures
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
    "chazos": "chazo",
    "tacos": "chazo",
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
    # Unidades de venta en plural, para que «2 metros» puntúe contra los productos que se venden por metro.
    "metros": "metro",
    "unidades": "unidad",
    "libras": "libra",
    "rollos": "rollo",
    "pares": "par",
    "pliegos": "pliego",
    "bolsas": "bolsa",
    "cajas": "caja",
}


def tokens(value: str, synonyms: bool = True) -> set[str]:
    """Palabras normalizadas con su singular; ``synonyms=False`` sirve para comparar variantes entre sí."""
    ascii_text = canonical_text(value)
    raw_words = [
        word
        for word in re.findall(r"[a-z0-9]+(?:/[0-9]+)?", ascii_text)
        if word not in STOPWORDS
    ]
    result = set(raw_words)
    for word in raw_words:
        # Plural regular («bisagras», «galones»): con cientos de productos no cabe un sinónimo por palabra.
        if len(word) >= 5 and word.endswith("s") and not word[-2].isdigit():
            result.add(word[:-1])
            if word.endswith("es") and len(word) >= 6:
                result.add(word[:-2])
        if synonyms and word in SYNONYMS:
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
        query_measures = measures(request.text)
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
            # La misma medida exacta («1/4x2», «50kg») pesa más que palabras sueltas: entre 16 pernos, sube
            # el que el cliente pidió al top de matches.
            score += 5 * len(query_measures & measures(f"{row['name']} {row['variant']}"))
            product = Product(**{key: row[key] for key in Product.__dataclass_fields__})
            entry = (score, product)
            if missing:
                # Mostrar otras presentaciones de la misma categoría solo si no hubo exactos. Una cercana que
                # cambia el uso o el material (conduit eléctrico frente a tubo para agua) va detrás de una que
                # solo cambia la medida, aunque coincida en la medida.
                nearby.append((score - 20 * len({"use", "material"} & set(missing)), product))
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

    def _rows(self, sql: str, params: tuple) -> list[sqlite3.Row]:
        """Consulta parametrizada en solo lectura, siempre filtrada por el negocio y la sede del servidor."""
        if not self.path.is_file():
            raise FileNotFoundError("No existe la base mock. Ejecuta: python -m asistendero.seed")
        connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            return connection.execute(sql, (self.business_id, self.store_id, *params)).fetchall()
        finally:
            connection.close()

    def categories(self) -> list[dict]:
        rows = self._rows(
            """SELECT category, COUNT(*) AS variants, SUM(stock > 0) AS available FROM products
               WHERE business_id = ? AND store_id = ? GROUP BY category ORDER BY category""",
            (),
        )
        return [{"categoria": row["category"], "variantes": row["variants"], "con_existencias": row["available"]}
                for row in rows]

    def category_overview(self, category: str) -> list[dict]:
        """Productos de una categoría con cuántas variantes tienen; sin precios, que salen de la búsqueda."""
        rows = self._rows(
            """SELECT name, COUNT(*) AS variants, SUM(stock > 0) AS available FROM products
               WHERE business_id = ? AND store_id = ? AND category = ? GROUP BY name ORDER BY name""",
            (category,),
        )
        return [{"nombre": row["name"], "variantes": row["variants"], "con_existencias": row["available"]}
                for row in rows]

    def store_info(self, topic: str) -> dict | None:
        rows = self._rows(
            "SELECT content FROM store_info WHERE business_id = ? AND store_id = ? AND topic = ?", (topic,),
        )
        return json.loads(rows[0]["content"]) if rows else None
