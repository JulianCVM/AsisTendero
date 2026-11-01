"""Un turno de chat: contexto de la sesión → mismo grafo trazado → memoria del turno.

Antes del grafo se mira quién atiende la conversación (``handoff.py``): si la tomó el tendero, o si el cliente pide
hablar con una persona, el turno se responde con un texto fijo y no se llama a Grok.
"""

from collections.abc import Callable
from datetime import datetime, timezone
import os
from time import perf_counter
from uuid import uuid4

from asistendero.catalog import MockCatalog
from asistendero.executor import catalog_executor
from asistendero.graph import MAX_MESSAGE_CHARS, Planner, ToolExecutor
from asistendero.grok import ModelError, PROMPT_VERSION, decide_with_grok
from asistendero.guardrails import redact_personal_data, screen_message
from asistendero.handoff import (
    HANDOFF_AGAIN_REPLY, HANDOFF_REPLY, STAFF_HOLD_REPLY, asks_for_human, attention, cancel_active,
    escalate_after_failures, last_status, request_human,
)
from asistendero.injection import detect_injection
from asistendero.orders import WEEKDAYS, OrderBook
from asistendero.choices import chosen_options, coherent_option_turn, shown_options
from asistendero.context_resolution import affirms_active_item, updated_specs
from asistendero.pricing import run_cost
from asistendero.sessions import MAX_CLOSED_ORDERS, SessionStore, remembered_products
from asistendero.shopping_list import updated_list
from asistendero.tracing import run_traced
from asistendero.vision import (
    BASE64_DATA_URI, SAMPLE_COUNTER_TEMPLATE, SCREW_SAFEGUARD_TEMPLATE,
    ImageAttributePayload, extract_vision_attributes,
    handle_vision_turn, sanitize_image_text,
)


def order_context(orders: list[dict]) -> list[dict]:
    """Pedidos de la sesión para Grok: activos más recientes cerrados, sin precios ni campos nulos."""
    active = [order for order in orders if order["estado"] in {"pendiente", "confirmado"}]
    closed = [order for order in orders if order["estado"] not in {"pendiente", "confirmado"}][:MAX_CLOSED_ORDERS]
    items = []
    for order in active + closed:
        entry = {
            "pedido": order["pedido"],
            "estado": order["estado"],
            "lineas": [{"sku": line["sku"], "nombre": line["nombre"], "variante": line["variante"],
                        "cantidad": line["cantidad"], "unidad": line["unidad"]} for line in order["lineas"]],
        }
        for optional in ("aparta_hasta", "recogida", "nota"):
            if order.get(optional):
                entry[optional] = order[optional]
        items.append(entry)
    return items


def session_context(store: SessionStore, session_id: str, orders: OrderBook | None) -> dict:
    """Lo que Grok sabe de la conversación: turnos, productos, hora de la tienda y pedidos del cliente."""
    context = store.context(session_id)
    context["session_id"] = session_id
    if orders is not None:
        now = orders.clock()
        # Sin la hora, «mañana a las 4» no se puede convertir en una fecha de recogida.
        context["ahora"] = f"{now.strftime('%Y-%m-%d %H:%M')} ({WEEKDAYS[now.weekday()]})"
        context["pedidos"] = order_context(orders.session_orders(session_id))
    return context


def ban_session(store: SessionStore, session_id: str, injection: dict, message: str,
                orders: OrderBook | None) -> list[str]:
    """Banea la sesión y cancela sus pedidos activos: un cliente baneado no deja unidades apartadas."""
    store.ban(session_id, injection["code"], injection["technique"], redact_personal_data(message)[0])
    return cancel_active(orders, session_id, "servidor tras un intento de inyección")


