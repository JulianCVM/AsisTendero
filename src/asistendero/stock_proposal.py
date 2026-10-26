"""Propuestas del asistente de bodega: se guardan, vencen, se aplican solo con la confirmación del tendero y una vez.

Flujo: ``propose(texto)`` pide a Grok la interpretación (``stock_assistant.py``), arma la propuesta con antes y
después (``stock_operations.py``) y la guarda en ``stock_proposals`` sin tocar inventario ni pedidos. ``apply(id)``
la aplica solo si sigue vigente (``VALID_MINUTES``), no se aplicó ni se descartó y lo que mostró sigue siendo
verdad (``stock_apply.stale``); si algo cambió, no aplica nada y responde ``PROPOSAL_STALE``. Cada operación
aplicada queda anotada en la fila, así que aplicar dos veces (un doble clic, un reintento tras un fallo) nunca
repite una llegada ni un pedido.

La fila guarda también modelo, versión del prompt, tokens y costo de la llamada a Grok, para la bitácora.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import secrets
import sqlite3

from asistendero.catalog import MockCatalog
from asistendero.inventory import InventoryError
from asistendero.orders import BOGOTA, _store_now, local_text, utc_text
from asistendero.purchasing import Purchasing, PurchasingError
from asistendero.purchasing_rules import MAX_LINES, OPEN
from asistendero.restock import SHOWN_WEEKDAYS
from asistendero.seed import DEFAULT_DB_PATH, DEMO_BUSINESS_ID, DEMO_STORE_ID
from asistendero.stock_apply import APPLICABLE, run, stale
from asistendero.stock_assistant import (StockAssistantError, clean_text, interpret_text,
                                         validate_interpretation)
from asistendero.stock_operations import ProposalBuilder

VALID_MINUTES = 15
# Un reintento de «aplicar» espera a que termine el anterior; pasado este plazo se asume que el anterior murió.
CLAIM_SECONDS = 60
MAX_HISTORY = 100
MAX_CONTEXT_ORDERS = 20
MAX_CONTEXT_SUPPLIERS = 50
PROPOSAL_ID = re.compile(r"^AS-[0-9A-F]{8}$")
STATUSES = ("pendiente", "aplicada", "descartada")
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS stock_proposals (
    business_id TEXT NOT NULL, store_id TEXT NOT NULL, id TEXT NOT NULL, text TEXT NOT NULL,
    created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ({", ".join(f"'{status}'" for status in STATUSES)})),
    proposal TEXT NOT NULL, summary TEXT NOT NULL, applied TEXT NOT NULL, results TEXT NOT NULL,
    claimed_at TEXT, closed_at TEXT, model TEXT, prompt_version TEXT, input_tokens INTEGER, output_tokens INTEGER,
    cost_usd TEXT, PRIMARY KEY (business_id, store_id, id)
);
"""


def _summary(operations: list[dict]) -> str:
    titles = [op["titulo"] for op in operations if op["aplicable"] and op["tipo"] in APPLICABLE]
    if titles:
        return " · ".join(titles)
    return "Consulta" if any(op["tipo"] == "consulta" for op in operations) else "Sin cambios aplicables"


def _unique(texts: list[str]) -> list[str]:
    return list(dict.fromkeys(texts))


