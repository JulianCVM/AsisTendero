"""Un turno de chat: contexto de la sesión → mismo grafo trazado → memoria del turno.

Antes del grafo se mira quién atiende la conversación (``handoff.py``): si la tomó el tendero, o si el cliente pide
hablar con una persona, el turno se responde con un texto fijo y no se llama a Grok.
"""

from collections.abc import Callable
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

from asistendero.agente.conversacion.handoff import (
    HANDOFF_AGAIN_REPLY, HANDOFF_REPLY, STAFF_HOLD_REPLY, asks_for_human, attention, cancel_active,
    escalate_after_failures, last_status, request_human,
)
from asistendero.agente.conversacion.sessions import SessionStore, order_context, remembered_products
from asistendero.agente.entrada.guardrails import redact_personal_data, screen_message
from asistendero.agente.entrada.injection import detect_injection
from asistendero.agente.flujo.graph import MAX_MESSAGE_CHARS, Planner
from asistendero.agente.herramientas.executor import catalog_executor
from asistendero.agente.herramientas.observations import ToolExecutor
from asistendero.agente.modelo.grok import ModelError, decide_with_grok
from asistendero.agente.modelo.prompt import BUSINESS_KIND, active_prompt
from asistendero.agente.reglas.choices import chosen_options, coherent_option_turn, shown_options
from asistendero.agente.reglas.context_resolution import affirms_active_item, updated_specs
from asistendero.agente.reglas.shopping_list import updated_list
from asistendero.agente.respuesta.reply_photos import reply_photos
from asistendero.agente.vision.attributes import BASE64_DATA_URI, ImageAttributePayload, sanitize_image_text
from asistendero.agente.vision.look import look_at
from asistendero.agente.vision.photo import PhotoRejected
from asistendero.agente.vision.photo_planner import PhotoPlanner, fixed_reply
from asistendero.observabilidad.tracing import run_traced
from asistendero.datos.seed import BUSINESSES
from asistendero.tienda.catalogo.catalog import MockCatalog
from asistendero.tienda.pedidos.orders import OrderBook
from asistendero.tienda.reloj import WEEKDAYS


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
    push("final", {"run_id": run_id, "prompt_version": active_prompt()[0], "estado": status, "respuesta": reply,
                   "error": None, "model_called": False, "model_calls": 0, "barreras": [], "inyeccion": None,
                   "tool_calls": 0, "tools_requested": [], "tools_executed": [], "input_tokens": None,
                   "output_tokens": None, "cached_input_tokens": None, "cache_hit_percent": 0.0, "total_tokens": None,
                   "duration_ms": elapsed, "cost": None})
    emit({"type": "session", "run_id": run_id, "session_id": session_id, "turno": turn, "productos_recordados": [],
          "lista": [], "bloqueada": False, "atencion": attention(store, session_id)})
    return {"run_id": run_id, "consulta": customer, "respuesta": reply, "estado": status, "error": None,
            "model_called": False, "model_calls": 0, "tool_calls": [], "referencia": "",
            "prompt_version": active_prompt()[0], "duration_ms": elapsed, "cost": None, "session_id": session_id,
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


PHOTO_UNAVAILABLE_REPLY = ("No pude revisar la foto en este momento. Escríbeme el nombre del producto y la medida, "
                           "o tráela al mostrador, y te ayudo.")


def _look(store: SessionStore, session_id: str, message: str, image: ImageAttributePayload | str, context: dict,
          orders: OrderBook | None, emit: Callable[[dict], None]) -> dict | tuple | None:
    """Mira la foto antes del grafo.

    Devuelve el turno ya respondido si la foto no sirve o Grok falla; None si el texto intenta una inyección (el
    grafo lo bloquea y banea sin gastar en la foto), o (mensaje con la referencia, planificador, visión) si sigue.
    """
    turns = context.get("turnos") or []
    if detect_injection(message, turns[-1]["cliente"] if turns else ""):
        return None
    business = BUSINESS_KIND.get() if orders is None else (
        "mercado" if orders.business_id == BUSINESSES["mercado"] else "ferreteria")
    shown = message.strip() or "[foto]"
    try:
        seen = look_at(image, business)
    except PhotoRejected as exc:
        return _without_grok(store, session_id, shown, "refused", str(exc), f"Foto rechazada ({exc.code}).", emit)
    except ModelError as exc:
        return _without_grok(store, session_id, shown, "model_error", PHOTO_UNAVAILABLE_REPLY,
                             f"Grok no pudo revisar la foto ({exc.code}).", emit)
    payload = seen.payload
    summary = payload.semantic_summary()
    vision = {"atributos": {key: value for key, value in payload.to_dict().items() if key != "usage"},
              "resumen": summary, "huella": seen.huella, "llamada": seen.llamada}
    planner = PhotoPlanner(payload, fixed_reply(payload, message, context))
    return f"{message.strip()} {summary}".strip(), planner, vision


def run_turn(
    store: SessionStore,
    session_id: str,
    message: str,
    emit: Callable[[dict], None] = lambda event: None,
    tool_executor: ToolExecutor | None = None,
    planner: Planner = decide_with_grok,
    orders: OrderBook | None = None,
    image: ImageAttributePayload | str | None = None,
) -> dict:
    """Ejecuta un mensaje dentro de una sesión y guarda el turno filtrado; lanza SessionError si no existe.

    Si el mensaje intentaba inyectar instrucciones, el grafo lo bloquea sin Grok y aquí se banea la sesión.

    Con ``orders`` el turno puede registrar, confirmar, agendar o cancelar pedidos de esta sesión; sin
    ``tool_executor`` se usa el catálogo del mismo archivo que el libro de pedidos.

    ``image`` es la foto del cliente (``data:image/...;base64,...``): se mira una vez (``look_at``) y el turno sigue
    por el mismo grafo con lo que se vio escrito como ``[Foto: …]`` y un planificador del servidor, sin otra llamada
    a Grok. La foto nunca se guarda: la sesión solo recuerda esa referencia corta.

    Si el tendero tomó la conversación o el cliente pide hablar con una persona, responde un texto fijo sin Grok
    (``handoff.py``); dos turnos seguidos en fallo le piden ayuda al tendero.
    """
    if image is None and BASE64_DATA_URI.search(message):
        image = BASE64_DATA_URI.search(message).group(0)
        message = BASE64_DATA_URI.sub(" ", message)
    if image is not None:
        message = sanitize_image_text(message)

    context = session_context(store, session_id, orders)
    human = _human_turn(store, session_id, message, context, emit)
    if human is not None:
        return human
    previous = last_status(store, session_id)
    if tool_executor is None:
        catalog = MockCatalog(orders.path, orders.business_id, orders.store_id) if orders is not None else MockCatalog()
        tool_executor = catalog_executor(catalog, orders, session_id)
    vision = None
    if image is not None:
        seen = _look(store, session_id, message, image, context, orders, emit)
        if isinstance(seen, dict):
            return seen
        if seen is not None:
            message, planner, vision = seen
    result = run_traced(message, emit, tool_executor, planner, context=context, vision=vision)
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
    photos = [] if injection else reply_photos(result.get("tool_calls", []))
    emit({"type": "session", "run_id": result["run_id"], "session_id": session_id, "turno": turn,
          "productos_recordados": [item["sku"] for item in products],
          "lista": [{"sku": item["sku"], "cantidad": item["cantidad"]} for item in shopping],
          "bloqueada": bool(injection), "atencion": attention(store, session_id), "imagenes": photos})
    result.update(session_id=session_id, turno=turn, imagenes=photos)
    return result