def _without_grok(store: SessionStore, session_id: str, message: str, status: str, reply: str, reason: str,
                  emit: Callable[[dict], None]) -> dict:
    """Turno respondido con un texto fijo: se guarda filtrado como cualquier otro y emite la misma forma de traza."""
    run_id, started = uuid4().hex[:12], perf_counter()
    customer = screen_message(message).consulta
    turn = store.record(session_id, customer, reply, status, [])
    elapsed = round((perf_counter() - started) * 1000)

    def push(event_type: str, details: dict) -> None:
        emit({"run_id": run_id, "type": event_type, "at": datetime.now(timezone.utc).isoformat(),
              "elapsed_ms": elapsed, "details": details})

    push("route", {"motivo": reason})
    push("final", {"run_id": run_id, "prompt_version": PROMPT_VERSION, "estado": status, "respuesta": reply,
                   "error": None, "model_called": False, "model_calls": 0, "barreras": [], "inyeccion": None,
                   "tool_calls": 0, "tools_requested": [], "tools_executed": [], "input_tokens": None,
                   "output_tokens": None, "cached_input_tokens": None, "cache_hit_percent": 0.0, "total_tokens": None,
                   "duration_ms": elapsed, "cost": None})
    emit({"type": "session", "run_id": run_id, "session_id": session_id, "turno": turn, "productos_recordados": [],
          "lista": [], "bloqueada": False, "atencion": attention(store, session_id)})
    return {"run_id": run_id, "consulta": customer, "respuesta": reply, "estado": status, "error": None,
            "model_called": False, "model_calls": 0, "tool_calls": [], "referencia": "",
            "prompt_version": PROMPT_VERSION, "duration_ms": elapsed, "cost": None, "session_id": session_id,
            "turno": turn}


def _human_turn(store: SessionStore, session_id: str, message: str, context: dict,
                emit: Callable[[dict], None]) -> dict | None:
    """El turno sin Grok si lo atiende el tendero o si el cliente pide una persona; None si sigue el grafo."""
    text = message.strip()
    turns = context.get("turnos") or []
    # Lo vacío, lo largo y la inyección los resuelve el grafo antes de Grok (rechazo, bloqueo y baneo).
    if not text or len(text) > MAX_MESSAGE_CHARS or detect_injection(text, turns[-1]["cliente"] if turns else ""):
        return None
    if attention(store, session_id) == "tendero":
        return _without_grok(store, session_id, text, "staff", STAFF_HOLD_REPLY,
                             "El tendero atiende esta conversación; no se llama a Grok.", emit)
    if asks_for_human(text):
        asked = request_human(store, session_id, "El cliente pidió hablar con una persona.", "asistente")
        return _without_grok(store, session_id, text, "handoff", HANDOFF_REPLY if asked else HANDOFF_AGAIN_REPLY,
                             "El cliente pidió hablar con una persona; se avisa al tendero sin llamar a Grok.", emit)
    return None


