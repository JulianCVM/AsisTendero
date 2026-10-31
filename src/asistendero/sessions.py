"""Sesiones de chat con memoria acotada, guardadas en SQLite local.

Cada turno corre el mismo grafo; la sesión solo aporta contexto. Lo que se guarda y se le muestra a Grok:

- los últimos ``MAX_CONTEXT_TURNS`` turnos, con el texto del cliente ya filtrado por ``guardrails`` (sin
  frases delicadas ni datos personales) y la respuesta con los montos tapados, porque un precio de un turno
  anterior puede no estar vigente;
- los productos identificados (SKU, nombre, variante y unidad), nunca su precio ni sus existencias;
- la lista de lo que el cliente ha ido cotizando, con la cantidad que dijo (``shopping_list.py``), para que
  «¿cuánto es todo?» sume lo de hace diez mensajes;
- las opciones de la última respuesta que mostró alguna, en orden (``choices.py``), para entender «del primero».

Precio y existencias se vuelven a leer del catálogo en cada turno. Una sesión vence a las
``SESSION_TTL`` sin actividad y se borra al crear la siguiente: no hay historial indefinido.

Una sesión en la que el cliente intentó inyectar instrucciones (``injection.py``) queda baneada: cada turno
siguiente recibe ``SESSION_BANNED`` sin llegar al grafo ni a Grok. Solo el tendero levanta el baneo desde su
panel. La sesión es la única identidad del cliente en el prototipo; con un canal real se banearía su número.
El tendero también puede bloquearla a mano con un motivo (código ``MANUAL_BAN``).

La atención de cada conversación (asistente, pide humano, tendero o finalizada), su historial y los mensajes del
tendero viven en tablas de esta misma base; las reglas y la API del panel están en ``handoff.py``. Una conversación
finalizada responde ``SESSION_CLOSED`` como una baneada: sin grafo ni Grok.
"""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from asistendero.observations import latest_quote, order_results, search_findings
from asistendero.validation import grounded_products


DEFAULT_SESSIONS_PATH = Path(".local/sessions.sqlite3")
MAX_CONTEXT_TURNS = 4
MAX_TURN_CHARS = 500
MAX_REMEMBERED_PRODUCTS = 8
MAX_SESSION_SPECS = 16
MAX_TURNS_PER_SESSION = 40
SESSION_TTL = timedelta(hours=12)
SESSION_ID = re.compile(r"^[0-9a-f]{32}$")
MAX_BAN_EXCERPT = 200
MAX_CLOSED_ORDERS = 2
MONEY = re.compile(r"\$\s?[\d.,]*\d(?:\s*COP)?")
OBSOLETE_TURN_NOTES = re.compile(r"\n*Precios y existencias de demostración\.\s*$")
MANUAL_BAN = "MANUAL"
CLOSED = "finalizada"


