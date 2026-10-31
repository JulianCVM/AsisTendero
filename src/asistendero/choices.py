"""Las opciones que el agente le mostró al cliente, para entender «dame del primero» o «la segunda, la de 60».

En la conversación del visor del 23-10 el agente listó tres tubos y el cliente respondió «dame del primero 3 metros»:
nadie sabía cuál era «el primero» y se cotizó otro tubo. La sesión guarda los grupos de opciones de la última
respuesta que mostró alguno (``shown_options``), en el mismo orden en que salen en pantalla, y Grok los recibe
numerados en ``conversacion.opciones``. Un ordinal dicho por el cliente (``chosen_options``) respalda ese producto
como si el cliente lo hubiera nombrado; la cantidad tiene que decirla igual. También vale el atributo que distingue a
una sola opción («el de 12», «la talla L», «la de galón»), como se elige en el mostrador.
"""

import re

from asistendero.catalog import tokens
from asistendero.context_resolution import (
    SALE_UNIT_TOKENS, _heads_in_text, affirms_active_item, filter_matches_by_spec, is_elliptical_turn,
    offered_short_quantity, pending_quantity_target, remembered_spec_for_item,
)
from asistendero.measures import SALE_UNITS, canonical_text, measures, split_atom
from asistendero.observations import ToolCall, latest_quote, order_results, search_findings
from asistendero.reply_text import MAX_NEARBY, MAX_OPTIONS, gender_of, in_sentence, label
from asistendero.search import CLAUSE_BREAK, NUMBER_WORDS
from asistendero.validation import (
    MAX_QUANTITY, SALE_UNIT, Rejected, foreign_unit, fractional_amount, grounded_products, grounded_selection,
    normalize_text, quantities_in_message, without_negated,
)


POSITIONS = {"primer": 1, "segund": 2, "tercer": 3, "cuart": 4, "quint": 5}
# Con artículo delante: «primero dime el horario» no elige nada; «del primero» y «la segunda», sí.
ORDINAL = re.compile(r"\b(?:el|la|los|las|del|al|de\s+la|de\s+las|de\s+los)\s+"
                     r"(?:(primer|segund|tercer|cuart|quint)[oa]?s?|(ultim)[oa]s?)\b|\bopcion\s+(\d)\b")
# «el de 12», «la de galón», «la talla L»: hasta tres palabras después del artículo describen la opción.
ATTRIBUTE = re.compile(r"\b(?:el|la|los|las|del)\s+(?:de|talla|que\s+es\s+de)\s+((?:\S+\s*){1,3})")
NUMBER = re.compile(r"^\d+(?:[.,/]\d+)?$")
# «dame 3 de ese», en singular: «me llevo esos» puede ser todo lo mostrado. Sin «esta», que también es el verbo
# («¿cuánto está?»).
DEMONSTRATIVE = re.compile(r"\b(?:es[eao]|est[eo]|aquel(?:la|lo)?)\b")
# Lo que acompaña una respuesta suelta a «¿cuál?» sin describir otro producto: «pues el negro, deme 15 metros porfa».
FILLERS = {"deme", "dame", "quiero", "necesito", "porfa", "pues", "pue", "mejor", "entonces", "listo", "ok", "unos",
           "unas", "llevo", "lleva", "seria", "sea", "sean", "favor"}
