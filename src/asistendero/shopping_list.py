"""La lista de la conversación: lo que el cliente ha ido cotizando, con la cantidad que dijo.

En una conversación larga el cliente arma su compra por partes («un metro de tubo conduit», luego «agrega una
manguera de abasto», luego «¿cuánto es todo?»). Los turnos recientes no bastaban: la cantidad del tubo pudo decirse
diez mensajes antes y Grok cotizaba solo la manguera. La sesión guarda la lista con SKU, nombre y cantidad, nunca el
precio (se relee al cotizar), y Grok la recibe en ``conversacion.lista``. Una línea de la lista cuenta como dicha por
el cliente: se puede cotizar o registrar con esa misma cantidad sin que la repita.

Cómo cambia en cada turno (``updated_list``):

- una cotización del turno suma sus líneas y actualiza la cantidad de las que ya estaban;
- «quita la manguera» saca de la lista lo que el cliente nombró; «empecemos de nuevo» la vacía;
- lo que entra a un pedido sale de la lista: ya quedó apartado y tiene su propio total.

Cabe en una sola cotización (``MAX_LIST_LINES``): si se pasa, quedan las líneas más recientes.
"""

import re

from asistendero.catalog import tokens
from asistendero.choices import chosen_options
from asistendero.grok import MAX_ITEMS
from asistendero.observations import ToolCall, latest_quote, order_results
from asistendero.validation import normalize_text, quantities_in_message


MAX_LIST_LINES = MAX_ITEMS
# Pedir el total de lo que lleva: siempre se cotiza la lista entera.
WHOLE_LIST = re.compile(
    r"\b(?:todo|toda\s+la\s+lista|(?:en\s+)?total|junto\s+con|lo\s+(?:demas|anterior|otro)"
    r"|con\s+(?:el|la|los|las)\s+(?:otr[oa]s?|anterior\w*|\w+\s+que\s+te\s+dije|que\s+te\s+dije)|cuanto\s+(?:me\s+)?(?:sale|queda|seria|es)\s+todo)\b"
)
# Sumar algo con su cantidad («agrega una manguera», «y también 2 brochas»): la lista más lo nuevo.
ADDS = re.compile(r"\b(?:agreg\w*|anad\w*|suma(?:le|me)?|ponle|ponme|tambien|ademas)\b")
REMOVES = re.compile(
    r"\b(?:quit(?:a|ale|alo|ala|alos|alas|ame|ar|en)|saca(?:le|lo|la|los|las|me)?|elimin\w*"
    r"|ya\s+no\s+(?:quiero|necesito|me\s+lleves?)|no\s+(?:quiero|necesito)\s+(?:el|la|los|las))\b"
)
RESTART = re.compile(r"\b(?:borr\w*\s+(?:la\s+lista|todo)|(?:empe[zc]|comen[zc])\w*\s+de\s+(?:nuevo|cero)|desde\s+cero"
                     r"|(?:nueva|otra)\s+cotizacion)\b")


def list_lines(context: dict | None) -> dict[str, int]:
    """SKU → cantidad de la lista de la sesión: lo que el cliente ya dijo que lleva."""
    return {item["sku"]: item["cantidad"] for item in (context or {}).get("lista") or []
            if isinstance(item.get("sku"), str) and isinstance(item.get("cantidad"), int)}


def usable_lines(message: str, context: dict | None) -> dict[str, int]:
    """La lista que respalda cantidades en este turno: nada si el cliente empezó de nuevo y sin lo que quitó.

    Con «empecemos de nuevo: necesito 2 brochas, ¿cuánto es todo?» Grok cotizó también el tubo de antes y la lista
    lo respaldaba (suite memoria con Grok real, 23-10-2026).
    """
    text = normalize_text(message)
    if RESTART.search(text):
        return {}
    removed = _named((context or {}).get("lista") or [], text) if REMOVES.search(text) else set()
    return {sku: quantity for sku, quantity in list_lines(context).items() if sku not in removed}


def asks_whole_list(message: str) -> bool:
    """El cliente pide el total o suma algo con cantidad: la cotización tiene que llevar toda la lista."""
    text = normalize_text(message)
    return bool(WHOLE_LIST.search(text) or (ADDS.search(text) and quantities_in_message(message)))


def _named(items: list[dict], text: str) -> set[str]:
    """SKU de la lista que el cliente nombró; con dos del mismo nombre, el que más palabras comparte."""
    said = tokens(text)
    heads = [item for item in items if tokens(item["nombre"].split()[0], synonyms=False) & said]
    if len(heads) < 2:
        return {item["sku"] for item in heads}
    scores = {item["sku"]: len(tokens(f"{item['nombre']} {item['variante']}") & said) for item in heads}
    best = max(scores.values())
    return {sku for sku, score in scores.items() if score == best}


def removed_now(items: list[dict], message: str) -> set[str]:
    """SKU que el cliente quita en este mensaje: lo que nombra después de «quítale», hasta la coma o el «pero».

    Z-33 (suite fallas): con «sí, pero quítale el cemento» Grok registró solo el cemento.
    """
    text = normalize_text(message)
    match = REMOVES.search(text)
    if not match:
        return set()
    return _named(items, re.split(r"[,;.]|\bpero\b", text[match.end():])[0])


def updated_list(previous: list[dict], message: str, calls: list[ToolCall]) -> list[dict]:
    """La lista después del turno: ``previous`` más lo cotizado, menos lo quitado y lo que entró a un pedido."""
    text = normalize_text(message)
    items = {} if RESTART.search(text) else {item["sku"]: dict(item) for item in previous}
    if REMOVES.search(text):
        for sku in _named(list(items.values()), text):
            items.pop(sku)
    quote, _ = latest_quote(calls)
    for line in (quote or {}).get("lines", []):
        if all(isinstance(line.get(key), str) for key in ("name", "variant", "unit")):
            items[line["sku"]] = {"sku": line["sku"], "nombre": line["name"], "variante": line["variant"],
                                  "unidad": line["unit"], "cantidad": line["quantity"]}
    ordered = {line.get("sku") for tool, order in order_results(calls) if tool == "registrar_pedido"
               for line in order["lineas"]}
    return [item for sku, item in items.items() if sku not in ordered][-MAX_LIST_LINES:]


def missing_from_quote(message: str, calls: list[ToolCall], context: dict | None) -> list[str]:
    """SKU que faltan en la cotización del turno; [] si no aplica.

    Faltan las líneas de la lista cuando el cliente pidió el total, y la opción que eligió por su orden cuando dio
    cantidad o pidió el total: con «dame de esa manguera la segunda, unas 3, ¿cuánto queda todo?» Grok cotizó solo
    el tubo (visor, 23-10). No aplica a la lista si el cliente quitó algo o empezó de nuevo, ni si el turno movió
    un pedido o la cotización falló (por existencias, se le dice cuánto hay en vez de insistir).
    """
    text = normalize_text(message)
    whole = asks_whole_list(message)
    listed = [] if not whole or REMOVES.search(text) or RESTART.search(text) else list(list_lines(context))
    chosen = [item["sku"] for item in chosen_options(message, context)] if whole or quantities_in_message(message) else []
    if not listed + chosen or order_results(calls):
        return []
    quote, quote_call = latest_quote(calls)
    if quote_call is not None and quote is None:
        return []
    quoted = {line["sku"] for line in (quote or {}).get("lines", [])}
    return [sku for sku in dict.fromkeys(listed + chosen) if sku not in quoted]
