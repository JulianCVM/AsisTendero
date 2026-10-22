"""Respuesta final: determinista con datos de herramientas o redacción de Grok comprobada."""

import re

from asistendero.catalog import Product, tokens
from asistendero.grok import AGENT_PROMPT, MAX_ITEMS, Decision
from asistendero.guardrails import leaks
from asistendero.observations import ToolCall, availability_by_sku, latest_quote, search_findings, store_info_by_topic
from asistendero.store_replies import store_lines, store_reply_is_consistent
from asistendero.validation import grounded_products, grounded_selection, normalize_text


PLURAL = {"metro": "metros", "unidad": "unidades", "bulto": "bultos", "galón": "galones", "libra": "libras",
          "rollo": "rollos", "par": "pares", "pliego": "pliegos", "bolsa": "bolsas", "caja": "cajas"}
# Una afirmación de acción ejecutada, descuento o equivalencia invalida la redacción de Grok, y también
# ofrecer apartar o reservar (en S2-02 Grok preguntó «¿Quieres apartar…?»): la demo no lo hace.
FORBIDDEN_CLAIMS = re.compile(
    r"\b(reservad|apartad|pagad|despachad|entregad|facturad|descuent|compatib|equivalen|abiert|cerrad)\w*"
    r"|\b(?:apart|reserv)ar\w*"
    r"|\bpedido\s+(?:creado|registrado|confirmado|listo)",
    re.I,
)

# Un pedido de apartar, reservar o fiar recibe siempre esta aclaración, la redacte Grok o no.
RESERVATION_REQUEST = re.compile(
    r"\b(?:apart\w+|reserv\w+|separ(?:a|e|ar|ame|amelo|en)\b|fia\w*|fiar\w*|credito|"
    r"(?:pago|pagar|pagaria)\s+(?:manana|despues|luego|la\s+otra\s+semana))"
)
RESERVATION_NOTE = "No es un pedido ni una reserva: por este chat no aparto productos, no fío ni recibo pagos."


def with_reservation_note(message: str, answer: str) -> str:
    """Agrega la aclaración cuando el cliente pidió apartar, reservar o fiar y la respuesta no la trae."""
    if not RESERVATION_REQUEST.search(normalize_text(message)) or "no es un pedido ni una reserva" in answer.casefold():
        return answer
    return f"{answer}\n{RESERVATION_NOTE}"


def format_cop(value: int) -> str:
    return f"${value:,}".replace(",", ".")


def _units(unit: str, amount: int) -> str:
    return unit if amount == 1 else PLURAL.get(unit, "unidades")


def _join_options(options: list[str]) -> str:
    if len(options) < 2:
        return options[0] if options else ""
    return ", ".join(options[:-1]) + " y " + options[-1]


def _available_options(products: list[Product]) -> str:
    same_name = len({item.name for item in products}) == 1
    return _join_options([
        f"{'' if same_name else item.name + ' '}{item.variant} "
        f"({str(item.stock) + ' ' + _units(item.unit, item.stock) + ' disponibles' if item.stock else 'agotado'})"
        for item in products
    ])


def direct_response(original: str, decision: Decision) -> str:
    # Sin consultar_info_tienda no hay horario verificado: aunque Grok clasifique «¿están atendiendo?»
    # como saludo, nunca se afirma apertura.
    if re.search(
        r"\b(atendiendo|atienden|atiende|abiert[oa]s?|cerrad[oa]s?|horario|abren|cierran)\b",
        normalize_text(original),
    ):
        return ("No pude verificar el horario de la tienda en este momento. "
                "Si me dices qué producto buscas, puedo revisar el catálogo de prueba contigo.")
    reply = decision.reply.strip()
    # Sin herramientas no hay precio ni existencias comprobadas que se puedan afirmar.
    if (
        not reply or len(reply) > 400 or FORBIDDEN_CLAIMS.search(reply) or "$" in reply
        or leaks(reply, AGENT_PROMPT)
        or re.search(r"\b\d+\s+(metro|bulto|unidad|galon)", normalize_text(reply))
    ):
        return "Puedo ayudarte a consultar productos del catálogo de demostración. ¿Qué necesitas?"
    return reply


