"""Cómo se le escribe al cliente: como un tendero amable por chat, que responde lo que le preguntaron.

Lo usan las respuestas deterministas (``answers.py``, ``order_replies.py``). Cada cifra sale de una observación; este
módulo solo decide la forma. El SKU es interno: el cliente no lo necesita y Grok lo lee de las observaciones.

Dos conversaciones del visor del 23-10 marcaron la forma. Primero la respuesta se leía como un reporte («SKU CON-050»,
«$3.900 COP c/u →», «Son datos de demostración» en cada mensaje). Después, cada opción decía «quedan 12 metros»
aunque el cliente no había preguntado cuánto hay. Ahora las existencias se dicen solo si el cliente las pregunta,
si quedan pocas o si no alcanzan; un producto se cotiza en una frase y varios, en una lista con su total.
"""

import re

from asistendero.catalog import Product


PLURAL = {"metro": "metros", "unidad": "unidades", "bulto": "bultos", "galón": "galones", "libra": "libras",
          "rollo": "rollos", "par": "pares", "pliego": "pliegos", "bolsa": "bolsas", "caja": "cajas"}
FEMININE = {"unidad", "libra", "bolsa", "caja"}
# Sustantivos femeninos del catálogo que no terminan en «a».
FEMININE_NOUNS = {"llave", "lija", "cerradura"}
# Una vez por conversación (el primer mensaje) o en cada consulta suelta: el catálogo es ficticio.
DEMO_NOTE = "Precios y existencias de demostración."
MAX_OPTIONS = 3
# Lo cercano no es lo pedido: se muestran pocas opciones.
MAX_NEARBY = 2
# Con pocas unidades vale avisar aunque no lo pregunten: el cliente puede necesitar más.
LOW_STOCK = 5
# Sobre el texto normalizado (sin tildes): «¿cuántos bultos de cemento les quedan?», «¿hay existencias?».
ASKS_STOCK = re.compile(r"\bcuant[oa]s\b[^?.!]{0,50}\b(?:quedan|hay|tienen?)\b|\b(?:existencias|stock|disponibles?"
                        r"|alcanza)\b")
# Si un producto sirve para una obra o un uso («¿sirve para una placa de 3 pisos?», «¿qué pegante me sirve para
# piscina?»): el catálogo no lo dice, así que nadie puede afirmarlo por el cliente.
ASKS_SUITABILITY = re.compile(r"\b(?:sirve[ns]?|me\s+sirve|funciona[ns]?|aguanta[ns]?|resiste[ns]?|es\s+(?:bueno|buena|apto|apta)"
                              r"|recomienda[ns]?|recomendaria)\b[^?.!]{0,60}\bpara\b")
SUITABILITY_NOTE = ("Si sirve para ese trabajo no te lo puedo asegurar: en el catálogo solo tengo precio y existencias. "
                    "Pregúntale a tu maestro de obra o en el mostrador.")
# Lo que la redacción de Grok no puede afirmar cuando el cliente pregunta si algo sirve.
SUITABILITY_CLAIM = re.compile(r"\b(?:si\s+(?:te\s+)?sirve|claro\s+que\s+(?:si|sirve)|es\s+ideal|ideal\s+para|perfect[oa]\s+para"
                               r"|te\s+(?:va\s+a\s+(?:servir|funcionar|aguantar)|sirve|funciona|aguanta)|apt[oa]\s+para"
                               r"|resiste\s+bien"
                               r"|aguanta\s+(?:bien|perfecto)|recomendad[oa]\s+para)\b")
# Variantes que empiezan por la presentación: «cemento gris en bulto de 50 kg».
PACKAGES = ("bulto", "galón", "galon", "caja", "bolsa", "rollo", "cuñete", "pliego", "juego", "par ", "kit")


def format_cop(value: int) -> str:
    return f"${value:,}".replace(",", ".")


def units(unit: str, amount: int) -> str:
    return unit if amount == 1 else PLURAL.get(unit, "unidades")


def per_unit(unit: str) -> str:
    """«el metro», «el bulto», «la libra»; por unidad se escribe «c/u», como en el mostrador."""
    if unit == "unidad":
        return "c/u"
    return f"{'la' if unit in FEMININE else 'el'} {unit}"