class SessionError(Exception):
    """Sesión inexistente, vencida, llena o baneada, con un código estable."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clip_to(text: str, limit: int) -> str:
    # Se marca el recorte para que nadie lo tome como el texto completo.
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _clip(text: str) -> str:
    return _clip_to(text, MAX_TURN_CHARS)


def _clean_assistant(text: str) -> str:
    """Enmascara precios viejos y quita aclaraciones fijas repetidas sin perder el contenido del turno."""
    masked = MONEY.sub("[precio]", text)
    trimmed = OBSOLETE_TURN_NOTES.sub("", masked).strip() or masked.strip()
    return _clip(re.sub(r"\n{3,}", "\n\n", trimmed))


def compact_context(context: dict) -> dict:
    """Poda colecciones vacías, pedidos cerrados obsoletos y metadatos internos para el payload de Grok.

    Coloca las colecciones estáticas primero (turnos, productos, lista, opciones, especificaciones, pedidos)
    y los datos volátiles de entorno («ahora», «abierto_ahora») estrictamente al final, preservando la inmutabilidad
    del prefijo para aciertos de Prompt Caching.
    """
    clean: dict = {}
    turns = [
        {"cliente": _clip(str(turn["cliente"])), "asistente": _clean_assistant(str(turn.get("asistente", "")))}
        for turn in (context.get("turnos") or [])[-MAX_CONTEXT_TURNS:]
        if isinstance(turn, dict) and turn.get("cliente")
    ]
    if turns:
        clean["turnos"] = turns
    products = [
        {key: item[key] for key in ("sku", "nombre", "variante", "unidad") if key in item}
        for item in (context.get("productos") or [])[:MAX_REMEMBERED_PRODUCTS]
        if isinstance(item, dict) and item.get("sku")
    ]
    if products:
        clean["productos"] = products
    listed = [
        {key: item[key] for key in ("sku", "nombre", "variante", "unidad", "cantidad") if key in item}
        for item in (context.get("lista") or []) if isinstance(item, dict) and item.get("sku")
    ]
    if listed:
        clean["lista"] = listed
    if context.get("opciones"):
        clean["opciones"] = [
            {
                "grupo": block["grupo"],
                "opciones": block["opciones"],
                **({"restantes_total": len(block["restantes"])} if block.get("restantes") else {}),
            }
            for block in context["opciones"] if isinstance(block, dict) and block.get("grupo")
        ]
    if isinstance(context.get("especificaciones"), dict) and context["especificaciones"]:
        specs = {
            head: {k: v for k, v in vals.items() if isinstance(v, str) and v}
            for head, vals in list(context["especificaciones"].items())[:MAX_SESSION_SPECS]
            if isinstance(vals, dict) and any(isinstance(v, str) and v for v in vals.values())
        }
        if specs:
            clean["especificaciones"] = specs
    orders = [order for order in (context.get("pedidos") or []) if isinstance(order, dict) and order.get("pedido")]
    if orders:
        active = [order for order in orders if order.get("estado") in {"pendiente", "confirmado"}]
        closed = [order for order in orders if order.get("estado") not in {"pendiente", "confirmado"}][:MAX_CLOSED_ORDERS]
        pruned_orders = []
        for order in active + closed:
            entry = {
                "pedido": order["pedido"],
                "estado": order["estado"],
                "lineas": [
                    {key: line[key] for key in ("sku", "nombre", "variante", "cantidad", "unidad") if key in line}
                    for line in (order.get("lineas") or []) if isinstance(line, dict)
                ],
            }
            for optional in ("aparta_hasta", "recogida", "nota"):
                if order.get(optional):
                    entry[optional] = order[optional]
            pruned_orders.append(entry)
        if pruned_orders:
            clean["pedidos"] = pruned_orders
    # Lo volátil (reloj del servidor, cálculo de abierto_ahora) va estrictamente al final:
    if isinstance(context.get("ahora"), str) and context["ahora"]:
        clean["ahora"] = context["ahora"]
    if context.get("abierto_ahora") is not None:
        clean["abierto_ahora"] = context["abierto_ahora"]
    return clean


def remembered_products(reference: str, calls: list[dict]) -> list[dict]:
    """Productos que el turno dejó identificados: los que el cliente distinguió y los cotizados."""
    products = {sku: product for sku, product in grounded_products(reference, calls).items()}
    quote, _ = latest_quote(calls)
    known = {product.sku: product for finding in search_findings(calls) for product in finding["matches"]}
    for line in (quote or {}).get("lines", []):
        if line["sku"] in known:
            products.setdefault(line["sku"], known[line["sku"]])
    remembered = {p.sku: {"sku": p.sku, "nombre": p.name, "variante": p.variant, "unidad": p.unit}
                  for p in products.values()}
    # Una cotización sin búsqueda en el turno («la de galón, deme 2») también deja el producto identificado: si no,
    # «mejor que sean 3» no tenía qué cotizar (suite natural, H-02).
    for line in (quote or {}).get("lines", []):
        if all(isinstance(line.get(key), str) for key in ("name", "variant", "unit")):
            remembered.setdefault(line["sku"], {"sku": line["sku"], "nombre": line["name"],
                                                "variante": line["variant"], "unidad": line["unit"]})
    # Lo que entró a un pedido también queda identificado: «agrégale otro de esos» se refiere a eso.
    for _, order in order_results(calls):
        for line in order["lineas"]:
            if all(isinstance(line.get(key), str) for key in ("nombre", "variante", "unidad")):
                remembered.setdefault(line["sku"], {"sku": line["sku"], "nombre": line["nombre"],
                                                    "variante": line["variante"], "unidad": line["unidad"]})
    return list(remembered.values())


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
                       last_turn INTEGER NOT NULL, PRIMARY KEY (session_id, sku));
                   CREATE TABLE IF NOT EXISTS notices (
                       session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                       created_at TEXT NOT NULL, text TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0);
                   CREATE TABLE IF NOT EXISTS bans (
                       session_id TEXT PRIMARY KEY, banned_at TEXT NOT NULL, code TEXT NOT NULL,
                       technique TEXT NOT NULL, excerpt TEXT NOT NULL, lifted_at TEXT);
                   CREATE TABLE IF NOT EXISTS session_list (
                       session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                       position INTEGER NOT NULL, sku TEXT NOT NULL, name TEXT NOT NULL, variant TEXT NOT NULL,
                       unit TEXT NOT NULL, quantity INTEGER NOT NULL, PRIMARY KEY (session_id, sku));
                   CREATE TABLE IF NOT EXISTS session_options (
                       session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                       grupo INTEGER NOT NULL, position INTEGER NOT NULL, label TEXT NOT NULL, sku TEXT NOT NULL,
                       name TEXT NOT NULL, variant TEXT NOT NULL, unit TEXT NOT NULL,
                       shown INTEGER NOT NULL DEFAULT 1,
                       PRIMARY KEY (session_id, grupo, position));
                   CREATE TABLE IF NOT EXISTS session_specs (
                       session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                       product_key TEXT NOT NULL, measure TEXT NOT NULL DEFAULT '',
                       material TEXT NOT NULL DEFAULT '', presentation TEXT NOT NULL DEFAULT '',
                       updated_turn INTEGER NOT NULL, PRIMARY KEY (session_id, product_key));
                   CREATE TABLE IF NOT EXISTS attention (
                       session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
                       state TEXT NOT NULL, updated_at TEXT NOT NULL);
                   CREATE TABLE IF NOT EXISTS attention_log (
                       session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE, changed_at TEXT NOT NULL,
                       from_state TEXT NOT NULL, to_state TEXT NOT NULL, reason TEXT NOT NULL, actor TEXT NOT NULL);
                   CREATE TABLE IF NOT EXISTS staff_messages (
                       session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                       created_at TEXT NOT NULL, text TEXT NOT NULL);"""
            )
            option_columns = {row[1] for row in connection.execute("PRAGMA table_info(session_options)").fetchall()}
            if "shown" not in option_columns:
                connection.execute("ALTER TABLE session_options ADD COLUMN shown INTEGER NOT NULL DEFAULT 1")

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

    def connection(self) -> AbstractContextManager[sqlite3.Connection]:
        """Conexión a esta base para ``handoff`` y ``supervision``, que guardan y leen tablas de la misma sesión."""
        return self._connect()

    def require(self, connection: sqlite3.Connection, session_id: str) -> int:
        """Turnos de una sesión que existe y no venció; si no, SessionError. El panel actúa también sobre baneadas."""
        if not isinstance(session_id, str) or not SESSION_ID.match(session_id):
            raise SessionError("SESSION_NOT_FOUND", "La sesión no existe. Empieza una conversación nueva.")
        row = connection.execute("SELECT updated_at, turns FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise SessionError("SESSION_NOT_FOUND", "La sesión no existe. Empieza una conversación nueva.")
        if datetime.fromisoformat(row[0]) < self.clock() - SESSION_TTL:
            raise SessionError("SESSION_EXPIRED", "La sesión venció por inactividad. Empieza una conversación nueva.")
        return row[1]

    def _check(self, connection: sqlite3.Connection, session_id: str) -> int:
        turns = self.require(connection, session_id)
        ban = connection.execute("SELECT code FROM bans WHERE session_id = ? AND lifted_at IS NULL",
                                 (session_id,)).fetchone()
        if ban and ban[0] == MANUAL_BAN:
            raise SessionError("SESSION_BANNED", "El tendero bloqueó esta conversación. Si fue un error, pídele en el "
                                                 "mostrador que la desbloquee.")
        if ban:
            raise SessionError("SESSION_BANNED", "Esta conversación quedó bloqueada por un intento de cambiar las "
                                                 "reglas del asistente. Si fue un error, pídele al tendero que la "
                                                 "desbloquee.")
        if connection.execute("SELECT 1 FROM attention WHERE session_id = ? AND state = ?",
                              (session_id, CLOSED)).fetchone():
            raise SessionError("SESSION_CLOSED", "El tendero dio por terminada esta conversación. Si necesitas algo "
                                                 "más, empieza una nueva.")
        if turns >= MAX_TURNS_PER_SESSION:
            raise SessionError("SESSION_FULL", f"La conversación llegó a {MAX_TURNS_PER_SESSION} turnos. "
                                               "Empieza una nueva para seguir.")
        return turns

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
            listed = connection.execute(
                "SELECT sku, name, variant, unit, quantity FROM session_list WHERE session_id = ? ORDER BY position",
                (session_id,),
            ).fetchall()
            shown = connection.execute(
                "SELECT grupo, label, sku, name, variant, unit, shown FROM session_options WHERE session_id = ? "
                "ORDER BY grupo, position", (session_id,),
            ).fetchall()
            spec_rows = connection.execute(
                "SELECT product_key, measure, material, presentation FROM session_specs WHERE session_id = ? "
                "ORDER BY updated_turn DESC, product_key LIMIT ?",
                (session_id, MAX_SESSION_SPECS),
            ).fetchall()
        options: dict[int, dict] = {}
        for group, label, sku, name, variant, unit, is_shown in shown:
            block = options.setdefault(group, {"grupo": label, "opciones": []})
            if is_shown:
                block["opciones"].append({"n": len(block["opciones"]) + 1, "sku": sku, "nombre": name,
                                          "variante": variant, "unidad": unit})
            else:
                block.setdefault("restantes", []).append({"sku": sku, "nombre": name,
                                                          "variante": variant, "unidad": unit})
        especificaciones = {
            product_key: {
                key: val
                for key, val in (("medida", measure), ("material", material), ("presentacion", presentation))
                if val
            }
            for product_key, measure, material, presentation in spec_rows
            if measure or material or presentation
        }
        return {
            "turnos": [
                {"cliente": _clip(customer), "asistente": _clean_assistant(assistant)}
                for customer, assistant in reversed(turns) if customer
            ],
            "productos": [{"sku": sku, "nombre": name, "variante": variant, "unidad": unit}
                          for sku, name, variant, unit in products],
            "lista": [{"sku": sku, "nombre": name, "variante": variant, "unidad": unit, "cantidad": quantity}
                      for sku, name, variant, unit, quantity in listed],
            "opciones": list(options.values()),
            "especificaciones": especificaciones,
        }

    def notify(self, session_id: str, text: str) -> bool:
        """Deja un aviso del servidor para el cliente (pedido por vencer o vencido); False si la sesión ya no existe."""
        with self._connect() as connection:
            if connection.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone() is None:
                return False
            connection.execute("INSERT INTO notices (session_id, created_at, text) VALUES (?, ?, ?)",
                               (session_id, self.clock().isoformat(), text))
        return True

    def take_notices(self, session_id: str) -> list[str]:
        """Avisos aún no entregados de la sesión, en orden; quedan marcados como entregados."""
        with self._connect() as connection:
            rows = connection.execute("SELECT rowid, text FROM notices WHERE session_id = ? AND delivered = 0 "
                                      "ORDER BY rowid", (session_id,)).fetchall()
            connection.executemany("UPDATE notices SET delivered = 1 WHERE rowid = ?", [(row[0],) for row in rows])
        return [row[1] for row in rows]

    def record(self, session_id: str, customer: str, assistant: str, status: str, products: list[dict],
               shopping: list[dict] | None = None, options: list[dict] | None = None,
               specs: dict[str, dict[str, str]] | None = None) -> int:
        """Guarda el turno ya filtrado y devuelve su número.

        ``shopping`` reemplaza la lista de la sesión; ``options``, si trae grupos, reemplaza las opciones mostradas;
        ``specs``, si se informa, actualiza las especificaciones fijadas por tipo de producto.
        """
        now = self.clock().isoformat()
        with self._connect() as connection:
            number = self._check(connection, session_id) + 1
            clean_customer = _clip(customer)
            clean_assistant = _clean_assistant(assistant)
            connection.execute("INSERT INTO turns VALUES (?, ?, ?, ?, ?, ?)",
                               (session_id, number, clean_customer, clean_assistant, status, now))
            connection.executemany(
                "INSERT INTO session_products VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(session_id, sku) DO UPDATE SET last_turn = excluded.last_turn",
                [(session_id, item["sku"], item["nombre"], item["variante"], item["unidad"], number)
                 for item in products],
            )
            if products:
                connection.execute(
                    "DELETE FROM session_products WHERE session_id = ? AND sku NOT IN ("
                    "SELECT sku FROM session_products WHERE session_id = ? ORDER BY last_turn DESC, sku LIMIT ?)",
                    (session_id, session_id, MAX_REMEMBERED_PRODUCTS),
                )
            if shopping is not None:
                connection.execute("DELETE FROM session_list WHERE session_id = ?", (session_id,))
                connection.executemany(
                    "INSERT INTO session_list VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [(session_id, position, item["sku"], item["nombre"], item["variante"], item["unidad"],
                      item["cantidad"]) for position, item in enumerate(shopping)],
                )
            if options:
                connection.execute("DELETE FROM session_options WHERE session_id = ?", (session_id,))
                option_rows = []
                for group, block in enumerate(options):
                    shown_items = block.get("opciones") or []
                    for position, item in enumerate(shown_items):
                        option_rows.append((session_id, group, position, block["grupo"], item["sku"],
                                            item["nombre"], item["variante"], item["unidad"], 1))
                    offset = len(shown_items)
                    for extra_pos, item in enumerate(block.get("restantes") or []):
                        option_rows.append((session_id, group, offset + extra_pos, block["grupo"], item["sku"],
                                            item["nombre"], item["variante"], item["unidad"], 0))
                connection.executemany(
                    "INSERT INTO session_options VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", option_rows,
                )
            if specs is not None:
                connection.execute("DELETE FROM session_specs WHERE session_id = ?", (session_id,))
                spec_rows = [
                    (session_id, head, str(values.get("medida") or ""), str(values.get("material") or ""),
                     str(values.get("presentacion") or ""), number)
                    for head, values in list(specs.items())[:MAX_SESSION_SPECS]
                    if isinstance(values, dict)
                    and (values.get("medida") or values.get("material") or values.get("presentacion"))
                ]
                if spec_rows:
                    connection.executemany("INSERT INTO session_specs VALUES (?, ?, ?, ?, ?, ?)", spec_rows)
            connection.execute("UPDATE sessions SET turns = ?, updated_at = ? WHERE id = ?", (number, now, session_id))
        return number

    def ban(self, session_id: str, code: str, technique: str, excerpt: str) -> None:
        """Banea la sesión; ``excerpt`` es el mensaje ya sin datos personales (o el motivo del bloqueo manual)."""
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO bans VALUES (?, ?, ?, ?, ?, NULL) ON CONFLICT(session_id) DO UPDATE SET "
                "banned_at = excluded.banned_at, code = excluded.code, technique = excluded.technique, "
                "excerpt = excluded.excerpt, lifted_at = NULL",
                (session_id, self.clock().isoformat(), code, technique, _clip_to(excerpt, MAX_BAN_EXCERPT)),
            )

    def unban(self, session_id: str) -> bool:
        """Levanta el baneo vigente; False si la sesión no estaba baneada."""
        with self._connect() as connection:
            lifted = connection.execute("UPDATE bans SET lifted_at = ? WHERE session_id = ? AND lifted_at IS NULL",
                                        (self.clock().isoformat(), session_id))
        return lifted.rowcount == 1

    def bans(self, limit: int = 50) -> list[dict]:
        """Baneos, el más reciente primero, con el código, si siguen vigentes y si fue manual o por inyección."""
        with self._connect() as connection:
            rows = connection.execute("SELECT session_id, banned_at, code, technique, excerpt, lifted_at FROM bans "
                                      "ORDER BY banned_at DESC LIMIT ?", (limit,)).fetchall()
        return [{"sesion": row[0], "baneada": row[1], "codigo": row[2], "tecnica": row[3], "mensaje": row[4],
                 "vigente": row[5] is None, "tipo": "manual" if row[2] == MANUAL_BAN else "automatico"}
                for row in rows]
