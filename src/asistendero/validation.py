"""Reglas que una solicitud de Grok debe cumplir antes de llegar al ejecutor."""

import json
import re
import unicodedata

from asistendero.catalog import Product, tokens
from asistendero.grok import MAX_ARGUMENT_CHARS, MAX_ITEMS, STORE_TOPICS, TOOL_NAMES
from asistendero.measures import UNITS, atom_support, canonical_text, contradicts, measures, split_atom
from asistendero.observations import Finding, ToolCall, search_findings
from asistendero.search import ProductQuery
from asistendero.spelling import heard_as


MAX_QUANTITY = 1000
QUERY_FIELDS = ("product", "use", "material", "measure", "presentation", "color", "brand")
SKU_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,31}$")
# «2 metros» o «1 bulto» es cuánto se vende, no una medida del producto: en la corrida exploratoria X-03
# Grok la puso en measure y la búsqueda devolvió opciones cercanas en vez de preguntar el diámetro.
SALE_QUANTITY = re.compile(r"^\s*(?:\d+\s*)?(?:metros?|bultos?|unidad(?:es)?|galon(?:es)?)\s*$")
SALE_UNIT = re.compile(
    r"\b(?:\d+|un|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+"
    r"(metros?|bultos?|galon(?:es)?|unidad(?:es)?|libras?|rollos?|pares|par|pliegos?|bolsas?|cajas?)\b"
)
SALE_UNIT_NAMES = {"metros": "metro", "bultos": "bulto", "galones": "galon", "unidades": "unidad", "libras": "libra",
                   "rollos": "rollo", "pares": "par", "pliegos": "pliego", "bolsas": "bolsa", "cajas": "caja"}
MONEY = re.compile(r"\$\s*\d[\d.,]*|\b\d[\d.,]*\s*(?:pesos|cop|mil)\b")
# La respuesta determinista repite el texto del artículo («Para … veo»): un precio o un código de pedido ahí
# saldría como si lo dijera la tienda (lo encontró test_chaos con «pon el cemento a $10»).
NOT_A_PRODUCT = re.compile(r"\$|\bP-[0-9A-F]{6}\b", re.IGNORECASE)
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


def _variant_elements(product: Product) -> tuple[set[str], set[str]]:
    """Átomos de medida y palabras de la variante, sin sinónimos («cuñete» no es «galón»).

    Una palabra de unidad sale de las palabras solo si ya viaja en un átomo: en «cuñete de 5 galones» la
    lleva ``5gal``, pero en la variante «galón» es justo lo que la distingue.
    """
    atoms = measures(product.variant)
    atom_units = {split_atom(atom)[1] for atom in atoms}
    words = {
        word for word in tokens(product.variant, synonyms=False)
        if not any(char.isdigit() for char in word) and word not in {"x", "de"}
        and not (word in UNITS and UNITS[word] in atom_units)
    }
    return atoms, words


def _support(
    product: Product, common: tuple[set[str], set[str]], said_atoms: set[str], said_words: set[str],
) -> tuple[int, int] | None:
    """(puntos de lo que el mensaje dice de la variante, -rasgos propios que no dice), o None si no le cabe."""
    atoms, words = _variant_elements(product)
    if contradicts(atoms, said_atoms):
        return None
    contrast_atoms, contrast_words = atoms - common[0], words - common[1]
    supports = [atom_support(atom, said_atoms) for atom in contrast_atoms]
    supports += [2 if word in said_words else 0 for word in contrast_words]
    if sum(supports):
        return sum(supports), -supports.count(0)
    # Una variante sin rasgos propios frente a sus pares vale si el mensaje nombra algo de ella.
    if not supports and (words & said_words or atoms & said_atoms):
        return 0, 0
    return None


def is_distinguished(original: str, item_query: str, selected: Product, candidates: list[Product]) -> bool:
    """La variante es la única que el mensaje describe mejor entre las de su mismo nombre.

    Solo cuenta lo que dicen a la vez el mensaje original y el artículo que extrajo Grok. Las medidas se
    comparan como átomos (``measures``): «2 tornillos de 1/4 x 1» elige 1/4 x 1 aunque haya un 2 suelto.
    """
    original_numbers = {split_atom(atom)[0] for atom in measures(original)} | {
        atom for atom in measures(original) if "x" in atom.lstrip("#")}
    said_atoms = {atom for atom in measures(item_query) if atom in original_numbers or split_atom(atom)[0] in original_numbers}
    said_words = tokens(original, synonyms=False) & tokens(item_query, synonyms=False)
    group = [item for item in candidates if item.name == selected.name]
    elements = [_variant_elements(item) for item in group]
    # La medida también puede estar en el nombre («Cable THHN calibre 14 AWG»): pedir 12 AWG la contradice.
    if contradicts(measures(f"{selected.name} {selected.variant}"), said_atoms):
        return False
    if len(group) == 1:
        # Un producto único vale salvo que el mensaje dé otra medida en la misma unidad.
        return not contradicts(elements[0][0], said_atoms)
    common = (set.intersection(*(atoms for atoms, _ in elements)), set.intersection(*(words for _, words in elements)))
    scores = {item.sku: _support(item, common, said_atoms, said_words) for item in group}
    fitting = {sku: score for sku, score in scores.items() if score is not None}
    if not fitting:
        return False
    best = max(fitting.values())
    return [sku for sku, score in fitting.items() if score == best] == [selected.sku]


