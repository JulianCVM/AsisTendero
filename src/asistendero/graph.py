"""Flujo: barreras → Grok decide → el servidor valida y ejecuta la herramienta → respuesta verificada.

Cada paso vive en su módulo: ``guardrails`` (lo que nunca llega a Grok), ``validation`` (antes de
ejecutar), ``observations`` (lo que devuelven las herramientas) y ``answers`` (la respuesta final).
En una sesión de chat, ``contexto`` trae los turnos previos que guardó ``sessions``.
"""

from collections.abc import Callable
from time import perf_counter
from typing import NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from asistendero.answers import direct_response, render_answer, reply_is_grounded, with_reservation_note
from asistendero.choices import (
    check_reference, chosen_options, pagination_group, pending_quantity_quote, unresolved_ordinal,
    without_chosen_measures,
)
from asistendero.context_resolution import (
    _heads_in_text, affirms_active_item, is_elliptical_turn, offered_short_quantity, remembered_spec_for_item,
    specs_from_context,
)
from asistendero.grok import ORDER_TOOLS, PROMPT_VERSION, Decision, ModelError
from asistendero.guardrails import screen_message
from asistendero.injection import INJECTION_CODES, blocked_reply, detect_injection
from asistendero.measures import measures
from asistendero.observations import (
    ToolCall, ToolExecutor, error_envelope, execute_safely, observation_for_model, order_results, search_findings,
)
from asistendero.order_rules import (
    RELATIVE_TIME, added_quantities, mentioned_hours, order_action_pending, validate_order_request, wants_to_buy,
)
from asistendero.reminders import pending_reminder, with_reminders
from asistendero.search import without_quantities
from asistendero.shopping_list import list_lines, usable_lines
from asistendero.spelling import heard_as
from asistendero.store_replies import full_category_listing
from asistendero.validation import (
    MAX_QUANTITY, Rejected, foreign_unit, fractional_amount, grounded_selection, is_distinguished, naming_numbers,
    normalize_text, quantities_in_message, quantity_of_other, sale_units, validate_request, without_negated,
)


__all__ = [
    "MAX_MESSAGE_CHARS", "MAX_TOOL_CALLS", "AgentState", "Planner", "ToolExecutor",
    "after_retrieve", "after_validate", "build_graph", "next_node",
]

# planner(mensaje, observaciones, llamadas_disponibles[, context=...]): el contexto solo va en una sesión.
Planner = Callable[..., Decision]

MAX_TOOL_CALLS = 6
MAX_MESSAGE_CHARS = 2000
# Turnos previos del cliente que cuentan como «lo que dijo» para elegir variante y cantidad.
REFERENCE_TURNS = 3
REFUSAL_CLOSING = ("Con gusto te ayudo con productos, precios y existencias del catálogo de demostración, "
                   "o con información de la tienda.")
PERSONAL_DATA_NOTE = "No hace falta compartir datos personales para cotizar; no los guardo."


class AgentState(TypedDict):
    consulta: str
    decisiones: NotRequired[list[Decision]]
    tool_calls: NotRequired[list[ToolCall]]
    error: NotRequired[dict | None]
    respuesta: NotRequired[str]
    estado: NotRequired[str]
    fuente: NotRequired[str]
    prompt_version: NotRequired[str]
    model_called: NotRequired[bool]
    model_calls: NotRequired[int]
    avisos: NotRequired[list[dict]]
    contexto: NotRequired[dict | None]
    referencia: NotRequired[str]
    filtro: NotRequired[dict]
    inyeccion: NotRequired[dict | None]


def _pending(state: AgentState) -> str | None:
    calls = state.get("tool_calls", [])
    if len(calls) >= MAX_TOOL_CALLS:
        return None
    sent = {item["code"] for item in state.get("avisos", [])}
    return pending_reminder(state["consulta"], state["decisiones"][-1], calls, sent, state.get("referencia"),
                            state.get("contexto"))


