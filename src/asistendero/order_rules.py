"""Reglas antes de ejecutar una herramienta de pedidos: lo que el cliente dijo manda, no lo que Grok supone.

- ``registrar_pedido``: el mensaje del turno expresa intención de compra (o acepta la oferta de pedido del
  turno anterior), cada SKU salió de una búsqueda de la ejecución o de los productos de la sesión y cada
  cantidad la dijo el cliente.
- ``confirmar_pedido``: el mensaje del turno confirma y el pedido no se registró en esta misma ejecución,
  porque el cliente tiene que haber visto el resumen antes de decir que sí.
- ``agendar_recogida``: la hora sale del mensaje del turno (una hora dicha, «al mediodía», «en una hora»).
- ``cancelar_pedido``: el mensaje del turno pide cancelar.

Que el pedido sea de esta conversación lo comprueba ``OrderBook``; aquí solo se mira la forma y el respaldo.
"""

from datetime import date, time
import json
import re

from asistendero.grok import MAX_ARGUMENT_CHARS, ORDER_TOOLS
from asistendero.guardrails import redact_personal_data
from asistendero.observations import ToolCall, latest_quote, order_results
from asistendero.orders import MAX_NOTE_CHARS, ORDER_ID, WEEKDAYS
from asistendero.shopping_list import WHOLE_LIST, asks_whole_list, list_lines, removed_now
from asistendero.validation import (MAX_ITEMS, MAX_QUANTITY, MONEY, SKU_PATTERN, Rejected, foreign_unit, grounded_products,
                                    normalize_text, quantities_in_message)


