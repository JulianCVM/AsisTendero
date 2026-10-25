"""Medidas de ferretería normalizadas para distinguir variantes sin confundirlas con cantidades.

«1/4 x 2 pulgadas» da los átomos ``1/4x2`` y ``2in``; «cemento de 50 kg», ``50kg``; «2 bisagras de 3 1/2"»,
``2`` (número suelto) y ``3-1/2in``. Con seis productos bastaba comparar palabras, pero con cientos de variantes
parecidas («2 tornillos de 1/4 x 1» frente a la variante «1/4 x 2») un número suelto no basta para elegir.
"""

import re
import unicodedata


UNITS = {
    "pulgada": "in", "pulgadas": "in", "pulg": "in",
    "kg": "kg", "kilo": "kg", "kilos": "kg", "kilogramo": "kg", "kilogramos": "kg",
    "g": "g", "gr": "g", "gramos": "g",
    "m": "m", "mt": "m", "mts": "m", "metro": "m", "metros": "m",
    "cm": "cm", "mm": "mm",
    "w": "w", "vatios": "w", "watts": "w",
    "v": "v", "voltios": "v",
    "a": "a", "amperios": "a", "amp": "a",
    "ml": "ml", "l": "l", "litro": "l", "litros": "l",
    "oz": "oz", "onzas": "oz", "awg": "awg", "lb": "lb", "libra": "lb", "libras": "lb",
    "galon": "gal", "galones": "gal",
}
# Unidades que también son de venta («2 metros de tubo», «2 galones de pintura»): una cifra con ellas no
# contradice la medida de una variante.
SALE_UNITS = {"m", "gal", "lb"}
_UNIT = "|".join(sorted(UNITS, key=len, reverse=True))
_NUMBER = r"#?\d+(?:\s+\d+/\d+|/\d+|[.,]\d+)?"
_X = re.compile(rf"({_NUMBER})\s*(?:{_UNIT})?\s*[x×]\s*({_NUMBER})(?:\s*({_UNIT})\b)?")
_WITH_UNIT = re.compile(rf"({_NUMBER})\s*({_UNIT})\b")
_BARE = re.compile(rf"(?<![\w/#.,])({_NUMBER})(?![\w/])")


def canonical_text(value: str) -> str:
    """Minúsculas sin tildes y con las formas habladas de medida reescritas («media pulgada» → 1/2 pulgada)."""
    normalized = unicodedata.normalize("NFKD", value.casefold())
    text = "".join(char for char in normalized if not unicodedata.combining(char))
    for pattern, replacement in (
        (r"\bmedi[ao]\s+pulgada\b", "1/2 pulgada"),
        (r"\bde\s+media\b", "de 1/2 pulgada"),
        (r"\btres\s+cuartos?(?:\s+de\s+pulgada)?\b", "3/4 pulgada"),
        (r"\bun\s+cuarto(?:\s+de\s+pulgada)?\b", "1/4 pulgada"),
        (r"\bcuarto\s+de\s+pulgada\b", "1/4 pulgada"),
        (r"\buna\s+pulgada\b", "1 pulgada"),
        (r"\bdos\s+pulgadas?\b", "2 pulgada"),
        (r"\bcincuenta\s+kilos?\b", "50 kg"),
        (r"\b([0-9]+(?:/[0-9]+)?)\s*\"", r"\1 pulgada"),
        (r"\b(\d+(?:/\d+)?)(kg|cm|mm)\b", r"\1 \2"),
    ):
        text = re.sub(pattern, replacement, text)
    return text


def _number(raw: str) -> str:
    return re.sub(r"\s+", "-", raw.strip()).replace(",", ".")


def measures(value: str) -> set[str]:
    """Átomos de medida del texto: ``AxB``, número con unidad (``50kg``) o número suelto (``2``)."""
    text = canonical_text(value)
    atoms: set[str] = set()
    for match in _X.finditer(text):
        first, second, unit = match.groups()
        atoms.add(f"{_number(first)}x{_number(second)}")
        if unit:
            atoms.add(f"{_number(second)}{UNITS[unit]}")
    text = _X.sub(" ", text)
    for match in _WITH_UNIT.finditer(text):
        atoms.add(f"{_number(match.group(1))}{UNITS[match.group(2)]}")
    text = _WITH_UNIT.sub(" ", text)
    atoms |= {_number(match.group(1)) for match in _BARE.finditer(text)}
    return atoms


def split_atom(atom: str) -> tuple[str, str | None]:
    """(número, unidad) de un átomo con unidad o suelto; las expresiones ``AxB`` vuelven sin unidad."""
    if "x" in atom.lstrip("#"):
        return atom, None
    match = re.fullmatch(r"(#?[\d./-]+)([a-z]+)?", atom)
    return (match.group(1), match.group(2)) if match else (atom, None)


def atom_support(atom: str, said: set[str]) -> int:
    """2 si el mensaje dice la misma medida; 1 si solo dice el número sin unidad; 0 si no la dice."""
    if atom in said:
        return 2
    number, unit = split_atom(atom)
    if unit is not None and number in said:
        return 1
    return 0


def contradicts(variant_atoms: set[str], said: set[str]) -> bool:
    """El mensaje da otra cifra en una unidad que la variante también usa (1 pulgada frente a 1/2 pulgada)."""
    by_unit: dict[str, set[str]] = {}
    for atom in variant_atoms:
        number, unit = split_atom(atom)
        if unit and unit not in SALE_UNITS:
            by_unit.setdefault(unit, set()).add(number)
    for atom in said:
        number, unit = split_atom(atom)
        if unit in by_unit and number not in by_unit[unit]:
            return True
    return False