COUNTED = re.compile(r"\b(\d+)\s+([a-z]+)")
# «de 50» responde a «¿de 25 o de 50 kg?»; «deme 50» no, porque ahí el número es la cantidad.
OF_NUMBER = re.compile(r"\bde\s+(\d+(?:[.,/]\d+)?)\b", re.IGNORECASE)
_NUM_OR_WORD = rf"(?:\d{{1,2}}|{'|'.join(NUMBER_WORDS)})"
_NON_PAGINATION_NOUN = (
    r"(?:medidas?|tamanos?|calibres?|presentaciones?|marcas?|colores?|productos?|cosas?|herramientas?|materiales?)"
)
MORE_OPTIONS = re.compile(
    rf"\b(?:(?:las|los|esas|esos)\s+)?(?:otr[oa]s|demas)\s+(?:{_NUM_OR_WORD}\s+)?(?:opcion(?:es)?|variantes?)\b"
    rf"|\b(?:muestr\w+|mostrar|ver|dime|cuales\s+son|que)\s+(?:las\s+|los\s+)?(?:otr[oa]s|demas)"
    rf"(?!\s+{_NON_PAGINATION_NOUN}\b)(?:\s+{_NUM_OR_WORD})?(?:\s+(?:opcion(?:es)?|variantes?))?\b"
    rf"|\b(?:las|los)\s+otr[oa]s\s+{_NUM_OR_WORD}\b(?!\s+{_NON_PAGINATION_NOUN}\b)"
    rf"|\b(?:mas|todas\s+las)\s+(?:opcion(?:es)?|variantes?)\b"
    rf"|\b(?:cuales\s+(?:faltan|quedan)|las\s+(?:restantes|que\s+faltan)|opcion(?:es)?\s+restantes)\b"
)
_REQUESTED_PAGE_COUNT = re.compile(rf"\b(?:otr[oa]s|demas)\s+({_NUM_OR_WORD})\b")


def _option(product) -> dict:
    return {"sku": product.sku, "nombre": product.name, "variante": product.variant, "unidad": product.unit}


def _group_heads(group: dict) -> set[str]:
    heads = set(_heads_in_text(str(group.get("grupo") or "")))
    for item in (group.get("opciones") or []) + (group.get("restantes") or []):
        heads.update(_heads_in_text(str(item.get("nombre") or "")))
    return heads


def pagination_group(message: str, context: dict | None) -> dict | None:
    """Grupo de opciones activo del que el cliente pide ver las demás opciones, o None si no aplica."""
    groups = (context or {}).get("opciones") or []
    if not groups:
        return None
    norm = normalize_text(message)
    if SALE_UNIT.search(norm) or "otra cosa" in norm or ORDINAL.search(norm) or not MORE_OPTIONS.search(norm):
        return None
    msg_heads = set(_heads_in_text(norm))
    if len(groups) == 1:
        group = groups[0]
        return group if not msg_heads or msg_heads <= _group_heads(group) else None
    if msg_heads:
        matching = [group for group in groups if msg_heads <= _group_heads(group)]
        return matching[0] if len(matching) == 1 else None
    with_overflow = [group for group in groups if group.get("restantes")]
    return with_overflow[0] if len(with_overflow) == 1 else None


def asks_more_options(message: str, context: dict | None) -> dict | None:
    """Grupo activo con opciones excedentes (``restantes``) que el cliente pidió mostrar."""
    group = pagination_group(message, context)
    return group if group and group.get("restantes") else None


def next_options_page(group: dict, message: str = "") -> tuple[list[dict], list[dict]]:
    """(opciones_a_mostrar_ahora, opciones_que_aun_quedan) para avanzar la paginación sin repetir las anteriores."""
    remaining = [{k: v for k, v in item.items() if k != "n"} for item in (group.get("restantes") or [])]
    if len(remaining) <= 5:
        return remaining, []
    match = _REQUESTED_PAGE_COUNT.search(normalize_text(message))
    raw = match.group(1) if match else ""
    wanted = (int(raw) if raw.isdigit() else NUMBER_WORDS.get(raw, 0)) if raw else 0
    page_size = wanted if 1 <= wanted <= 5 else MAX_OPTIONS
    return remaining[:page_size], remaining[page_size:]