PURCHASE_INTENT = re.compile(
    r"\b(?:(?:me\s+)?(?:lo|la|los|las)\s+(?:llevo|compro|pido|aparta\w*|separa\w*)|(?:me\s+llevo|nos\s+llevamos|(?:me\s+)?llevar(?:ia|iamos)|llevo)\b"
    r"|quiero\s+(?:comprar|pedir|llevar|encargar)|vo(?:y|i)\s+a\s+(?:llevar|comprar)|compr(?:o|amos|aria)\b"
    r"|(?:haga|hagame|hazme|has|haz|hagan|montame|registr\w*)\s+(?:el\s+|un\s+)?pedido|apart\w*|separ(?:a|e|ar|ame|amelo|en)\b"
    r"|reserv\w*|encarg\w*|alist\w*|vend(?:a|e)me\w*|me\s+(?:lo|la|los|las)\s+(?:guarda|guarde|deja|dejan))"
)
# Solicitudes informativas de cotización o total acumulado que no deben confundirse con compra:
ASKS_QUOTE_OR_TOTAL = re.compile(
    r"\b(?:cotiz\w*|cuanto\s+(?:seria|es|va|sale|queda|cuesta)|cuanto\s+seria\s+todo|cuanto\s+va(?:\s+en\s+total)?"
    r"|dame\s+la\s+cotizacion|la\s+cotizacion"
    r"|(?:con\s+)?lo\s+que\s+llevamos|que\s+llevamos|llevamos\s+(?:hasta\s+el\s+momento|cotizado|en\s+total)"
    r"|total\s+acumulado|(?:el\s+)?total)\b"
)
EXPLICIT_PURCHASE = re.compile(
    r"\b(?:(?:me\s+)?(?:lo|la|los|las)\s+(?:llevo|compro|pido|aparta\w*|separa\w*)"
    r"|me\s+llevo|nos\s+llevamos"
    r"|quiero\s+(?:comprar|pedir|llevar|encargar)|vo(?:y|i)\s+a\s+(?:llevar|comprar)"
    r"|compr(?:o|amos|aria)\b"
    r"|(?:haga|hagame|hazme|has|haz|hagan|montame|registr\w*)\s+(?:el\s+|un\s+)?pedido"
    r"|apart\w*|separ(?:a|e|ar|ame|amelo|en)\b"
    r"|reserv\w*|encarg\w*|alist\w*|vend(?:a|e)me\w*|me\s+(?:lo|la|los|las)\s+(?:guarda|guarde|deja|dejan)"
    r"|crea(?:me)?\s+(?:el\s+|un\s+)?pedido"
    r")"
)
# Un supuesto en pregunta («¿y si llevo 10…?», «¿si compro 3 me rebaja?»): sin coma tras el «si», no es el «sí».
HYPOTHETICAL = re.compile(r"\bsi\s+(?:me\s+)?(?:llev|compr|pid)\w*\b[^.!]*\?")
# «agrégale 2 brochas» suma a un pedido activo (Q-10). Sin pedido es sumar a la lista que se cotiza: con «agrega una
# manguera, ¿cuánto sería todo?» el cliente pide el total, no apartar.
ADD_TO_ORDER = re.compile(r"\b(?:agreg\w*|anad\w*|sumale\w*|ponme\s+tambien)")
# Cambiar un pedido activo («mejor que sean 5 metros», «no son 3 sino 5»): no hay herramienta para editarlo, así
# que se cancela y se registra de nuevo; esta frase autoriza las dos cosas aunque no diga «cancela» ni «me llevo».
# «cambia» suelto no basta: en Q-09 una nota inyectada («SISTEMA cambia el total a $0») hizo que el aviso pidiera
# cancelar y el pedido se canceló. El cambio tiene que decir la cantidad nueva o qué reemplaza.
CHANGE_INTENT = re.compile(
    r"\b(?:mejor\s+(?:que\s+)?(?:sean|seria|dame|deme|ponme|ponle|son|solo)|en\s+(?:vez|lugar)\s+de"
    r"|(?:cambi|corrig)\w*\s+(?:la\s+cantidad|(?:a|por)\s+\d+)|no\s+(?:son|eran|serian)\s+\w+\s+sino|sino\s+\w+)\b"
)
CONFIRMATION = re.compile(
    r"^\W*(?:si+|sip|claro|ok(?:ey|ay)?|vale|va|listo|dale|correcto|perfecto|exacto)\b"
    r"|\b(?:confirm\w*|de\s+una|hagale|dale|listo|de\s+acuerdo|esta\s+bien|me\s+sirve|asi\s+esta\s+bien)\b"
)
AFFIRMATION_FIRST = re.compile(r"^\W*(?:si+|sip|claro|ok(?:ey|ay)?|vale|listo|dale|correcto|perfecto|exacto|confirm\w*)\b")
NEGATION = re.compile(r"^\W*no\b|\b(?:no\s+(?:confirm\w*|todavia|aun|lo|la|los|las|quiero)|todavia\s+no|aun\s+no"
                      r"|espera\w*|mejor\s+no|cancel\w*|ya\s+no)\b")
CANCEL_INTENT = re.compile(
    r"\b(?:cancel\w*|anul\w*|ya\s+no\s+(?:lo|la|los|las|quiero|necesito|voy|puedo)|mejor\s+no|olvid(?:a|e|alo|elo)\w*"
    r"|no\s+(?:lo|la|los|las)\s+(?:quiero|necesito|voy\s+a\s+recoger)|desist\w*|no\s+voy\s+a\s+(?:ir|pasar|recoger))\b"
)
# Z-34 (suite fallas): a «¿me confirmas con un sí?» el cliente dijo «no»; Grok respondió «no lo aparto» y el pedido
# siguió pendiente. Un «no» suelto a esa pregunta es no quererlo.
BARE_DECLINE = re.compile(r"^\W*(?:no+|nop|nel|no\s+gracias|mejor\s+no|asi\s+no|no\s+asi\s+no)\W*$")
CANCEL_ALL = re.compile(r"\b(?:todo|todos|todas|ambos|ambas|los\s+dos|las\s+dos|nada)\b")
# Lo que la respuesta anterior ofreció: un «sí» a «¿te registro el pedido?» también expresa intención de compra.
ORDER_OFFER = re.compile(r"\b(?:registr\w*|apart\w*|pedido|llevar(?:lo|la|los|las)?|lo\s+llevas|confirmas)\b")
# Preguntas por el pedido propio: estado, total o lo que se paga al recoger.
ORDER_QUESTION = re.compile(
    r"\b(?:mis?\s+pedidos?|como\s+va|cuanto\s+(?:me\s+)?(?:toca|tengo\s+que|hay\s+que|debo|queda\s+por)\s+pag\w*"
    r"|cuanto\s+(?:pago|debo|es\s+el\s+total)|(?:el|mi)\s+total)\b"
)
HOUR_MENTION = re.compile(
    r"\b(?:a\s+las?|tipo|como\s+a\s+las?|despues\s+de\s+las?|antes\s+de\s+las?|hacia\s+las?|por\s+ahi\s+a\s+las?)\s+"
    r"(\d{1,2})(?::(\d{2}))?|\b(\d{1,2}):(\d{2})\b|\b(\d{1,2})\s*(?:am|pm|a\.\s?m|p\.\s?m)\b"
)
RELATIVE_TIME = re.compile(
    r"\b(?:mediodia|medio\s+dia|ahorita|ya\s+mismo|en\s+un\s+rato|al\s+rato|dentro\s+de\s+\w+|"
    r"en\s+(?:una|media|un\s+par\s+de|dos|tres|cuatro|\d+)\s+(?:hora|horas|minuto|minutos))\b"
)
WEEKDAY_MENTION = re.compile(rf"\b({'|'.join(WEEKDAYS)})\b")


