"""Respuesta final: determinista con datos de herramientas o redacción de Grok comprobada."""

import re

from asistendero.agente.entrada.guardrails import leaks
from asistendero.agente.herramientas.observations import (
    availability_by_sku, latest_quote, order_results, search_findings, store_info_by_topic, ToolCall,
)
from asistendero.agente.modelo.grok import MAX_ITEMS, Decision
from asistendero.agente.modelo.prompt import active_prompt
from asistendero.agente.reglas.choices import (
    ambiguous_reference, chosen_options, next_options_page, pagination_group, unresolved_ordinal,
)
from asistendero.agente.reglas.context_resolution import (
    affirms_active_item, filter_matches_by_spec, pending_quantity_target, remembered_spec_for_item,
)
from asistendero.agente.reglas.validation import (
    foreign_unit, fractional_amount, grounded_products, grounded_selection, naming_numbers, quantities_in_message,
    without_negated,
)
from asistendero.agente.respuesta.order_replies import order_allowances, order_reply, rushes_the_customer
from asistendero.agente.respuesta.reply_text import (
    DEMO_NOTE, FEMININE, LOW_STOCK, MAX_NEARBY, MAX_OPTIONS, SUITABILITY_CLAIM, SUITABILITY_NOTE, asks_stock,
    asks_suitability, found_sentence, in_sentence, label, of_the, option_lines, quote_block, quote_offer,
    short_stock_line, short_stock_text, units, whole_units_question,
)
from asistendero.agente.respuesta.restock import asks_restock, restock_reply_ok, restock_sentence, restock_subjects
from asistendero.agente.respuesta.store_replies import (
    asks_assortment, full_category_listing, promises_credit, store_lines, store_reply_is_consistent,
)
from asistendero.tienda.catalogo.catalog import Product, tokens
from asistendero.tienda.vocabulario import format_cop, normalize_text


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

# Pagar después es pedir fiado: «le pago el viernes» (P-fiado-2, corrida 42: Grok ofreció anotarlo sin decir que
# no se fía), «se lo pago en la quincena».
PAY_LATER = (r"(?:pago|pagar|pagaria)\s+(?:(?:el|la|en\s+la|a\s+fin\s+de)\s+)?(?:manana|despues|luego|otra\s+semana"
             r"|lunes|martes|miercoles|jueves|viernes|sabado|domingo|quincena|mes|semana\s+que\s+viene)")
# Un pedido de apartar, reservar o fiar recibe siempre esta aclaración, la redacte Grok o no.
RESERVATION_REQUEST = re.compile(
    r"\b(?:apart\w+|reserv\w+|separ(?:a|e|ar|ame|amelo|en)\b|fia\w*|fiar\w*|credito|" + PAY_LATER + ")"
)
RESERVATION_NOTE = "No es un pedido ni una reserva: por este chat solo te comparto la cotización; no aparto productos, no fío ni recibo pagos."
# En una sesión sí hay pedidos: lo que nunca se hace es fiar o cobrar, y sin pedido registrado no hay nada apartado.
CREDIT_REQUEST = re.compile(r"\b(?:fia\w*|fiar\w*|credito|" + PAY_LATER + ")")
CREDIT_NOTE = "Vecino, por políticas de la tienda no fío ni recibo pagos por este chat: todo se cancela en el mostrador al momento de recoger."
NO_ORDER_NOTE = "Todavía no hay nada apartado: si te antojas de llevarlo, dime cuántas unidades necesitas y con mucho gusto registro el pedido."


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
OUT_OF_STOCK = re.compile(r"\bagotad|\bse (?:me |nos |le )?(?:acabo|acabaron|agoto|agotaron)\b|\bno (?:me|nos) quedan?\b")