def shown_options(
    reference: str, calls: list[ToolCall], current: str | None = None, context: dict | None = None,
) -> list[dict]:
    """Grupos de opciones que mostró la respuesta de este turno, como los arma ``answers.render_answer``.

    ``current`` es el mensaje del turno: lo que el cliente dijo que no quiere tampoco se mostró.
    """
    asked = current or reference
    quote, _ = latest_quote(calls)
    if not quote and not order_results(calls) and (page_group := asks_more_options(asked, context)) is not None:
        shown_now, still_left = next_options_page(page_group, asked)
        updated_groups = []
        for group in (context or {}).get("opciones") or []:
            if group is page_group or group.get("grupo") == page_group.get("grupo"):
                entry = {"grupo": group["grupo"], "opciones": shown_now}
                if still_left:
                    entry["restantes"] = still_left
                updated_groups.append(entry)
            else:
                kept = {
                    "grupo": group["grupo"],
                    "opciones": [{k: v for k, v in item.items() if k != "n"} for item in (group.get("opciones") or [])],
                }
                if group.get("restantes"):
                    kept["restantes"] = [{k: v for k, v in item.items() if k != "n"} for item in group["restantes"]]
                updated_groups.append(kept)
        return updated_groups

    quoted = {line["sku"] for line in (quote or {}).get("lines", [])}
    picked_skus = {opt["sku"] for opt in chosen_options(asked, context) if opt.get("sku")}
    if not picked_skus and (aff := affirms_active_item(asked, context)) and aff.get("sku"):
        picked_skus = {aff["sku"]}
    groups = []
    seen = set()
    for finding in search_findings(calls):
        finding = without_negated(asked, finding)
        spec = remembered_spec_for_item(finding["query"], finding["request"].get("product"), asked, context)
        matches = filter_matches_by_spec(list(finding["matches"]), spec)
        nearby = finding["nearby"]
        same = (tuple(item.sku for item in matches), tuple(item.sku for item in nearby)) if matches or nearby else (
            finding["query"],
        )
        if same in seen:
            continue
        seen.add(same)
        filtered_finding = {**finding, "matches": matches}
        in_picked = [item for item in matches if item.sku in picked_skus]
        if matches and (
            grounded_selection(reference, filtered_finding)
            or any(item.sku in quoted for item in matches)
            or len(in_picked) == 1
        ):
            continue
        shown = matches[:MAX_OPTIONS] if matches else nearby[:MAX_NEARBY]
        overflow = matches[MAX_OPTIONS:] if matches else []
        if shown:
            entry = {"grupo": finding["query"], "opciones": [_option(item) for item in shown]}
            if overflow:
                entry["restantes"] = [_option(item) for item in overflow]
            groups.append(entry)
    return groups


def _position(match: re.Match) -> int:
    word, last, number = match.groups()
    return POSITIONS[word] if word else (-1 if last else int(number))


def _by_attribute(said: str, options: list[dict]) -> dict | None:
    """La única opción que describe lo dicho: toda su variante está dicha, o tiene cada número que se dijo."""
    words = tokens(said)
    variants = [tokens(option["variante"]) for option in options]
    whole = [option for option, variant in zip(options, variants) if variant and variant <= words]
    if len(whole) == 1:
        return whole[0]
    numbers = {word for word in words if NUMBER.match(word)}
    wanted = numbers or words
    holding = [option for option, variant in zip(options, variants) if wanted <= variant]
    return holding[0] if len(holding) == 1 else None


def _bare_answer(text: str, group: dict) -> dict | None:
    """La opción que nombra una respuesta suelta («Negro, 15 metros»), si el mensaje no dice nada más.

    M-03 (corrida 35): tras «¿cuál?» con blanco, negro y rojo, «Negro, 15 metros» no respaldaba el cable negro y la
    cotización se rechazó dos veces. La cantidad cuenta solo si va con la unidad de la opción; otro número («de 14»)
    tiene que ser de la opción, o no se elige nada. En la corrida del video (25-10), tras «¿el bulto de 25 o de 50
    kg?», «de 50» tampoco elegía: un número dicho con «de» elige la única opción que lo tiene en su variante.
    """
    options = group["opciones"]
    counted = set()
    for number, unit in COUNTED.findall(text):
        if any(tokens(unit) & tokens(option.get("unidad") or "") for option in options):
            counted |= {number} | tokens(unit)
    said = tokens(text) - counted - FILLERS
    whole = [option for option in options if option.get("variante") and tokens(option["variante"]) <= said]
    numbers = set(OF_NUMBER.findall(text)) - counted
    if len(whole) != 1 and numbers:
        whole = [option for option in options if numbers <= tokens(option.get("variante") or "")]
    if len(whole) != 1:
        return None
    option = whole[0]
    known = (tokens(option["variante"]) | tokens(option.get("nombre") or "") | tokens(group["grupo"])
             | tokens(option.get("unidad") or ""))
    return option if said <= known else None