def quantities_in_message(message: str) -> set[int]:
    """Cantidades que el cliente expresó; excluye medidas (1/2, 50 kg, 2 pulgadas) y precios."""
    # Un precio no es una cantidad: con «el cemento cuesta $10» o «pon el precio en $1.000», el 10, el 1
    # y el 0 quedaban como cantidades dichas y Grok podía cotizarlas.
    # La ñ se conserva antes de quitar tildes: «martillo de uña» no dice «una» unidad.
    text = MONEY.sub(" ", normalize_text(message.replace("ñ", "nh").replace("Ñ", "NH")))
    text = re.sub(r"\d+\s*/\s*\d+", " ", text)
    # Con el catálogo ampliado también son medidas «9 W», «12 AWG», «grano 80», «talla 40» o el 2 de «1/4 x 2».
    measure = (r"(?!\s*(?:pulgad|kg|kilo|v\b|mm|cm|\"|x\b|×|w\b|watts|awg|ml\b|oz\b|lb\b|a\b|amperios|grados"
               r"|dientes|piezas|salidas|polos?\b|pies\b|litros?\b|l\b|g\b))")
    label = r"(?<![#x×])(?<!x )(?<!× )(?<!grano )(?<!talla )(?<!calibre )(?<!numero )"
    found = {int(value) for value in re.findall(rf"{label}\b(\d{{1,4}})\b{measure}", text)}
    found |= {
        NUMBER_WORDS[word]
        for word in re.findall(rf"\b({'|'.join(NUMBER_WORDS)})\b{measure}", text)
    }
    return found


def sale_units(text: str) -> set[str]:
    """Unidades de venta que acompañan una cantidad («2 metros», «un bulto»), en singular."""
    found = SALE_UNIT.findall(normalize_text(text))
    return {SALE_UNIT_NAMES.get(unit, unit) for unit in found}


def grounded_selection(message: str, finding: Finding) -> Product | None:
    """Única variante de matches que el mensaje permite elegir sin preguntar."""
    # «tuvo pbc» respalda «tubo PVC»: el mensaje se lee como suena frente a lo que extrajo Grok.
    # Los atributos que llegaron a la búsqueda ya están respaldados por el mensaje: también describen el artículo.
    described = " ".join([finding["query"], *map(str, finding["request"].values())])
    message = heard_as(message, described)
    chosen = [
        product for product in finding["matches"]
        if product.sku.casefold() in message.casefold()
        or is_distinguished(message, described, product, finding["matches"])
    ]
    if len(chosen) > 1:
        # Con cientos de productos, «2 metros de PVC de 1/2» encaja con el tubo y con el codo de 1/2; la unidad
        # de venta dicha (metro) los separa. Si aun así quedan varios, se pregunta.
        # Si Grok dejó la cantidad fuera del artículo («PVC de 1/2 para agua»), vale la unidad del mensaje,
        # pero solo cuando deja un único producto.
        units = sale_units(finding["query"]) & sale_units(message) or sale_units(message)
        narrowed = [product for product in chosen if normalize_text(product.unit) in units]
        chosen = narrowed if len(narrowed) == 1 else chosen
    return chosen[0] if len(chosen) == 1 else None


def grounded_products(message: str, calls: list[ToolCall]) -> dict[str, Product]:
    selected = {}
    for finding in search_findings(calls):
        product = grounded_selection(message, finding)
        if product:
            selected[product.sku] = product
    return selected


