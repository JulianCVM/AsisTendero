"""Sesiones de chat con memoria acotada, guardadas en SQLite local.

Cada turno corre el mismo grafo; la sesión solo aporta contexto. Lo que se guarda y se le muestra a Grok:

- los últimos ``MAX_CONTEXT_TURNS`` turnos, con el texto del cliente ya filtrado por ``guardrails`` (sin
  frases delicadas ni datos personales) y la respuesta con los montos tapados, porque un precio de un turno
  anterior puede no estar vigente;
- los productos identificados (SKU, nombre, variante y unidad), nunca su precio ni sus existencias.

Precio y existencias se vuelven a leer del catálogo en cada turno. Una sesión vence a las
``SESSION_TTL`` sin actividad y se borra al crear la siguiente: no hay historial indefinido.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from asistendero.observations import latest_quote, search_findings
from asistendero.validation import grounded_products


DEFAULT_SESSIONS_PATH = Path(".local/sessions.sqlite3")
MAX_CONTEXT_TURNS = 4
MAX_TURN_CHARS = 500
MAX_REMEMBERED_PRODUCTS = 8
MAX_TURNS_PER_SESSION = 40
SESSION_TTL = timedelta(hours=12)
SESSION_ID = re.compile(r"^[0-9a-f]{32}$")
MONEY = re.compile(r"\$\s?[\d.,]*\d(?:\s*COP)?")


class SessionError(Exception):
    """Sesión inexistente, vencida o llena, con un código estable."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clip(text: str) -> str:
    # El contexto es un resumen para Grok: se marca el recorte para que no lo tome como el texto completo.
    return text if len(text) <= MAX_TURN_CHARS else text[:MAX_TURN_CHARS - 1] + "…"


def remembered_products(reference: str, calls: list[dict]) -> list[dict]:
    """Productos que el turno dejó identificados: los que el cliente distinguió y los cotizados."""
    products = {sku: product for sku, product in grounded_products(reference, calls).items()}
    quote, _ = latest_quote(calls)
    known = {product.sku: product for finding in search_findings(calls) for product in finding["matches"]}
    for line in (quote or {}).get("lines", []):
        if line["sku"] in known:
            products.setdefault(line["sku"], known[line["sku"]])
    return [{"sku": p.sku, "nombre": p.name, "variante": p.variant, "unidad": p.unit} for p in products.values()]


class SessionStore:
    def __init__(self, path: Path = DEFAULT_SESSIONS_PATH, clock: Callable[[], datetime] = _now):
        self.path = path.resolve()
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """CREATE TABLE IF NOT EXISTS sessions (
                       id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                       turns INTEGER NOT NULL DEFAULT 0);
                   CREATE TABLE IF NOT EXISTS turns (
                       session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                       number INTEGER NOT NULL, customer TEXT NOT NULL, assistant TEXT NOT NULL,
                       status TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (session_id, number));
                   CREATE TABLE IF NOT EXISTS session_products (
                       session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                       sku TEXT NOT NULL, name TEXT NOT NULL, variant TEXT NOT NULL, unit TEXT NOT NULL,
                       last_turn INTEGER NOT NULL, PRIMARY KEY (session_id, sku));"""
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # «with sqlite3.connect()» confirma la transacción pero no cierra: en Windows el archivo queda tomado.
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                yield connection
        finally:
            connection.close()

    def create(self) -> str:
        """Abre una sesión nueva con un identificador del servidor y borra las vencidas."""
        now = self.clock()
        session_id = uuid4().hex
        with self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE updated_at < ?", ((now - SESSION_TTL).isoformat(),))
            connection.execute("INSERT INTO sessions VALUES (?, ?, ?, 0)", (session_id, now.isoformat(), now.isoformat()))
        return session_id

    def _check(self, connection: sqlite3.Connection, session_id: str) -> int:
        if not isinstance(session_id, str) or not SESSION_ID.match(session_id):
            raise SessionError("SESSION_NOT_FOUND", "La sesión no existe. Empieza una conversación nueva.")
        row = connection.execute("SELECT updated_at, turns FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise SessionError("SESSION_NOT_FOUND", "La sesión no existe. Empieza una conversación nueva.")
        if datetime.fromisoformat(row[0]) < self.clock() - SESSION_TTL:
            raise SessionError("SESSION_EXPIRED", "La sesión venció por inactividad. Empieza una conversación nueva.")
        if row[1] >= MAX_TURNS_PER_SESSION:
            raise SessionError("SESSION_FULL", f"La conversación llegó a {MAX_TURNS_PER_SESSION} turnos. "
                                               "Empieza una nueva para seguir.")
        return row[1]

    def context(self, session_id: str) -> dict:
        """Contexto que ve Grok: turnos recientes sin montos y productos identificados sin precio."""
        with self._connect() as connection:
            self._check(connection, session_id)
            turns = connection.execute(
                "SELECT customer, assistant FROM turns WHERE session_id = ? ORDER BY number DESC LIMIT ?",
                (session_id, MAX_CONTEXT_TURNS),
            ).fetchall()
            products = connection.execute(
                "SELECT sku, name, variant, unit FROM session_products WHERE session_id = ? "
                "ORDER BY last_turn DESC, sku LIMIT ?",
                (session_id, MAX_REMEMBERED_PRODUCTS),
            ).fetchall()
        return {
            "turnos": [
                {"cliente": _clip(customer), "asistente": _clip(MONEY.sub("[precio]", assistant))}
                for customer, assistant in reversed(turns) if customer
            ],
            "productos": [{"sku": sku, "nombre": name, "variante": variant, "unidad": unit}
                          for sku, name, variant, unit in products],
        }

    def record(self, session_id: str, customer: str, assistant: str, status: str, products: list[dict]) -> int:
        """Guarda el turno ya filtrado y devuelve su número."""
        now = self.clock().isoformat()
        with self._connect() as connection:
            number = self._check(connection, session_id) + 1
            connection.execute("INSERT INTO turns VALUES (?, ?, ?, ?, ?, ?)",
                               (session_id, number, customer, assistant, status, now))
            connection.executemany(
                "INSERT INTO session_products VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(session_id, sku) DO UPDATE SET last_turn = excluded.last_turn",
                [(session_id, item["sku"], item["nombre"], item["variante"], item["unidad"], number)
                 for item in products],
            )
            connection.execute("UPDATE sessions SET turns = ?, updated_at = ? WHERE id = ?", (number, now, session_id))
        return number