def chosen_options(message: str, context: dict | None) -> list[dict]:
    """Opciones que el cliente eligió por su orden; [] si no dijo un orden o no se sabe de qué grupo habla."""
    groups = (context or {}).get("opciones") or []
    text = normalize_text(message)
    chosen = []
    for clause in CLAUSE_BREAK.split(text):
        for match in ORDINAL.finditer(clause):
            # Con varios grupos, el cliente dice de cuál («de esa manguera la segunda», o «de la manguera, la
            # segunda» en otra parte del mensaje); si no, no se adivina.
            named = ([group for group in groups if tokens(group["grupo"]) & tokens(clause)]
                     or [group for group in groups if tokens(group["grupo"]) & tokens(text)])
            candidates = named or (groups if len(groups) == 1 else [])
            if len(candidates) != 1:
                continue
            options, position = candidates[0]["opciones"], _position(match)
            index = position - 1 if position > 0 else position
            if -len(options) <= index < len(options) and options[index] not in chosen:
                chosen.append(options[index])
        for match in ATTRIBUTE.finditer(clause):
            named = ([group for group in groups if tokens(group["grupo"]) & tokens(clause)]
                     or [group for group in groups if tokens(group["grupo"]) & tokens(text)])
            candidates = named or (groups if len(groups) == 1 else [])
            option = _by_attribute(match.group(1), candidates[0]["opciones"]) if len(candidates) == 1 else None
            if option and option not in chosen:
                chosen.append(option)
    if not chosen and len(groups) == 1:
        option = _bare_answer(text, groups[0])
        if option:
            chosen = [option]
        elif len(groups[0].get("opciones") or []) == 1 and (affirmed := affirms_active_item(message, context)):
            chosen = [affirmed]
    return chosen


def unresolved_ordinal(message: str, context: dict | None) -> str | None:
    """Pregunta de aclaración si el cliente dijo un ordinal sobre las opciones activas que no resuelve ninguna."""
    groups = (context or {}).get("opciones") or []
    if not groups or chosen_options(message, context):
        return None
    norm = normalize_text(message)
    if not ORDINAL.search(norm) or _heads_in_text(norm):
        return None
    if len(groups) > 1:
        return "¿De cuál de los productos que te mostré me hablas?"
    count = len(groups[0].get("opciones") or [])
    return f"Solo te mostré {count} {'opción' if count == 1 else 'opciones'}; ¿cuál de esas te sirve?"


_ALLOWED_QTY_WORDS = (
    set(NUMBER_WORDS)
    | SALE_UNIT_TOKENS
    | {
        "m", "mt", "mts", "ud", "uds", "und", "unds", "media", "docena", "ciento",
        "dame", "deme", "quiero", "necesito", "seria", "serian", "cotizame", "cotiza",
        "por", "favor", "porfa", "gracias", "solo", "solamente", "unos", "unas",
        "entonces", "pues", "bueno", "listo", "dale", "si", "claro",
        "las", "los", "el", "la", "me", "nos", "llevo", "llevamos", "llevar",
        "ponle", "ponme", "pon", "dejame", "deje", "dejamelos", "dejamelas",
        "esos", "esas", "este", "esta", "estos", "estas", "con", "de",
    }
)


