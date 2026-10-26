"""Respuestas sobre pedidos, armadas solo con lo que devolvieron las herramientas de pedidos.

También dice qué puede afirmar la redacción de Grok: un «quedó confirmado» solo vale si ``confirmar_pedido``
lo confirmó en esta ejecución, y cada código, monto, cantidad y hora debe salir de una observación.
"""

from datetime import datetime
import re

from asistendero.grok import ORDER_TOOLS
from asistendero.observations import ToolCall, order_results
from asistendero.orders import CONFIRMED_HOLD, HOLD_MINUTES, PAYMENT
from asistendero.reply_text import order_lines
from asistendero.validation import normalize_text


DAY_NAMES = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
STATUS_TEXT = {"pendiente": "pendiente de confirmar", "confirmado": "confirmado", "entregado": "entregado",
               "cancelado": "cancelado", "vencido": "vencido"}
# Palabras que la redacción de Grok solo puede usar si el estado del pedido las respalda.
CLAIMS_BY_STATUS = {
    "pendiente": r"apartad\w*|registrad\w*|separad\w*|reservad\w*|pedido\s+(?:creado|registrado)",
    "confirmado": r"apartad\w*|registrad\w*|separad\w*|reservad\w*|confirmad\w*|pedido\s+(?:creado|registrado|confirmado)",
}
# El apartado de 5 minutos es para confirmar, no para llegar: en el visor (23-10) Grok le dijo a un cliente que vivía
# a media hora «tienes hasta las 17:47 para llegar, ¡apúrate!». Con un pedido pendiente, eso no se puede afirmar.
RUSHES = re.compile(r"\bapur|\bapresur|date prisa|se (?:te |le )?vence pronto|tienes? (?:solo )?(?:hasta|\d+ minutos?)\b"
                    r"[^.?!]{0,40}\b(?:llegar|recoger|pasar|venir)")