def _deterministic_complete(state: AgentState) -> bool:
    """True cuando retrieve ya dejó una salida determinista completa y no falta ningún paso ni desambiguación."""
    calls = state.get("tool_calls", [])
    if not calls or state.get("error"):
        return False
    last = calls[-1]
    context = state.get("contexto")
    is_pending_qty = (
        last["requested_tool"] == "calcular_cotizacion_informativa"
        and pending_quantity_quote(state["consulta"], context) is not None
    )
    if (
        last["executed"]
        and is_pending_qty
        and (last["response"].get("error") or {}).get("code") == "INSUFFICIENT_STOCK"
    ):
        return True
    if not last["executed"] or last["response"].get("status") != "ok":
        return False
    decision = state["decisiones"][-1]
    probe = Decision("respond", decision.intent, None, None, "ok")
    if pending_reminder(state["consulta"], probe, calls, set(), state.get("referencia"), context):
        return False
    tool = last["requested_tool"]
    if is_pending_qty:
        return True
    if tool == "explorar_categoria":
        return full_category_listing(calls) or (
            not search_findings(calls) and not order_results(calls) and not quantities_in_message(state["consulta"])
        )
    if tool == "buscar_productos":
        if pagination_group(state["consulta"], context) is not None:
            return True
        findings = [without_negated(state["consulta"], f) for f in search_findings(calls)]
        return bool(findings) and all(not f["matches"] and not f["nearby"] for f in findings)
    if tool == "confirmar_pedido":
        confirmed = {order["pedido"] for name, order in order_results(calls) if name == "confirmar_pedido"}
        pending_left = any(
            order.get("estado") == "pendiente" and order.get("pedido") not in confirmed
            for order in (context or {}).get("pedidos") or []
        )
        has_time = bool(mentioned_hours(state["consulta"]) or RELATIVE_TIME.search(normalize_text(state["consulta"])))
        scheduled = any(name == "agendar_recogida" for name, _ in order_results(calls))
        return not pending_left and (not has_time or scheduled) and "?" not in state["consulta"]
    if tool == "cancelar_pedido":
        return "?" not in state["consulta"]
    if tool == "consultar_pedido":
        return not ((last["response"].get("data") or {}).get("pedidos")) and state["consulta"].count("?") <= 1
    return False


def after_retrieve(state: AgentState) -> str:
    """Salta directo a respond si la herramienta completó una respuesta estandarizada sin pasos pendientes."""
    return "respond" if _deterministic_complete(state) else "interpret"


def _auto_quote_call(
    state: AgentState, calls: list[ToolCall], picked: list[dict], quantities: set[int],
    remembered: dict[str, str], listed: dict[str, int], tool_executor: ToolExecutor,
) -> ToolCall | None:
    """Auto-cotiza en retrieve cuando buscar_productos retorna 1 match unívoco y hay cantidad entera explícita."""
    search_call = calls[-1]
    if (
        search_call["requested_tool"] != "buscar_productos" or not search_call["executed"]
        or search_call["response"].get("status") != "ok" or len(calls) + 1 >= MAX_TOOL_CALLS
        or any(previous["requested_tool"] == "calcular_cotizacion_informativa" for previous in calls)
    ):
        return None
    items = (search_call["arguments"] or {}).get("items") or []
    context = state.get("contexto")
    consulta = state["consulta"]
    if (
        len(items) != 1 or listed or list_lines(context)
        or pagination_group(consulta, context) is not None
        or (bool(context) and wants_to_buy(consulta, context))
    ):
        return None
    if order_action_pending(consulta, state["referencia"], calls, context) is not None:
        return None
    raw_findings = search_findings([search_call])
    if len(raw_findings) != 1 or len(raw_findings[0]["matches"]) != 1:
        return None
    finding = without_negated(consulta, raw_findings[0])
    if len(finding["matches"]) != 1:
        return None
    match = finding["matches"][0]
    described = " ".join([finding["query"], *map(str, finding["request"].values())])
    said_ref = state["referencia"]
    ref_msg = (without_quantities(normalize_text(said_ref))
               if normalize_text(match.unit) in sale_units(said_ref) else said_ref)
    if not is_distinguished(heard_as(ref_msg, described), described, match, finding["matches"]):
        return None
    if grounded_selection(said_ref, finding) != match or fractional_amount(consulta) is not None:
        return None
    turn_quantities = (
        quantities_in_message(without_chosen_measures(consulta, picked))
        - naming_numbers(consulta, finding["matches"] + finding["nearby"])
        - mentioned_hours(consulta)
    )
    valid_quantities = [q for q in turn_quantities if 1 <= q <= MAX_QUANTITY]
    if len(valid_quantities) != 1:
        return None
    quantity = valid_quantities[0]
    if (
        foreign_unit(consulta, quantity, f"{match.unit} {match.variant}")
        or quantity_of_other(consulta, quantity, f"{match.name} {match.variant} {match.unit}")
    ):
        return None
    try:
        quote_args = validate_request(
            "calcular_cotizacion_informativa", {"lines": [{"sku": match.sku, "quantity": quantity}]},
            said_ref, calls, quantities, remembered, listed, consulta,
        )
    except Rejected:
        return None
    started = perf_counter()
    response = execute_safely(tool_executor, "calcular_cotizacion_informativa", quote_args)
    return {
        "step": len(calls) + 1, "requested_tool": "calcular_cotizacion_informativa",
        "requested_arguments": quote_args, "executed": True, "arguments": quote_args,
        "response": response, "duration_ms": round((perf_counter() - started) * 1000),
    }