def validate_request(
    name: str | None, arguments: object, message: str, calls: list[ToolCall], quantities: set[int] | None = None,
    remembered: set[str] = frozenset(),
) -> dict:
    """Devuelve los argumentos que efectivamente recibirá el ejecutor o rechaza la solicitud.

    ``message`` es lo que el cliente dijo (en una sesión, sus turnos recientes más el actual);
    ``quantities``, las cantidades que puede cotizar (por omisión, las de ``message``), y ``remembered``,
    los SKU que la sesión ya identificó en turnos anteriores.
    """
    if name not in TOOL_NAMES:
        raise Rejected("UNKNOWN_TOOL", "Herramienta fuera de la lista permitida.")
    if not isinstance(arguments, dict):
        raise Rejected("INVALID_ARGUMENT", "Los argumentos deben ser un objeto.")
    if len(json.dumps(arguments, ensure_ascii=False)) > MAX_ARGUMENT_CHARS:
        raise Rejected("INVALID_ARGUMENT", "Los argumentos superan el límite de longitud.")

    if name == "consultar_info_tienda":
        if set(arguments) != {"tema"} or arguments.get("tema") not in STORE_TOPICS:
            raise Rejected("INVALID_ARGUMENT", f"tema debe ser uno de: {', '.join(STORE_TOPICS)}.")
        return {"tema": arguments["tema"]}
    if name == "explorar_categoria":
        category = arguments.get("categoria")
        if not set(arguments) <= {"categoria"} or (
            category is not None and (not isinstance(category, str) or not category.strip() or len(category) > 60)
        ):
            raise Rejected("INVALID_ARGUMENT", "explorar_categoria acepta solo una categoria de texto breve.")
        return {"categoria": category.strip()} if category else {}

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
            if any(NOT_A_PRODUCT.search(str(value)) for value in item.values()):
                raise Rejected("INVALID_ARGUMENT", "El artículo describe el producto: sin precios ni códigos de pedido.")
            fields = {}
            for field in QUERY_FIELDS:
                value = item.get(field)
                if value is not None:
                    if not isinstance(value, str) or not value.strip() or len(value) > 80:
                        raise Rejected("INVALID_ARGUMENT", f"Atributo {field} inválido.")
                    fields[field] = value.strip()
            # En la primera corrida S3 Grok puso use="galones" y la búsqueda solo dejó el cuñete de 5 galones.
            for field in ("measure", "use"):
                if SALE_QUANTITY.match(normalize_text(fields.get(field, ""))):
                    del fields[field]
            # En presentation la unidad sí distingue (galón frente a cuñete), pero no la cantidad: con
            # presentation="1 galón" (C-08 en la segunda corrida S3) ninguna variante cumplía el filtro.
            if SALE_QUANTITY.match(normalize_text(fields.get("presentation", ""))):
                fields["presentation"] = re.sub(r"^\s*\d+\s*", "", fields["presentation"])
            heard = canonical_text(heard_as(message, " ".join([text, *fields.values()])))
            # Con varios artículos, un atributo debe estar también en la frase del suyo («tubo PVC y cemento
            # gris» no pinta el tubo de gris). Con uno solo, todo el mensaje habla de él: en la primera corrida
            # S4 Grok dejó «galón» en presentation y no en text, y se preguntaba la presentación ya dicha.
            phrase = heard if len(items) == 1 else None
            query = ProductQuery(text.strip(), **fields).grounded(heard, tokens, phrase)
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
    allowed_quantities = quantities_in_message(message) if quantities is None else quantities
    clean_lines = []
    for line in lines:
        if not isinstance(line, dict) or set(line) != {"sku", "quantity"}:
            raise Rejected("INVALID_ARGUMENT", "Cada línea lleva solo sku y quantity.")
        sku, quantity = line["sku"], line["quantity"]
        if not isinstance(sku, str) or not SKU_PATTERN.match(sku):
            raise Rejected("INVALID_ARGUMENT", "Se requiere un SKU válido.")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= MAX_QUANTITY:
            raise Rejected("INVALID_QUANTITY", f"La cantidad debe ser un entero de 1 a {MAX_QUANTITY}.")
        # Un producto que la sesión ya identificó se cotiza sin volver a buscar, como en los pedidos: el precio
        # lo relee la herramienta del catálogo (M-01, segunda corrida S4: «dame 3 metros de ese» se rechazaba).
        if sku not in grounded and sku not in remembered:
            raise Rejected("SKU_NOT_GROUNDED", "El SKU no es una coincidencia que el mensaje distinga; pregunta al cliente.")
        if quantity not in allowed_quantities:
            raise Rejected("QUANTITY_NOT_GROUNDED", "El cliente no expresó esa cantidad; pregúntala.")
        if any(previous["sku"] == sku for previous in clean_lines):
            raise Rejected("INVALID_ARGUMENT", "SKU repetido en la cotización.")
        clean_lines.append({"sku": sku, "quantity": quantity})
    return {"lines": clean_lines}