def direct_response(original: str, decision: Decision) -> str:
    # Sin consultar_info_tienda no hay horario verificado: aunque Grok clasifique «¿están atendiendo?»
    # como saludo, nunca se afirma apertura.
    if re.search(
        r"\b(atendiendo|atienden|atiende|abiert[oa]s?|cerrad[oa]s?|horario|abren|cierran)\b",
        normalize_text(original),
    ):
        return ("No pude verificar el horario de la tienda en este momento. "
                "Si me cuentas qué producto buscas, con mucho gusto te doy precio y disponibilidad.")
    reply = decision.reply.strip()
    # Sin explorar_categoria, una lista de lo que vende la tienda sería inventada («herramientas eléctricas», 26-10).
    if asks_assortment(normalize_text(original)):
        return "¡Hola! Con mucho gusto te ayudo. ¿Qué estás buscando? Dime el producto y la medida, y de una te doy precio y disponibilidad."
    # Fiar nunca se promete, consulte o no la tienda: el pago es en el mostrador (contrato del agente). En la corrida
    # 40 (M-33) Grok respondió sin herramientas «Listo, te lo anoto en el cuaderno… Pasa el viernes a pagar».
    if promises_credit(normalize_text(reply)):
        return ("Vecino, por políticas de la tienda no fiamos ni manejamos fiado: todo se cancela en el mostrador al "
                "momento de recoger. ¿Te puedo colaborar con alguna otra consulta?")
    # Sin herramientas no hay precio ni existencias comprobadas que se puedan afirmar.
    if (
        not reply or len(reply) > 400 or FORBIDDEN_CLAIMS.search(reply) or "$" in reply
        or leaks(reply, active_prompt()[1])
        or re.search(r"\b\d+\s+(metro|bulto|unidad|galon)", normalize_text(reply))
    ):
        return "¡Hola! Con mucho gusto te atiendo. ¿Qué estás buscando? Te doy precio y disponibilidad de lo que necesites."
    return reply


def _join(parts: list[str]) -> str:
    return "\n\n".join(part for part in parts if part)


def _option_to_product(item: dict) -> Product:
    return Product(
        sku=item.get("sku") or "",
        name=item.get("nombre") or "producto",
        variant=item.get("variante") or "",
        unit=item.get("unidad") or "unidad",
        price_cop=0,
        stock=0,
        updated_at="",
    )


def _render_pagination(group: dict, asked_raw: str, store: list[str], demo: list[str]) -> tuple[str, str]:
    if group.get("restantes"):
        shown_now, still_left = next_options_page(group, asked_raw)
        items = [_option_to_product(opt) for opt in shown_now]
        same_name = len({item.name for item in items}) == 1
        subject = in_sentence(items[0].name) if same_name else _display(group["grupo"], items, shared=True)
        extra = len(still_left)
        more = f"\n(y {extra} {'opción' if extra == 1 else 'opciones'} más)" if extra > 0 else ""
        question = ("¿Qué medida o referencia necesitas? Con gusto te doy el precio." if same_name
                    else "¿Cuál te sirve? Con mucho gusto te doy el precio.")
        block = f"De {subject} también tengo estas opciones:\n" + "\n".join(option_lines(items)) + f"{more}\n{question}"
        return "clarify", _join([block, *store, *demo])
    items = [_option_to_product(opt) for opt in (group.get("opciones") or [])]
    if not items:
        return "clarify", _join(["¿Qué producto y qué medida buscas? Dime y con mucho gusto te ayudo.", *store, *demo])
    same_name = len({item.name for item in items}) == 1
    subject = in_sentence(items[0].name) if same_name else _display(group["grupo"], items, shared=True)
    question = ("¿Qué medida o referencia necesitas? Con gusto te doy el precio." if same_name
                else "¿Cuál te sirve? Con mucho gusto te doy el precio.")
    block = f"De {subject} esas son todas las opciones que manejo:\n" + "\n".join(option_lines(items)) + f"\n{question}"
    return "clarify", _join([block, *store, *demo])