def render_answer(message: str, calls: list[ToolCall]) -> tuple[str, str]:
    """Respuesta determinista construida solo con lo que devolvieron las herramientas."""
    findings = search_findings(calls)
    store = store_lines(calls)
    if not findings and store:
        return "informed", "\n".join(store) + "\nSon datos de demostración."
    if not findings:
        if any((call["response"].get("error") or {}).get("code") == "TOO_MANY_ITEMS" for call in calls):
            return "clarify", (f"Puedo revisar hasta {MAX_ITEMS} productos por mensaje. ¿Me mandas la lista "
                               f"en grupos de {MAX_ITEMS} o menos?")
        if any(call["response"]["status"] == "error" for call in calls):
            return "tool_error", ("No pude consultar el catálogo de demostración en este momento, así que no "
                                  "tengo precios ni existencias verificados. Intenta de nuevo en unos minutos.")
        return "not_verified", ("No pude verificar ese producto en el catálogo de demostración. "
                                "¿Me dices qué producto y qué medida buscas?")

    availability = availability_by_sku(calls)
    lines, statuses, products = [], [], {}
    for finding in findings:
        matches, nearby = finding["matches"], finding["nearby"]
        for product in matches + nearby:
            products[product.sku] = product
        selected = grounded_selection(message, finding) if matches else None
        if not matches and nearby:
            category = nearby[0].name if len({item.name for item in nearby}) == 1 else "esa categoría"
            category = category[0].lower() + category[1:]
            material = finding["request"].get("material")
            material_differs = material and all(
                not tokens(material) <= tokens(f"{item.name} {item.variant}") for item in nearby
            )
            caveat = " Son de otro material; habría que confirmar si te sirven para ese uso." if material_differs else ""
            lines.append(f"No encontré {finding['query']} tal como lo pides. De {category} sí aparecen "
                         f"{_available_options(nearby[:2])}, que no son lo mismo.{caveat} ¿Alguna de esas opciones te interesa?")
            statuses.append("nearby")
        elif not matches:
            lines.append(f"No encontré {finding['query']} en el catálogo de prueba. Si tienes otra referencia o medida, la reviso.")
            statuses.append("not_found")
        elif selected:
            stock = availability.get(selected.sku, {}).get("stock", selected.stock)
            state = f"{stock} {_units(selected.unit, stock)} disponibles" if stock else "agotado"
            lines.append(f"Encontré {selected.name} ({selected.variant}, SKU {selected.sku}): "
                         f"{format_cop(selected.price_cop)} COP por {selected.unit}; {state}.")
            statuses.append("found")
        else:
            category = matches[0].name if len({item.name for item in matches}) == 1 else finding["query"]
            lines.append(f"Para {category} veo {_available_options(matches[:3])}. ¿Qué medida o presentación necesitas?")
            statuses.append("clarify")

    status = "found" if all(s == "found" for s in statuses) else (statuses[0] if len(statuses) == 1 else "partial")
    answer = "".join(line + "\n" for line in store)
    answer += ("Con gusto, esto encontré:\n" if len(lines) > 1 else "")
    answer += ("\n".join(f"• {line.removeprefix('Encontré ')}" for line in lines) if len(lines) > 1 else lines[0])

    quote, quote_call = latest_quote(calls)
    if quote:
        quote_lines = []
        for line in quote["lines"]:
            product = products.get(line["sku"])
            label = f"{product.name} {product.variant}" if product else f"SKU {line['sku']}"
            unit = product.unit if product else "unidad"
            quote_lines.append(f"• {line['quantity']} {_units(unit, line['quantity'])} de {label}: "
                               f"{format_cop(line['unit_price_cop'])} COP c/u → {format_cop(line['subtotal_cop'])} COP")
        answer += ("\nCotización informativa:\n" + "\n".join(quote_lines)
                   + f"\nTotal informativo: {format_cop(quote['total_cop'])} COP. No es un pedido ni una reserva.")
        if status == "found":
            status = "quoted"
    elif quote_call:
        error = quote_call["response"]["error"]
        if error["code"] == "INSUFFICIENT_STOCK":
            short = []
            for line in quote_call["arguments"]["lines"]:
                product = products.get(line["sku"])
                stock = availability.get(line["sku"], {}).get("stock", product.stock if product else None)
                if product and stock is not None and line["quantity"] > stock:
                    short.append(f"pides {line['quantity']} {_units(product.unit, line['quantity'])} de "
                                 f"{product.name} ({product.variant}) y hay {stock} {_units(product.unit, stock)} disponibles")
            detail = "; ".join(short) if short else "la cantidad pedida supera las existencias"
            answer += f"\nNo alcanza para cotizar: {detail}. ¿Quieres que cotice una cantidad menor?"
            status = "insufficient_stock"
        else:
            answer += "\nNo pude calcular la cotización en este momento; los datos anteriores sí vienen del catálogo."
            status = "quote_error"
    return status, answer + "\nSon datos de demostración."