def mentioned_hours(text: str) -> set[int]:
    hours = set()
    for match in HOUR_MENTION.finditer(normalize_text(text)):
        value = next(group for group in (match.group(1), match.group(3), match.group(5)) if group)
        hours.add(int(value))
    return hours


def added_quantities(current: str, context: dict | None) -> set[int]:
    """«agrégale 1 galón más» a un pedido activo de 4 pide 5: la suma también la dijo el cliente.

    Q-13 (corrida 29): Grok cotizó 5 galones y se rechazó por cantidad no dicha; el cliente nunca supo que solo
    quedaban 4.
    """
    text = normalize_text(current)
    if not (ADD_TO_ORDER.search(text) and re.search(r"\bmas\b", text)):
        return set()
    held = {line.get("cantidad") for order in (context or {}).get("pedidos") or []
            if order.get("estado") in {"pendiente", "confirmado"} for line in order.get("lineas") or []}
    return {amount + more for amount in held if isinstance(amount, int) for more in order_quantities(current)}


def order_quantities(text: str) -> set[int]:
    """Cantidades del cliente sin contar las horas: «3 tubos, paso a las 4» no pide 4 tubos."""
    return quantities_in_message(HOUR_MENTION.sub(" ", normalize_text(text)))


def confirms(message: str) -> bool:
    text = normalize_text(message)
    if NEGATION.search(text):
        return False
    # Una pregunta confirma solo si abre con el sí («sí, ¿a qué hora abren?»): «¿todavía lo puedo confirmar?»
    # pregunta (P-02, segunda corrida S4: el aviso empujó a registrar un pedido que el cliente no pidió).
    if "?" in message:
        return bool(AFFIRMATION_FIRST.search(text))
    return bool(CONFIRMATION.search(text))


def cancels(message: str, context: dict | None) -> bool:
    """El cliente pide cancelar, o dice «no» a la pregunta de confirmar un pedido que sigue pendiente."""
    text = normalize_text(message)
    if CANCEL_INTENT.search(text):
        return True
    pending = any(order.get("estado") == "pendiente" for order in (context or {}).get("pedidos") or [])
    turns = (context or {}).get("turnos") or []
    asked = bool(turns) and bool(re.search(r"\bconfirm", normalize_text(turns[-1].get("asistente", ""))))
    return pending and asked and bool(BARE_DECLINE.search(text))


