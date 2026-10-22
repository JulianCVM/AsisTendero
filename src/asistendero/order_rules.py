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
from asistendero.validation import (MAX_ITEMS, MAX_QUANTITY, SKU_PATTERN, Rejected, grounded_products,
                                    normalize_text, quantities_in_message)


PURCHASE_INTENT = re.compile(
    r"\b(?:(?:me\s+)?(?:lo|la|los|las)\s+(?:llevo|compro|pido|aparta\w*|separa\w*)|(?:me\s+)?llev(?:o|amos|aria|ariamos)\b"
    r"|quiero\s+(?:comprar|pedir|llevar|encargar)|vo(?:y|i)\s+a\s+(?:llevar|comprar)|compr(?:o|amos|aria)\b"
    r"|(?:haga|hagame|hazme|has|haz|hagan|montame|registr\w*)\s+(?:el\s+|un\s+)?pedido|apart\w*|separ(?:a|e|ar|ame|amelo|en)\b"
    r"|reserv\w*|encarg\w*|alist\w*|vend(?:a|e)me\w*|me\s+(?:lo|la|los|las)\s+(?:guarda|guarde|deja|dejan))"
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


def wants_to_buy(message: str, context: dict | None) -> bool:
    text = normalize_text(message)
    if PURCHASE_INTENT.search(text) and not re.search(r"\bno\s+(?:lo|la|los|las)?\s*(?:llevo|compro)\b", text):
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


def _lines(arguments: dict, reference: str, calls: list[ToolCall], context: dict | None) -> list[dict]:
    lines = arguments.get("lines")
    if set(arguments) != {"lines"} or not isinstance(lines, list) or not 1 <= len(lines) <= MAX_ITEMS:
        raise Rejected("INVALID_ARGUMENT", f"Se requieren de 1 a {MAX_ITEMS} líneas.")
    quote, _ = latest_quote(calls)
    grounded = set(grounded_products(reference, calls)) | {line["sku"] for line in (quote or {}).get("lines", [])}
    # Los productos de la sesión los identificó el cliente en turnos anteriores; el precio se relee al registrar.
    grounded |= {item.get("sku") for item in (context or {}).get("productos") or []}
    allowed = order_quantities(reference)
    clean = []
    for line in lines:
        if not isinstance(line, dict) or set(line) != {"sku", "quantity"}:
            raise Rejected("INVALID_ARGUMENT", "Cada línea lleva solo sku y quantity.")
        sku, quantity = line["sku"], line["quantity"]
        if not isinstance(sku, str) or not SKU_PATTERN.match(sku):
            raise Rejected("INVALID_ARGUMENT", "Se requiere un SKU válido.")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= MAX_QUANTITY:
            raise Rejected("INVALID_QUANTITY", f"La cantidad debe ser un entero de 1 a {MAX_QUANTITY}.")
        if sku not in grounded:
            raise Rejected("SKU_NOT_GROUNDED", "Ese SKU no lo identificó el cliente; búscalo o pregunta cuál quiere.")
        if quantity not in allowed:
            raise Rejected("QUANTITY_NOT_GROUNDED", "El cliente no dijo esa cantidad; pregúntala.")
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
        clean["nota"] = redact_personal_data(note.strip())[0]
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
        return {"lines": _lines(arguments, reference, calls, context)}
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
    elif not CANCEL_INTENT.search(normalize_text(current)):
        raise Rejected("CANCEL_NOT_STATED", "El cliente no pidió cancelar ese pedido.")
    return {"pedido": order_id}


def order_action_pending(current: str, reference: str, calls: list[ToolCall], context: dict | None) -> str | None:
    """Herramienta de pedido que el mensaje pide y Grok no intentó; la usa el aviso ORDER_REQUIRED."""
    if context is None:
        return None
    tools = {call["requested_tool"] for call in calls}
    orders = [*(context.get("pedidos") or []), *(order for _, order in order_results(calls))]
    pending = any(order.get("estado") == "pendiente" for order in orders)
    active = any(order.get("estado") in {"pendiente", "confirmado"} for order in orders)
    text = normalize_text(current)
    if CANCEL_INTENT.search(text):
        return "cancelar_pedido" if active and "cancelar_pedido" not in tools else None
    if pending and confirms(current) and "confirmar_pedido" not in tools and "registrar_pedido" not in tools:
        return "confirmar_pedido"
    if active and mentioned_hours(current) and "agendar_recogida" not in tools:
        return "agendar_recogida"
    known = set(grounded_products(reference, calls)) | {item.get("sku") for item in context.get("productos") or []}
    # Un pedido vencido no se confirma: si el cliente aún lo quiere, se registra de nuevo (P-02, primera corrida S4).
    if (wants_to_buy(current, context) and order_quantities(reference) and known
            and "registrar_pedido" not in tools and not pending):
        return "registrar_pedido"
    # «"pedidos"» no trae precios: el total o el estado solo salen de la herramienta (L-02, primera corrida S4).
    if orders and ORDER_QUESTION.search(text) and not tools & set(ORDER_TOOLS):
        return "consultar_pedido"
    return None
