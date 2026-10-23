"""Conversaciones evaluadas con pedidos: muchos turnos, varios clientes a la vez y la hora de la tienda.

Cada conversación (``turns``) corre sobre su propia copia del catálogo: lo que aparta no cambia otros casos. Un
caso con ``clients`` es una sola tienda con varios clientes escribiendo al mismo tiempo, un hilo y un modelo por
cliente: muestra que dos personas no se llevan la misma última unidad.

Además de lo que revisa ``eval_checks.verdict``, un turno puede traer:

- ``wait_minutes``: antes del mensaje pasan esos minutos para esta conversación (se corren hacia atrás sus
  plazos y se barre como en el visor). ``expected_notice`` son textos que deben estar en los avisos que deja.
  Un turno sin ``query`` solo espera y no llama a Grok.
- ``expected_orders``: estados de los pedidos de la sesión, del más viejo al más nuevo.
- ``expected_pickup`` y ``expected_note``: texto que debe aparecer en la recogida o en la nota de algún pedido.
- ``expected_status`` puede ser un código de sesión (``SESSION_BANNED``): el turno no llega al grafo.

Un caso con ``clients`` puede traer ``expected_active_total``: pedidos activos entre todos al final.
"""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
import shutil
import time

from asistendero import tools
from asistendero.chat import run_turn
from asistendero.eval_checks import record, sum_known
from asistendero.graph import Planner
from asistendero.grok import MODEL_OVERRIDE, current_model
from asistendero.inventory import Inventory
from asistendero.order_replies import notice_text
from asistendero.order_watch import last_event, notices, warn_due
from asistendero.orders import ACTIVE, BOGOTA, OrderBook, utc_text
from asistendero.pricing import run_cost
from asistendero.sessions import SessionError, SessionStore


# Un miércoles a las 9:00: con la hora real, «mañana a las 10» fallaría un sábado o de noche.
SIM_START = datetime(2026, 10, 21, 9, 0, tzinfo=BOGOTA)


class StoreClock:
    """Hora de la tienda en una corrida: empieza en ``start`` y avanza con el tiempo real."""

    def __init__(self, start: datetime = SIM_START):
        self.start, self.origin = start, time.monotonic()

    def __call__(self) -> datetime:
        return self.start + timedelta(seconds=time.monotonic() - self.origin)


@contextmanager
def store_time(clock) -> Iterator[None]:
    """Fija la hora que ven las herramientas, los pedidos y el contexto de Grok mientras dura la corrida."""
    previous = tools.local_now
    tools.local_now = clock
    try:
        yield
    finally:
        tools.local_now = previous


@contextmanager
def using_model(model: str | None) -> Iterator[None]:
    """Modelo de Grok para este hilo; cada cliente simulado puede usar uno distinto."""
    token = MODEL_OVERRIDE.set(model) if model else None
    try:
        yield
    finally:
        if token is not None:
            MODEL_OVERRIDE.reset(token)


def fast_forward(book: OrderBook, session_id: str, minutes: float) -> None:
    """Simula que pasan ``minutes`` solo para esta sesión: adelanta el vencimiento de sus pedidos activos."""
    with book.transaction() as connection:
        rows = connection.execute("SELECT id, hold_until FROM orders WHERE session_id = ? AND status IN (?, ?)",
                                  (session_id, *ACTIVE)).fetchall()
        for row in rows:
            moved = datetime.fromisoformat(row["hold_until"]) - timedelta(minutes=minutes)
            connection.execute("UPDATE orders SET hold_until = ? WHERE id = ?", (utc_text(moved), row["id"]))


def order_reasons(check: dict, orders: list[dict], notes: list[str]) -> list[str]:
    reasons = []
    states = [order["estado"] for order in orders]
    if "expected_orders" in check and states != check["expected_orders"]:
        reasons.append(f"pedidos {states}")
    for key, field in (("expected_pickup", "recogida"), ("expected_note", "nota")):
        wanted = check.get(key)
        if wanted and not any(wanted.casefold() in (order.get(field) or "").casefold() for order in orders):
            reasons.append(f"sin {field} «{wanted}»")
    reasons += [f"sin aviso «{text}»" for text in check.get("expected_notice", [])
                if not any(text.casefold() in note.casefold() for note in notes)]
    return reasons


def _waiting(check: dict) -> dict:
    return {"query": None, "wait_minutes": check["wait_minutes"], "expected_status": None, "actual_status": "espera",
            "passed": True, "fail_reasons": [], "response": "", "model_calls": 0, "tools": [], "tools_executed": [],
            "input_tokens": None, "output_tokens": None, "cached_input_tokens": None, "total_tokens": None,
            "cost": None, "elapsed_ms": 0, "events": []}


def _session_error(check: dict, error: SessionError) -> dict:
    """Turno que la sesión rechazó antes del grafo (baneada, vencida o llena): sin Grok ni herramientas."""
    expected = check["expected_status"]
    passed = error.code in (expected if isinstance(expected, list) else [expected])
    return {**_waiting({"wait_minutes": 0}), "query": check["query"], "expected_status": expected,
            "actual_status": error.code, "passed": passed, "fail_reasons": [] if passed else [f"estado {error.code}"],
            "response": str(error)}