def next_node(state: AgentState) -> str:
    """Ruta tras cada decisión de Grok; la traza usa la misma regla."""
    if state.get("error"):
        return "respond"
    decision = state["decisiones"][-1]
    if decision.valid_json and decision.action == "call_tool" and len(state.get("tool_calls", [])) < MAX_TOOL_CALLS:
        return "retrieve"
    if _pending(state):
        return "interpret"
    return "respond"


def after_validate(state: AgentState) -> str:
    """Si todo el mensaje pedía algo que no se entrega, se responde sin llamar a Grok."""
    return "interpret" if state["consulta"] else "respond"


def reference_text(message: str, context: dict | None) -> str:
    """Lo que el cliente dijo en la conversación reciente, las especificaciones fijadas vigentes y el mensaje actual."""
    turns = (context or {}).get("turnos") or []
    previous = [turn["cliente"] for turn in turns[-REFERENCE_TURNS:] if isinstance(turn.get("cliente"), str)]
    spec_lines: list[str] = []
    if specs_from_context(context):
        heads = list(_heads_in_text(message))
        if not heads and (elliptical := is_elliptical_turn(message, context)):
            heads = [elliptical[1]]
        for head in heads:
            spec = remembered_spec_for_item(head, head, message, context)
            parts = [spec[k] for k in ("material", "medida", "presentacion") if spec.get(k)]
            if parts:
                spec_lines.append(f"{head} {' '.join(parts)}")
    return "\n".join([*spec_lines, *previous, message])