def run_turn(
    store: SessionStore,
    session_id: str,
    message: str,
    emit: Callable[[dict], None] = lambda event: None,
    tool_executor: ToolExecutor | None = None,
    planner: Planner = decide_with_grok,
    orders: OrderBook | None = None,
    image: ImageAttributePayload | dict | str | None = None,
) -> dict:
    """Ejecuta un mensaje dentro de una sesión y guarda el turno filtrado; lanza SessionError si no existe.

    Si el mensaje intentaba inyectar instrucciones, el grafo lo bloquea sin Grok y aquí se banea la sesión.

    Con ``orders`` el turno puede registrar, confirmar, agendar o cancelar pedidos de esta sesión; sin
    ``tool_executor`` se usa el catálogo del mismo archivo que el libro de pedidos.

    Si se proporciona una imagen o datos en base64, se realiza extracción estructurada de atributos (visión)
    una sola vez, ejecutando la búsqueda en SQLite local y saltos deterministas sin quemar llamadas a Grok.

    Si el tendero tomó la conversación o el cliente pide hablar con una persona, responde un texto fijo sin Grok
    (``handoff.py``); dos turnos seguidos en fallo le piden ayuda al tendero.
    """
    if image is None and ("data:image/" in message or ";base64," in message):
        data_match = BASE64_DATA_URI.search(message)
        if data_match:
            image = data_match.group(0)
            message = BASE64_DATA_URI.sub("", message).strip()

    context = session_context(store, session_id, orders)
    human = _human_turn(store, session_id, message, context, emit)
    if human is not None:
        return human
    previous = last_status(store, session_id)
    if tool_executor is None:
        catalog = MockCatalog(orders.path) if orders is not None else MockCatalog()
        tool_executor = catalog_executor(catalog, orders, session_id)
    else:
        catalog = MockCatalog(orders.path) if orders is not None else MockCatalog()

    if image is not None:
        run_id, started = uuid4().hex[:12], perf_counter()
        now_iso = lambda: datetime.now(timezone.utc).isoformat()
        elapsed_now = lambda: round((perf_counter() - started) * 1000)

        clean_msg = sanitize_image_text(message)
        initial_customer_turn = clean_msg if clean_msg else "[foto adjunta]"

        # 1. Notificar entrada del cliente
        emit({
            "run_id": run_id, "type": "input", "at": now_iso(),
            "elapsed_ms": 0, "details": {
                "run_id": run_id, "consulta": redact_personal_data(initial_customer_turn)[0],
                "prompt_version": PROMPT_VERSION, "sesion": True, "imagen_adjunta": True,
            },
        })

        # Notificar llamada a Grok Visión
        vision_model = (
            os.getenv("GROK_VISION_MODEL")
            or os.getenv("GROK_MODEL")
            or "grok-4.20-0309-non-reasoning"
        )
        if vision_model in ("grok-2-vision-1212", "grok-vision"):
            vision_model = "grok-4.20-0309-non-reasoning"

        emit({
            "run_id": run_id, "type": "model_request", "at": now_iso(),
            "elapsed_ms": elapsed_now(), "details": {
                "run_id": run_id,
                "phase": "vision",
                "step": 1,
                "model": vision_model,
                "api_key": "[omitida]",
            },
        })

        try:
            payload = extract_vision_attributes(image)
        except Exception as exc:
            call_ms = elapsed_now()
            emit({
                "run_id": run_id, "type": "model_response", "at": now_iso(),
                "elapsed_ms": call_ms, "details": {
                    "run_id": run_id, "phase": "vision", "step": 1,
                    "duration_ms": call_ms,
                    "error": {"code": "VISION_API_ERROR", "message": str(exc)},
                    "cost": None,
                },
            })
            emit({
                "run_id": run_id, "type": "error", "at": now_iso(),
                "code": "VISION_API_ERROR",
                "message": f"Fallo en Grok Visión ({type(exc).__name__}): {exc}",
            })
            raise ModelError("VISION_API_ERROR", f"Fallo en Grok Visión ({type(exc).__name__}): {exc}")

        # Extraer métricas de la llamada multimodal
        usage = payload.usage or {}
        has_model_call = bool(usage)
        in_tokens = usage.get("input_tokens")
        out_tokens = usage.get("output_tokens")
        cached_tokens = usage.get("cached_input_tokens") or 0
        call_cost_data = usage.get("cost")
        duration_ms = usage.get("duration_ms", elapsed_now())

        if has_model_call:
            emit({
                "run_id": run_id, "type": "model_response", "at": now_iso(),
                "elapsed_ms": elapsed_now(), "details": {
                    "run_id": run_id,
                    "phase": "vision",
                    "step": 1,
                    "model": usage.get("model", vision_model),
                    "input_tokens": in_tokens,
                    "output_tokens": out_tokens,
                    "cached_input_tokens": cached_tokens,
                    "duration_ms": duration_ms,
                    "cost": call_cost_data,
                },
            })

        summary = payload.semantic_summary()
        customer_turn = f"{clean_msg} {summary}".strip() if clean_msg else summary

        # 2. Notificar atributos de visión estructurados
        emit({
            "run_id": run_id, "type": "vision", "at": now_iso(),
            "elapsed_ms": elapsed_now(), "details": {
                "payload": payload.to_dict(),
                "resumen": summary,
                "confianza": payload.confianza_visual,
                "tipo_producto": payload.tipo_producto,
                "material": payload.material,
                "medidas_visibles": payload.medidas_visibles,
                "presentacion_uso": payload.presentacion_uso,
                "color_acabado": payload.color_acabado,
            },
        })

        # 3. Etapa 1: Validar
        emit({
            "run_id": run_id, "type": "node", "node": "validate", "status": "running",
            "at": now_iso(), "elapsed_ms": elapsed_now(),
            "details": {"run_id": run_id},
        })
        emit({
            "run_id": run_id, "type": "node", "node": "validate", "status": "complete",
            "at": now_iso(), "elapsed_ms": elapsed_now(),
            "details": {"longitud": len(customer_turn), "inyeccion": None},
        })

        # 4. Etapa 2: Interpretar
        emit({
            "run_id": run_id, "type": "node", "node": "interpret", "status": "running",
            "at": now_iso(), "elapsed_ms": elapsed_now(),
            "details": {"run_id": run_id},
        })

        vision_res = handle_vision_turn(
            payload, clean_msg, catalog, tool_executor, context=context, session_id=session_id,
        )

        # Salvaguarda: la respuesta nunca debe ser vacía ni None
        if not vision_res.get("respuesta"):
            is_screw = "tornillo" in customer_turn.lower()
            vision_res["respuesta"] = SCREW_SAFEGUARD_TEMPLATE if is_screw else SAMPLE_COUNTER_TEMPLATE

        tool_calls = vision_res.get("tool_calls", [])
        if tool_calls:
            first_tool = tool_calls[0]
            decision_dict = {
                "action": "call_tool",
                "tool": first_tool.get("requested_tool"),
                "arguments": first_tool.get("arguments", {}),
                "reply": "",
            }
        else:
            decision_dict = {
                "action": "respond",
                "tool": None,
                "arguments": None,
                "reply": vision_res["respuesta"],
            }

        emit({
            "run_id": run_id, "type": "node", "node": "interpret", "status": "complete",
            "at": now_iso(), "elapsed_ms": elapsed_now(),
            "details": {"decision": decision_dict, "vision_payload": payload.to_dict()},
        })

        # 5. Etapa 4: Ejecución de herramientas (retrieve)
        if tool_calls:
            for call in tool_calls:
                emit({
                    "run_id": run_id, "type": "node", "node": "retrieve", "status": "running",
                    "at": now_iso(), "elapsed_ms": elapsed_now(),
                    "details": {"run_id": run_id, "tool": call.get("requested_tool")},
                })
                emit({
                    "run_id": run_id, "type": "node", "node": "retrieve", "status": "complete",
                    "at": now_iso(), "elapsed_ms": elapsed_now(),
                    "details": {"tool_call": call},
                })
        else:
            emit({
                "run_id": run_id, "type": "node", "node": "retrieve", "status": "skipped",
                "at": now_iso(), "elapsed_ms": elapsed_now(),
                "details": {"motivo": "visión multimodal directa sin consultas de catálogo"},
            })

        # 6. Etapa 5: Responder (respond)
        emit({
            "run_id": run_id, "type": "node", "node": "respond", "status": "running",
            "at": now_iso(), "elapsed_ms": elapsed_now(),
            "details": {"run_id": run_id},
        })
        emit({
            "run_id": run_id, "type": "node", "node": "respond", "status": "complete",
            "at": now_iso(), "elapsed_ms": elapsed_now(),
            "details": {"run_id": run_id},
        })

        turn = store.record(
            session_id, customer_turn, vision_res["respuesta"], vision_res["estado"],
            vision_res["products"],
            shopping=vision_res["shopping"] if vision_res.get("shopping") else None,
            options=vision_res["options"] if vision_res.get("options") else None,
            specs=vision_res["specs"],
        )
        elapsed = elapsed_now()

        costs_list = [call_cost_data] if call_cost_data else []
        final_cost = run_cost(costs_list) if costs_list else None
        model_calls = 1 if has_model_call else 0
        total_tokens = (in_tokens + out_tokens) if (isinstance(in_tokens, int) and isinstance(out_tokens, int)) else None
        cache_hit_pct = ((cached_tokens / in_tokens) * 100) if (isinstance(in_tokens, int) and in_tokens > 0) else 0.0

        final_details = {
            "run_id": run_id,
            "prompt_version": PROMPT_VERSION,
            "estado": vision_res["estado"],
            "respuesta": vision_res["respuesta"],
            "error": None,
            "model_called": has_model_call,
            "model_calls": model_calls,
            "barreras": [],
            "inyeccion": None,
            "tool_calls": len(tool_calls),
            "tools_requested": [c["requested_tool"] for c in tool_calls],
            "tools_executed": [c["requested_tool"] for c in tool_calls if c.get("executed")],
            "input_tokens": in_tokens,
            "output_tokens": out_tokens,
            "cached_input_tokens": cached_tokens,
            "cache_hit_percent": cache_hit_pct,
            "total_tokens": total_tokens,
            "duration_ms": elapsed,
            "cost": final_cost,
            "vision_confidence": payload.confianza_visual,
            "vision_payload": payload.to_dict(),
        }

        emit({
            "run_id": run_id,
            "type": "final",
            "at": now_iso(),
            "elapsed_ms": elapsed,
            "details": final_details,
            **final_details,
        })
        emit({
            "type": "session", "run_id": run_id, "session_id": session_id, "turno": turn,
            "productos_recordados": [item["sku"] for item in vision_res["products"]],
            "lista": [{"sku": item["sku"], "cantidad": item["cantidad"]} for item in vision_res.get("shopping", [])],
            "bloqueada": False, "atencion": attention(store, session_id),
        })

        return {
            "run_id": run_id, "consulta": customer_turn, "respuesta": vision_res["respuesta"],
            "estado": vision_res["estado"], "error": None, "model_called": has_model_call, "model_calls": model_calls,
            "tool_calls": tool_calls, "referencia": customer_turn,
            "prompt_version": PROMPT_VERSION, "duration_ms": elapsed, "cost": final_cost,
            "session_id": session_id, "turno": turn, "vision_payload": payload.to_dict(),
            "input_tokens": in_tokens, "output_tokens": out_tokens, "cached_input_tokens": cached_tokens,
            "total_tokens": total_tokens,
        }

    result = run_traced(message, emit, tool_executor, planner, context=context)
    consulta = result["consulta"]
    coherent = bool(consulta) and coherent_option_turn(consulta, context)
    products = remembered_products(result.get("referencia", ""), result.get("tool_calls", []))
    picked_now = (chosen_options(consulta, context) or (
        [aff] if (aff := affirms_active_item(consulta, context)) else []
    )) if consulta else []
    for picked_opt in picked_now:
        if picked_opt.get("sku") and all(picked_opt.get(k) for k in ("nombre", "variante", "unidad")):
            if not any(item["sku"] == picked_opt["sku"] for item in products):
                products.append({key: picked_opt[key] for key in ("sku", "nombre", "variante", "unidad")})
    shopping = updated_list(context.get("lista") or [], consulta, result.get("tool_calls", []))
    options = shown_options(result.get("referencia", ""), result.get("tool_calls", []), consulta, context=context)
    specs = updated_specs(context.get("especificaciones"), consulta, context) if consulta else None
    turn = store.record(session_id, consulta, result["respuesta"], result["estado"], products, shopping,
                        options, specs=specs)
    injection = result.get("inyeccion")
    if injection:
        cancelled = ban_session(store, session_id, injection, message, orders)
        emit({"type": "ban", "run_id": result["run_id"], "session_id": session_id,
              "details": {**injection, "pedidos_cancelados": cancelled}})
    else:
        escalate_after_failures(store, session_id, previous, result["estado"], coherent=coherent)
    emit({"type": "session", "run_id": result["run_id"], "session_id": session_id, "turno": turn,
          "productos_recordados": [item["sku"] for item in products],
          "lista": [{"sku": item["sku"], "cantidad": item["cantidad"]} for item in shopping],
          "bloqueada": bool(injection), "atencion": attention(store, session_id)})
    result.update(session_id=session_id, turno=turn)
    return result