class Conversation:
    """Un cliente en una tienda: su sesión, sus pedidos y los avisos que ya recibió."""

    def __init__(self, book: OrderBook, store: SessionStore, planner: Planner):
        self.book, self.store, self.planner = book, store, planner
        self.session_id = store.create()
        self.seen = last_event(book)

    def _wait(self, minutes: float) -> list[str]:
        fast_forward(self.book, self.session_id, minutes)
        self.book.expire_due()
        warn_due(self.book)
        events = notices(self.book, self.seen)
        self.seen = max([self.seen, *(event["id"] for event in events)])
        return [notice_text(event) for event in events if event["session_id"] == self.session_id]

    def turn(self, check: dict) -> dict:
        notes = self._wait(check["wait_minutes"]) if check.get("wait_minutes") else []
        if check.get("query"):
            events: list[dict] = []
            try:
                result = run_turn(self.store, self.session_id, check["query"], events.append, None, self.planner,
                                  orders=self.book)
            except SessionError as error:
                turn = _session_error(check, error)
            else:
                turn = record(check, result, events)
        else:
            turn = _waiting(check)
        orders = list(reversed(self.book.session_orders(self.session_id, limit=10)))
        turn["orders"] = [{key: order[key] for key in ("pedido", "estado", "recogida", "nota")} for order in orders]
        turn["notices"] = notes
        turn["fail_reasons"] += order_reasons(check, orders, notes)
        turn["passed"] = not turn["fail_reasons"]
        return turn


def totals(turns: list[dict]) -> dict:
    """Campos de un caso de varios turnos: pasa solo si pasa cada turno; el costo suma lo conocido."""
    asked = [turn for turn in turns if turn["query"]]
    return {
        "query": " / ".join(turn["query"] or f"(pasan {turn['wait_minutes']} min)" for turn in turns),
        "expected_status": [turn["expected_status"] for turn in turns],
        "actual_status": [turn["actual_status"] for turn in turns],
        "passed": all(turn["passed"] for turn in turns),
        "fail_reasons": [f"turno {index}: {reason}" for index, turn in enumerate(turns, 1) for reason in turn["fail_reasons"]],
        "response": asked[-1]["response"] if asked else "",
        "model_calls": sum(turn["model_calls"] for turn in turns),
        "tools": [name for turn in turns for name in turn["tools"]],
        "tools_executed": [name for turn in turns for name in turn["tools_executed"]],
        "input_tokens": sum_known([turn["input_tokens"] for turn in turns]),
        "output_tokens": sum_known([turn["output_tokens"] for turn in turns]),
        "cached_input_tokens": sum_known([turn["cached_input_tokens"] for turn in turns]),
        "total_tokens": sum_known([turn["total_tokens"] for turn in turns]),
        "cost": run_cost([turn["cost"] for turn in turns if turn["model_calls"]]),
        "elapsed_ms": sum(turn["elapsed_ms"] for turn in turns),
        "turns": turns,
    }


def _store(case: dict, catalog_path: Path, folder: Path) -> tuple[OrderBook, SessionStore]:
    """Copia propia del catálogo para el caso: los pedidos de un caso no apartan existencias de otro."""
    database = folder / f"{case['id']}.sqlite3"
    shutil.copy(catalog_path, database)
    return OrderBook(database), SessionStore(folder / f"{case['id']}-sesiones.sqlite3")


def run_conversation(case: dict, *, catalog_path: Path, folder: Path, planner: Planner) -> dict:
    book, store = _store(case, catalog_path, folder)
    conversation = Conversation(book, store, planner)
    turns = [conversation.turn(check) for check in case["turns"]]
    return {"id": case["id"], "suite": case.get("suite", "conversacion"), "model": current_model(), **totals(turns)}


def run_clients(case: dict, *, catalog_path: Path, folder: Path, planner: Planner, models: list[str]) -> dict:
    """Varios clientes en la misma tienda, todos a la vez; el cliente i usa ``models[i % len(models)]``."""
    book, store = _store(case, catalog_path, folder)

    def client(index: int) -> dict:
        model = models[index % len(models)]
        with using_model(model):
            conversation = Conversation(book, store, planner)
            turns = [conversation.turn(check) for check in case["clients"][index]["turns"]]
        return {"client": index + 1, "model": model, "session": conversation.session_id, **totals(turns)}

    with ThreadPoolExecutor(max_workers=len(case["clients"])) as pool:
        clients = list(pool.map(client, range(len(case["clients"]))))
    active = sum(order["estado"] in ACTIVE for item in clients for order in book.session_orders(item["session"], limit=10))
    reasons = [f"cliente {item['client']}: {reason}" for item in clients for reason in item["fail_reasons"]]
    if "expected_active_total" in case and active != case["expected_active_total"]:
        reasons.append(f"{active} pedidos activos entre todos")
    # Pase lo que pase con cada cliente, lo apartado nunca supera lo que hay en bodega.
    reasons += [f"{item['sku']} con {item['apartado']} apartados y {item['stock']} en bodega"
                for item in Inventory(book.path).products() if item["apartado"] > item["stock"]]
    merged = totals([turn for item in clients for turn in item["turns"]])
    return {"id": case["id"], "suite": case.get("suite", "concurrencia"), "model": ", ".join(sorted(set(models))),
            **merged, "passed": not reasons, "fail_reasons": reasons, "active_orders": active, "clients": clients}
