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
from asistendero.observations import ToolCall, latest_quote, search_findings
from asistendero.reply_text import MAX_NEARBY, MAX_OPTIONS, gender_of, in_sentence, label
from asistendero.search import CLAUSE_BREAK
from asistendero.validation import Rejected, grounded_products, grounded_selection, normalize_text, without_negated


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


def _option(product) -> dict:
    return {"sku": product.sku, "nombre": product.name, "variante": product.variant, "unidad": product.unit}


def shown_options(reference: str, calls: list[ToolCall], current: str | None = None) -> list[dict]:
    """Grupos de opciones que mostró la respuesta de este turno, como los arma ``answers.render_answer``.

    ``current`` es el mensaje del turno: lo que el cliente dijo que no quiere tampoco se mostró.
    """
    quote, _ = latest_quote(calls)
    quoted = {line["sku"] for line in (quote or {}).get("lines", [])}
    groups = []
    for finding in search_findings(calls):
        finding = without_negated(current or reference, finding)
        matches, nearby = finding["matches"], finding["nearby"]
        if matches and (grounded_selection(reference, finding) or any(item.sku in quoted for item in matches)):
            continue
        shown = matches[:MAX_OPTIONS] if matches else nearby[:MAX_NEARBY]
        if shown:
            groups.append({"grupo": finding["query"], "opciones": [_option(item) for item in shown]})
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
    tiene que ser de la opción, o no se elige nada.
    """
    options = group["opciones"]
    counted = set()
    for number, unit in COUNTED.findall(text):
        if any(tokens(unit) & tokens(option.get("unidad") or "") for option in options):
            counted |= {number} | tokens(unit)
    said = tokens(text) - counted - FILLERS
    whole = [option for option in options if option.get("variante") and tokens(option["variante"]) <= said]
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
        chosen = [option] if option else []
    return chosen


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