def label(name: str, variant: str) -> str:
    """«Tubo PVC presión para agua de 1/2 pulgada», «Cemento gris en bulto de 50 kg»."""
    variant = variant.strip()
    if variant[:1].isdigit():
        variant = f"de {variant}"
    elif variant.casefold().startswith(PACKAGES):
        variant = f"en {variant}"
    return f"{name} {variant}".strip()


def names_unit(text: str, unit: str) -> bool:
    """La variante ya dice la unidad («bulto de 50 kg»): no se repite «el bulto» después del precio."""
    return unit != "unidad" and unit in text.casefold().split()


def gender_of(name: str) -> tuple[bool, bool]:
    """(femenino, plural) del producto por su primera palabra: «cinta», «llave» y «guantes» no van con «el»."""
    first = (name.split() or [""])[0].casefold()
    plural = first.endswith("s") and len(first) > 3
    stem = first[:-1] if plural else first
    return stem.endswith("a") or stem in FEMININE_NOUNS, plural


def of_the(name: str) -> str:
    """«del tubo», «de la cinta», «de los guantes»."""
    feminine, plural = gender_of(name)
    return {(False, False): "del", (True, False): "de la", (False, True): "de los", (True, True): "de las"}[
        (feminine, plural)] + f" {name}"


def in_sentence(text: str) -> str:
    """«Tubo PVC…» → «tubo PVC…» dentro de una frase; una sigla («PVC», «LED») se deja igual."""
    return text[0].lower() + text[1:] if len(text) > 1 and text[1].islower() else text


def asks_stock(normalized_message: str) -> bool:
    return bool(ASKS_STOCK.search(normalized_message))


def stock_note(unit: str, stock: int, asked: bool, needed: int = 0) -> str:
    """«Me quedan 12 metros.» solo si lo preguntó; con pocas o sin alcanzar lo que pide, «Ojo, solo me quedan…»."""
    if stock <= LOW_STOCK or needed > stock:
        return f" Ojo, solo me {'queda' if stock == 1 else 'quedan'} {stock} {units(unit, stock)}."
    return f" Me quedan {stock} {units(unit, stock)}." if asked else ""


def whole_units_question(unit: str, whole: int) -> str:
    """«Lo vendo por metro completo: ¿te cotizo 2 o 3 metros?» cuando el cliente pidió una fracción."""
    complete = "completa" if unit in FEMININE else "completo"
    return f"Lo vendo por {unit} {complete}: ¿te cotizo {whole} o {whole + 1} {units(unit, 2)}?"


def asks_suitability(normalized_message: str) -> bool:
    return bool(ASKS_SUITABILITY.search(normalized_message))


def found_sentence(product: Product, stock: int, first: bool, asked: bool = False, needed: int = 0,
                   suitability: bool = False) -> str:
    name = in_sentence(label(product.name, product.variant))
    if stock <= 0:
        return f"El {name} está agotado por ahora."
    each = "" if names_unit(name, product.unit) else f" {per_unit(product.unit)}"
    # «¿sirve para fundir una placa?» contestado con «Sí, tenemos…» sonaba a «sí sirve» (Z-22, suite fallas).
    opening = ("Tengo" if suitability else "Sí, tenemos") if first else "También tengo"
    return f"{opening} {name}, a {format_cop(product.price_cop)}{each}.{stock_note(product.unit, stock, asked, needed)}"


def option_lines(products: list[Product]) -> list[str]:
    """Una viñeta por opción, sin precio ni existencias; con el mismo nombre basta la variante.

    Sin precio: mientras el cliente no elige, un precio junto a una opción se lee como la elegida (con medida
    ambigua se pregunta), y lo cercano no es lo pedido.
    """
    same_name = len({item.name for item in products}) == 1
    return [f"• {item.variant if same_name else label(item.name, item.variant)}" for item in products]


def sold_as(unit: str, variant: str) -> tuple[str, str]:
    """La presentación cuenta como unidad: «10 galones de pintura vinilo beige», no «10 unidades de … en galón»."""
    first, _, rest = variant.strip().partition(" ")
    if unit == "unidad" and first.casefold() in PLURAL and first.casefold() != "unidad":
        return first.casefold(), rest
    if variant.casefold().startswith(f"{unit} "):
        return unit, variant[len(unit) + 1:]
    return unit, variant