def build_graph(tool_executor: ToolExecutor, planner: Planner):
    def validate(state: AgentState) -> dict:
        message = state["consulta"].strip()
        if not message:
            raise ValueError("La consulta no puede estar vacía.")
        if len(message) > MAX_MESSAGE_CHARS:
            raise ValueError(f"La consulta supera el límite de {MAX_MESSAGE_CHARS} caracteres.")
        context = state.get("contexto") or None
        turns = (context or {}).get("turnos") or []
        injection = detect_injection(message, (turns[-1].get("cliente") or "") if turns else "")
        if injection:
            # El mensaje no se guarda ni llega a Grok: intentaba cambiar las reglas del agente.
            return {"consulta": "", "decisiones": [], "tool_calls": [], "error": None, "model_calls": 0,
                    "referencia": "", "filtro": {"codes": [], "refusal": "", "redacted": False},
                    "inyeccion": {"code": injection.code, "technique": injection.technique}}
        screening = screen_message(message)
        return {
            "consulta": screening.consulta, "decisiones": [], "tool_calls": [], "error": None, "model_calls": 0,
            "referencia": reference_text(screening.consulta, context) if screening.consulta else "",
            "filtro": {"codes": list(screening.codes), "refusal": screening.refusal, "redacted": screening.redacted},
        }

    def interpret(state: AgentState) -> dict:
        calls = state["tool_calls"]
        model_calls = state["model_calls"] + 1
        update: dict = {"model_called": True, "model_calls": model_calls}
        avisos = state.get("avisos", [])
        # Solo se vuelve aquí tras un «respond» cuando next_node detectó un aviso pendiente.
        if state["decisiones"] and state["decisiones"][-1].action == "respond":
            avisos = update["avisos"] = avisos + [{"code": _pending(state), "at": len(calls)}]
        observations = with_reminders([observation_for_model(call) for call in calls], avisos)
        context = state.get("contexto")
        try:
            decision = planner(state["consulta"], observations, MAX_TOOL_CALLS - len(calls),
                               **({"context": context} if context else {}))
        except ModelError as exc:
            return {**update, "error": {"code": exc.code, "message": str(exc)}}
        except Exception as exc:
            return {**update, "error": {"code": "MODEL_UNAVAILABLE",
                                        "message": f"Fallo inesperado del modelo ({type(exc).__name__})."}}
        return {**update, "decisiones": state["decisiones"] + [decision]}

    def retrieve(state: AgentState) -> dict:
        decision = state["decisiones"][-1]
        calls = state["tool_calls"]
        started = perf_counter()
        context = state.get("contexto")
        # «dame del primero» o «sí, esa» (con opción única): cuenta como producto identificado.
        picked = chosen_options(state["consulta"], context)
        if not picked and (affirmed := affirms_active_item(state["consulta"], context)):
            picked = [affirmed]
        pending_qty = None if picked else pending_quantity_quote(state["consulta"], context)
        if pending_qty is not None:
            picked = [pending_qty[0]]
        effective_tool = decision.tool
        effective_args = decision.arguments
        if pending_qty is not None and effective_tool == "buscar_productos":
            effective_tool = "calcular_cotizacion_informativa"
            effective_args = {"lines": [{"sku": pending_qty[0]["sku"], "quantity": pending_qty[1]}]}
        call: ToolCall = {
            "step": len(calls) + 1, "requested_tool": effective_tool,
            "requested_arguments": effective_args, "executed": False, "arguments": None,
            "response": {}, "duration_ms": 0,
        }
        listed = usable_lines(state["consulta"], context)
        # Lo que el cliente quitó o dejó atrás al empezar de nuevo tampoco vale como producto recordado.
        dropped = set(list_lines(context)) - set(listed)
        known = [*((context or {}).get("productos") or []), *picked]
        remembered = {item.get("sku"): f"{item.get('nombre', '')} {item.get('variante', '')} {item.get('unidad', '')}"
                      for item in known if item.get("sku") not in dropped}
        quantities: set[int] = set()
        try:
            turns = (context or {}).get("turnos") or []
            recent_utterances = "\n".join([
                *(turn["cliente"] for turn in turns[-REFERENCE_TURNS:] if isinstance(turn.get("cliente"), str)),
                state["consulta"],
            ])
            offered_qty = offered_short_quantity(state["consulta"], context)
            # Las cantidades son las del turno; si el turno no dice ninguna («cotízalo»), las de la conversación.
            quantities = (
                quantities_in_message(without_chosen_measures(state["consulta"], picked))
                or ({offered_qty} if offered_qty is not None else set())
                or quantities_in_message(without_chosen_measures(recent_utterances, picked))
            )
            if offered_qty is not None:
                quantities.add(offered_qty)
            if pending_qty is not None:
                quantities.add(pending_qty[1])
            quantities |= added_quantities(state["consulta"], context)
            check_reference(effective_tool, effective_args, state["consulta"], calls, context)
            if effective_tool in ORDER_TOOLS and isinstance(effective_args, dict):
                # Los pedidos miran el mensaje del turno: confirmar o cancelar lo tiene que decir ahora el cliente.
                arguments = validate_order_request(effective_tool, effective_args, current=state["consulta"],
                                                   reference=state["referencia"], calls=calls, context=context)
            else:
                arguments = validate_request(
                    effective_tool, effective_args, state["referencia"], calls, quantities,
                    remembered, listed, state["consulta"], context=context, picked=picked,
                )
            if any(previous["executed"] and previous["requested_tool"] == effective_tool
                   and previous["arguments"] == arguments for previous in calls):
                raise Rejected("DUPLICATE_CALL", "Esa llamada ya se ejecutó; usa su observación.")
        except Rejected as exc:
            message = str(exc)
            if exc.code == "SKU_NOT_GROUNDED" and picked:
                # Corrida 26: Grok leyó «del primero» como la primera manguera, el rechazo no decía cuál era y la
                # conversación perdió el tubo. Se nombra lo que el cliente eligió de las opciones que vio.
                message += " De las opciones que vio, el cliente eligió: " + "; ".join(
                    f"{item['sku']} ({item.get('nombre', '')} {item.get('variante', '')})".strip() for item in picked) + "."
            call["response"] = error_envelope("rejected", exc.code, message, "agent_validation")
        else:
            response = execute_safely(tool_executor, effective_tool, arguments)
            if (
                effective_tool == "buscar_productos"
                and response.get("status") == "ok"
                and isinstance(effective_args, dict)
            ):
                raw_items = effective_args.get("items") or []
                clean_items = arguments.get("items") or []
                results = (response.get("data") or {}).get("results") or []
                retried_items = []
                needs_retry = False
                for idx, clean_item in enumerate(clean_items):
                    raw_item = raw_items[idx] if idx < len(raw_items) and isinstance(raw_items[idx], dict) else {}
                    res_matches = (
                        results[idx].get("matches") if idx < len(results) and isinstance(results[idx], dict) else None
                    )
                    if (
                        res_matches == []
                        and "measure" in clean_item
                        and not raw_item.get("measure")
                        and not measures(state["consulta"])
                    ):
                        retried_items.append({k: v for k, v in clean_item.items() if k != "measure"})
                        needs_retry = True
                    else:
                        retried_items.append(clean_item)
                if needs_retry:
                    arguments = {"items": retried_items}
                    response = execute_safely(tool_executor, effective_tool, arguments)
            call.update(executed=True, arguments=arguments, response=response)
        call["duration_ms"] = round((perf_counter() - started) * 1000)
        updated_calls = calls + [call]
        auto_quote = _auto_quote_call(state, updated_calls, picked, quantities, remembered, listed, tool_executor)
        if auto_quote is not None:
            updated_calls.append(auto_quote)
        return {"tool_calls": updated_calls, "fuente": "mock_sqlite"}

    def respond(state: AgentState) -> dict:
        injection = state.get("inyeccion")
        if injection:
            return {"prompt_version": PROMPT_VERSION, "model_called": False, "model_calls": 0, "estado": "blocked",
                    "respuesta": blocked_reply(state.get("contexto")),
                    "error": {"code": "INJECTION_DETECTED", "message": INJECTION_CODES[injection["code"]]}}
        guard = state.get("filtro") or {}
        notes = [note for note in (guard.get("refusal"), PERSONAL_DATA_NOTE if guard.get("redacted") else "") if note]
        if not state["consulta"]:
            return {"prompt_version": PROMPT_VERSION, "model_called": False, "model_calls": 0,
                    "estado": "refused", "respuesta": " ".join([*notes, REFUSAL_CLOSING])}
        update = _respond(state)
        update["respuesta"] = with_reservation_note(state["consulta"], update["respuesta"], state["tool_calls"],
                                                    state.get("contexto"))
        if notes:
            update["respuesta"] = " ".join(notes) + "\n" + update["respuesta"]
        return update

    def _respond(state: AgentState) -> dict:
        message, calls = state["referencia"], state["tool_calls"]
        common = {"prompt_version": PROMPT_VERSION, "model_called": state.get("model_called", False),
                  "model_calls": state.get("model_calls", 0)}
        error = state.get("error")
        decision = state["decisiones"][-1] if state["decisiones"] else None
        if error is None and decision is not None and not decision.valid_json:
            error = {"code": "MODEL_INVALID_OUTPUT", "message": "Grok devolvió una decisión con formato inválido."}
        elif error is None and decision is not None and decision.action == "call_tool" and not _deterministic_complete(state):
            error = {"code": "TOOL_CALL_LIMIT", "message": f"Se alcanzó el límite de {MAX_TOOL_CALLS} herramientas."}

        if error:
            estado = {"MODEL_INVALID_OUTPUT": "model_invalid", "TOOL_CALL_LIMIT": "limit_reached"}.get(error["code"], "model_error")
            if calls:
                # Lo ya consultado es verificable; se muestra aunque el modelo haya fallado.
                _, answer = render_answer(message, calls, state.get("contexto"), state["consulta"])
            elif estado == "model_invalid":
                answer = "No pude interpretar bien tu mensaje. ¿Puedes contarme de nuevo qué producto necesitas?"
            else:
                answer = ("No pude completar la consulta con el asistente en este momento, así que no tengo "
                          "precios ni existencias verificados. Intenta de nuevo en unos minutos.")
            return {**common, "estado": estado, "error": error, "respuesta": answer}

        if not calls:
            context = state.get("contexto")
            asked = state["consulta"]
            if pagination_group(asked, context) is not None or unresolved_ordinal(asked, context) is not None:
                status, answer = render_answer(message, calls, context, asked)
                return {**common, "estado": status, "respuesta": answer}
            selected_only = chosen_options(asked, context) or (
                [aff] if (aff := affirms_active_item(asked, context)) else []
            )
            if len(selected_only) == 1 and not quantities_in_message(without_chosen_measures(asked, selected_only)):
                status, answer = render_answer(message, calls, context, asked)
                return {**common, "estado": status, "respuesta": answer}
            return {**common, "estado": "answered", "respuesta": direct_response(asked, decision)}
        status, answer = render_answer(message, calls, state.get("contexto"), state["consulta"])
        if decision.action == "respond" and reply_is_grounded(
            decision.reply, message, calls, state.get("contexto"), state["consulta"],
        ):
            answer = decision.reply.strip()
        return {**common, "estado": status, "respuesta": answer}

    builder = StateGraph(AgentState)
    builder.add_node("validate", validate)
    builder.add_node("interpret", interpret)
    builder.add_node("retrieve", retrieve)
    builder.add_node("respond", respond)
    builder.add_edge(START, "validate")
    builder.add_conditional_edges("validate", after_validate, {"interpret": "interpret", "respond": "respond"})
    builder.add_conditional_edges(
        "interpret", next_node, {"retrieve": "retrieve", "respond": "respond", "interpret": "interpret"},
    )
    builder.add_conditional_edges("retrieve", after_retrieve, {"interpret": "interpret", "respond": "respond"})
    builder.add_edge("respond", END)
    return builder.compile()
