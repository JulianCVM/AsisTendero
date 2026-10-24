"""Respuesta final: determinista con datos de herramientas o redacción de Grok comprobada."""

import re

from asistendero.catalog import Product, tokens
from asistendero.choices import ambiguous_reference
from asistendero.grok import AGENT_PROMPT, MAX_ITEMS, Decision
from asistendero.guardrails import leaks
from asistendero.observations import (ToolCall, availability_by_sku, latest_quote, order_results, search_findings,
                                      store_info_by_topic)
from asistendero.order_replies import order_allowances, order_reply, rushes_the_customer
from asistendero.reply_text import (DEMO_NOTE, FEMININE, LOW_STOCK, MAX_NEARBY, MAX_OPTIONS, SUITABILITY_CLAIM,
                                    SUITABILITY_NOTE, asks_stock, asks_suitability, format_cop, found_sentence,
                                    in_sentence, label, of_the, option_lines, quote_block, quote_offer, short_stock_text,
                                    units, whole_units_question)
from asistendero.restock import asks_restock, restock_reply_ok, restock_sentence, restock_subjects
from asistendero.store_replies import store_lines, store_reply_is_consistent
from asistendero.validation import (fractional_amount, grounded_products, grounded_selection, naming_numbers,
                                    normalize_text, quantities_in_message, without_negated)


