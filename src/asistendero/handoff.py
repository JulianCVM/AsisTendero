"""Intervención humana: quién atiende cada conversación y cuándo el asistente le pide ayuda al tendero.

Estados de atención (tabla ``attention`` de la base de sesiones; sin fila, la conversación está en ``ia``):

- ``ia``: responde el asistente (Grok con las barreras del servidor).
- ``requiere_humano``: el asistente pidió ayuda y sigue respondiendo hasta que el tendero tome la conversación.
- ``tendero``: el tendero la tomó; el mensaje del cliente se guarda y se responde un texto fijo, sin Grok.
- ``finalizada``: el tendero la cerró; cada turno siguiente recibe ``SESSION_CLOSED`` (``sessions.py``).

Cuándo pide ayuda el asistente lo decide el código, no Grok:

- el cliente pide hablar con una persona (``asks_for_human``): el turno responde un texto fijo sin llamar a Grok;
- dos turnos seguidos terminan en un estado de fallo (``FAILURE_STATES``): se deja un aviso al cliente.

Una pregunta sobre una persona de la tienda («¿el dueño abre el domingo?», «¿el dueño atiende hoy?», «¿eres una
persona o un bot?») no es un pedido de hablar con ella: la responde el asistente con la información de la tienda.
Solo cuenta un verbo de pedir contacto («hablar con», «páseme al», «comuníqueme con», «que me atienda») dirigido
a una persona y sin un «no» delante, o el rechazo explícito al bot («no quiero hablar con un bot»).

Los mensajes del tendero llegan al cliente como avisos (``notify``) y nunca a Grok: un precio que escriba el tendero
no es un dato del catálogo.
"""

import re

from asistendero.guardrails import redact_personal_data
from asistendero.orders import ACTIVE, OrderBook
from asistendero.sessions import CLOSED, MANUAL_BAN, MAX_BAN_EXCERPT, SessionError, SessionStore
from asistendero.validation import normalize_text


ATTENTION_STATES = ("ia", "requiere_humano", "tendero", CLOSED)
ACTORS = ("asistente", "tendero", "sistema")
FAILURE_STATES = frozenset({"model_error", "model_invalid", "limit_reached", "tool_error", "not_verified"})
MAX_REASON_CHARS = MAX_BAN_EXCERPT
MAX_STAFF_REPLY_CHARS = 500

HANDOFF_REPLY = ("Le aviso al tendero para que te atienda por aquí. Mientras tanto, si quieres, te sigo ayudando "
                 "con precios y existencias.")
HANDOFF_AGAIN_REPLY = "Ya le avisé al tendero; en cuanto pueda te atiende por aquí."
STAFF_HOLD_REPLY = "El tendero está atendiendo esta conversación y te responde por aquí en un momento."
ESCALATION_NOTICE = "No pude resolver tus últimos mensajes, así que le avisé al tendero para que te ayude por aquí."
TAKEN_NOTICE = "El tendero tomó la conversación y te responde por aquí."
RELEASED_NOTICE = "El tendero te deja de nuevo con el asistente."
FINISHED_NOTICE = "El tendero dio por terminada la conversación. ¡Gracias por escribir!"
STAFF_PREFIX = "Tendero: "

# Acción del panel → estados desde los que se permite y estado al que lleva.
CHANGES = {
    "tomar": (("ia", "requiere_humano"), "tendero"),
    "devolver": (("requiere_humano", "tendero", CLOSED), "ia"),
    "finalizar": (("ia", "requiere_humano", "tendero"), CLOSED),
}

_PEOPLE = (r"(?:duen[oa]|encargad[oa]|gerente|administrador(?:a)?|jef[ea]|tender[oa]|propietari[oa]|vendedor(?:a)?"
           r"|asesor(?:a)?|emplead[oa]|cajer[oa])")
# «con el dueño», «al encargado», «con alguien», «con un humano»: la persona va siempre tras «con» o «a».
_WHO = (rf"(?:(?:con\s+(?:el|la|un|una|algun|alguna|su)|al|a\s+(?:la|un|una|algun|alguna|su))\s+(?:senor\s+|senora\s+)?"
        rf"{_PEOPLE}|(?:con|a)\s+(?:alguien|una\s+persona|un\s+(?:ser\s+)?humano|una\s+humana|humanos?|personas?)\b)")
_ASK_VERBS = (r"(?:hablar|comunicar(?:me|nos|se)?|comuniqueme|comunicame|comuniquenme|me\s+comunica[ns]?"
              r"|conectar(?:me)?|conecteme|conectame|paseme|pasame|pasenme|pasarme|me\s+pasa[ns]?|ponme|pongame"
              r"|me\s+pone[ns]?|llame|llama|llamen|llamar)")
