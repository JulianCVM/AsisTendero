"""Supervisión de conversaciones para el panel del tendero, en solo lectura.

``conversations`` lista las conversaciones vigentes con su estado de atención, bloqueo, incidencias y pedidos;
``conversation`` da el detalle de una: turnos y mensajes del tendero en orden, pedidos, historial de atención,
bloqueo y acciones posibles. Las acciones están en ``handoff.py``.

Privacidad: el texto del cliente se guarda ya filtrado (``screen_message`` tapa los datos personales antes de
``SessionStore.record``) y el extracto de un baneo también; aquí no se vuelve a filtrar. Los identificadores son
los de la sesión, aleatorios: nunca llevan un dato del cliente.
"""

from datetime import datetime, timedelta
from textwrap import shorten

from asistendero.handoff import ATTENTION_STATES, FAILURE_STATES, AttentionError, actions
from asistendero.injection import INJECTION_CODES
from asistendero.orders import ORDER_ID, OrderBook, local_text
from asistendero.sessions import MANUAL_BAN, SESSION_TTL, SessionStore


LIVE_WINDOW = timedelta(minutes=15)
INCIDENT_STATES = tuple(sorted(FAILURE_STATES | {"refused", "blocked"}))
MAX_QUERY_CHARS = 100
MAX_LIST = 200
MAX_ORDERS_SHOWN = 10
PREVIEW_CHARS = 80
SHORT_ID = 8
MANUAL_RULE = "Bloqueo manual del tendero."

_LIST_SQL = f"""
SELECT s.id, s.created_at, s.updated_at, s.turns, COALESCE(a.state, 'ia'),
       (SELECT customer FROM turns t WHERE t.session_id = s.id AND t.customer != '' ORDER BY number DESC LIMIT 1),
       (SELECT COUNT(*) FROM turns t WHERE t.session_id = s.id
                                     AND t.status IN ({', '.join('?' for _ in INCIDENT_STATES)})),
       b.code, b.technique, b.banned_at
FROM sessions s
LEFT JOIN attention a ON a.session_id = s.id
LEFT JOIN bans b ON b.session_id = s.id AND b.lifted_at IS NULL
WHERE s.updated_at >= ? AND (? IS NULL OR COALESCE(a.state, 'ia') = ?)
  AND (? = '' OR s.id LIKE ? ESCAPE '\\' OR s.id = ?
       OR EXISTS (SELECT 1 FROM turns t WHERE t.session_id = s.id AND t.customer LIKE ? ESCAPE '\\')
       OR EXISTS (SELECT 1 FROM staff_messages m WHERE m.session_id = s.id AND m.text LIKE ? ESCAPE '\\'))
ORDER BY s.updated_at DESC, s.id LIMIT ?
"""


def _like(text: str) -> str:
    # El texto del panel es dato: sus % y _ no pueden volverse comodines de la consulta.
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _order_session(book: OrderBook | None, query: str) -> str | None:
    """Sesión de un código de pedido escrito en la búsqueda («P-ABC123»), si existe."""
    code = query.strip().upper()
    if book is None or not ORDER_ID.match(code):
        return None
    # La vista del pedido no trae la sesión: se lee el dueño en la base de pedidos, filtrado por negocio y sede.
    with book.transaction() as connection:
        row = connection.execute("SELECT session_id FROM orders WHERE id = ? AND business_id = ? AND store_id = ?",
                                 (code, book.business_id, book.store_id)).fetchone()
    return row["session_id"] if row else None


def _orders(book: OrderBook | None, session_id: str) -> list[dict]:
    if book is None:
        return []
    return [{"pedido": order["pedido"], "estado": order["estado"], "total_cop": order["total_cop"]}
            for order in book.session_orders(session_id, limit=MAX_ORDERS_SHOWN)]


