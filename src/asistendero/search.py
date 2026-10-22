"""Contrato tipado entre la interpretación del agente y la búsqueda del servidor."""

from dataclasses import dataclass, replace
import re

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
                    if explicit_units and not (value_words & explicit_units):
                        grounded = False
                else:
                    grounded = bool(value_words and value_words <= message_words and value_words <= phrase_words)
                if not grounded:
                    changes[field] = None
        return replace(self, **changes)