_FILLER = r"(?:\s+(?:directamente|ya|rapido|ahora|por\s+favor|porfa|mejor))?"
HUMAN_REQUESTS = [
    re.compile(rf"\b{_ASK_VERBS}{_FILLER}\s+{_WHO}"),
    re.compile(rf"\bque\s+me\s+atienda(?:n)?\s+(?:(?:el|la|un|una|algun|alguna)\s+)?(?:{_PEOPLE}|persona|humano|alguien)\b"),
    re.compile(r"\b(?:quiero|necesito|prefiero)\s+(?:un\s+(?:ser\s+)?humano|una\s+persona\s+(?:real|de\s+verdad)"
               r"|atencion\s+humana)\b"),
    re.compile(r"\batencion\s+humana\b"),
]
# «no quiero hablar con un bot»: el «no» rechaza al asistente, así que sí pide a una persona.
NOT_A_BOT = re.compile(r"\bno\s+(?:quiero|me\s+sirve|me\s+gusta)\s+(?:hablar|chatear|escribir(?:le)?)\s+(?:con\s+)?"
                       r"(?:un|una|el|la|este|esta)?\s*(?:bot|robot|maquina|ia|asistente|programa)\b")
# «no necesito hablar con el dueño»: un «no» hasta tres palabras antes anula el pedido.
NEGATED = re.compile(r"\bno\s+(?:\w+\s+){0,3}$")


class AttentionError(SessionError):
    """Cambio de atención o mensaje del tendero que no se permite, con un código estable."""


def asks_for_human(message: str) -> bool:
    """True si el cliente pide hablar con una persona de la tienda (no si solo pregunta por ella)."""
    text = " ".join(normalize_text(message).split())
    if NOT_A_BOT.search(text):
        return True
    return any(not NEGATED.search(text[:match.start()]) for pattern in HUMAN_REQUESTS for match in pattern.finditer(text))


def _checked(value: object, limit: int, field: str, label: str) -> str:
    # Nunca se recorta en silencio: lo vacío o lo largo se rechaza con un mensaje que dice qué hacer.
    if not isinstance(value, str) or not value.strip():
        raise AttentionError(f"{field}_EMPTY", f"Escribe {label}.")
    if len(value.strip()) > limit:
        raise AttentionError(f"{field}_TOO_LONG", f"{label[0].upper()}{label[1:]} admite máximo {limit} caracteres.")
    return value.strip()


def _state(connection, session_id: str) -> str:
    row = connection.execute("SELECT state FROM attention WHERE session_id = ?", (session_id,)).fetchone()
    return row[0] if row else "ia"


def _banned(connection, session_id: str) -> bool:
    return connection.execute("SELECT 1 FROM bans WHERE session_id = ? AND lifted_at IS NULL",
                              (session_id,)).fetchone() is not None


def attention(store: SessionStore, session_id: str) -> str:
    """Estado de atención de una sesión vigente (``ia`` si nadie lo cambió)."""
    with store.connection() as connection:
        store.require(connection, session_id)
        return _state(connection, session_id)


def last_status(store: SessionStore, session_id: str) -> str | None:
    """Estado del último turno guardado, para saber si el siguiente fallo es el segundo seguido."""
    with store.connection() as connection:
        row = connection.execute("SELECT status FROM turns WHERE session_id = ? ORDER BY number DESC LIMIT 1",
                                 (session_id,)).fetchone()
    return row[0] if row else None


def _move(connection, store: SessionStore, session_id: str, before: str, after: str, reason: str, actor: str) -> None:
    now = store.clock().isoformat()
    connection.execute("INSERT INTO attention VALUES (?, ?, ?) ON CONFLICT(session_id) DO UPDATE SET "
                       "state = excluded.state, updated_at = excluded.updated_at", (session_id, after, now))
    connection.execute("INSERT INTO attention_log VALUES (?, ?, ?, ?, ?, ?)",
                       (session_id, now, before, after, reason, actor))
    # Un cambio de atención es actividad: la conversación no vence mientras el tendero la atiende.
    connection.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))


def request_human(store: SessionStore, session_id: str, motivo: str, actor: str = "asistente") -> bool:
    """Pasa de ``ia`` a ``requiere_humano``; False si ya la atiende o la espera el tendero, o si está cerrada."""
    if actor not in ACTORS:
        raise AttentionError("ACTOR_INVALID", f"El actor debe ser uno de: {', '.join(ACTORS)}.")
    reason = _checked(motivo, MAX_REASON_CHARS, "REASON", "el motivo")
    with store.connection() as connection:
        store.require(connection, session_id)
        if _state(connection, session_id) != "ia":
            return False
        _move(connection, store, session_id, "ia", "requiere_humano", redact_personal_data(reason)[0], actor)
    return True