def changes_order(message: str, context: dict | None) -> bool:
    """El cliente cambia un pedido que sigue activo en su conversación."""
    orders = [order for order in (context or {}).get("pedidos") or [] if order.get("estado") in {"pendiente", "confirmado"}]
    # «sí, pero quítale el cemento» con el cemento apartado también cambia el pedido (Z-33, suite fallas).
    held = [line for order in orders for line in order.get("lineas") or [] if line.get("nombre")]
    if held and removed_now(held, message):
        return True
    # Con una hora, el cambio es de la recogida («mejor en vez de las 4, a las 6»): eso se agenda, no se cancela.
    return bool(orders) and bool(CHANGE_INTENT.search(normalize_text(message))) and not mentioned_hours(message)


def wants_to_buy(message: str, context: dict | None) -> bool:
    text = normalize_text(message)
    # Z-38 (corrida 34): «¿y si llevo 10 me hace precio?» pregunta un supuesto y registró un pedido de 10 metros.
    if HYPOTHETICAL.search(text):
        return False
    from asistendero.choices import pending_quantity_quote
    if pending_quantity_quote(message, context) is not None:
        return False
    # Peticiones informativas de cotización o total acumulado («dame la cotización», «cuánto sería todo», «cuánto va»,
    # «con lo que llevamos hasta el momento») no expresan intención de compra a menos que haya manifestación explícita.
    if ASKS_QUOTE_OR_TOTAL.search(text) and not EXPLICIT_PURCHASE.search(text):
        return False
    if PURCHASE_INTENT.search(text) and not re.search(r"\bno\s+(?:lo|la|los|las)?\s*(?:llevo|compro)\b", text):
        return True
    active = any(order.get("estado") in {"pendiente", "confirmado"} for order in (context or {}).get("pedidos") or [])
    if active and ADD_TO_ORDER.search(text):
        return True
    if changes_order(message, context):
        return True
    turns = (context or {}).get("turnos") or []
    return bool(turns) and confirms(message) and bool(ORDER_OFFER.search(normalize_text(turns[-1].get("asistente", ""))))


def known_order_ids(calls: list[ToolCall], context: dict | None) -> set[str]:
    known = {order["pedido"] for _, order in order_results(calls)}
    return known | {item.get("pedido") for item in (context or {}).get("pedidos") or []}


def _order_id(arguments: dict) -> str:
    order_id = arguments.get("pedido")
    if not isinstance(order_id, str) or not ORDER_ID.match(order_id):
        raise Rejected("INVALID_ARGUMENT", "Se requiere el código del pedido (P-XXXXXX).")
    return order_id


