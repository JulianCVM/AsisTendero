"""Convierte las filas del inventario real de Ferretería Carluz en productos del catálogo; no toca la base.

El Excel trae ÍTEM, DESCRIPCIÓN, VALOR, CANTIDAD y TOTAL, sin categorías, unidades ni imágenes. Todo se deduce aquí
con reglas fijas y sin Grok: 2.041 filas por modelo costarían créditos en cada importación y una descripción mal
leída no se podría auditar. Los datos reales nunca entran al repositorio; este módulo solo sabe de su forma.

**El valor no es un precio de venta.** En las 134 descripciones que el libro repite en su hoja de facturas, 126 dan
exactamente costo × 1,19: es el costo de compra con IVA. El catálogo lo guarda en ``price_cop`` porque es la única
cifra que hay, y el agente de esta tienda lo presenta como valor de inventario (``STORE_NOTES`` en ``reply_text.py``).
"""

from dataclasses import dataclass
from fractions import Fraction
import re
import unicodedata

from asistendero.datos.carluz_vocabulario import ALIASES, CATEGORIES, DISPLAY_WORDS, OTHER_CATEGORY, TOOL_KEYS


CARLUZ_BUSINESS_ID = "ferreteria-carluz"
SKU_PREFIX = "CLZ"
SHEET = "INVENTARIO REAL"
# Un valor unitario así no es mercancía: PRIMA COMERCIAL, MUEBLES Y ENSERES o un lote de tornillos «x 1».
MAX_UNIT_VALUE_COP = 2_000_000
NON_MERCHANDISE = re.compile(r"\b(?:PRIMA COMERCIAL|MUEBLES Y ENSERES)\b")
# Dos filas con la misma descripción y valores tan distintos son el rollo y su venta por metro (malla, manguera).
ROLL_TO_METER_RATIO = 10
# Un TOTAL que no da cantidad × valor delata una cantidad mal leída.
RECONCILE_TOLERANCE_COP = 1

_MIXED = re.compile(r"^(\d+)\s*[A-Z]?\s*\+\s*(\d+)/(\d+)$")
_DECIMAL = re.compile(r"^\d+(?:[.,]\d+)?$")
_METER_TAIL = re.compile(r"\s+(?:X\s*)?(?:MT|MTS|MTR|MTRS|METRO)\s*$")
_UNIT_TAILS = (
    (re.compile(r"\s+(?:X\s*)?GAL(?:ON)?\s*$"), "galón"),
    (re.compile(r"\s+(?:X\s*)?ROLLO\s*$"), "rollo"),
    (re.compile(r"\s+(?:X\s*)?(?:KG|KILO|KILOS)\s*$"), "kilo"),
    (re.compile(r"\s+(?:X\s*)?(?:LB|LIBRA)\s*$"), "libra"),
    (re.compile(r"\s+(?:X\s*)?TRAMO\s*$"), "tramo"),
    (re.compile(r"\s+(?:X\s*)?PAR\s*$"), "par"),
    (re.compile(r"\s+(?:X\s*)?BULTO\s*$"), "bulto"),
    (re.compile(r"\s+(?:X\s*)?CAJA\s*$"), "caja"),
)
_BAG = re.compile(r"\bBULTO\b")
_INCH = r"\d+\s+\d+/\d+|\d+/\d+"
_LENGTH = r"MMX\d+|MM|CMTS|CMS|CM|MTRS|MTR|MTS|MT|METROS|KGS|KG|GR|LB|WATTS|W|AMP|VDC|V|LT|ML"
_MEASURE = re.compile(
    rf"(?:(?<![\w/])(?:{_INCH})\"?(?:\s*[X*]\s*(?:{_INCH}|\d+)\"?)?)"  # 1 1/2, 3/8", 1/4 X 2
    rf"|(?<![\w/])\d+(?:[.,]\d+)?\s*[X*]\s*\d+(?:[.,]\d+)?(?:\s*(?:{_LENGTH})\b)?"  # 2*12, 60X48
    rf"|(?<![\w/])\d+(?:[.,]\d+)?\s*(?:{_LENGTH})(?:X\d+)?(?![A-Z])"  # 9MM, 50KG, 4MMX35
    r"|(?<![\w/])\d+\""  # 4"
    r"|#\s*\d+"  # #16
    r"|\bCAL(?:IBRE)?[.\s]*\d+\b"  # CALIBRE 12
    r"|\bC[.,]\d+\b"  # C.22
    r"|\bT\d\b"  # T1, T2: la calidad del vinilo
)
_LEADING_NUMBER = re.compile(r"^(\d+)\s+(?=[A-ZÑÁÉÍÓÚ])")
_WORD = re.compile(r"[A-ZÑÁÉÍÓÚÜ]{2,}")
_PAINT_TYPE = re.compile(r"\bT([123])\b")
_TIMES = re.compile(r"\s*\*\s*")


@dataclass(frozen=True)
class SourceRow:
    """Una fila de la hoja, sin interpretar más que sus números."""
    item: int
    description: str
    value: float
    quantity: float
    line_total: float | None


@dataclass(frozen=True)
class CatalogItem:
    sku: str
    name: str
    variant: str
    unit: str
    price_cop: int
    stock: int
    search_terms: str
    category: str
    items: tuple[int, ...]


