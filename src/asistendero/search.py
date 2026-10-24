"""Contrato tipado entre la interpretación del agente y la búsqueda del servidor."""

from dataclasses import dataclass, replace
import re
from asistendero.measures import measures

SALE_UNIT_NAME = r"(metros?|bultos?|galon(?:es)?|unidad(?:es)?|libras?|rollos?|pares|par|pliegos?|bolsas?|cajas?)"
NUMBER_WORDS = {
    "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "quince": 15, "veinte": 20,
}
# «3 metros de tubo» es cuánto lleva, no una medida. En la conversación del visor del 23-10, «dame del primero 3
# metros» llevó a Grok a buscar «tubo PVC 3 metros» y se eligió el tubo sanitario de 3 pulgadas. «de 3 metros» o
# «x 15 m» sí describen el producto (un flexómetro, una manguera) y se dejan.
SAID_QUANTITY = re.compile(r"(?<!\bde )(?<!\bx )\b(?:\d+|" + "|".join(NUMBER_WORDS) + r")\s+" + SALE_UNIT_NAME + r"\b",
                           re.IGNORECASE)
PRESENTATION_UNIT = re.compile(r"(?:galon(?:es)?|galón|cajas?|bolsas?|pliegos?|rollos?)$", re.IGNORECASE)


def without_quantities(text: str) -> str:
    """El texto sin las cantidades con unidad de venta que el cliente pidió («3 metros de tubo» → «de tubo»).

    De «2 galones» queda «galones»: en la pintura el galón también es la presentación (galón frente a cuñete).
    """
    def drop(match: re.Match) -> str:
        unit = match.group(1)
        return f" {unit} " if PRESENTATION_UNIT.match(unit) else " "
    return re.sub(r"\s{2,}", " ", SAID_QUANTITY.sub(drop, text)).strip()


# Separa los artículos de un mensaje: «1 galón de pintura blanca y 2 brochas de 3 pulgadas».
CLAUSE_BREAK = re.compile(r",|;|\n|\s(?:y|e|ademas|tambien)\s")


def item_clause(message: str, text: str, tokenize) -> str:
    """Lo que el cliente dijo de un artículo: la parte del mensaje que más palabras comparte con su texto.

    Grok a veces deja un atributo fuera de ``text`` («galón» solo en presentation); la parte del mensaje lo
    respalda sin prestarle a un artículo lo que el cliente dijo de otro. Sin coincidencias, queda el texto solo.
    """
    words = tokenize(text)
    clauses = [part for part in CLAUSE_BREAK.split(message) if part.strip()]
    best = max(clauses, key=lambda part: len(tokenize(part) & words), default="")
    return f"{best} {text}" if words & tokenize(best) else text


@dataclass(frozen=True)
class ProductQuery:
    text: str
    product: str | None = None
    use: str | None = None
    material: str | None = None
    measure: str | None = None
    presentation: str | None = None
    color: str | None = None
    brand: str | None = None
    quantity: int | None = None

    def grounded(self, message: str, tokenize, phrase: str | None = None) -> "ProductQuery":
        """Descarta filtros que Grok no pueda respaldar con la frase y el mensaje.

        ``phrase`` es lo que el cliente dijo de este artículo; por defecto, el ``text`` que armó Grok.
        """
        message_words = tokenize(message)
        phrase_words = tokenize(phrase or self.text)
        changes = {}
        for field in ("product", "use", "material", "measure", "presentation", "color", "brand"):
            value = getattr(self, field)
            if value:
                value_words = tokenize(value)
                if field == "measure":
                    numbers = {word for word in value_words if any(char.isdigit() for char in word)}
                    # metro y galón no cuentan: también son unidades de venta («2 metros de PVC de 1/2»).
                    units = {"pulgada", "kg", "cm", "mm", "litro"}
                    explicit_units = phrase_words & units
                    grounded = bool(numbers and numbers <= message_words and numbers <= phrase_words)
                    # R-03 (corrida 29): el cliente escribió «d 9 w» y Grok, measure="9w"; la búsqueda perdió la
                    # medida y preguntó entre 9, 18 y 20 W. Como átomos («9w») sí coinciden.
                    atoms = measures(value)
                    if not grounded and atoms:
                        grounded = atoms <= measures(message) and atoms <= measures(phrase or self.text)
                    if explicit_units and not (value_words & explicit_units):
                        grounded = False
                else:
                    grounded = bool(value_words and value_words <= message_words and value_words <= phrase_words)
                if not grounded:
                    changes[field] = None
        return replace(self, **changes)


# «la pintura que no es la blanca», «cualquiera menos la blanca»: esa palabra describe lo que el cliente no quiere.
# Z-17 (suite fallas): la búsqueda llevó «blanca» y la respuesta ofreció la pintura blanca.
NEGATED = re.compile(r"\b(?:que\s+no\s+(?:es|sea|son|sean)|no\s+(?:el|la|los|las)|menos|excepto|salvo"
                     r"|(?:distint|diferent)[oae]s?\s+(?:a|al|de|del))\s+(?:(?:el|la|los|las)\s+)?([a-z]{3,})\b")


def negated_words(normalized_message: str, tokenize) -> set[str]:
    """Las palabras (ya en tokens) de lo que el cliente dijo que no quiere."""
    return set().union(*(tokenize(match.group(1)) for match in NEGATED.finditer(normalized_message)))