def render_answer(message: str, calls: list[ToolCall], context: dict | None = None,
                  current: str | None = None) -> tuple[str, str]:
    """Respuesta determinista construida solo con lo que devolvieron las herramientas.

    ``context`` es el de la sesión (None fuera de ella): en una conversación la cotización termina ofreciendo
    apartar y la aclaración de demostración va solo en el primer mensaje. ``message`` es la referencia (turnos
    recientes más el actual, para respaldar productos); ``current``, solo el mensaje de este turno: lo que el cliente
    pregunta ahora (cuánto queda, cuándo llega) no se arrastra de un turno anterior.
    """
    asked_raw = message if current is None else current
    asked = normalize_text(asked_raw)
    findings = search_findings(calls)
    store = store_lines(calls, with_listing=not findings or asks_assortment(asked))
    orders = order_reply(calls)
    quote, quote_call = latest_quote(calls)
    demo = [DEMO_NOTE] if context is None or not context.get("turnos") else []
    order_text = [orders[1]] if orders else []
    if not quote and not orders and (page_group := pagination_group(asked_raw, context)) is not None:
        return _render_pagination(page_group, asked_raw, store, demo)
    if not findings and quote:
        block = _with_offer(quote_block(quote, {}, _quote_header(quote, {})), quote,
                            quote_offer(context, orders and orders[0], False))
        return (orders and orders[0]) or "quoted", _join([block, *store, *order_text, *demo])
    rejected = {(call["response"].get("error") or {}).get("code") for call in calls if not call["executed"]}
    if not findings and not store and not any(call["executed"] for call in calls) and "SESSION_REQUIRED" in rejected:
        # Z-11 (corrida 34): sin conversación, «deme 3 de esos» intentó un pedido y la respuesta decía «abre una
        # conversación»; el cliente nunca dijo qué producto quería.
        return "clarify", _join(["¡Con mucho gusto te ayudo! ¿De qué producto me hablas? Dime cuál y qué medida, y te lo busco de una.", *demo])
    if not findings and (store or orders):
        return (orders and (orders[0] or "order_issue")) or "informed", _join([*store, *order_text, *demo])
    checked = availability_by_sku(calls)
    if not findings and quote_call and (quote_call["response"].get("error") or {}).get("code") == "INSUFFICIENT_STOCK":
        # Q-13 (corrida 30): «agrégale 1 galón más» se cotizó sin buscar en el turno; no alcanzaba y la respuesta
        # decía «No pude consultar el catálogo».
        return "insufficient_stock", _join([_short_of_known(quote_call, context, checked), *demo])
    if not findings and checked:
        # Un producto que la sesión ya conocía, consultado sin buscar («¿y cuándo le llegan más?»).
        lines = [_availability_line(data, asked) for data in checked.values()]
        return "found", _join([*lines, *demo])
    if not findings:
        options = ambiguous_reference(asked_raw, context)
        if options and any((call["response"].get("error") or {}).get("code") == "AMBIGUOUS_REFERENCE" for call in calls):
            return "clarify", f"¿Cuál quieres: {' o '.join(options)}? Dime cuál prefieres y con mucho gusto te lo cotizo."
        if any((call["response"].get("error") or {}).get("code") == "VAGUE_SEARCH" for call in calls):
            return "clarify", "¡Con mucho gusto te ayudo! ¿De qué producto me hablas? Dime cuál y qué medida, y te lo busco de una."
        if any((call["response"].get("error") or {}).get("code") == "TOO_MANY_ITEMS" for call in calls):
            return "clarify", (f"Puedo revisar hasta {MAX_ITEMS} productos por mensaje para darte el dato exacto. "
                               f"¿Me mandas la lista en grupos de {MAX_ITEMS} o menos, por favor?")
        selected_ctx = chosen_options(asked_raw, context)
        if not selected_ctx and (aff := affirms_active_item(asked_raw, context)):
            selected_ctx = [aff]
        if len(selected_ctx) == 1 and selected_ctx[0].get("nombre"):
            target = selected_ctx[0]
            unit = target.get("unidad") or "unidad"
            many = "Cuántas" if unit in FEMININE else "Cuántos"
            item_name = in_sentence(label(target["nombre"], target.get("variante") or ""))
            return "clarify", _join([f"¡Perfecto! ¿{many} {units(unit, 2)} {of_the(item_name)} necesitas? Con gusto te cotizo.", *demo])
        if ordinal_note := unresolved_ordinal(asked_raw, context):
            return "clarify", _join([ordinal_note, *demo])
        if any(call["response"]["status"] == "error" for call in calls):
            return "tool_error", ("En este momento no pude consultar el catálogo, así que no tengo precios ni "
                                  "existencias verificados. Por favor intenta de nuevo en unos minutos y con gusto te atiendo.")
        return "not_verified", ("Ese producto no lo tengo identificado así en el catálogo. ¿Me cuentas qué "
                                "producto y qué medida buscas para colaborarte con gusto?")

    availability = availability_by_sku(calls)
    quoted = {line["sku"] for line in (quote or {}).get("lines", [])}
    picked_skus = {opt["sku"] for opt in chosen_options(asked_raw, context) if opt.get("sku")}
    if not picked_skus and (aff := affirms_active_item(asked_raw, context)) and aff.get("sku"):
        picked_skus = {aff["sku"]}
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
    last_selected: Product | None = None
    zero_restock_said = False
    seen = set()
    for index, finding in enumerate(findings):
        finding = without_negated(asked, finding)
        spec = remembered_spec_for_item(finding["query"], finding["request"].get("product"), asked_raw, context)
        matches = filter_matches_by_spec(list(finding["matches"]), spec)
        finding = {**finding, "matches": matches}
        nearby = finding["nearby"]
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
        in_picked = [product for product in matches if product.sku in picked_skus]
        selected = selected or (in_picked[0] if len(in_picked) == 1 else None)
        if not matches and nearby:
            material = finding["request"].get("material")
            material_differs = material and all(
                not tokens(material) <= tokens(f"{item.name} {item.variant}") for item in nearby
            )
            caveat = " Es de otro material, habría que ver si te sirve para ese uso." if material_differs else ""
            closest = in_sentence(nearby[0].name) if len({item.name for item in nearby[:MAX_NEARBY]}) == 1 else "esto"
            options = "\n".join(option_lines(nearby[:MAX_NEARBY]))
            query = _display(finding["query"], nearby)
            sentences.append(f"{query[0].upper()}{query[1:]} así como lo pides no lo tengo disponible por ahora. "
                             f"Lo más parecido que tengo es {closest}, aunque no es exactamente lo mismo.{caveat}\n{options}")
            statuses.append("nearby")
        elif not matches:
            sentences.append(f"Por ahora {finding['query']} no lo manejo. Si buscas alguna otra herramienta, "
                             "referencia o medida, cuéntame y con mucho gusto te la busco.")
            statuses.append("not_found")
        elif selected:
            last_selected = selected
            stock = availability.get(selected.sku, {}).get("stock", selected.stock)
            first = not any(status == "found" for status in statuses)
            restock_val = availability.get(selected.sku, {}).get("restock", selected.restock)
            restock = restock_sentence(in_sentence(label(selected.name, selected.variant)),
                                       restock_val, index in restock_about, stock)
            # Lo que va en la cotización ya sale con su precio ahí: repetirlo arriba sonaba a reporte. Agotado, la
            # frase del surtido ya lo dice.
            if selected.sku not in quoted and stock > 0:
                sentences.append(found_sentence(selected, stock, first, asks_stock(asked) and not short, needed,
                                                suitability))
            if restock and not (short and stock <= 0 and not restock_val and index not in restock_about):
                sentences.append(restock)
                if stock <= 0:
                    zero_restock_said = True
            statuses.append("found")
        else:
            same_name = len({item.name for item in matches}) == 1
            intro = (f"De {in_sentence(matches[0].name)} tengo estas opciones:" if same_name
                     else f"De {_display(finding['query'], matches, shared=True)} tengo estas opciones:")
            extra = len(matches) - MAX_OPTIONS
            more = f"\n(y {extra} {'opción' if extra == 1 else 'opciones'} más)" if extra > 0 else ""
            # Con el mismo nombre solo cambia la variante: se pregunta por ella, como en el mostrador.
            question = ("¿Qué medida o referencia necesitas? Con gusto te doy el precio." if same_name
                        else "¿Cuál te sirve? Con mucho gusto te doy el precio.")
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
            quote_part = short_stock_text(quote_call["arguments"]["lines"], products, availability,
                                          skip_zero=zero_restock_said)
            if not quote_part and not zero_restock_said:
                quote_part = _short_of_known(quote_call, context, availability)
            status = "insufficient_stock"
        else:
            quote_part = "En este momento no pude calcular el total, pero los precios unitarios de arriba sí están al día."
            status = "quote_error"
    if orders:
        status = orders[0] or status
    if status == "found" and len(statuses) == 1 and not store and not orders and not restock_asked:
        product = next(iter(grounded_products(message, calls).values()), None) or last_selected
        if product and availability.get(product.sku, {}).get("stock", product.stock) > 0:
            # Z-01 (suite fallas): con «2.5 metros» se preguntaba «¿Cuántos metros necesitas?», como si no lo hubiera
            # dicho; se vende por unidad entera y se ofrecen las dos más cercanas.
            whole = fractional_amount(asked_raw)
            many = "Cuántas" if product.unit in FEMININE else "Cuántos"
            questions.append(whole_units_question(product.unit, whole) if whole
                             else f"¿{many} {units(product.unit, 2)} necesitas? Con gusto te cotizo.")
    # La tienda va después de los productos: el horario se suele preguntar al final («¿a qué hora paso?»).
    caution = [SUITABILITY_NOTE] if suitability else []
    answer = _join([*sentences, *caution, quote_part, *store, *questions, *order_text, *demo])
    return status, answer


