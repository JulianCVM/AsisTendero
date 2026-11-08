"""Contrato tipado entre la interpretación del agente y la búsqueda del servidor."""

from dataclasses import dataclass, replace
import re
from asistendero.tienda.catalogo.measures import NUMBER_WORDS, measures
from asistendero.tienda.vocabulario import normalize_text

# Las seis últimas son de la tienda de mercado: «2 paquetes de pan» o «una cubeta de huevos».
SALE_UNIT_NAME = (r"(metros?|bultos?|galon(?:es)?|unidad(?:es)?|libras?|rollos?|pares|par|pliegos?|bolsas?|cajas?|"
                  r"paquetes?|botellas?|latas?|cubetas?|atados?|barras?|kilos?)")
# «3 metros de tubo» es cuánto lleva, no una medida. En la conversación del visor del 23-10, «dame del primero 3
# metros» llevó a Grok a buscar «tubo PVC 3 metros» y se eligió el tubo sanitario de 3 pulgadas. «de 3 metros» o
# «x 15 m» sí describen el producto (un flexómetro, una manguera) y se dejan.
SAID_QUANTITY = re.compile(r"(?<!\bde )(?<!\bx )\b(?:\d+|" + "|".join(NUMBER_WORDS) + r")\s+" + SALE_UNIT_NAME + r"\b",
                           re.IGNORECASE)
PRESENTATION_UNIT = re.compile(r"(?:galon(?:es)?|galón|cajas?|bolsas?|pliegos?|rollos?)$", re.IGNORECASE)
# Corrida 39 (31-10): Grok buscó «2 libras de papa criolla» con presentation="2 libras", «12 huevos» con
# presentation="12" y «una docena» con presentation="docena"; ningún producto tiene esa presentación y todo quedó en
# opciones cercanas. Un número con libra, metro, unidad o par, «y media» o «docena» puede ser cuánto lleva el
# cliente; también puede ser la presentación («media libra» de queso), por eso la búsqueda solo lo suelta si no hay
# ningún producto exacto con él.
_COUNT = r"(?:\d+(?:[.,]\d+)?|" + "|".join(NUMBER_WORDS) + r"|media|medio)"
ONLY_QUANTITY = re.compile(r"^(?:" + _COUNT + r"\s+)*(?:" + _COUNT + r"|docenas?|libras?|metros?|unidad(?:es)?|pares|par)"
                           r"(?:\s+(?:de\s+)?(?:docenas?|libras?|metros?|unidad(?:es)?))?(?:\s+y\s+medi[oa])?$")


def only_quantity(value: str, text: str) -> bool:
    """¿La medida o presentación que puso Grok puede ser solo la cantidad pedida («2 libras», «docena», «12»)?

    Dicha tras «de» en el texto del artículo describe el producto y no se suelta: «manguera de 15 metros» sin una de
    15 metros sigue siendo una opción cercana, nunca otra manguera como si fuera la pedida.
    """
    value = re.sub(r"\s+", " ", normalize_text(value)).strip()
    return bool(ONLY_QUANTITY.match(value)) and not re.search(r"\bde\s+" + re.escape(value) + r"\b",
                                                              normalize_text(text))


def quantity_unit(value: str) -> str:
    """La unidad de venta de una cantidad dicha: «2 libras» → libra; «docena», «12» o «media docena» → unidad."""
    unit = re.search(r"\b(libra|metro|unidad|par)", normalize_text(value))
    return unit.group(1) if unit else "unidad"


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
        # X-14 (corrida 45): «I need 2 bags of grey cement 50 kg» y Grok, presentation="bolsa 50 kg". «bolsa» no está
        # en el mensaje y se descartaba el campo entero, con los «50 kg» que el cliente sí dijo: salía «¿25 o 50 kg?».
        # La medida dicha se conserva como medida; la palabra que no dijo, no.
        if "presentation" in changes and (self.measure is None or "measure" in changes):
            said = {atom for atom in measures(self.presentation) if not atom.isdigit()}
            if said and said <= measures(message) and said <= measures(phrase or self.text):
                changes["measure"] = " ".join(sorted(said))
        # M-08 (corrida 46): «2 libras de papa criolla y una de tomate» y Grok, text="papa criolla de 2 libras". Tras
        # «de», la búsqueda lo toma como el tamaño del producto y no lo suelta: la papa criolla por libra salió como
        # opción cercana. Si es la cantidad lo decide lo que escribió el cliente, así que el «de» de Grok se quita.
        text = self.text
        for field in ("measure", "presentation"):
            value = getattr(self, field) if field not in changes else changes[field]
            if value and only_quantity(value, message) and not only_quantity(value, text):
                words = r"\s+".join(map(re.escape, value.split()))
                text = re.sub(r"\s*\bde\s+" + words + r"\b", "", text, flags=re.IGNORECASE).strip() or text
        if text != self.text:
            changes["text"] = text
        return replace(self, **changes)


# «la pintura que no es la blanca», «cualquiera menos la blanca»: esa palabra describe lo que el cliente no quiere.
# Z-17 (suite fallas): la búsqueda llevó «blanca» y la respuesta ofreció la pintura blanca.
NEGATED = re.compile(r"\b(?:que\s+no\s+(?:es|sea|son|sean)|no\s+(?:el|la|los|las)|menos|excepto|salvo"
                     r"|(?:distint|diferent)[oae]s?\s+(?:a|al|de|del))\s+(?:(?:el|la|los|las)\s+)?([a-z]{3,})\b")


def negated_words(normalized_message: str, tokenize) -> set[str]:
    """Las palabras (ya en tokens) de lo que el cliente dijo que no quiere."""
    return set().union(*(tokenize(match.group(1)) for match in NEGATED.finditer(normalized_message)))