def reply_is_grounded(reply: str, message: str, calls: list[ToolCall]) -> bool:
    """La redacción de Grok solo se usa si cada cifra sale de una observación de esta ejecución."""
    if not reply or len(reply) > 1200 or leaks(reply, AGENT_PROMPT):
        return False
    normalized = normalize_text(reply)
    # Con el horario consultado, «abierto» y «cerrado» valen si coinciden con el reloj del servidor.
    checked = re.sub(r"\b(?:abiert|cerrad)\w*", "", reply, flags=re.I) if "horario" in store_info_by_topic(calls) else reply
    if FORBIDDEN_CLAIMS.search(checked):
        return False
    consistent, store_amounts = store_reply_is_consistent(normalized, calls)
    if not consistent:
        return False
    if not re.search(r"simulad|demostracion|fictici|de prueba", normalized):
        return False
    findings = search_findings(calls)
    selected = grounded_products(message, calls)
    availability = availability_by_sku(calls)
    quote, quote_call = latest_quote(calls)
    allowed_amounts = {format_cop(p.price_cop) for p in selected.values()} | store_amounts
    allowed_counts = {p.stock for f in findings for p in f["matches"] + f["nearby"]}
    allowed_counts |= {data["stock"] for data in availability.values()}
    allowed_skus = {p.sku for f in findings for p in f["matches"] + f["nearby"]}
    if quote:
        allowed_amounts |= {format_cop(quote["total_cop"])}
        for line in quote["lines"]:
            allowed_amounts |= {format_cop(line["unit_price_cop"]), format_cop(line["subtotal_cop"])}
            allowed_counts.add(line["quantity"])
        if format_cop(quote["total_cop"]) not in reply:
            return False
    elif quote_call:
        allowed_counts |= {line["quantity"] for line in quote_call["arguments"]["lines"]}
    if not set(re.findall(r"\$[\d.,]*\d", reply)) <= allowed_amounts:
        return False
    if not set(re.findall(r"\b[A-Z]{2,5}-[A-Z0-9-]+\b", reply)) <= allowed_skus:
        return False
    counts = re.findall(r"\b(\d+)\s+(?:metros?|bultos?|unidad(?:es)?|galon(?:es)?|libras?|rollos?|par(?:es)?|pliegos?|bolsas?|cajas?)\b", normalized)
    if any(int(count) not in allowed_counts for count in counts):
        return False
    # «Agotado» solo vale si algún producto elegido tiene stock 0 (en S2-07 Grok escribió «agotado para 20»
    # con 12 metros disponibles).
    stocks = [availability.get(p.sku, {}).get("stock", p.stock) for p in selected.values()]
    if "agotad" in normalized and 0 not in stocks:
        return False
    # Cada producto elegido debe aparecer con su precio y su estado real.
    for product in selected.values():
        stock = availability.get(product.sku, {}).get("stock", product.stock)
        if format_cop(product.price_cop) not in reply:
            return False
        if stock == 0 and "agotad" not in normalized:
            return False
        if stock > 0 and not re.search(rf"\b{stock}\s+{normalize_text(_units(product.unit, stock))}\b", normalized):
            return False
    return True