def _change(store: SessionStore, session_id: str, action: str, reason: str) -> dict:
    allowed, after = CHANGES[action]
    with store.connection() as connection:
        store.require(connection, session_id)
        before = _state(connection, session_id)
        if action != "finalizar" and _banned(connection, session_id):
            raise AttentionError("ATTENTION_BANNED", "La conversación está bloqueada: desbloquéala primero.")
        if before not in allowed:
            raise AttentionError("ATTENTION_INVALID_CHANGE",
                                 f"La conversación está en «{before}»; desde ahí no se puede {action}.")
        _move(connection, store, session_id, before, after, reason, "tendero")
    return {"sesion": session_id, "antes": before, "estado": after}


def take_over(store: SessionStore, session_id: str) -> dict:
    """El tendero toma la conversación: desde ahora el asistente no llama a Grok y el cliente recibe un aviso."""
    change = _change(store, session_id, "tomar", "El tendero tomó la conversación.")
    store.notify(session_id, TAKEN_NOTICE)
    return change


def release(store: SessionStore, session_id: str) -> dict:
    """Devuelve la conversación al asistente (también reabre una finalizada)."""
    change = _change(store, session_id, "devolver", "El tendero devolvió la conversación al asistente.")
    if change["antes"] == "tendero":
        store.notify(session_id, RELEASED_NOTICE)
    return change


def finish(store: SessionStore, session_id: str) -> dict:
    """Cierra la conversación: el cliente recibe un aviso y sus turnos siguientes, ``SESSION_CLOSED``."""
    change = _change(store, session_id, "finalizar", "El tendero dio por terminada la conversación.")
    store.notify(session_id, FINISHED_NOTICE)
    return change


def staff_reply(store: SessionStore, session_id: str, texto: str) -> dict:
    """Mensaje del tendero: se guarda con su hora y le llega al cliente como aviso. Exige haber tomado la conversación."""
    # El tendero puede repetir un dato del cliente: se tapa igual que en los turnos.
    text = redact_personal_data(_checked(texto, MAX_STAFF_REPLY_CHARS, "STAFF_REPLY", "el mensaje"))[0]
    with store.connection() as connection:
        store.require(connection, session_id)
        if _banned(connection, session_id):
            raise AttentionError("ATTENTION_BANNED", "La conversación está bloqueada: desbloquéala primero.")
        if _state(connection, session_id) != "tendero":
            raise AttentionError("ATTENTION_NOT_TAKEN", "Toma la conversación antes de responder al cliente.")
        now = store.clock().isoformat()
        connection.execute("INSERT INTO staff_messages VALUES (?, ?, ?)", (session_id, now, text))
        connection.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
    store.notify(session_id, STAFF_PREFIX + text)
    return {"sesion": session_id, "texto": text, "hora": now}


def cancel_active(orders: OrderBook | None, session_id: str, by: str) -> list[str]:
    """Cancela los pedidos activos de una sesión bloqueada: un cliente bloqueado no deja unidades apartadas."""
    if orders is None:
        return []
    active = [order["pedido"] for order in orders.session_orders(session_id, limit=50) if order["estado"] in ACTIVE]
    for order_id in active:
        orders.cancel(order_id, session_id, by=by)
    return active


def ban_manually(store: SessionStore, session_id: str, motivo: str, orders: OrderBook | None = None) -> list[str]:
    """Bloqueo del tendero con un motivo; cancela los pedidos activos y devuelve sus códigos."""
    reason = redact_personal_data(_checked(motivo, MAX_REASON_CHARS, "REASON", "el motivo"))[0]
    with store.connection() as connection:
        store.require(connection, session_id)
    store.ban(session_id, MANUAL_BAN, "manual", reason)
    return cancel_active(orders, session_id, "tendero al bloquear la conversación")


def escalate_after_failures(store: SessionStore, session_id: str, previous: str | None, current: str) -> bool:
    """Dos turnos seguidos en fallo piden al tendero y avisan al cliente; uno solo no."""
    if previous not in FAILURE_STATES or current not in FAILURE_STATES:
        return False
    if not request_human(store, session_id, f"Dos turnos seguidos sin respuesta verificada ({previous}, {current}).",
                         "sistema"):
        return False
    store.notify(session_id, ESCALATION_NOTICE)
    return True


def actions(state: str, banned: bool) -> list[str]:
    """Acciones del panel posibles para una conversación en ese estado."""
    if banned:
        return ["desbloquear", *(["finalizar"] if state != CLOSED else [])]
    possible = [action for action, (allowed, _) in CHANGES.items() if state in allowed]
    return [*possible, *(["responder"] if state == "tendero" else []), "bloquear"]