class StockAssistant:
    def __init__(self, path: Path = DEFAULT_DB_PATH, clock: Callable[[], datetime] = _store_now,
                 interpret: Callable[[str, dict], dict] = interpret_text, business_id: str = DEMO_BUSINESS_ID,
                 store_id: str = DEMO_STORE_ID):
        self.purchasing = Purchasing(path, clock, business_id, store_id)
        self.path = self.purchasing.path
        self.catalog = MockCatalog(self.path, business_id, store_id)
        self.clock = clock
        self.interpret = interpret
        self.scope = (business_id, store_id)
        with self._transaction() as connection:
            connection.execute(SCHEMA)

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            connection.execute("COMMIT")
        finally:
            connection.close()

    def _context(self) -> tuple[dict, list[dict], list[dict], dict]:
        """Lo que ve Grok: hoy, proveedores y lo pendiente de los pedidos abiertos; nunca el catálogo ni costos."""
        now = self.clock().astimezone(BOGOTA)
        suppliers = self.purchasing.suppliers()
        orders = [order for order in self.purchasing.orders() if order["estado"] in OPEN]
        context = {
            "hoy": {"fecha": now.date().isoformat(), "dia": SHOWN_WEEKDAYS[now.weekday()],
                    "hora": now.strftime("%H:%M")},
            "proveedores": [{"proveedor": item["proveedor"], "nombre": item["nombre"]}
                            for item in suppliers[:MAX_CONTEXT_SUPPLIERS]],
            "pedidos_abiertos": [{
                "oc": order["oc"], "proveedor": order["proveedor"], "fecha_estimada": order["fecha_estimada"],
                "lineas": [{"sku": line["sku"], "nombre": line["nombre"], "variante": line["variante"],
                            "pendiente": line["pendiente"]} for line in order["lineas"] if line["pendiente"] > 0][
                    :MAX_LINES],
            } for order in orders[:MAX_CONTEXT_ORDERS]],
        }
        return context, suppliers, orders, self.purchasing.pending_by_sku()

    def propose(self, texto: str) -> dict:
        text = clean_text(texto)
        context, suppliers, orders, pending = self._context()
        raw = self.interpret(text, context)
        if not isinstance(raw, dict):
            raise StockAssistantError("ASSISTANT_INVALID_OUTPUT", "No pude entender la respuesta del asistente.")
        usage = raw.get("uso") if isinstance(raw.get("uso"), dict) else {}
        # Se vuelve a validar aunque venga de interpret_text: el interpretador es reemplazable.
        data = validate_interpretation({key: value for key, value in raw.items() if key != "uso"})
        proposal_id = f"AS-{secrets.token_hex(4).upper()}"
        now = self.clock()
        builder = ProposalBuilder(self.purchasing, self.catalog, text, now.astimezone(BOGOTA).date(),
                                  f"asistente {proposal_id}", suppliers, orders, pending)
        operations, warnings = builder.build(data["operaciones"])
        if not data["operaciones"] and not data["dudas"]:
            warnings.append("No encontré un cambio de inventario en el mensaje; cuéntamelo con producto y cantidad.")
        created, expires = utc_text(now), utc_text(now + timedelta(minutes=VALID_MINUTES))
        proposal = {"id": proposal_id, "texto": text, "creada": local_text(created), "vence": local_text(expires),
                    "aplicable": any(op["aplicable"] and op["tipo"] in APPLICABLE for op in operations),
                    "advertencias": _unique(warnings), "dudas": data["dudas"], "operaciones": operations}
        cost = usage.get("costo") if isinstance(usage.get("costo"), dict) else {}
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO stock_proposals (business_id, store_id, id, text, created_at, expires_at, status, "
                "proposal, summary, applied, results, model, prompt_version, input_tokens, output_tokens, cost_usd) "
                "VALUES (?, ?, ?, ?, ?, ?, 'pendiente', ?, ?, '[]', '[]', ?, ?, ?, ?, ?)",
                (*self.scope, proposal_id, text, created, expires, json.dumps(proposal, ensure_ascii=False),
                 _summary(operations), usage.get("modelo"), usage.get("prompt"), usage.get("tokens_entrada"),
                 usage.get("tokens_salida"), cost.get("usd")))
        return proposal

    def _load(self, connection: sqlite3.Connection, proposal_id: object) -> sqlite3.Row:
        row = None
        if isinstance(proposal_id, str) and PROPOSAL_ID.match(proposal_id):
            row = connection.execute("SELECT * FROM stock_proposals WHERE business_id = ? AND store_id = ? AND id = ?",
                                     (*self.scope, proposal_id)).fetchone()
        if row is None:
            raise StockAssistantError("PROPOSAL_NOT_FOUND", "No encuentro esa propuesta; vuelve a contármelo.")
        return row

    def _expired(self, row: sqlite3.Row) -> bool:
        return utc_text(self.clock()) >= row["expires_at"]

    def _claim(self, proposal_id: object) -> dict | tuple[dict, list[int], list[str]]:
        """Toma la propuesta para aplicarla; si ya estaba aplicada devuelve el resultado guardado."""
        now = self.clock()
        with self._transaction() as connection:
            row = self._load(connection, proposal_id)
            if row["status"] == "aplicada":
                return {"id": row["id"], "aplicada": True, "resultados": json.loads(row["results"])}
            if row["status"] == "descartada":
                raise StockAssistantError("PROPOSAL_DISCARDED", "Esa propuesta se descartó; vuelve a contármelo.")
            if self._expired(row):
                raise StockAssistantError("PROPOSAL_EXPIRED", f"La propuesta venció ({VALID_MINUTES} minutos); "
                                                              "vuelve a contármelo para revisar el estado actual.")
            if row["claimed_at"] and row["claimed_at"] > utc_text(now - timedelta(seconds=CLAIM_SECONDS)):
                raise StockAssistantError("PROPOSAL_BUSY", "Ya estoy aplicando esta propuesta; espera un momento.")
            connection.execute("UPDATE stock_proposals SET claimed_at = ? WHERE business_id = ? AND store_id = ? "
                               "AND id = ?", (utc_text(now), *self.scope, row["id"]))
            return json.loads(row["proposal"]), json.loads(row["applied"]), json.loads(row["results"])

    def _save(self, proposal_id: str, applied: list[int], results: list[str], done: bool) -> None:
        with self._transaction() as connection:
            connection.execute(
                "UPDATE stock_proposals SET applied = ?, results = ?, claimed_at = NULL, status = ?, closed_at = ? "
                "WHERE business_id = ? AND store_id = ? AND id = ?",
                (json.dumps(applied), json.dumps(results, ensure_ascii=False), "aplicada" if done else "pendiente",
                 utc_text(self.clock()) if done else None, *self.scope, proposal_id))

    def apply(self, proposal_id: str) -> dict:
        claimed = self._claim(proposal_id)
        if isinstance(claimed, dict):
            return claimed
        proposal, applied, results = claimed
        todo = [(index, op) for index, op in enumerate(proposal["operaciones"])
                if op["aplicable"] and op["tipo"] in APPLICABLE and index not in applied]
        today = self.clock().astimezone(BOGOTA).date()
        if not todo and not applied:
            self._save(proposal["id"], applied, results, done=False)
            raise StockAssistantError("PROPOSAL_NOT_APPLICABLE", "Esta propuesta no tiene cambios que aplicar.")
        reasons = [reason for _, op in todo if (reason := stale(self.purchasing, op, today))]
        if reasons:
            self._save(proposal["id"], applied, results, done=False)
            raise StockAssistantError("PROPOSAL_STALE", f"No apliqué nada: {reasons[0]}. Vuelve a contármelo para "
                                                        "armar la propuesta con lo que hay ahora.")
        origin = f"asistente {proposal['id']}"
        for index, op in todo:
            try:
                results.append(run(self.purchasing, op, origin))
            except (PurchasingError, InventoryError) as error:
                self._save(proposal["id"], applied, results, done=False)
                raise StockAssistantError("APPLY_FAILED", f"Apliqué {len(applied)} cambios y el siguiente falló: "
                                                          f"{error}. Revisa y vuelve a confirmar.") from None
            applied.append(index)
            self._save(proposal["id"], applied, results, done=False)
        self._save(proposal["id"], applied, results, done=True)
        return {"id": proposal["id"], "aplicada": True, "resultados": results}

    def discard(self, proposal_id: str) -> dict:
        with self._transaction() as connection:
            row = self._load(connection, proposal_id)
            if row["status"] == "aplicada":
                raise StockAssistantError("PROPOSAL_APPLIED", "Esa propuesta ya se aplicó; corrige con otro cambio.")
            if row["applied"] != "[]":
                raise StockAssistantError("PROPOSAL_APPLIED", "Parte de esa propuesta ya se aplicó; confírmala o "
                                                              "corrige con otro cambio.")
            if row["status"] == "pendiente":
                connection.execute("UPDATE stock_proposals SET status = 'descartada', closed_at = ? WHERE "
                                   "business_id = ? AND store_id = ? AND id = ?",
                                   (utc_text(self.clock()), *self.scope, row["id"]))
        return {"id": row["id"], "descartada": True}

    def history(self, limit: int = 20) -> list[dict]:
        """Propuestas más recientes primero; una pendiente que pasó su plazo se muestra «vencida»."""
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_HISTORY:
            raise StockAssistantError("INVALID_ARGUMENT", f"El límite es un entero de 1 a {MAX_HISTORY}.")
        with self._transaction() as connection:
            rows = connection.execute("SELECT * FROM stock_proposals WHERE business_id = ? AND store_id = ? "
                                      "ORDER BY created_at DESC, rowid DESC LIMIT ?", (*self.scope, limit)).fetchall()
        return [{"id": row["id"], "hora": local_text(row["created_at"]), "texto": row["text"],
                 "estado": "vencida" if row["status"] == "pendiente" and self._expired(row) else row["status"],
                 "resumen": row["summary"]} for row in rows]