def conversations(store: SessionStore, book: OrderBook | None = None, query: str = "", estado: str | None = None,
                  limit: int = 50) -> list[dict]:
    """Conversaciones vigentes, la de actividad más reciente primero, filtradas por texto o estado de atención.

    ``query`` busca en el identificador, en lo que escribió el cliente, en los mensajes del tendero y, con
    ``book``, por código de pedido. ``estado`` es uno de ``ATTENTION_STATES``.
    """
    if not isinstance(query, str) or len(query.strip()) > MAX_QUERY_CHARS:
        raise AttentionError("QUERY_TOO_LONG", f"La búsqueda admite máximo {MAX_QUERY_CHARS} caracteres.")
    if estado is not None and estado not in ATTENTION_STATES:
        raise AttentionError("ATTENTION_STATE_INVALID", f"El estado debe ser uno de: {', '.join(ATTENTION_STATES)}.")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIST:
        raise AttentionError("LIMIT_INVALID", f"El límite va de 1 a {MAX_LIST}.")
    text = query.strip()
    pattern = f"%{_like(text)}%"
    now = store.clock()
    with store.connection() as connection:
        rows = connection.execute(_LIST_SQL, (*INCIDENT_STATES, (now - SESSION_TTL).isoformat(), estado, estado, text,
                                              f"{_like(text.casefold())}%", _order_session(book, text) or "",
                                              pattern, pattern, limit)).fetchall()
    return [{
        "id": session_id, "id_corto": session_id[:SHORT_ID], "creada": local_text(created),
        "ultima_actividad": local_text(updated), "turnos": turns, "atencion": state,
        "vista_previa": shorten(last or "", PREVIEW_CHARS, placeholder="…"),
        "en_vivo": datetime.fromisoformat(updated) >= now - LIVE_WINDOW, "incidencias": incidents,
        "bloqueo": {"tipo": "manual" if code == MANUAL_BAN else "automatico", "codigo": code, "tecnica": technique,
                    "desde": local_text(banned_at)} if code else None,
        "pedidos": _orders(book, session_id),
    } for session_id, created, updated, turns, state, last, incidents, code, technique, banned_at in rows]


def _ban(row: tuple | None) -> dict | None:
    if row is None:
        return None
    code, technique, excerpt, banned_at, lifted_at = row
    manual = code == MANUAL_BAN
    return {"vigente": lifted_at is None, "tipo": "manual" if manual else "automatico", "codigo": code,
            "tecnica": technique, "regla": MANUAL_RULE if manual else INJECTION_CODES.get(code, ""),
            "extracto": excerpt, "desde": local_text(banned_at), "levantado": local_text(lifted_at)}


def conversation(store: SessionStore, session_id: str, book: OrderBook | None = None) -> dict:
    """Detalle de una conversación vigente; SessionError si no existe o venció."""
    with store.connection() as connection:
        total = store.require(connection, session_id)
        created, updated = connection.execute("SELECT created_at, updated_at FROM sessions WHERE id = ?",
                                              (session_id,)).fetchone()
        turns = connection.execute("SELECT number, customer, assistant, status, created_at FROM turns "
                                   "WHERE session_id = ? ORDER BY number", (session_id,)).fetchall()
        staff = connection.execute("SELECT created_at, text FROM staff_messages WHERE session_id = ? ORDER BY rowid",
                                   (session_id,)).fetchall()
        state = connection.execute("SELECT state FROM attention WHERE session_id = ?", (session_id,)).fetchone()
        log = connection.execute("SELECT changed_at, from_state, to_state, reason, actor FROM attention_log "
                                 "WHERE session_id = ? ORDER BY rowid", (session_id,)).fetchall()
        ban = connection.execute("SELECT code, technique, excerpt, banned_at, lifted_at FROM bans WHERE session_id = ?",
                                 (session_id,)).fetchone()
    # Orden por hora; con la misma hora, el turno del cliente va antes que la respuesta del tendero.
    timeline = sorted(
        [(at, 0, {"tipo": "turno", "numero": number, "cliente": customer, "asistente": assistant, "estado": status,
                  "hora": local_text(at)}) for number, customer, assistant, status, at in turns]
        + [(at, 1, {"tipo": "tendero", "texto": text, "hora": local_text(at)}) for at, text in staff],
        key=lambda item: (item[0], item[1]),
    )
    attention = state[0] if state else "ia"
    blocked = _ban(ban)
    return {
        "id": session_id, "id_corto": session_id[:SHORT_ID], "creada": local_text(created),
        "ultima_actividad": local_text(updated), "en_vivo": datetime.fromisoformat(updated) >= store.clock() - LIVE_WINDOW,
        "turnos_total": total,
        "atencion": {"estado": attention, "historial": [
            {"hora": local_text(at), "de": before, "a": after, "motivo": reason, "actor": actor}
            for at, before, after, reason, actor in log]},
        "mensajes": [entry for _, _, entry in timeline],
        "pedidos": book.session_orders(session_id, limit=MAX_ORDERS_SHOWN) if book is not None else [],
        "bloqueo": blocked,
        "acciones": actions(attention, bool(blocked and blocked["vigente"])),
    }
