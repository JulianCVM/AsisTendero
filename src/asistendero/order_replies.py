"""Respuestas sobre pedidos, armadas solo con lo que devolvieron las herramientas de pedidos.

También dice qué puede afirmar la redacción de Grok: un «quedó confirmado» solo vale si ``confirmar_pedido``
lo confirmó en esta ejecución, y cada código, monto, cantidad y hora debe salir de una observación.
"""

from datetime import datetime
import re

from asistendero.grok import ORDER_TOOLS
from asistendero.observations import ToolCall, order_results
from asistendero.orders import HOLD_MINUTES, PAYMENT


PLURAL = {"metro": "metros", "unidad": "unidades", "bulto": "bultos", "galón": "galones", "libra": "libras",
          "rollo": "rollos", "par": "pares", "pliego": "pliegos", "bolsa": "bolsas", "caja": "cajas"}
DAY_NAMES = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
STATUS_TEXT = {"pendiente": "pendiente de confirmar", "confirmado": "confirmado", "entregado": "entregado",
               "cancelado": "cancelado", "vencido": "vencido"}
# Palabras que la redacción de Grok solo puede usar si el estado del pedido las respalda.
CLAIMS_BY_STATUS = {
    "pendiente": r"apartad\w*|registrad\w*|separad\w*|reservad\w*|pedido\s+(?:creado|registrado)",
    "confirmado": r"apartad\w*|registrad\w*|separad\w*|reservad\w*|confirmad\w*|pedido\s+(?:creado|registrado|confirmado)",
}
# Un rechazo de la validación también tiene una salida fija: se le pide al cliente lo que falta.
REJECTION_TEXT = {
    "PURCHASE_NOT_STATED": "¿Quieres que registre el pedido? Dime qué te llevas y cuántas unidades, y te muestro el resumen.",
    "CONFIRMATION_NOT_STATED": "Revisa el resumen del pedido y respóndeme «sí, confirmo» para confirmarlo.",
    "TIME_NOT_GROUNDED": "¿Qué día y a qué hora pasas a recoger? Por ejemplo: «hoy a las 4».",
    "CANCEL_NOT_STATED": "¿Quieres cancelar el pedido? Dímelo y lo cancelo.",
    "SESSION_REQUIRED": "Para registrar un pedido abre una conversación; aquí solo puedo cotizar.",
    # Sin estos textos, un código de pedido inventado («P-XXXXXX») terminaba en «No pude verificar ese producto».
    "INVALID_ARGUMENT": "No encuentro ese pedido en esta conversación. Si quieres llevar algo, dime el producto y "
                        "cuántas unidades.",
    "SKU_NOT_GROUNDED": "¿Qué producto te llevas? Dime cuál y cuántas unidades, y registro el pedido.",
    "QUANTITY_NOT_GROUNDED": "¿Cuántas unidades te llevas? Dímelo y registro el pedido.",
}


def _cop(value: int) -> str:
    return f"${value:,}".replace(",", ".")


def _units(unit: str, amount: int) -> str:
    return unit if amount == 1 else PLURAL.get(unit, "unidades")


def _hour(stamp: str | None) -> str:
    return stamp.split(" ")[1] if stamp else ""


def _when(stamp: str) -> str:
    """«2026-10-22 16:00» → «jueves 22/10 a las 16:00»: el cliente no lee fechas ISO."""
    moment = datetime.strptime(stamp, "%Y-%m-%d %H:%M")
    return f"{DAY_NAMES[moment.weekday()]} {moment.strftime('%d/%m')} a las {moment.strftime('%H:%M')}"


def _summary(order: dict) -> str:
    lines = [f"• {line['cantidad']} {_units(line.get('unidad', 'unidad'), line['cantidad'])} de {line.get('nombre', '')} "
             f"{line.get('variante', '')}: {_cop(line['precio_unitario_cop'])} COP c/u → {_cop(line['subtotal_cop'])} COP"
             for line in order["lineas"]]
    return "\n".join(lines) + f"\nTotal: {_cop(order['total_cop'])} COP."


def _describe(tool: str, order: dict) -> str:
    code = order["pedido"]
    if tool == "registrar_pedido":
        return (f"Registré el pedido {code} para recoger en la tienda:\n{_summary(order)}\n"
                f"Lo aparto {HOLD_MINUTES} minutos, hasta las {_hour(order.get('aparta_hasta'))}, mientras lo confirmas. "
                "¿Confirmas el pedido?")
    if tool == "confirmar_pedido":
        pickup = (f"Te esperamos el {_when(order['recogida'])}." if order.get("recogida")
                  else "¿Qué día y a qué hora pasas a recogerlo?")
        return f"Listo, confirmé el pedido {code} por {_cop(order['total_cop'])} COP. {pickup}"
    if tool == "agendar_recogida":
        parts = [f"Anoté para el pedido {code}"]
        if order.get("recogida"):
            parts.append(f" la recogida el {_when(order['recogida'])}")
        if order.get("nota"):
            parts.append(f"{' y' if order.get('recogida') else ''} la nota «{order['nota']}»")
        text = "".join(parts) + "."
        if order["estado"] == "pendiente":
            text += f" Aún falta que lo confirmes: lo aparto hasta las {_hour(order.get('aparta_hasta'))}."
        return text
    if tool == "cancelar_pedido":
        return f"Cancelé el pedido {code} y liberé lo apartado."
    pickup = f", recogida el {_when(order['recogida'])}" if order.get("recogida") else ""
    hold = f", apartado hasta el {_when(order['aparta_hasta'])}" if order.get("aparta_hasta") else ""
    return f"Pedido {code}: {STATUS_TEXT.get(order['estado'], order['estado'])}{hold}{pickup}.\n{_summary(order)}"


STATUS_BY_TOOL = {"registrar_pedido": "order_pending", "confirmar_pedido": "order_confirmed",
                  "agendar_recogida": "pickup_scheduled", "cancelar_pedido": "order_cancelled",
                  "consultar_pedido": "order_status"}


def order_reply(calls: list[ToolCall]) -> tuple[str | None, str] | None:
    """(estado, texto) para lo que pasó con los pedidos en la ejecución, o None si no hubo herramientas de pedidos.

    El estado es None cuando el único problema es que no hay conversación: la respuesta sigue siendo la cotización.
    """
    order_calls = [call for call in calls if call["requested_tool"] in ORDER_TOOLS]
    if not order_calls:
        return None
    results = order_results(calls)
    lines = [_describe(tool, order) for tool, order in results]
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
    if results or any(call["response"].get("status") == "error" for call in order_calls):
        lines.append(PAYMENT)
    if not results and all((call["response"].get("error") or {}).get("code") == "SESSION_REQUIRED" for call in order_calls):
        status = None
    return status, "\n".join(lines)


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