def amount_of(quantity: int, unit: str, name: str, variant: str) -> str:
    """«3 metros de tubo PVC…», «1 bulto de cemento gris de 50 kg»; una sola unidad es solo el nombre."""
    unit, variant = sold_as(unit, variant)
    text = label(name, variant)
    if unit == "unidad" and quantity == 1:
        return text
    return f"{quantity} {units(unit, quantity)} de {in_sentence(text)}"


def item_line(quantity: int, unit: str, name: str, variant: str, unit_price: int, subtotal: int) -> str:
    """«• 3 metros de tubo PVC… (a $8.500 el metro): $25.500»; con una sola unidad, sin el precio unitario."""
    each = f" (a {format_cop(unit_price)} {per_unit(sold_as(unit, variant)[0])})" if quantity > 1 else ""
    return f"• {amount_of(quantity, unit, name, variant)}{each}: {format_cop(subtotal)}"


def _line_parts(line: dict, products: dict[str, Product]) -> tuple[str, str, str]:
    product = products.get(line["sku"])
    if product:
        return product.name, product.variant, product.unit
    return line.get("name") or "producto", line.get("variant") or "", line.get("unit") or "unidad"


def quote_block(quote: dict, products: dict[str, Product], header: str) -> str:
    """Un producto en una frase («Los 3 metros de … te salen en $25.500»); varios, en lista con su total."""
    lines = quote["lines"]
    if len(lines) == 1:
        line = lines[0]
        name, variant, unit = _line_parts(line, products)
        amount = amount_of(line["quantity"], unit, name, variant)
        if line["quantity"] == 1:
            return f"{amount[0].upper()}{amount[1:]} te sale en {format_cop(line['subtotal_cop'])}."
        unit = sold_as(unit, variant)[0]
        article = "Las" if unit in FEMININE else "Los"
        return (f"{article} {amount} te salen en {format_cop(line['subtotal_cop'])} "
                f"(a {format_cop(line['unit_price_cop'])} {per_unit(unit)}).")
    rows = []
    for line in lines:
        name, variant, unit = _line_parts(line, products)
        rows.append(item_line(line["quantity"], unit, name, variant, line["unit_price_cop"], line["subtotal_cop"]))
    return "\n".join([header, *rows, f"Total: {format_cop(quote['total_cop'])}"])


def quote_offer(context: dict | None, orders, clarifying: bool) -> str:
    """Cierre de una cotización: fuera de una conversación no aparta; dentro, se ofrece apartar."""
    if context is None:
        return "Es solo una cotización. No es un pedido ni una reserva."
    if orders or clarifying:
        return ""
    return "¿Quieres que te lo aparte para que pases a recogerlo?"


def short_stock_text(lines: list[dict], products: dict, availability: dict) -> str:
    """«Uy, del tubo … solo me quedan 12 metros y necesitas 20. ¿Te cotizo los 12?»"""
    short = []
    for line in lines:
        product = products.get(line["sku"])
        stock = availability.get(line["sku"], {}).get("stock", product.stock if product else None)
        if product and stock is not None and line["quantity"] > stock:
            short.append((in_sentence(label(product.name, product.variant)), stock, line["quantity"], product.unit))
    if not short:
        return "No me alcanza para esa cantidad. ¿Te cotizo una cantidad menor?"
    # Agotado, ya lo dijo la frase del surtido: «solo me quedan 0 unidades» sobraba (suite surtido, U-10).
    short = [item for item in short if item[1] > 0]
    if not short:
        return ""
    text = "; ".join(f"{of_the(name)} solo me {'queda' if stock == 1 else 'quedan'} {stock} {units(unit, stock)} y "
                     f"necesitas {quantity}" for name, stock, quantity, unit in short)
    stock = short[0][1]
    offer = (f"¿Te cotizo {'el' if stock == 1 else 'los'} {stock}?" if len(short) == 1 and stock
             else "¿Te cotizo una cantidad menor?")
    return f"Uy, {text}. {offer}"


def order_lines(order: dict) -> str:
    """El resumen de un pedido con la misma forma que la cotización."""
    lines = [item_line(line["cantidad"], line.get("unidad", "unidad"), line.get("nombre", ""), line.get("variante", ""),
                       line["precio_unitario_cop"], line["subtotal_cop"]) for line in order["lineas"]]
    return "\n".join([*lines, f"Total: {format_cop(order['total_cop'])}"])
