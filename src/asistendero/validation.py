"""Reglas que una solicitud de Grok debe cumplir antes de llegar al ejecutor."""

import json
import re
import unicodedata

from asistendero.catalog import Product, tokens
from asistendero.grok import MAX_ARGUMENT_CHARS, MAX_ITEMS, TOOL_NAMES
from asistendero.observations import Finding, ToolCall, search_findings
from asistendero.search import ProductQuery


MAX_QUANTITY = 1000
QUERY_FIELDS = ("product", "use", "material", "measure", "presentation", "color", "brand")
SKU_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,31}$")
# «2 metros» o «1 bulto» es cuánto se vende, no una medida del producto: en la corrida exploratoria X-03
# Grok la puso en measure y la búsqueda devolvió opciones cercanas en vez de preguntar el diámetro.
SALE_QUANTITY = re.compile(r"^\s*\d+\s*(?:metros?|bultos?|unidad(?:es)?|galon(?:es)?)\s*$")
MONEY = re.compile(r"\$\s*\d[\d.,]*|\b\d[\d.,]*\s*(?:pesos|cop|mil)\b")
NUMBER_WORDS = {
    "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "quince": 15, "veinte": 20,
}


class Rejected(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def is_distinguished(original: str, item_query: str, selected: Product, candidates: list[Product]) -> bool:
    """La variante debe estar respaldada por el mensaje original y por el item extraído."""
    original_tokens = tokens(original)
    item_tokens = tokens(item_query)
    variant_tokens = tokens(selected.variant)
    explicit_measures = re.findall(
        r"\b(\d+(?:/\d+)?)\s*(?:pulgada\w*|kg|kilo\w*)\b",
        normalize_text(item_query),
    )
    if explicit_measures and not (set(explicit_measures) & variant_tokens):
        return False
    peers = [item for item in candidates if item.name == selected.name and item.sku != selected.sku]
    if not peers:
        # Para un producto único tampoco aceptamos una medida contradictoria.
        return not explicit_measures or bool(set(explicit_measures) & variant_tokens)
    unique_variant = variant_tokens - set().union(*(tokens(item.variant) for item in peers))
    return bool(unique_variant & original_tokens & item_tokens)


def quantities_in_message(message: str) -> set[int]:
    """Cantidades que el cliente expresó; excluye medidas (1/2, 50 kg, 2 pulgadas) y precios."""
    # Un precio no es una cantidad: con «el cemento cuesta $10» o «pon el precio en $1.000», el 10, el 1
    # y el 0 quedaban como cantidades dichas y Grok podía cotizarlas.
    text = MONEY.sub(" ", normalize_text(message))
    text = re.sub(r"\d+\s*/\s*\d+", " ", text)
    measure = r"(?!\s*(?:pulgad|kg|kilo|v\b|mm|cm|\"|x\b|×))"
    found = {int(value) for value in re.findall(rf"\b(\d{{1,4}})\b{measure}", text)}
    found |= {
        NUMBER_WORDS[word]
        for word in re.findall(rf"\b({'|'.join(NUMBER_WORDS)})\b{measure}", text)
    }
    return found


def grounded_selection(message: str, finding: Finding) -> Product | None:
    """Única variante de matches que el mensaje permite elegir sin preguntar."""
    chosen = [
        product for product in finding["matches"]
        if product.sku.casefold() in message.casefold()
        or is_distinguished(message, finding["query"], product, finding["matches"])
    ]
    return chosen[0] if len(chosen) == 1 else None


def grounded_products(message: str, calls: list[ToolCall]) -> dict[str, Product]:
    selected = {}
    for finding in search_findings(calls):
        product = grounded_selection(message, finding)
        if product:
            selected[product.sku] = product
    return selected


def validate_request(name: str | None, arguments: object, message: str, calls: list[ToolCall]) -> dict:
    """Devuelve los argumentos que efectivamente recibirá el ejecutor o rechaza la solicitud."""
    if name not in TOOL_NAMES:
        raise Rejected("UNKNOWN_TOOL", "Herramienta fuera de la lista permitida.")
    if not isinstance(arguments, dict):
        raise Rejected("INVALID_ARGUMENT", "Los argumentos deben ser un objeto.")
    if len(json.dumps(arguments, ensure_ascii=False)) > MAX_ARGUMENT_CHARS:
        raise Rejected("INVALID_ARGUMENT", "Los argumentos superan el límite de longitud.")

    if name == "buscar_productos":
        items = arguments.get("items")
        if set(arguments) != {"items"} or not isinstance(items, list) or not items:
            raise Rejected("INVALID_ARGUMENT", "Se requiere al menos un artículo en items.")
        # Tras pasarse del límite, tampoco vale una lista recortada: en X-09 Grok quitó un artículo en silencio.
        if len(items) > MAX_ITEMS or any(
            (call["response"].get("error") or {}).get("code") == "TOO_MANY_ITEMS" for call in calls
        ):
            raise Rejected("TOO_MANY_ITEMS", f"El cliente pidió más de {MAX_ITEMS} artículos: no recortes la "
                                             "lista; responde pidiéndole que la divida.")
        clean = []
        for item in items:
            # quantity se tolera porque Grok la extrae con el artículo, pero la búsqueda no la usa.
            if not isinstance(item, dict) or not set(item) <= {"text", "quantity", *QUERY_FIELDS}:
                raise Rejected("INVALID_ARGUMENT", "Artículo con campos no permitidos.")
            text = item.get("text")
            if not isinstance(text, str) or not text.strip() or len(text) > 180:
                raise Rejected("INVALID_ARGUMENT", "Cada artículo necesita un texto breve.")
            fields = {}
            for field in QUERY_FIELDS:
                value = item.get(field)
                if value is not None:
                    if not isinstance(value, str) or not value.strip() or len(value) > 80:
                        raise Rejected("INVALID_ARGUMENT", f"Atributo {field} inválido.")
                    fields[field] = value.strip()
            if SALE_QUANTITY.match(normalize_text(fields.get("measure", ""))):
                del fields["measure"]
            query = ProductQuery(text.strip(), **fields).grounded(message, tokens)
            clean.append({key: value for key, value in vars(query).items() if value is not None})
        return {"items": clean}

    grounded = grounded_products(message, calls)
    if name == "consultar_disponibilidad":
        sku = arguments.get("sku")
        if set(arguments) != {"sku"} or not isinstance(sku, str) or not SKU_PATTERN.match(sku):
            raise Rejected("INVALID_ARGUMENT", "Se requiere un SKU válido.")
        if sku not in grounded:
            raise Rejected("SKU_NOT_GROUNDED", "El SKU no es una coincidencia que el mensaje distinga; pregunta al cliente.")
        return {"sku": sku}

    lines = arguments.get("lines")
    if set(arguments) != {"lines"} or not isinstance(lines, list) or not 1 <= len(lines) <= MAX_ITEMS:
        raise Rejected("INVALID_ARGUMENT", f"Se requieren de 1 a {MAX_ITEMS} líneas.")
    allowed_quantities = quantities_in_message(message)
    clean_lines = []
    for line in lines:
        if not isinstance(line, dict) or set(line) != {"sku", "quantity"}:
            raise Rejected("INVALID_ARGUMENT", "Cada línea lleva solo sku y quantity.")
        sku, quantity = line["sku"], line["quantity"]
        if not isinstance(sku, str) or not SKU_PATTERN.match(sku):
            raise Rejected("INVALID_ARGUMENT", "Se requiere un SKU válido.")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= MAX_QUANTITY:
            raise Rejected("INVALID_QUANTITY", f"La cantidad debe ser un entero de 1 a {MAX_QUANTITY}.")
        if sku not in grounded:
            raise Rejected("SKU_NOT_GROUNDED", "El SKU no es una coincidencia que el mensaje distinga; pregunta al cliente.")
        if quantity not in allowed_quantities:
            raise Rejected("QUANTITY_NOT_GROUNDED", "El cliente no expresó esa cantidad; pregúntala.")
        if any(previous["sku"] == sku for previous in clean_lines):
            raise Rejected("INVALID_ARGUMENT", "SKU repetido en la cotización.")
        clean_lines.append({"sku": sku, "quantity": quantity})
    return {"lines": clean_lines}