CONFIRMED_HOURS = int(CONFIRMED_HOLD.total_seconds() // 3600)
# Un rechazo de la validación también tiene una salida fija: se le pide al cliente lo que falta.
REJECTION_TEXT = {
    "PURCHASE_NOT_STATED": "¿Quieres que registre el pedido? Dime qué te llevas y cuántas unidades, y te muestro el resumen.",
    "CONFIRMATION_NOT_STATED": "Revisa el resumen del pedido y respóndeme «sí, confirmo» para confirmarlo.",
    "TIME_NOT_GROUNDED": "¿Qué día y a qué hora pasas a recoger? Por ejemplo: «hoy a las 4».",
    "CANCEL_NOT_STATED": "¿Quieres cancelar el pedido? Dímelo y lo cancelo.",
    "ORDER_UNCHANGED": "¿Qué te llevas en lugar de lo que cancelé? Dime el producto y cuántas unidades.",
    "SESSION_REQUIRED": "Para registrar un pedido abre una conversación; aquí solo puedo cotizar.",
    # Sin estos textos, un código de pedido inventado («P-XXXXXX») terminaba en «No pude verificar ese producto».
    "INVALID_ARGUMENT": "No encuentro ese pedido en esta conversación. Si quieres llevar algo, dime el producto y "
                        "cuántas unidades.",
    "SKU_NOT_GROUNDED": "¿Qué producto te llevas? Dime cuál y cuántas unidades, y registro el pedido.",
    "QUANTITY_NOT_GROUNDED": "¿Cuántas unidades te llevas? Dímelo y registro el pedido.",
}


def _cop(value: int) -> str:
    return f"${value:,}".replace(",", ".")


def _hour(stamp: str | None) -> str:
    return stamp.split(" ")[1] if stamp else ""


def _when(stamp: str) -> str:
    """«2026-10-22 16:00» → «jueves 22/10 a las 16:00»: el cliente no lee fechas ISO."""
    moment = datetime.strptime(stamp, "%Y-%m-%d %H:%M")
    return f"{DAY_NAMES[moment.weekday()]} {moment.strftime('%d/%m')} a las {moment.strftime('%H:%M')}"


def _summary(order: dict) -> str:
    return order_lines(order)


def _describe(tool: str, order: dict) -> str:
    code = order["pedido"]
    if tool == "registrar_pedido":
        opening = (f"Listo, cambié tu pedido: cancelé el {order['reemplaza']} y registré el {code}"
                   if order.get("reemplaza") else f"Listo, registré tu pedido {code}")
        return (f"{opening} para recoger en la tienda:\n{_summary(order)}\n"
                f"Para dejártelo guardado, ¿me confirmas con un «sí» antes de las {_hour(order.get('aparta_hasta'))}? "
                f"Ya confirmado te lo guardo hasta {CONFIRMED_HOURS} horas, así que puedes venir con calma.")
    if tool == "confirmar_pedido":
        held = f" y te lo guardo hasta el {_when(order['aparta_hasta'])}" if order.get("aparta_hasta") else ""
        pickup = (f"Te esperamos el {_when(order['recogida'])}." if order.get("recogida")
                  else "¿Más o menos a qué hora pasas por él?")
        return f"¡Listo! Confirmé el pedido {code} por {_cop(order['total_cop'])}: quedó confirmado{held}. {pickup}"
    if tool == "agendar_recogida":
        text = f"Perfecto, te esperamos el {_when(order['recogida'])} con tu pedido {code}." if order.get("recogida") else ""
        if order.get("nota"):
            text = f"{text} Anoté en el pedido {code}: «{order['nota']}».".strip()
        if order["estado"] == "pendiente":
            text += f" Aún falta que lo confirmes: lo aparto hasta las {_hour(order.get('aparta_hasta'))}."
        return text
    if tool == "cancelar_pedido":
        return f"Listo, cancelé el pedido {code}. Si lo vuelves a necesitar, me dices."
    pickup = f", recogida el {_when(order['recogida'])}" if order.get("recogida") else ""
    hold = f", apartado hasta el {_when(order['aparta_hasta'])}" if order.get("aparta_hasta") else ""
    return f"Pedido {code}: {STATUS_TEXT.get(order['estado'], order['estado'])}{hold}{pickup}.\n{_summary(order)}"


STATUS_BY_TOOL = {"registrar_pedido": "order_pending", "confirmar_pedido": "order_confirmed",
                  "agendar_recogida": "pickup_scheduled", "cancelar_pedido": "order_cancelled",
                  "consultar_pedido": "order_status"}


def order_reply(calls: list[ToolCall]) -> tuple[str | None, str] | None:
    """(estado, texto) para lo que pasó con los pedidos en la ejecución, o None si no hubo herramientas de pedidos.

    El estado es None cuando ningún pedido cambió porque el servidor rechazó cada intento antes de ejecutarlo (sin
    conversación, sin intención de compra dicha…): la respuesta sigue siendo la de la búsqueda o la cotización.
    """
    order_calls = [call for call in calls if call["requested_tool"] in ORDER_TOOLS]
    if not order_calls:
        return None
    results = order_results(calls)
    lines = []
    # Corrida del video (25-10): confirmar y agendar en el mismo turno daba dos textos que se contradecían (la hora
    # del apartado de confirmar ya no valía y preguntaba la hora que el cliente acababa de dar). Ese pedido se
    # describe una vez, como quedó al final.
    latest = {order["pedido"]: order for _, order in results}
    both = {code for code in latest if {"confirmar_pedido", "agendar_recogida"}
            <= {tool for tool, order in results if order["pedido"] == code}}
    for tool, order in results:
        code = order["pedido"]
        if code not in both:
            lines.append(_describe(tool, order))
        elif tool == "confirmar_pedido":
            note = latest[code].get("nota")
            lines.append(_describe(tool, latest[code]) + (f" Anoté en el pedido {code}: «{note}»." if note else ""))
    status = STATUS_BY_TOOL[results[-1][0]] if results else "order_issue"
    for call in order_calls:
        response = call["response"]
        if response.get("status") == "ok":
            if call["requested_tool"] == "consultar_pedido" and not (response.get("data") or {}).get("pedidos"):
                lines.append("No tienes pedidos en esta conversación.")
                status = status if results else "order_status"
            continue
        code = (response.get("error") or {}).get("code")
        # Un error de negocio trae un mensaje seguro del libro de pedidos; un rechazo, la pregunta fija.
        text = REJECTION_TEXT.get(code) or (response["error"].get("message") if response.get("status") == "error" else None)
        if text and text not in lines:
            lines.append(text)
    if not lines:
        return None
    # El pago se aclara al registrar (o si algo falló), no en cada mensaje del pedido: repetido se leía como un aviso legal.
    if any(tool == "registrar_pedido" for tool, _ in results) or any(
            call["response"].get("status") == "error" for call in order_calls):
        lines.append(PAYMENT)
    if not results and not any(call["executed"] for call in order_calls):
        status = None
    return status, "\n".join(lines)


def rushes_the_customer(reply: str, calls: list[ToolCall], context: dict | None) -> bool:
    """La redacción le mete prisa al cliente con un pedido pendiente: los 5 minutos son para confirmar."""
    orders = [*((context or {}).get("pedidos") or []), *(order for _, order in order_results(calls))]
    pending = any(order.get("estado") == "pendiente" for order in orders)
    return pending and bool(RUSHES.search(normalize_text(reply)))


def order_allowances(calls: list[ToolCall], context: dict | None) -> dict:
    """Lo que la redacción de Grok puede citar de los pedidos: códigos, montos, cantidades, horas y afirmaciones."""
    amounts, counts, skus, times, claims = set(), set(), set(), set(), []
    codes = {item.get("pedido") for item in (context or {}).get("pedidos") or []}
    for tool, order in order_results(calls):
        codes.add(order["pedido"])
        amounts.add(_cop(order["total_cop"]))
        for line in order["lineas"]:
            amounts |= {_cop(line["precio_unitario_cop"]), _cop(line["subtotal_cop"])}
            counts.add(line["cantidad"])
            skus.add(line["sku"])
        times |= {_hour(order.get(key)) for key in ("aparta_hasta", "recogida") if order.get(key)}
        if order["estado"] in CLAIMS_BY_STATUS:
            claims.append(CLAIMS_BY_STATUS[order["estado"]])
        if order.get("recogida"):
            claims.append(r"agendad\w*|programad\w*")
    return {"codes": codes - {None}, "amounts": amounts, "counts": counts, "skus": skus,
            "times": times - {""}, "claims": re.compile("|".join(claims), re.I) if claims else None,
            "required": {order["pedido"] for tool, order in order_results(calls) if tool != "consultar_pedido"}}


def notice_text(event: dict) -> str:
    """Aviso proactivo para el cliente a partir de un evento del pedido (orders.OrderBook.notices)."""
    code = event["pedido"]
    if event["estado"] == "vencido" and event["detalle"] == "sin confirmar a tiempo":
        return (f"Pasaron {HOLD_MINUTES} minutos sin confirmar el pedido {code}, así que liberé lo apartado. "
                "Si aún lo quieres, escríbeme y lo registro de nuevo con el precio vigente.")
    if event["estado"] == "vencido":
        return f"El pedido {code} venció porque no se recogió a tiempo, y se liberó lo apartado."
    return (f"Tu pedido {code} sigue apartado solo hasta las {_hour(event.get('aparta_hasta'))}. "
            "¿Lo confirmas? Respóndeme «sí, confirmo».")