def _short_of_known(call: ToolCall, context: dict | None, availability: dict | None = None) -> str:
    """Lo que no alcanzó, nombrado con lo que la sesión ya conoce del producto (no hubo búsqueda en el turno)."""
    known = {
        opt.get("sku"): opt
        for group in (context or {}).get("opciones") or []
        for opt in (group.get("opciones") or [])
        if isinstance(opt, dict) and opt.get("sku")
    }
    if (focus := pending_quantity_target(context)) and focus.get("sku"):
        known[focus["sku"]] = focus
    known.update({item.get("sku"): item for item in (context or {}).get("productos") or []})
    held = {line.get("sku") for order in (context or {}).get("pedidos") or []
            if order.get("estado") in {"pendiente", "confirmado"} for line in order.get("lineas") or []}
    lines = call["arguments"]["lines"]
    error_msg = (call["response"].get("error") or {}).get("message") or ""
    line = next((line for line in lines if line["sku"] in error_msg), lines[0])
    sku = line["sku"]
    avail_data = (availability or {}).get(sku) or {}
    item = known.get(sku) or avail_data or {}
    name = in_sentence(label(item.get("nombre") or item.get("name") or "ese producto",
                             item.get("variante") or item.get("variant") or ""))
    unit = item.get("unidad") or item.get("unit") or "unidad"
    quantity = line["quantity"]
    note = " Lo que ya tienes apartado en tu pedido también cuenta." if sku in held else ""
    stock = avail_data.get("stock") if isinstance(avail_data.get("stock"), int) else None
    if stock is None and (match := re.search(r"disponibles?\s+(\d+)", error_msg)):
        stock = int(match.group(1))
    if stock is None and isinstance(item.get("stock"), int):
        stock = item["stock"]
    if stock is not None:
        return short_stock_line(name, stock, quantity, unit, note)
    req_article = ("la" if quantity == 1 else "las") if unit in FEMININE else ("el" if quantity == 1 else "los")
    reach = "alcanza" if quantity == 1 else "alcanzan"
    clause = f"{of_the(name)} no me {reach} {req_article} {quantity} {units(unit, quantity)}."
    return f"{clause[0].upper()}{clause[1:]}{note} ¿Prefieres revisar otra cantidad o medida?"


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
    return "¡Con mucho gusto! Con lo que llevas, te quedaría así:" if carried else "¡Con mucho gusto! Te quedaría así:"


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
    if not reply or len(reply) > 1200 or leaks(reply, active_prompt()[1]) or rushes_the_customer(reply, calls, context):
        return False
    # La lista de categorías va siempre con los nombres del catálogo: en el visor (26-10) Grok la resumió como
    # «herramientas manuales y eléctricas … y más», y no hay herramientas eléctricas.
    if full_category_listing(calls):
        return False
    if pagination_group(message if current is None else current, context) is not None:
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
    # H-09 (corrida 42): Grok registró el pedido y escribió «apartado por 5 minutos. ¿A qué hora pasas?» sin pedir el
    # «sí»; el pedido vence si no se confirma y el cliente no lo sabía.
    if (any(tool == "registrar_pedido" and order["estado"] == "pendiente" for tool, order in order_results(calls))
            and "confirm" not in normalized):
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
        err_msg = (quote_call["response"].get("error") or {}).get("message") or ""
        if match := re.search(r"disponibles?\s+(\d+)", err_msg):
            allowed_counts.add(int(match.group(1)))
    if not set(re.findall(r"\$[\d.,]*\d", reply)) <= allowed_amounts:
        return False
    # X-06 (corrida 39): el cable se vende por metro y Grok escribió «un rollo … te sale a $2.700 el metro», como si
    # el rollo costara eso. Con la cantidad en otra unidad de venta, la respuesta determinista pregunta.
    asked_now = message if current is None else current
    if not quote and any(foreign_unit(asked_now, quantity, f"{product.unit} {product.variant}")
                         for product in selected.values() for quantity in quantities_in_message(asked_now)):
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
    if short:
        err_msg = (quote_call["response"].get("error") or {}).get("message") or ""
        err_stock = int(m.group(1)) if (m := re.search(r"disponibles?\s+(\d+)", err_msg)) else None
        for line in quote_call["arguments"]["lines"]:
            product = selected.get(line["sku"])
            stock = availability.get(line["sku"], {}).get("stock", product.stock if product else err_stock)
            if stock is not None and line["quantity"] > stock:
                if stock > 0 and not re.search(rf"\b{stock}\b", reply):
                    return False
                if stock == 0 and not OUT_OF_STOCK.search(normalized):
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