def parse_quantity(raw: str) -> float | None:
    """«85», «2,95», «1+3/4» o «1G+3/4» (galones y cuartos, como se anotan a mano); None si no se entiende."""
    text = raw.strip().upper()
    if _DECIMAL.match(text):
        return float(text.replace(",", "."))
    mixed = _MIXED.match(text)
    if mixed and int(mixed[3]):
        return float(int(mixed[1]) + Fraction(int(mixed[2]), int(mixed[3])))
    return None


def clean_description(raw: str) -> str:
    return " ".join(raw.upper().split())


def plain(text: str) -> str:
    """Mayúsculas sin tildes: las claves de los vocabularios se escriben así."""
    decomposed = unicodedata.normalize("NFKD", text.upper().replace("Ñ", "\0"))
    return "".join(char for char in decomposed if not unicodedata.combining(char)).replace("\0", "Ñ")


def is_merchandise(row: SourceRow) -> bool:
    return not NON_MERCHANDISE.search(row.description) and row.value < MAX_UNIT_VALUE_COP


def sale_unit(description: str) -> tuple[str, str]:
    """(unidad de venta, descripción sin ella). «X 3 METROS» es una medida, no una venta por metro."""
    if _METER_TAIL.search(description):
        return "metro", _METER_TAIL.sub("", description)
    for pattern, unit in _UNIT_TAILS:
        if pattern.search(description):
            return unit, pattern.sub("", description)
    return ("bulto", description) if _BAG.search(description) else ("unidad", description)


def split_description(description: str) -> tuple[str, str, str]:
    """(nombre, variante, unidad): las medidas pasan a la variante para que el agente pregunte cuál, no elija."""
    unit, text = sale_unit(description)
    found = [" ".join(match.group().split()) for match in _MEASURE.finditer(text)]
    rest = _MEASURE.sub(" ", text).strip()
    leading = _LEADING_NUMBER.match(rest)
    if leading and text.startswith(leading[1]):
        # «2 BIS COMUN» y «3 PASADOR ALEMAN»: en esta hoja un número al frente son pulgadas.
        found.insert(0, f'{leading[1]}"')
        rest = rest[leading.end():]
    words = [DISPLAY_WORDS.get(plain(word), word) for word in rest.split()]
    while words and plain(words[-1]) in {"X", "DE", "POR", "CON", "EN", "Y", "PARA"}:
        words.pop()
    while words and plain(words[0]) in {"X", "DE", "POR"}:
        words.pop(0)
    # «BOMBILLO LED COLOR, 9VDC»: al sacar la medida queda colgando la coma.
    name = " ".join(words).rstrip(" ,;:-").capitalize() or description.capitalize()
    # «2*12» se escribe «2x12», que es como lo dice el cliente y como lo compara ``measures``.
    return name, _TIMES.sub("x", " ".join(found)).lower(), unit


def category_of(description: str) -> str:
    """La categoría por la primera palabra, salvo las llaves: «llave boca fija» es herramienta y no plomería."""
    words = _WORD.findall(plain(description))
    if not words:
        return OTHER_CATEGORY
    if words[0] == "LLAVE" and TOOL_KEYS & set(words):
        return "Herramientas"
    for category, keys in CATEGORIES.items():
        if words[0] in keys:
            return category
    return OTHER_CATEGORY


def search_terms(description: str) -> str:
    """Los términos con que un cliente pediría el producto: las abreviaturas de la hoja no se dicen en el mostrador."""
    words = _WORD.findall(plain(description))
    found = {alias for word in words for alias in ALIASES.get(word, ())}
    # «T1» es como lo escribe la hoja; en el mostrador se pide «tipo 1».
    found |= {f"tipo {kind}" for kind in _PAINT_TYPE.findall(plain(description))}
    return "|".join(sorted(found))


def _merged(rows: list[SourceRow]) -> list[tuple[SourceRow, str | None, tuple[int, ...]]]:
    """Une lo que el Excel repite. Con valores distintos queda el mayor, para no ofrecer por debajo de ningún lote.

    Vuelve (fila, unidad forzada, ítems que la forman): el rollo y su venta por metro siguen siendo dos productos.
    """
    groups: dict[tuple[str, str, str], list[SourceRow]] = {}
    for row in rows:
        groups.setdefault(split_description(row.description), []).append(row)
    merged: list[tuple[SourceRow, str | None, tuple[int, ...]]] = []
    for group in groups.values():
        cheapest, dearest = min(row.value for row in group), max(row.value for row in group)
        if len(group) == 2 and dearest >= ROLL_TO_METER_RATIO * cheapest:
            merged.extend((row, "rollo" if row.value == dearest else "metro", (row.item,)) for row in group)
            continue
        first = min(group, key=lambda row: row.item)
        total = sum(row.quantity for row in group)
        merged.append((SourceRow(first.item, first.description, dearest, total, None), None,
                       tuple(sorted(row.item for row in group))))
    return merged


def build_catalog(rows: list[SourceRow]) -> tuple[list[CatalogItem], list[SourceRow]]:
    """(productos, filas excluidas). Las existencias van en unidades enteras porque el agente cotiza enteras."""
    excluded = [row for row in rows if not is_merchandise(row)]
    products = []
    for row, forced_unit, items in _merged([row for row in rows if is_merchandise(row)]):
        name, variant, unit = split_description(row.description)
        products.append(CatalogItem(
            sku=f"{SKU_PREFIX}-{row.item:04d}",
            name=name,
            variant=variant,
            unit=forced_unit or unit,
            price_cop=round(row.value),
            stock=int(row.quantity),
            search_terms=search_terms(row.description),
            category=category_of(row.description),
            items=items,
        ))
    return products, excluded