def pending_quantity_quote(message: str, context: dict | None) -> tuple[dict, int] | None:
    """(producto_en_foco, cantidad) si el asistente acaba de pedir cantidad/metraje y el cliente dio solo magnitud."""
    target = pending_quantity_target(context)
    if target is None or "?" in message or fractional_amount(message) is not None:
        return None
    norm = " ".join(canonical_text(message).split())
    if not norm or OF_NUMBER.search(norm) or ORDINAL.search(normalize_text(message)) or re.search(r"\d+\s*/\s*\d+", norm):
        return None
    if _heads_in_text(norm):
        return None
    for atom in measures(message):
        num, unit = split_atom(atom)
        if "x" in atom or "/" in num or "." in num or (unit is not None and unit not in SALE_UNITS):
            return None
    words = re.findall(r"[a-z0-9]+", norm)
    if not words or not all(word.isdigit() or word in _ALLOWED_QTY_WORDS for word in words):
        return None
    valid = [qty for qty in quantities_in_message(message) if 1 <= qty <= MAX_QUANTITY]
    if len(valid) != 1:
        return None
    quantity = valid[0]
    target_unit = f"{target.get('unidad') or ''} {target.get('variante') or ''}".strip()
    if target_unit and foreign_unit(message, quantity, target_unit):
        return None
    return target, quantity


def coherent_option_turn(message: str, context: dict | None) -> bool:
    """True si el cliente navega o aclara coherentemente dentro del árbol de opciones o contexto activo."""
    return bool(
        pagination_group(message, context)
        or chosen_options(message, context)
        or unresolved_ordinal(message, context)
        or affirms_active_item(message, context)
        or offered_short_quantity(message, context)
        or pending_quantity_quote(message, context)
        or is_elliptical_turn(message, context)
    )


def without_chosen_measures(text: str, picked: list[dict]) -> str:
    """El texto sin el «de 50» que eligió una opción: ese número es su medida, no la cantidad que se cotiza.

    Corrida del video (25-10): con «de 50» como única cifra del turno, el 50 quedaba como cantidad dicha y tapaba los
    «2 bultos» del turno anterior; además, Grok habría podido cotizar 50 bultos.
    """
    measures = set().union(*(tokens(option.get("variante") or "") for option in picked)) if picked else set()
    return OF_NUMBER.sub(lambda match: " " if match.group(1) in measures else match.group(0), text)


def ambiguous_reference(message: str, context: dict | None) -> list[str]:
    """Los productos que puede ser «ese» cuando el cliente no dice cuál; [] si no hay duda.

    Z-36 (suite fallas): tras preguntar por la brocha y el rodillo, «dame 3 de ese» cotizó la brocha. Hay duda si
    la respuesta anterior nombró más de un producto de la sesión y el mensaje no nombra ninguno ni elige una opción.
    """
    text = normalize_text(message)
    products = [item for item in (context or {}).get("productos") or [] if item.get("nombre")]
    # «me llevo todo eso» habla de todo lo mostrado (N-02).
    if not DEMONSTRATIVE.search(text) or re.search(r"\btod[oa]s?\b", text) or chosen_options(message, context):
        return []
    said = tokens(text)
    if any(tokens(item["nombre"].split()[0], synonyms=False) & said for item in products):
        return []
    turns = (context or {}).get("turnos") or []
    last = tokens(normalize_text(turns[-1].get("asistente", ""))) if turns else set()
    shown = {}
    for item in products:
        if tokens(item["nombre"].split()[0], synonyms=False) & last:
            article = "la" if gender_of(item["nombre"])[0] else "el"
            shown.setdefault(item["nombre"], f'{article} {in_sentence(label(item["nombre"], item.get("variante") or ""))}')
    return list(shown.values()) if len(shown) > 1 else []


def check_reference(tool: str, arguments: object, message: str, calls: list[ToolCall], context: dict | None) -> None:
    """Rechaza cotizar o registrar «ese» si puede ser más de un producto y el mensaje no distingue cuál."""
    if tool not in {"calcular_cotizacion_informativa", "registrar_pedido"} or not isinstance(arguments, dict):
        return
    options = ambiguous_reference(message, context)
    said = grounded_products(message, calls)
    lines = arguments.get("lines") if isinstance(arguments.get("lines"), list) else []
    if options and any(isinstance(line, dict) and line.get("sku") not in said for line in lines):
        raise Rejected("AMBIGUOUS_REFERENCE", f"«ese» puede ser {' o '.join(options)}: pregúntale al cliente cuál.")