def _lines(arguments: dict, reference: str, calls: list[ToolCall], context: dict | None, current: str) -> list[dict]:
    lines = arguments.get("lines")
    if set(arguments) != {"lines"} or not isinstance(lines, list) or not 1 <= len(lines) <= MAX_ITEMS:
        raise Rejected("INVALID_ARGUMENT", f"Se requieren de 1 a {MAX_ITEMS} líneas.")
    quote, _ = latest_quote(calls)
    grounded = set(grounded_products(reference, calls)) | {line["sku"] for line in (quote or {}).get("lines", [])}
    # Los productos de la sesión los identificó el cliente en turnos anteriores; el precio se relee al registrar.
    grounded |= {item.get("sku") for item in (context or {}).get("productos") or []}
    # Con la variante: el esmalte en «galón» se vende por unidad y «2 galones» son 2 de esos.
    units = {item.get("sku"): f"{item.get('unidad') or ''} {item.get('variante') or ''}"
             for item in (context or {}).get("productos") or []}
    units |= {line["sku"]: f"{line.get('unit') or ''} {line.get('variant') or ''}" for line in (quote or {}).get("lines", [])}
    units |= {sku: f"{product.unit} {product.variant}" for sku, product in grounded_products(reference, calls).items()}
    named = [{"sku": item.get("sku"), "nombre": item.get("nombre") or "", "variante": item.get("variante") or ""}
             for item in (context or {}).get("productos") or []]
    named += [{"sku": line["sku"], "nombre": line.get("name") or "", "variante": line.get("variant") or ""}
              for line in (quote or {}).get("lines", [])]
    named += [{"sku": sku, "nombre": product.name, "variante": product.variant}
              for sku, product in grounded_products(reference, calls).items()]
    removed = removed_now([item for item in named if item["nombre"]], current)
    allowed = order_quantities(reference) | added_quantities(current, context)
    # «me llevo todo»: las líneas de la lista ya las dijo el cliente, con su cantidad.
    listed = list_lines(context)
    clean = []
    for line in lines:
        if not isinstance(line, dict) or set(line) != {"sku", "quantity"}:
            raise Rejected("INVALID_ARGUMENT", "Cada línea lleva solo sku y quantity.")
        sku, quantity = line["sku"], line["quantity"]
        if not isinstance(sku, str) or not SKU_PATTERN.match(sku):
            raise Rejected("INVALID_ARGUMENT", "Se requiere un SKU válido.")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= MAX_QUANTITY:
            raise Rejected("INVALID_QUANTITY", f"La cantidad debe ser un entero de 1 a {MAX_QUANTITY}.")
        if sku in removed:
            raise Rejected("PRODUCT_REMOVED", f"El cliente quitó {sku} en este mensaje: registra solo lo demás.")
        if listed.get(sku) == quantity and not any(previous["sku"] == sku for previous in clean):
            clean.append({"sku": sku, "quantity": quantity})
            continue
        if sku not in grounded:
            raise Rejected("SKU_NOT_GROUNDED", "Ese SKU no lo identificó el cliente; búscalo o pregunta cuál quiere.")
        if quantity not in allowed:
            raise Rejected("QUANTITY_NOT_GROUNDED", "El cliente no dijo esa cantidad; pregúntala.")
        if units.get(sku, "").strip() and foreign_unit(reference, quantity, units[sku]):
            raise Rejected("QUANTITY_NOT_GROUNDED", f"Esa cantidad la dijo en otra unidad; se vende por {units[sku]}.")
        if any(previous["sku"] == sku for previous in clean):
            raise Rejected("INVALID_ARGUMENT", "SKU repetido en el pedido.")
        clean.append({"sku": sku, "quantity": quantity})
    return clean


def _pickup(arguments: dict, current: str) -> dict:
    clean: dict = {"pedido": _order_id(arguments)}
    if not set(arguments) <= {"pedido", "fecha", "hora", "nota"}:
        raise Rejected("INVALID_ARGUMENT", "agendar_recogida acepta pedido, fecha, hora y nota.")
    day, hour = arguments.get("fecha"), arguments.get("hora")
    if (day is None) != (hour is None):
        raise Rejected("INVALID_ARGUMENT", "La recogida necesita fecha y hora juntas.")
    if day is not None:
        try:
            parsed_day, parsed_hour = date.fromisoformat(day), time.fromisoformat(hour)
        except (TypeError, ValueError):
            raise Rejected("INVALID_ARGUMENT", "fecha va como AAAA-MM-DD y hora como HH:MM.") from None
        said = mentioned_hours(current)
        text = normalize_text(current)
        if not said and not RELATIVE_TIME.search(text):
            raise Rejected("TIME_NOT_GROUNDED", "El cliente no dijo a qué hora pasa; pregúntale.")
        if said and parsed_hour.hour not in said | {value + 12 for value in said if value < 12}:
            raise Rejected("TIME_NOT_GROUNDED", "Esa hora no es la que dijo el cliente.")
        weekday = WEEKDAY_MENTION.search(text)
        if weekday and WEEKDAYS[parsed_day.weekday()] != weekday.group(1):
            raise Rejected("TIME_NOT_GROUNDED", "Esa fecha no cae el día que dijo el cliente.")
        clean.update(fecha=parsed_day.isoformat(), hora=parsed_hour.strftime("%H:%M"))
    note = arguments.get("nota")
    if note is not None:
        if not isinstance(note, str) or not note.strip() or len(note) > MAX_NOTE_CHARS:
            raise Rejected("INVALID_ARGUMENT", f"La nota es un texto de hasta {MAX_NOTE_CHARS} caracteres.")
        # La nota la lee el tendero: nunca guarda un teléfono, un correo ni un documento.
        # Tampoco un monto: la respuesta repite la nota y «$0» parecería un total (Q-09).
        clean["nota"] = MONEY.sub("[monto omitido]", redact_personal_data(note.strip())[0])
    if len(clean) == 1:
        raise Rejected("INVALID_ARGUMENT", "Indica la fecha y la hora de recogida o una nota.")
    return clean


