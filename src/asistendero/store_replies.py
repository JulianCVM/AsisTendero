"""Respuestas sobre la tienda y sus categorías, armadas solo con lo que devolvieron las herramientas."""

import re

from asistendero.catalog import tokens
from asistendero.observations import ToolCall, category_listings, store_info_by_topic


DAY_NAMES = {"lunes": "lunes", "martes": "martes", "miercoles": "miércoles", "jueves": "jueves",
             "viernes": "viernes", "sabado": "sábado", "domingo": "domingo"}
MAX_LISTED_PRODUCTS = 15
# «Estamos abiertos» cuando el servidor dice que está cerrada (o al revés) invalida la redacción de Grok.
SAYS_OPEN = re.compile(r"\b(?:estamos|esta|seguimos|ya)\s+abiert|\babiert[oa]s?\s+(?:ahora|en\s+este\s+momento)")
SAYS_CLOSED = re.compile(r"\b(?:estamos|esta|ya)\s+cerrad|\bcerrad[oa]s?\s+(?:ahora|en\s+este\s+momento)")

# Políticas que Grok solo puede afirmar si consultó ese tema en la ejecución: en la primera corrida S3
# cerró una cotización con «pago al retirar» sin haber consultado medios de pago.
POLICY_CLAIMS = {
    "medios_pago": re.compile(r"\b(?:efectivo|tarjetas?|nequi|daviplata|transferencias?|contraentrega"
                              r"|pago\s+(?:al|en|con|contra)|pagar\s+(?:al|en|con))\b"),
    "domicilios": re.compile(r"\b(?:domicilios?|envios?|enviamos|despachamos)\b"),
    "garantias": re.compile(r"\b(?:garantias?|devoluci\w+)\b"),
    "ubicacion": re.compile(r"\b(?:calle|carrera|direccion)\b"),
    "facturacion": re.compile(r"\b(?:iva|impuestos?|factura\s+electronica|facturamos|facturar\w*|emit\w+\s+factura)\b"),
}

# Si un precio lleva IVA no lo dice ningún tema de la tienda: ni consultando «facturacion» se puede afirmar.
IVA_CLAIM = re.compile(r"\b(?:incluy\w*|incluid\w*|traen|trae|llevan|lleva|tienen|sin|mas|con)\s+(?:el\s+)?iva\b"
                       r"|\biva\s+(?:incluid\w*|aparte|adicional)")


# «¿Qué venden?» pregunta por todo el surtido, no por un producto. En el visor (26-10) Grok buscó productos
# inventados hasta el límite (10 llamadas) y otra vez respondió «herramientas eléctricas y más», que el catálogo no
# tiene. Lo que pregunta el surtido se responde con explorar_categoria y la lista determinista de categorías.
ASSORTMENT_QUESTION = re.compile(
    r"\bque\s+(?:(?:cosas|productos|articulos|clase\s+de\s+(?:cosas|productos)|tipo\s+de\s+(?:cosas|productos))\s+)?"
    r"(?:venden|vende|vendes|tienen|tiene|tienes|manejan|maneja|manejas|ofrecen|ofrece|ofreces|hay|consigo)\b"
    r"|\b(?:catalogo|categorias|surtido)\b"
)
# Lo que acompaña la pregunta sin nombrar un producto: saludos, «aquí», «la ferretería».
ASSORTMENT_FILLER = tokens(
    "hola buenas buenos dias tardes noches veci vecino vecina amigo amiga senor senora don dona usted ustedes aqui aca "
    "ahi alla tienda ferreteria negocio cosas productos articulos todo muestrame mostrar ver catalogo categorias "
    "surtido venden manejan ofrecen", synonyms=False,
)


def asks_assortment(normalized_message: str) -> bool:
    """El mensaje (ya normalizado) pregunta qué vende la tienda en general, sin nombrar un producto ni categoría.

    «¿qué tienen de plomería?» no cuenta: nombra la categoría y se explora esa.
    """
    if not ASSORTMENT_QUESTION.search(normalized_message):
        return False
    rest = ASSORTMENT_QUESTION.sub(" ", normalized_message)
    return not tokens(rest, synonyms=False) - ASSORTMENT_FILLER


def full_category_listing(calls: list[ToolCall]) -> bool:
    """Se observó la lista completa de categorías (explorar_categoria sin argumentos)."""
    return any("categorias" in listing for listing in category_listings(calls))