# Una afirmación de acción ejecutada, descuento o equivalencia invalida la redacción de Grok, y también
# ofrecer apartar o reservar fuera de una sesión (en S2-02 Grok preguntó «¿Quieres apartar…?»). Dentro de una
# sesión, lo que respalda un pedido observado se quita antes de mirar (order_replies.CLAIMS_BY_STATUS).
FORBIDDEN_CLAIMS = re.compile(
    r"\b(reservad|apartad|separad|registrad|confirmad|agendad|programad|pagad|despachad|entregad|facturad|descuent"
    r"|compatib|equivalen|abiert|cerrad)\w*"
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
# En una sesión sí hay pedidos: lo que nunca se hace es fiar o cobrar, y sin pedido registrado no hay nada apartado.
CREDIT_REQUEST = re.compile(r"\b(?:fia\w*|fiar\w*|credito|(?:pago|pagar|pagaria)\s+(?:manana|despues|luego|la\s+otra\s+semana))")
CREDIT_NOTE = "No fío ni recibo pagos por este chat: el pago es en el mostrador al recoger."
NO_ORDER_NOTE = "Todavía no hay nada apartado: si lo quieres llevar, dime cuántas unidades y registro el pedido."


def with_reservation_note(message: str, answer: str, calls: list[ToolCall] | None = None,
                          context: dict | None = None) -> str:
    """Agrega la aclaración cuando el cliente pidió apartar, reservar o fiar y la respuesta no la trae.

    Fuera de una sesión (``context`` None) no hay pedidos. Dentro, fiar nunca se hace y «apártalo» sin un pedido
    registrado o activo recibe la indicación de cómo registrarlo.
    """
    text = normalize_text(message)
    if not RESERVATION_REQUEST.search(text):
        return answer
    if context is None:
        return answer if "no es un pedido ni una reserva" in answer.casefold() else f"{answer}\n{RESERVATION_NOTE}"
    if CREDIT_REQUEST.search(text):
        return answer if "no fío" in answer.casefold() else f"{answer}\n{CREDIT_NOTE}"
    active = any(order.get("estado") in {"pendiente", "confirmado"} for order in context.get("pedidos") or [])
    # La cotización en una sesión ya ofrece apartar: repetir cómo registrar sobraba.
    if order_results(calls or []) or active or "nada apartado" in answer.casefold() or "te lo aparto" in answer.casefold():
        return answer
    return f"{answer}\n{NO_ORDER_NOTE}"


# «Se me acabó» y «no me quedan» dicen lo mismo que «agotado» (Grok real, suite surtido).
OUT_OF_STOCK = re.compile(r"\bagotad|\bse (?:me |nos |le )?(?:acabo|acabaron)\b|\bno (?:me|nos) quedan?\b")


def direct_response(original: str, decision: Decision) -> str:
    # Sin consultar_info_tienda no hay horario verificado: aunque Grok clasifique «¿están atendiendo?»
    # como saludo, nunca se afirma apertura.
    if re.search(
        r"\b(atendiendo|atienden|atiende|abiert[oa]s?|cerrad[oa]s?|horario|abren|cierran)\b",
        normalize_text(original),
    ):
        return ("No pude verificar el horario de la tienda en este momento. "
                "Si me dices qué producto buscas, te doy precio y disponibilidad.")
    reply = decision.reply.strip()
    # Sin herramientas no hay precio ni existencias comprobadas que se puedan afirmar.
    if (
        not reply or len(reply) > 400 or FORBIDDEN_CLAIMS.search(reply) or "$" in reply
        or leaks(reply, AGENT_PROMPT)
        or re.search(r"\b\d+\s+(metro|bulto|unidad|galon)", normalize_text(reply))
    ):
        return "¿Qué estás buscando? Te doy precio y disponibilidad de lo que necesites."
    return reply


def _join(parts: list[str]) -> str:
    return "\n\n".join(part for part in parts if part)


def render_answer(message: str, calls: list[ToolCall], context: dict | None = None,
                  current: str | None = None) -> tuple[str, str]:
    """Respuesta determinista construida solo con lo que devolvieron las herramientas.

    ``context`` es el de la sesión (None fuera de ella): en una conversación la cotización termina ofreciendo
    apartar y la aclaración de demostración va solo en el primer mensaje. ``message`` es la referencia (turnos
    recientes más el actual, para respaldar productos); ``current``, solo el mensaje de este turno: lo que el cliente
    pregunta ahora (cuánto queda, cuándo llega) no se arrastra de un turno anterior.
    """
    asked = normalize_text(message if current is None else current)
    findings = search_findings(calls)
    store = store_lines(calls)
    orders = order_reply(calls)
    quote, quote_call = latest_quote(calls)
    demo = [DEMO_NOTE] if context is None or not context.get("turnos") else []
    order_text = [orders[1]] if orders else []
    if not findings and quote:
        block = _with_offer(quote_block(quote, {}, _quote_header(quote, {})), quote,
                            quote_offer(context, orders and orders[0], False))
        return (orders and orders[0]) or "quoted", _join([block, *store, *order_text, *demo])
    rejected = {(call["response"].get("error") or {}).get("code") for call in calls if not call["executed"]}
    if not findings and not store and not any(call["executed"] for call in calls) and "SESSION_REQUIRED" in rejected:
        # Z-11 (corrida 34): sin conversación, «deme 3 de esos» intentó un pedido y la respuesta decía «abre una
        # conversación»; el cliente nunca dijo qué producto quería.
        return "clarify", _join(["¿De qué producto me hablas? Dime cuál y qué medida, y te lo busco.", *demo])
    if not findings and (store or orders):
        return (orders and (orders[0] or "order_issue")) or "informed", _join([*store, *order_text, *demo])
    checked = availability_by_sku(calls)
    if not findings and checked:
        # Un producto que la sesión ya conocía, consultado sin buscar («¿y cuándo le llegan más?»).
        lines = [_availability_line(data, asked) for data in checked.values()]
        return "found", _join([*lines, *demo])
    if not findings and quote_call and (quote_call["response"].get("error") or {}).get("code") == "INSUFFICIENT_STOCK":
        # Q-13 (corrida 30): «agrégale 1 galón más» se cotizó sin buscar en el turno; no alcanzaba y la respuesta
        # decía «No pude consultar el catálogo».
        return "insufficient_stock", _join([_short_of_known(quote_call, context), *demo])
    if not findings:
        options = ambiguous_reference(message if current is None else current, context)
        if options and any((call["response"].get("error") or {}).get("code") == "AMBIGUOUS_REFERENCE" for call in calls):
            return "clarify", f"¿Cuál quieres: {' o '.join(options)}? Dime cuál y te lo cotizo."
        if any((call["response"].get("error") or {}).get("code") == "VAGUE_SEARCH" for call in calls):
            return "clarify", "¿De qué producto me hablas? Dime cuál y qué medida, y te lo busco."
        if any((call["response"].get("error") or {}).get("code") == "TOO_MANY_ITEMS" for call in calls):
            return "clarify", (f"Puedo revisar hasta {MAX_ITEMS} productos por mensaje. ¿Me mandas la lista "
                               f"en grupos de {MAX_ITEMS} o menos?")
        if any(call["response"]["status"] == "error" for call in calls):
            return "tool_error", ("No pude consultar el catálogo en este momento, así que no tengo precios ni "
                                  "existencias verificados. Intenta de nuevo en unos minutos.")
        return "not_verified", ("No pude verificar ese producto en el catálogo. ¿Me dices qué producto y qué "
                                "medida buscas?")

    availability = availability_by_sku(calls)
    quoted = {line["sku"] for line in (quote or {}).get("lines", [])}
    # Si la cotización falló por existencias, cuánto queda se explica una vez, abajo (``short_stock_text``).
    short = quote_call is not None and (quote_call["response"].get("error") or {}).get("code") == "INSUFFICIENT_STOCK"
    # Z-14 y Z-22 (suite fallas): el 90 de «codo de 90» y el 50 de «cemento de 50» contaban como lo que el cliente
    # necesitaba y salía «Ojo, solo me quedan 34».
    found = [item for finding in findings for item in finding["matches"] + finding["nearby"]]
    said = quantities_in_message(message) - naming_numbers(message, found)
    needed = 0 if short else max(said, default=0)
    restock_asked = asks_restock(asked)
    # Z-25: «¿tienen candado…, cuándo les llega el martillo…?» decía «no tengo fecha» también del candado.
    restock_about = restock_subjects(asked, [finding["query"] for finding in findings]) if restock_asked else set()
    suitability = asks_suitability(asked)
    sentences, questions, statuses, products = [], [], [], {}
    seen = set()
    for index, finding in enumerate(findings):
        finding = without_negated(asked, finding)
        matches, nearby = finding["matches"], finding["nearby"]
        # Dos búsquedas con el mismo resultado son una sola respuesta (X-22, corrida 30: «taladro no lo manejo» salía
        # dos veces; Z-33: «tubo PVC de 1/2» y «tubo PVC de 1/2 para agua» repetían las mismas opciones).
        same = (tuple(item.sku for item in matches), tuple(item.sku for item in nearby)) if matches or nearby else (
            finding["query"],)
        if same in seen:
            continue
        seen.add(same)
        for product in matches + nearby:
            products[product.sku] = product
        selected = grounded_selection(message, finding) if matches else None
        # Lo que ya está en la cotización lo eligió el cliente antes («la manguera de 40 cm» de la lista): no se
        # vuelve a preguntar cuál.
        in_quote = [product for product in matches if product.sku in quoted]
        selected = selected or (in_quote[0] if len(in_quote) == 1 else None)
        if not matches and nearby:
            material = finding["request"].get("material")
            material_differs = material and all(
                not tokens(material) <= tokens(f"{item.name} {item.variant}") for item in nearby
            )
            caveat = " Es de otro material, habría que ver si te sirve para ese uso." if material_differs else ""
            closest = in_sentence(nearby[0].name) if len({item.name for item in nearby[:MAX_NEARBY]}) == 1 else "esto"
            options = "\n".join(option_lines(nearby[:MAX_NEARBY]))
            query = _display(finding["query"], nearby)
            sentences.append(f"{query[0].upper()}{query[1:]} así como lo pides no lo manejo. Lo más parecido que tengo es "
                             f"{closest}, aunque no es exactamente lo mismo.{caveat}\n{options}")
            statuses.append("nearby")
        elif not matches:
            sentences.append(f"Uy, {finding['query']} no lo manejo por ahora. Si tienes otra referencia o medida, con "
                             "gusto te la busco.")
            statuses.append("not_found")
        elif selected:
            stock = availability.get(selected.sku, {}).get("stock", selected.stock)
            first = not any(status == "found" for status in statuses)
            restock = restock_sentence(in_sentence(label(selected.name, selected.variant)),
                                       availability.get(selected.sku, {}).get("restock", selected.restock),
                                       index in restock_about, stock)
            # Lo que va en la cotización ya sale con su precio ahí: repetirlo arriba sonaba a reporte. Agotado, la
            # frase del surtido ya lo dice.
            if selected.sku not in quoted and stock > 0:
                sentences.append(found_sentence(selected, stock, first, asks_stock(asked) and not short, needed,
                                                suitability))
            if restock:
                sentences.append(restock)
            statuses.append("found")
        else:
            same_name = len({item.name for item in matches}) == 1
            intro = (f"De {in_sentence(matches[0].name)} tengo estas opciones:" if same_name
                     else f"De {_display(finding['query'], matches, shared=True)} tengo estas opciones:")
            extra = len(matches) - MAX_OPTIONS
            more = f"\n(y {extra} {'opción' if extra == 1 else 'opciones'} más)" if extra > 0 else ""
            # Con el mismo nombre solo cambia la variante: se pregunta por ella, como en el mostrador.
            question = "¿Qué medida o referencia necesitas?" if same_name else "¿Cuál te sirve?"
            questions.append(intro + "\n" + "\n".join(option_lines(matches[:MAX_OPTIONS])) + f"{more}\n{question}")
            statuses.append("clarify")

    status = "found" if all(s == "found" for s in statuses) else (statuses[0] if len(statuses) == 1 else "partial")
    quote_part = ""
    if quote:
        quote_part = _with_offer(quote_block(quote, products, _quote_header(quote, products)), quote,
                                 quote_offer(context, orders and orders[0], bool(questions)))
        if status == "found":
            status = "quoted"
    elif quote_call:
        error = quote_call["response"]["error"]
        if error["code"] == "INSUFFICIENT_STOCK":
            quote_part = short_stock_text(quote_call["arguments"]["lines"], products, availability)
            status = "insufficient_stock"
        else:
            quote_part = "No pude sacar el total en este momento; los precios de arriba sí están al día."
            status = "quote_error"
    if orders:
        status = orders[0] or status
    if status == "found" and len(statuses) == 1 and not store and not orders and not restock_asked:
        product = next(iter(grounded_products(message, calls).values()), None)
        if product and availability.get(product.sku, {}).get("stock", product.stock) > 0:
            # Z-01 (suite fallas): con «2.5 metros» se preguntaba «¿Cuántos metros necesitas?», como si no lo hubiera
            # dicho; se vende por unidad entera y se ofrecen las dos más cercanas.
            whole = fractional_amount(message if current is None else current)
            many = "Cuántas" if product.unit in FEMININE else "Cuántos"
            questions.append(whole_units_question(product.unit, whole) if whole
                             else f"¿{many} {units(product.unit, 2)} necesitas?")
    # La tienda va después de los productos: el horario se suele preguntar al final («¿a qué hora paso?»).
    caution = [SUITABILITY_NOTE] if suitability else []
    answer = _join([*sentences, *caution, quote_part, *store, *questions, *order_text, *demo])
    return status, answer


def _short_of_known(call: ToolCall, context: dict | None) -> str:
    """Lo que no alcanzó, nombrado con lo que la sesión ya conoce del producto (no hubo búsqueda en el turno)."""
    known = {item.get("sku"): item for item in (context or {}).get("productos") or []}
    held = {line.get("sku") for order in (context or {}).get("pedidos") or []
            if order.get("estado") in {"pendiente", "confirmado"} for line in order.get("lineas") or []}
    lines = call["arguments"]["lines"]
    line = next((line for line in lines if line["sku"] in call["response"]["error"]["message"]), lines[0])
    item = known.get(line["sku"]) or {}
    name = in_sentence(label(item.get("nombre") or "ese producto", item.get("variante") or ""))
    quantity = line["quantity"]
    note = " Lo que ya tienes apartado en tu pedido también cuenta." if line["sku"] in held else ""
    return (f"Uy, {of_the(name)} no tengo {quantity} {units(item.get('unidad') or 'unidad', quantity)} "
            f"disponibles.{note} ¿Te cotizo una cantidad menor?")


def _availability_line(data: dict, asked: str) -> str:
    name = in_sentence(label(data.get("name") or "producto", data.get("variant") or ""))
    stock = data["stock"]
    restock = restock_sentence(name, data.get("restock") or "", asks_restock(asked), stock)
    if restock and (stock <= 0 or not asks_stock(asked)):
        return restock
    left = of_the(name).capitalize()
    left += f" me {'queda' if stock == 1 else 'quedan'} {stock} {units(data.get('unit') or 'unidad', stock)}."
    return f"{left} {restock}".strip()


def _quote_header(quote: dict, products: dict[str, Product]) -> str:
    """Con líneas que no se buscaron en este turno, la cotización suma lo que el cliente ya llevaba."""
    carried = len(quote["lines"]) > 1 and any(line["sku"] not in products for line in quote["lines"])
    return "Con lo que llevas, te quedaría así:" if carried else "Te quedaría así:"


def _with_offer(block: str, quote: dict, offer: str) -> str:
    """Una cotización de una línea es una frase y la oferta la sigue; una lista la lleva debajo."""
    if not offer:
        return block
    return f"{block} {offer}" if len(quote["lines"]) == 1 else f"{block}\n{offer}"


def _display(query: str, products: list[Product], shared: bool = False) -> str:
    """El texto que buscó Grok con las siglas como en el catálogo: «tubos pvc» → «tubos PVC».

    Con ``shared`` quedan solo las palabras que tienen las opciones: si Grok buscó «mangueras PVC» con el «PVC»
    de otro producto, la respuesta no dice «De mangueras PVC tengo…» con mangueras que no son de PVC.
    """
    acronyms = {word.casefold(): word for item in products for word in f"{item.name} {item.variant}".split()
                if len(word) > 1 and word.isupper()}
    known = set().union(*(tokens(f"{item.name} {item.variant}") for item in products))
    parts = query.split()
    kept = [not shared or position == 0 or not tokens(word) or tokens(word) <= known for position, word in enumerate(parts)]
    # Sin «pared», «pintura beige para pared» no deja el «para» colgando (suite natural, H-02).
    for position in range(len(parts) - 1, 0, -1):
        if kept[position] and not tokens(parts[position]) and (position + 1 == len(parts) or not kept[position + 1]):
            kept[position] = False
    return " ".join(acronyms.get(word.casefold(), word) for word, keep in zip(parts, kept) if keep)


def reply_is_grounded(reply: str, message: str, calls: list[ToolCall], context: dict | None = None,
                      current: str | None = None) -> bool:
    """La redacción de Grok solo se usa si cada cifra sale de una observación de esta ejecución.

    ``context`` es el de la sesión (None fuera de ella): aporta los códigos de pedido que el cliente ya conoce y
    dice si es el primer mensaje. ``current`` es el mensaje de este turno (por omisión, ``message``): dice si el
    cliente preguntó cuánto queda.
    """
    if not reply or len(reply) > 1200 or leaks(reply, AGENT_PROMPT) or rushes_the_customer(reply, calls, context):
        return False
    normalized = normalize_text(reply)
    orders = order_allowances(calls, context)
    # Con el horario consultado, «abierto» y «cerrado» valen si coinciden con el reloj del servidor.
    checked = re.sub(r"\b(?:abiert|cerrad)\w*", "", reply, flags=re.I) if "horario" in store_info_by_topic(calls) else reply
    if orders["claims"]:
        checked = orders["claims"].sub("", checked)
    if context is not None:
        # En una sesión ofrecer el pedido es legítimo («¿te lo aparto?»); afirmarlo sin herramienta, no.
        checked = re.sub(r"\b(?:apart|reserv)ar\w*", "", checked, flags=re.I)
    if FORBIDDEN_CLAIMS.search(checked):
        return False
    if asks_suitability(normalize_text(message if current is None else current)) and SUITABILITY_CLAIM.search(normalized):
        return False
    said_codes = set(re.findall(r"\bP-[0-9A-F]{6}\b", reply))
    if not said_codes <= orders["codes"] or not orders["required"] <= said_codes:
        return False
    for moment in orders["times"]:
        normalized = normalized.replace(moment, "")
    consistent, store_amounts = store_reply_is_consistent(normalized, calls, paid_at_pickup=bool(order_results(calls)))
    if not consistent:
        return False
    # La aclaración de demostración va una vez: en el primer mensaje de la conversación o en una consulta suelta.
    first = context is None or not context.get("turnos")
    if first and not re.search(r"simulad|demostracion|fictici|de prueba", normalized):
        return False
    findings = search_findings(calls)
    selected = grounded_products(message, calls)
    availability = availability_by_sku(calls)
    quote, quote_call = latest_quote(calls)
    allowed_amounts = {format_cop(p.price_cop) for p in selected.values()} | store_amounts | orders["amounts"]
    allowed_counts = {p.stock for f in findings for p in f["matches"] + f["nearby"]} | orders["counts"]
    allowed_counts |= {data["stock"] for data in availability.values()}
    allowed_skus = {p.sku for f in findings for p in f["matches"] + f["nearby"]} | orders["skus"]
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
    # Cuánto queda se dice si el cliente lo preguntó, si quedan pocas o si no alcanza (visor, 23-10). En la corrida
    # 26 Grok escribió «Tenemos 27 unidades disponibles» sin que nadie lo preguntara: va la salida determinista.
    short = quote_call is not None and (quote_call["response"].get("error") or {}).get("code") == "INSUFFICIENT_STOCK"
    if not short and not asks_stock(normalize_text(message if current is None else current)):
        said = quantities_in_message(message) | {line["quantity"] for line in (quote or {}).get("lines", [])}
        plenty = {stock for stock in allowed_counts - orders["counts"] if stock > LOW_STOCK} - said
        stated = counts + re.findall(r"\b(\d+)\s+(?:disponibles?|en (?:stock|bodega|existencia))\b", normalized)
        if any(int(count) in plenty for count in stated):
            return False
    # «Agotado» solo vale si algún producto elegido tiene stock 0 (en S2-07 Grok escribió «agotado para 20»
    # con 12 metros disponibles).
    restocks = [p.restock for f in findings for p in f["matches"] + f["nearby"]]
    restocks += [data.get("restock") or "" for data in availability.values()]
    if not restock_reply_ok(normalized, restocks):
        return False
    stocks = [availability.get(p.sku, {}).get("stock", p.stock) for p in selected.values()]
    if OUT_OF_STOCK.search(normalized) and 0 not in stocks:
        return False
    # Cada producto elegido debe aparecer con su precio y, si está agotado, decirlo (ahí el precio sobra: «está
    # agotado, me llega el martes»). Cuánto queda no se exige: el cliente no lo preguntó (visor, 23-10); si Grok lo
    # dice, la cifra ya se comprobó arriba.
    for product in selected.values():
        stock = availability.get(product.sku, {}).get("stock", product.stock)
        if stock > 0 and format_cop(product.price_cop) not in reply:
            return False
        if stock == 0 and not OUT_OF_STOCK.search(normalized):
            return False
    return True