def validate_order_request(
    name: str, arguments: dict, *, current: str, reference: str, calls: list[ToolCall], context: dict | None,
) -> dict:
    """Argumentos limpios para la herramienta de pedidos o ``Rejected`` con el código que ve Grok."""
    if context is None:
        raise Rejected("SESSION_REQUIRED", "Los pedidos solo se registran dentro de una conversación con sesión.")
    if len(json.dumps(arguments, ensure_ascii=False)) > MAX_ARGUMENT_CHARS:
        raise Rejected("INVALID_ARGUMENT", "Los argumentos superan el límite de longitud.")
    if name == "registrar_pedido":
        if not wants_to_buy(current, context):
            raise Rejected("PURCHASE_NOT_STATED", "El cliente no dijo que lo quiere llevar; pregúntale antes de registrar.")
        lines = _lines(arguments, reference, calls, context, current)
        replaced = _replaced_order(lines, current, calls, context)
        # W-03 con Grok real: con «mejor que sean blancos, no amarillos» canceló los cascos amarillos y volvió a
        # registrar los mismos; el cliente terminó sin pedido. Lo cancelado en este turno no se registra igual.
        wanted = sorted((line["sku"], line["quantity"]) for line in lines)
        if any(tool == "cancelar_pedido" and sorted((line.get("sku"), line.get("cantidad")) for line in order["lineas"]) == wanted
               for tool, order in order_results(calls)):
            raise Rejected("ORDER_UNCHANGED", "Es el mismo pedido que se acaba de cancelar: registra lo que el cliente "
                                              "pidió ahora y, si cambió el producto, búscalo primero.")
        if replaced and wanted == sorted((line.get("sku"), line.get("cantidad")) for line in replaced["lineas"]):
            raise Rejected("ORDER_UNCHANGED", "Es el mismo pedido que ya tiene: registra lo que el cliente pidió ahora "
                                              "y, si cambió el producto, búscalo primero.")
        return {"lines": lines, "reemplaza": replaced["pedido"]} if replaced else {"lines": lines}
    if name == "consultar_pedido":
        if not set(arguments) <= {"pedido"}:
            raise Rejected("INVALID_ARGUMENT", "consultar_pedido acepta solo pedido.")
        return {"pedido": _order_id(arguments)} if "pedido" in arguments else {}
    if name == "agendar_recogida":
        return _pickup(arguments, current)
    if set(arguments) != {"pedido"}:
        raise Rejected("INVALID_ARGUMENT", f"{name} acepta solo pedido.")
    order_id = _order_id(arguments)
    if name == "confirmar_pedido":
        if not confirms(current):
            raise Rejected("CONFIRMATION_NOT_STATED", "El cliente no confirmó en este mensaje; pídele que confirme.")
        if any(tool == "registrar_pedido" and order["pedido"] == order_id for tool, order in order_results(calls)):
            raise Rejected("CONFIRMATION_NOT_STATED", "El pedido se acaba de registrar: muéstrale el resumen y "
                                                      "espera su confirmación.")
    elif not cancels(current, context) and changes_order(current, context):
        # Z-32: cancelar antes de saber si alcanza la cantidad nueva dejaba al cliente sin pedido.
        raise Rejected("CHANGE_BY_REGISTERING", "Para cambiar el pedido no lo canceles: registra el nuevo con "
                                                "registrar_pedido y el servidor reemplaza el anterior solo si alcanza.")
    elif not cancels(current, context):
        raise Rejected("CANCEL_NOT_STATED", "El cliente no pidió cancelar ese pedido.")
    return {"pedido": order_id}


