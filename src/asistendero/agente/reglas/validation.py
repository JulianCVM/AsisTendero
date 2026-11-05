"""Reglas que una solicitud de Grok debe cumplir antes de llegar al ejecutor."""

import json
import re

from asistendero.agente.entrada.spelling import heard_as
from asistendero.agente.herramientas.observations import Finding, search_findings, ToolCall
from asistendero.agente.modelo.grok import MAX_ARGUMENT_CHARS, MAX_ITEMS, STORE_TOPICS, TOOL_NAMES
from asistendero.agente.reglas.context_resolution import (
    _heads_in_text, enrich_elliptical_text, remembered_spec_for_item,
)
from asistendero.agente.respuesta.store_replies import asks_assortment
from asistendero.tienda.catalogo.catalog import Product, tokens
from asistendero.tienda.catalogo.measures import canonical_text, measures
from asistendero.tienda.catalogo.product_fit import closest_named, described_whole, is_distinguished
from asistendero.tienda.catalogo.search import (
    CLAUSE_BREAK, NUMBER_WORDS, SALE_UNIT_NAME, item_clause, negated_words, ProductQuery, without_quantities,
)
from asistendero.tienda.vocabulario import SKU_PATTERN, normalize_text


MAX_QUANTITY = 1000
QUERY_FIELDS = ("product", "use", "material", "measure", "presentation", "color", "brand")
# «2 metros» o «1 bulto» es cuánto se vende, no una medida del producto: en la corrida exploratoria X-03
# Grok la puso en measure y la búsqueda devolvió opciones cercanas en vez de preguntar el diámetro.
SALE_QUANTITY = re.compile(r"^\s*(?:\d+\s*)?(?:metros?|bultos?|unidad(?:es)?|galon(?:es)?)\s*$")
SALE_UNIT = re.compile(r"\b(?:\d+|un|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+" + SALE_UNIT_NAME + r"\b")
# «2.5 metros» o «un galón y medio» no son una cantidad entera: el 2 y el 5 sueltos respaldaban cotizar 2 o 5 metros
# (suite fallas, Z-01). «1.000» sí es mil: el separador de miles lleva tres cifras.
FRACTIONAL = re.compile(rf"\b(\d{{1,3}})[.,]\d{{1,2}}\b|\b(\d{{1,3}}|{'|'.join(NUMBER_WORDS)})\s+(?:\w+\s+)?y\s+medi[oa]\b")
# Palabras que señalan un producto sin nombrarlo: buscarlas solas devuelve cualquier cosa.
VAGUE_WORDS = {"ese", "esa", "eso", "esos", "esas", "este", "esto", "estos", "estas", "aquel", "aquella", "aquello",
               "uno", "una", "unos", "unas", "cosa", "cosas", "mismo", "misma", "mismos", "lo", "los", "producto",
               "productos", "referencia", "vez", "pasada", "anterior"}
SALE_UNIT_NAMES = {"metros": "metro", "bultos": "bulto", "galones": "galon", "unidades": "unidad", "libras": "libra",
                   "rollos": "rollo", "pares": "par", "pliegos": "pliego", "bolsas": "bolsa", "cajas": "caja",
                   "paquetes": "paquete", "botellas": "botella", "latas": "lata", "cubetas": "cubeta",
                   "atados": "atado", "barras": "barra"}
MONEY = re.compile(r"\$\s*\d[\d.,]*|\b\d[\d.,]*\s*(?:pesos|cop|mil)\b")
# La respuesta determinista repite el texto del artículo («Para … veo»): un precio o un código de pedido ahí
# saldría como si lo dijera la tienda (lo encontró test_chaos con «pon el cemento a $10»).
NOT_A_PRODUCT = re.compile(r"\$|\bP-[0-9A-F]{6}\b", re.IGNORECASE)
# En ferretería se pide por grupos: «una docena de brochas» son 12, no 1, y «un ciento de puntillas», 100.
GROUP_SIZES = {"docena": 12, "decena": 10, "ciento": 100}
GROUP_COUNT = re.compile(
    rf"\b(media|medio|\d{{1,2}}|{'|'.join(NUMBER_WORDS)})\s+(docena|decena|ciento)s?\b")