def _hour(value: str) -> str:
    return value.lstrip("0") if not value.startswith("00") else value[1:]


def _schedule_text(days: dict) -> str:
    """Agrupa días seguidos con el mismo horario: «lunes a viernes de 7:00 a 18:00»."""
    groups: list[tuple[list[str], list[str] | None]] = []
    for day in DAY_NAMES:
        hours = days.get(day)
        if groups and groups[-1][1] == hours:
            groups[-1][0].append(day)
        else:
            groups.append(([day], hours))
    parts = []
    for names, hours in groups:
        label = f"el {DAY_NAMES[names[0]]}" if len(names) == 1 else f"de {DAY_NAMES[names[0]]} a {DAY_NAMES[names[-1]]}"
        parts.append(f"{label} de {_hour(hours[0])} a {_hour(hours[1])}" if hours else f"{label} cerrado")
    return ", ".join(parts[:-1]) + " y " + parts[-1] if len(parts) > 1 else parts[0]


def store_lines(calls: list[ToolCall]) -> list[str]:
    """Líneas de la respuesta determinista para información de la tienda y categorías."""
    lines = []
    for topic, data in store_info_by_topic(calls).items():
        if topic == "horario" and isinstance(data.get("dias"), dict):
            now = "Ahora mismo estamos abiertos." if data.get("abierto_ahora") else "Ahora mismo estamos cerrados."
            lines.append(f"Atendemos {_schedule_text(data['dias'])}. {data.get('festivos', '')} {now}"
                         .replace("  ", " "))
        elif isinstance(data.get("texto"), str):
            lines.append(data["texto"])
    for listing in category_listings(calls):
        if "categorias" in listing:
            # Una línea por categoría, tal como está en el catálogo: nada de «y más» ni familias que no existen.
            names = "\n".join(f"• {item['categoria']}" for item in listing["categorias"])
            lines.append(f"Manejamos artículos de ferretería en {len(listing['categorias'])} categorías:\n{names}\n"
                         "¿Qué estás buscando? Dime el producto y la medida, y te doy precio y disponibilidad.")
        else:
            products = listing["productos"]
            shown = [item["nombre"] for item in products[:MAX_LISTED_PRODUCTS]]
            more = f" y {len(products) - len(shown)} más" if len(products) > len(shown) else ""
            lines.append(f"En {listing['categoria']} hay: {', '.join(shown)}{more}. Dime cuál y qué medida "
                         "necesitas para darte precio y existencias.")
    return lines


def store_allowances(calls: list[ToolCall]) -> tuple[set[str], set[str], bool | None]:
    """Montos, horas y estado de apertura que la redacción de Grok puede afirmar sobre la tienda."""
    amounts, hours, open_now = set(), set(), None
    for topic, data in store_info_by_topic(calls).items():
        amounts |= set(re.findall(r"\$[\d.,]*\d", data.get("texto", "")))
        if topic == "horario" and isinstance(data.get("dias"), dict):
            open_now = data.get("abierto_ahora")
            for value in data["dias"].values():
                hours |= {_hour(item) for item in value or []}
    return amounts, hours, open_now


def store_reply_is_consistent(
    normalized_reply: str, calls: list[ToolCall], paid_at_pickup: bool = False,
) -> tuple[bool, set[str]]:
    """(¿la redacción respeta horario y apertura?, montos de la tienda que puede citar).

    ``paid_at_pickup``: hubo un pedido observado, que ya dice que el pago es en el mostrador al recoger.
    """
    amounts, hours, open_now = store_allowances(calls)
    consulted = set(store_info_by_topic(calls)) | ({"medios_pago"} if paid_at_pickup else set())
    if any(topic not in consulted and pattern.search(normalized_reply) for topic, pattern in POLICY_CLAIMS.items()):
        return False, amounts
    if IVA_CLAIM.search(normalized_reply):
        return False, amounts
    said_hours = {_hour(value) for value in re.findall(r"\b\d{1,2}:\d{2}\b", normalized_reply)}
    if not said_hours <= hours:
        return False, amounts
    if open_now is None and (SAYS_OPEN.search(normalized_reply) or SAYS_CLOSED.search(normalized_reply)):
        return False, amounts
    if open_now is False and SAYS_OPEN.search(normalized_reply):
        return False, amounts
    if open_now is True and SAYS_CLOSED.search(normalized_reply):
        return False, amounts
    return True, amounts
