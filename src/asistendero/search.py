"""Contrato tipado entre la interpretación del agente y la búsqueda del servidor."""

from dataclasses import dataclass, replace


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

    def grounded(self, message: str, tokenize) -> "ProductQuery":
        """Descarta filtros que Grok no pueda respaldar con la frase y el mensaje."""
        message_words = tokenize(message)
        phrase_words = tokenize(self.text)
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