def _replaced_order(lines: list[dict], current: str, calls: list[ToolCall], context: dict | None) -> dict | None:
    """El pedido activo que cambia el cliente («mejor que sean 20»), o None si el registro es un pedido aparte.

    Es el que comparte un producto con el nuevo o, si cambió el producto, el único activo. Lo cancelado en este
    turno ya no se reemplaza.
    """
    if not changes_order(current, context):
        return None
    cancelled = {order["pedido"] for tool, order in order_results(calls) if tool == "cancelar_pedido"}
    active = [order for order in (context or {}).get("pedidos") or []
              if order.get("estado") in {"pendiente", "confirmado"} and order.get("pedido") not in cancelled]
    skus = {line["sku"] for line in lines}
    sharing = [order for order in active if skus & {line.get("sku") for line in order.get("lineas") or []}]
    candidates = sharing or active
    if len(candidates) > 1:
        raise Rejected("ORDER_AMBIGUOUS", "Hay más de un pedido activo: pregúntale al cliente cuál quiere cambiar.")
    return candidates[0] if candidates else None


def order_action_pending(current: str, reference: str, calls: list[ToolCall], context: dict | None) -> str | None:
    """Herramienta de pedido que el mensaje pide y Grok no intentó; la usa el aviso ORDER_REQUIRED."""
    if context is None:
        return None
    tools = {call["requested_tool"] for call in calls}
    orders = [*(context.get("pedidos") or []), *(order for _, order in order_results(calls))]
    pending = any(order.get("estado") == "pendiente" for order in orders)
    active = any(order.get("estado") in {"pendiente", "confirmado"} for order in orders)
    text = normalize_text(current)
    if cancels(current, context):
        if "cancelar_pedido" not in tools:
            return "cancelar_pedido" if active else None
        # W-03 (corrida 29): con «cancela ese y mejor…» Grok canceló y preguntó; falta registrar lo nuevo.
        if changes_order(current, context) and "registrar_pedido" not in tools:
            return "registrar_cambio"
        # Q-06: con «cancela todo» Grok canceló un pedido y preguntó por el otro.
        cancelled = {order["pedido"] for tool, order in order_results(calls) if tool == "cancelar_pedido"}
        left = [order for order in context.get("pedidos") or []
                if order.get("estado") in {"pendiente", "confirmado"} and order.get("pedido") not in cancelled]
        return "cancelar_todos" if CANCEL_ALL.search(text) and left else None
    if changes_order(current, context) and "registrar_pedido" not in tools:
        # Sin «cancela», el pedido nuevo reemplaza al anterior al registrarse (``_replaced_order``).
        return "cambiar_pedido"
    if pending and confirms(current) and "confirmar_pedido" not in tools and "registrar_pedido" not in tools:
        return "confirmar_pedido"
    if active and mentioned_hours(current) and "agendar_recogida" not in tools:
        return "agendar_recogida"
    known = set(grounded_products(reference, calls)) | {item.get("sku") for item in context.get("productos") or []}
    listed = list_lines(context)
    # Un intento rechazado (un SKU inventado) no registró nada, y con un pedido pendiente de otro producto el nuevo
    # también se registra (Q-06: «también me llevo 1 bulto de cemento» con las brochas pendientes).
    executed = {call["requested_tool"] for call in calls if call["executed"]}
    held = {line.get("sku") for order in orders if order.get("estado") == "pendiente" for line in order.get("lineas") or []}
    new_products = set(grounded_products(reference, calls)) - held
    # Un pedido vencido no se confirma: si el cliente aún lo quiere, se registra de nuevo (P-02, primera corrida S4).
    said = order_quantities(reference) or (listed and WHOLE_LIST.search(text))
    if (asks_whole_list(current) or ASKS_QUOTE_OR_TOTAL.search(text)) and not EXPLICIT_PURCHASE.search(text):
        return None
    if (wants_to_buy(current, context) and said and (known or listed)
            and "registrar_pedido" not in executed and (not pending or new_products)):
        return "registrar_pedido"
    # «"pedidos"» no trae precios: el total o el estado solo salen de la herramienta (L-02, primera corrida S4).
    if orders and ORDER_QUESTION.search(text) and not tools & set(ORDER_TOOLS):
        return "consultar_pedido"
    return None