class Rejected(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def quantities_in_message(message: str) -> set[int]:
    """Cantidades que el cliente expresó; excluye medidas (1/2, 50 kg, 2 pulgadas) y precios."""
    # Un precio no es una cantidad: con «el cemento cuesta $10» o «pon el precio en $1.000», el 10, el 1
    # y el 0 quedaban como cantidades dichas y Grok podía cotizarlas.
    # La ñ se conserva antes de quitar tildes: «martillo de uña» no dice «una» unidad.
    text = MONEY.sub(" ", normalize_text(message.replace("ñ", "nh").replace("Ñ", "NH")))
    text = re.sub(r"\d+\s*/\s*\d+", " ", text)
    # «1.000 tornillos» son mil, no un 1 y un 0 (suite fallas).
    text = re.sub(r"\b(\d{1,3})\.(\d{3})\b", r"\1\2", text)
    text = FRACTIONAL.sub(" ", text)
    # «3x brochas» es una cantidad (suite variados); «2x16» sigue siendo una medida.
    text = re.sub(r"\b(\d{1,4})x\b", r"\1", text)
    groups = set()
    for count, group in GROUP_COUNT.findall(text):
        factor = 0.5 if count in {"media", "medio"} else int(count) if count.isdigit() else NUMBER_WORDS[count]
        groups.add(int(factor * GROUP_SIZES[group]))
    text = GROUP_COUNT.sub(" ", text)
    text = re.sub(
        rf"\b(?:cuales\s+son|muestrame|muestreme|mostrar|dime|ver)\s+(?:las\s+|los\s+)?otr[oa]s\s+"
        rf"(?:\d{{1,2}}|{'|'.join(NUMBER_WORDS)})\b",
        " ",
        text,
    )
    # Con el catálogo ampliado también son medidas «9 W», «12 AWG», «grano 80», «talla 40» o el 2 de «1/4 x 2».
    # La obra tampoco es la cantidad: el 3 de «una casa de 3 pisos» pedía cotizar 3 bultos (Z-22, suite fallas).
    measure = (r"(?!\s*(?:pulgad|kg|kilo|v\b|mm|cm|\"|x\b|×|w\b|watts|awg|ml\b|oz\b|lb\b|a\b|amperios|grados"
               r"|dientes|piezas|salidas|polos?\b|pies\b|litros?\b|l\b|g\b|pisos?\b|plantas?\b|niveles?\b"
               r"|habitacion\w*|banhos?\b|anhos?\b|mes(?:es)?\b|dias?\b|semanas?\b|horas?\b|minutos?\b"
               r"|personas?\b|cuadras?\b|veces\b|hijos?\b|opcion(?:es)?\b|variantes?\b))")
    label = r"(?<![#x×])(?<!x )(?<!× )(?<!grano )(?<!talla )(?<!calibre )(?<!numero )"
    found = {int(value) for value in re.findall(rf"{label}\b(\d{{1,4}})\b{measure}", text)}
    # «para un baño» o «en una pared» describen el uso; el artículo no es la cantidad del producto (J-45).
    text = re.sub(r"\b(?:para|en|de|del|con|por|como|sin|sobre)\s+(?:un|una|uno)\b", " ", text)
    found |= {
        NUMBER_WORDS[word]
        for word in re.findall(rf"\b({'|'.join(NUMBER_WORDS)})\b{measure}", text)
    }
    return found | groups


def naming_numbers(message: str, products: list[Product]) -> set[int]:
    """Números del mensaje que nombran un producto encontrado y no son cuántos lleva.

    «el cemento gris de 50» o «el codo de 90» dicen la variante: el 50 y el 90 salen una vez, tras «de», y están en
    el nombre o la variante (Z-14 y Z-22, suite fallas). En «12 bombillos de 12» el 12 se dice dos veces y sigue
    siendo cantidad.
    """
    # Un número entero, no un trozo de fracción ni de miles: con «un flotador de 1/2» y «el tanque de 1.000 litros»
    # el «1» de la variante borraba el «un» que dijo el cliente y no se cotizaba (A-10 y P-tanque-2, corrida 41).
    whole = r"(?<![\d/.,]){}(?![\d/]|[.,]\d)"
    text = re.sub(r"\b(\d{1,3})\.(\d{3})\b", r"\1\2", normalize_text(message))
    described = {number.replace(".", "") for product in products
                 for number in re.findall(whole.format(r"\d+(?:\.\d{3})*"), f"{product.name} {product.variant}")}
    return {int(number) for number in described
            if len(re.findall(whole.format(number), text)) == 1 and re.search(r"\bde\s+" + whole.format(number), text)}


def fractional_amount(message: str) -> int | None:
    """La parte entera de una cantidad con fracción («2.5 metros» → 2, «un galón y medio» → 1), si la hay."""
    match = FRACTIONAL.search(normalize_text(message))
    if not match:
        return None
    whole = match.group(1) or match.group(2)
    return int(whole) if whole.isdigit() else NUMBER_WORDS[whole]


def sale_units(text: str) -> set[str]:
    """Unidades de venta que acompañan una cantidad («2 metros», «un bulto»), en singular."""
    found = SALE_UNIT.findall(normalize_text(text))
    return {SALE_UNIT_NAMES.get(unit, unit) for unit in found}


def foreign_unit(message: str, quantity: int, unit: str) -> str | None:
    """Unidad de venta que el cliente pegó a esa cantidad y que ``unit`` no nombra, si nunca la dijo suelta.

    ``unit`` lleva la unidad y la variante del producto: el esmalte en «galón» se vende por unidad y «2 galones»
    sí son 2 de esos (V-31 en la suite variados).

    «un rollo de cable» no son 1 metro: en la corrida de escenarios extremos el aviso QUOTE_REQUIRED empujó a Grok
    a cotizar 1 metro. «2 metros de cable y 2 brochas» sí deja cotizar 2 brochas: el segundo 2 va suelto.
    """
    text = re.sub(r"\d+\s*/\s*\d+", " ", normalize_text(message))
    words = "|".join(NUMBER_WORDS)
    said = [NUMBER_WORDS.get(value) or int(value) for value in re.findall(rf"\b(\d+|{words})\b", text)]
    attached = [(NUMBER_WORDS.get(value) or int(value), SALE_UNIT_NAMES.get(name, name))
                for value, name in re.findall(rf"\b(\d+|{words})\s+{SALE_UNIT_NAME}\b", text)]
    units = {name for value, name in attached if value == quantity}
    offered = {SALE_UNIT_NAMES.get(word, word) for word in re.findall(r"[a-z]+", normalize_text(unit))}
    if not units or units & offered or said.count(quantity) > len([1 for value, _ in attached if value == quantity]):
        return None
    return sorted(units)[0]


# Palabras que pueden seguir a una cantidad sin nombrar otro producto («3 para la casa», «2 porfa»).
AFTER_QUANTITY = {"para", "porfa", "favor", "cada", "veces", "horas", "dias", "pesos", "piezas", "juegos"}


def quantity_of_other(message: str, quantity: int, description: str) -> str | None:
    """Producto distinto al que el cliente pegó esa cantidad («2 brochas»), si nunca la dijo para este.

    Con un producto recordado de un turno anterior, «agrégale 2 brochas» dejaba cotizar 2 bultos del cemento que
    se había consultado (suite memoria con Grok real, 23-10-2026): el 2 era de las brochas. ``description`` es el
    nombre, la variante y la unidad del producto recordado.
    """
    text = re.sub(r"\d+\s*/\s*\d+", " ", normalize_text(message))
    words = "|".join(NUMBER_WORDS)
    heads = [word for value, word in re.findall(rf"\b(\d+|{words})\b\s*([a-z]*)", text)
             if (NUMBER_WORDS.get(value) or (int(value) if value.isdigit() else None)) == quantity]
    own = tokens(description)
    others = [word for word in heads if len(word) >= 4 and word not in AFTER_QUANTITY
              and not re.fullmatch(SALE_UNIT_NAME, word) and not tokens(word) & own]
    return others[0] if heads and len(others) == len(heads) else None


def sole_head(finding: Finding) -> Product | None:
    """El único producto que lleva lo pedido como sustantivo (primera palabra del nombre) y no tiene otra variante.

    Tienda de mercado (31-10): «tomate» encaja con el tomate chonto y con las sardinas en salsa de tomate, «limones»
    con el limón y con las papas de limón, y «12 huevos» con el huevo y con la cubeta de huevos. Los otros solo
    nombran lo pedido; preguntar «¿cuál te sirve?» ahí era fricción sin ambigüedad real. Con dos variantes del
    mismo producto (panela de 500 g o de 1 kg) sí se pregunta. Cada palabra que el cliente dijo del artículo debe
    estar en ese producto: «tomate cherry» no es el tomate chonto (una opción cercana no es equivalente).
    """
    asked = tokens(finding["query"])
    heads = [product for product in finding["matches"] if tokens(product.name.split()[0], synonyms=False) & asked]
    if len(heads) != 1 or sum(product.name == heads[0].name for product in finding["matches"]) != 1:
        return None
    counting = set(GROUP_SIZES) | set(SALE_UNIT_NAMES) | set(SALE_UNIT_NAMES.values()) | {"media", "medio"}
    own = tokens(f"{heads[0].name} {heads[0].variant}")
    # Palabra por palabra, con sus formas: «huevos» es «huevo» y «limones», «limón».
    unsaid = [word for word in re.findall(r"[a-z0-9]+", normalize_text(finding["query"]))
              if (forms := tokens(word)) and not word.isdigit() and not forms & (own | counting)]
    return None if unsaid else heads[0]


def grounded_selection(message: str, finding: Finding) -> Product | None:
    """Única variante de matches que el mensaje permite elegir sin preguntar."""
    # «tuvo pbc» respalda «tubo PVC»: el mensaje se lee como suena frente a lo que extrajo Grok.
    # Los atributos que llegaron a la búsqueda ya están respaldados por el mensaje: también describen el artículo.
    described = " ".join([finding["query"], *map(str, finding["request"].values())])
    said = message
    # Si todo lo encontrado se vende por metro, «3 metros» es la cantidad y no puede elegir «3 pulgadas». Con una
    # manguera que se vende por unidad, «15 metros» sí es su largo.
    if {normalize_text(product.unit) for product in finding["matches"]} <= sale_units(message):
        message = without_quantities(normalize_text(message))
    message = heard_as(message, described)
    chosen = [
        product for product in finding["matches"]
        if product.sku.casefold() in message.casefold()
        or is_distinguished(message, described, product, finding["matches"])
    ]
    if len({product.name for product in finding["matches"]}) > 1:
        # Se compara con todas las coincidencias, no solo con las distinguidas: en la corrida de variados Grok
        # buscó sin «galón», el cuñete era el único beige de su nombre y se eligió aunque el cliente dijo
        # «10 galones». Si el que mejor describe no se distinguió, vale solo si el cliente lo dijo entero.
        leaders = closest_named(message, finding["query"], list(finding["matches"]))
        if leaders:
            whole = [product for product in leaders if described_whole(message, finding["query"], product)]
            chosen = [product for product in chosen if product in leaders] or (whole if len(whole) == 1 else [])
    head = sole_head(finding)
    if len(chosen) == 1 and len({product.name for product in finding["matches"]}) > 1:
        # Solo en su nombre, un producto queda «distinguido» con cualquier palabra; si la que lo describe la dicen
        # todas las coincidencias, no elige (suite natural: «pintura beige» eligió el cuñete, el único con «beige»
        # en la variante; los otros dos lo llevan en el nombre).
        product = chosen[0]
        shared = set.intersection(*(tokens(f"{item.name} {item.variant}") for item in finding["matches"]))
        alone = sum(item.name == product.name for item in finding["matches"]) == 1
        support = tokens(f"{product.name} {product.variant}") & tokens(message) & tokens(described)
        if alone and not support - shared and product.sku.casefold() not in message.casefold() and product != head:
            return None
    if not chosen and head is not None:
        chosen = [head]
    if len(chosen) > 1:
        # Con cientos de productos, «2 metros de PVC de 1/2» encaja con el tubo y con el codo de 1/2; la unidad
        # de venta dicha (metro) los separa. Si aun así quedan varios, se pregunta.
        # Si Grok dejó la cantidad fuera del artículo («PVC de 1/2 para agua»), vale la unidad del mensaje,
        # pero solo cuando deja un único producto.
        units = sale_units(finding["query"]) & sale_units(said) or sale_units(said)
        narrowed = [product for product in chosen if normalize_text(product.unit) in units]
        chosen = narrowed if len(narrowed) == 1 else chosen
    return chosen[0] if len(chosen) == 1 else None


def without_negated(message: str, finding: Finding) -> Finding:
    """La búsqueda sin lo que el cliente dijo que no quiere («la pintura que no es la blanca»)."""
    refused = negated_words(normalize_text(message), tokens)
    if not refused:
        return finding
    keep = lambda product: not refused & tokens(f"{product.name} {product.variant}")
    return {**finding, "matches": [p for p in finding["matches"] if keep(p)],
            "nearby": [p for p in finding["nearby"] if keep(p)]}


def grounded_products(message: str, calls: list[ToolCall]) -> dict[str, Product]:
    selected = {}
    for finding in search_findings(calls):
        product = grounded_selection(message, without_negated(message, finding))
        if product:
            selected[product.sku] = product
    return selected


def session_phrase(current: str, reference: str, text: str, product: str | None, several: bool) -> str:
    """Lo que el cliente dijo de un artículo en la conversación, sin el ``text`` de Grok.

    Del mensaje actual cuenta todo (o, con varios artículos, la parte que habla de este); de los anteriores, solo
    las partes que nombran el mismo producto. Así «¿y el de 3/4?» hereda el «PVC» del tubo, pero «de mangueras
    que tiene» no, aunque Grok escriba «mangueras PVC» en ``text``.
    """
    words = tokens(text)
    now = canonical_text(heard_as(current, text))
    if several:
        parts = [part for part in CLAUSE_BREAK.split(now) if part.strip()]
        now = max(parts, key=lambda part: len(tokens(part) & words), default="")
    named = tokens(product) if product else tokens(text.split()[0] if text.split() else "")
    earlier = [part for part in CLAUSE_BREAK.split(canonical_text(heard_as(reference, text)))
               if named and named & tokens(part)]
    return " ".join([now, *earlier])


def validate_request(
    name: str | None, arguments: object, message: str, calls: list[ToolCall], quantities: set[int] | None = None,
    remembered: dict[str, str] | None = None, listed: dict[str, int] | None = None, current: str | None = None,
    context: dict | None = None, picked: list[dict] | None = None,
) -> dict:
    """Devuelve los argumentos que efectivamente recibirá el ejecutor o rechaza la solicitud.

    ``message`` es lo que el cliente dijo (en una sesión, sus turnos recientes más el actual);
    ``quantities``, las cantidades que puede cotizar (por omisión, las de ``message``), y ``remembered``,
    los SKU que la sesión ya identificó en turnos anteriores, con su nombre, variante y unidad. ``listed`` es la lista de la conversación (SKU →
    cantidad): esa línea ya la dijo el cliente, aunque haya sido hace muchos turnos. ``current`` es el mensaje del
    turno: con un solo artículo, lo dicho en turnos anteriores solo respalda atributos en la frase de ese producto.
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
        # Visor, 26-10: «que venden» terminó en seis búsquedas de productos que el cliente nunca nombró.
        if asks_assortment(normalize_text(current or message)):
            raise Rejected("ASSORTMENT_QUESTION", "El cliente pregunta qué vende la tienda en general, sin nombrar un "
                                                  "producto: llama a explorar_categoria sin argumentos.")
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
            inherited_head: str | None = None
            picked_item: dict | None = None
            if len(items) == 1 and picked and len(picked) == 1 and not _heads_in_text(text):
                picked_item = picked[0]
                text = f"{picked_item.get('nombre', '')} {picked_item.get('variante', '')}".strip() or text
            elif len(items) == 1:
                text, inherited_head = enrich_elliptical_text(text, current or message, context)
            if not tokens(without_quantities(text)):
                raise Rejected("INVALID_ARGUMENT", "El artículo solo dice una cantidad: usa el producto que el cliente "
                                                   "eligió o pregúntale cuál quiere.")
            # Z-11 (suite fallas): «deme 3 de esos» sin conversación buscó «3» y ofreció duchas y bisagras.
            if all(word.isdigit() or word in VAGUE_WORDS for word in tokens(without_quantities(text), synonyms=False)):
                raise Rejected("VAGUE_SEARCH", "El texto no nombra un producto: pregúntale al cliente qué producto busca.")
            refused = negated_words(normalize_text(current or message), tokens)
            asked = tokens(" ".join(str(item.get(field) or "") for field in ("text", "color", "material", "presentation")))
            if refused & asked:
                raise Rejected("NEGATED_ATTRIBUTE", f"El cliente dijo que no quiere «{sorted(refused & asked)[0]}»: "
                                                    "busca sin esa palabra.")
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
            extra_support = ""
            if picked_item is not None:
                if picked_item.get("nombre"):
                    fields.setdefault("product", picked_item["nombre"].split()[0])
                if picked_item.get("variante") and measures(picked_item["variante"]):
                    fields.setdefault("measure", picked_item["variante"])
                extra_support = canonical_text(text)
            else:
                if inherited_head:
                    fields.setdefault("product", inherited_head)
                spec = remembered_spec_for_item(text, fields.get("product"), current or message, context)
                kept_specs: list[str] = []
                if spec.get("material") and not (tokens(spec["material"]) & refused):
                    fields.setdefault("material", spec["material"])
                    kept_specs.append(spec["material"])
                if spec.get("medida"):
                    fields.setdefault("measure", spec["medida"])
                    kept_specs.append(spec["medida"])
                if spec.get("presentacion") and not (tokens(spec["presentacion"]) & refused):
                    fields.setdefault("presentation", spec["presentacion"])
                    kept_specs.append(spec["presentacion"])
                if inherited_head:
                    kept_specs.append(text)
                extra_support = canonical_text(" ".join(kept_specs))
            heard = canonical_text(heard_as(message, " ".join([text, *fields.values()])))
            # Con varios artículos, un atributo debe estar en la parte del mensaje que habla del suyo («tubo PVC y
            # cemento gris» no pinta el tubo de gris). Con uno solo, todo el mensaje habla de él. En las corridas S4
            # Grok dejó «galón» en presentation y no en text (P-03 y C-08) y se preguntaba la presentación ya dicha.
            # En una conversación, el «PVC» del tubo de hace dos turnos llegó a la búsqueda de «mangueras» y no
            # hubo coincidencias (visor, 23-10): lo de turnos anteriores vale solo en la frase de este producto.
            if current is not None and current != message:
                phrase = session_phrase(current, message, text, fields.get("product"), len(items) > 1)
            elif len(items) > 1:
                phrase = item_clause(heard, text, tokens)
            else:
                phrase = heard
            if extra_support:
                heard = f"{heard} {extra_support}".strip()
                phrase = f"{phrase} {extra_support}".strip()
            query = ProductQuery(text.strip(), **fields).grounded(heard, tokens, phrase)
            clean.append({key: value for key, value in vars(query).items() if value is not None})
        return {"items": clean}

    grounded = grounded_products(message, calls)
    if name == "consultar_disponibilidad":
        sku = arguments.get("sku")
        if set(arguments) != {"sku"} or not isinstance(sku, str) or not SKU_PATTERN.match(sku):
            raise Rejected("INVALID_ARGUMENT", "Se requiere un SKU válido.")
        # Solo lee existencias y surtido: un producto que la sesión ya identificó vale («¿y cuándo le llegan más?»).
        if sku not in grounded and sku not in (remembered or {}):
            raise Rejected("SKU_NOT_GROUNDED", "El SKU no es una coincidencia que el mensaje distinga; pregunta al cliente.")
        return {"sku": sku}

    remembered = remembered or {}
    lines = arguments.get("lines")
    if set(arguments) != {"lines"} or not isinstance(lines, list) or not 1 <= len(lines) <= MAX_ITEMS:
        raise Rejected("INVALID_ARGUMENT", f"Se requieren de 1 a {MAX_ITEMS} líneas.")
    allowed_quantities = quantities_in_message(message) if quantities is None else quantities
    findings = search_findings(calls)
    missing_search = any(not finding["matches"] and not finding["nearby"] for finding in findings)
    known_skus = {product.sku for finding in findings for product in finding["matches"] + finding["nearby"]}
    known_skus |= set(remembered) | set(listed or {}) | {item.get("sku") for item in (picked or []) if item.get("sku")}
    for turn_group in (context or {}).get("opciones") or []:
        known_skus |= {opt.get("sku") for opt in (turn_group.get("opciones") or []) if isinstance(opt, dict) and opt.get("sku")}
    clean_lines = []
    ungrounded_skus: list[str] = []
    for line in lines:
        if not isinstance(line, dict) or set(line) != {"sku", "quantity"}:
            raise Rejected("INVALID_ARGUMENT", "Cada línea lleva solo sku y quantity.")
        sku, quantity = line["sku"], line["quantity"]
        if not isinstance(sku, str) or not SKU_PATTERN.match(sku):
            raise Rejected("INVALID_ARGUMENT", "Se requiere un SKU válido.")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= MAX_QUANTITY:
            raise Rejected("INVALID_QUANTITY", f"La cantidad debe ser un entero de 1 a {MAX_QUANTITY}.")
        if (listed or {}).get(sku) == quantity:
            if any(previous["sku"] == sku for previous in clean_lines):
                raise Rejected("INVALID_ARGUMENT", "SKU repetido en la cotización.")
            clean_lines.append({"sku": sku, "quantity": quantity})
            continue
        # Un producto que la sesión ya identificó se cotiza sin volver a buscar, como en los pedidos: el precio
        # lo relee la herramienta del catálogo (M-01, segunda corrida S4: «dame 3 metros de ese» se rechazaba).
        # X-22 (corrida 48): si Grok cotiza ítems respaldados junto a un SKU alucinado para un artículo sin
        # resultados en el catálogo, se particiona y cotiza determinísticamente el subconjunto válido.
        if sku not in grounded and sku not in remembered:
            if len(lines) > 1 and missing_search and not listed and sku not in known_skus:
                ungrounded_skus.append(sku)
                continue
            raise Rejected("SKU_NOT_GROUNDED", f"{sku} no es una coincidencia que el mensaje distinga: quítalo y "
                                               "cotiza solo lo identificado, o pregunta al cliente.")
        if quantity not in allowed_quantities:
            raise Rejected("QUANTITY_NOT_GROUNDED", "El cliente no expresó esa cantidad; pregúntala.")
        other = foreign_unit(message, quantity, f"{grounded[sku].unit} {grounded[sku].variant}") if sku in grounded else None
        product = None if sku in grounded else quantity_of_other(message, quantity, remembered[sku])
        if product:
            raise Rejected("QUANTITY_NOT_GROUNDED", f"El cliente dijo {quantity} {product}: esa cantidad es de otro "
                                                    "producto; búscalo antes de cotizarlo.")
        if other:
            raise Rejected("QUANTITY_NOT_GROUNDED", f"El cliente dijo {quantity} {other} y se vende por "
                                                    f"{grounded[sku].unit}; pregúntale cuántos {grounded[sku].unit}.")
        if any(previous["sku"] == sku for previous in clean_lines):
            raise Rejected("INVALID_ARGUMENT", "SKU repetido en la cotización.")
        clean_lines.append({"sku": sku, "quantity": quantity})
    if not clean_lines and ungrounded_skus:
        sku = ungrounded_skus[0]
        raise Rejected("SKU_NOT_GROUNDED", f"{sku} no es una coincidencia que el mensaje distinga: quítalo y "
                                           "cotiza solo lo identificado, o pregunta al cliente.")
    return {"lines": clean_lines}
