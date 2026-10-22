"""Vigilancia de pedidos: vence lo que pasó su plazo y deja avisos para cada cliente.

Corre en un hilo del visor (``Watcher``) o a mano (``sweep``). Los avisos salen de los eventos de los pedidos y
no de lo que vence en cada barrido: un pedido que venció dentro de otra operación (``OrderBook`` vence de forma
perezosa antes de cada cambio) también se avisa. Los textos son fijos; Grok no interviene ni gasta créditos.
"""

from datetime import timedelta
import threading

from asistendero.order_replies import notice_text
from asistendero.orders import OrderBook, local_text, utc_text
from asistendero.sessions import SessionStore


WARN_BEFORE = timedelta(minutes=1)
WARNING = "aviso de vencimiento"
SWEEP_SECONDS = 15


def warn_due(book: OrderBook) -> int:
    """Deja un evento de aviso en cada pedido pendiente al que le queda ``WARN_BEFORE`` o menos."""
    now = book.clock()
    with book.transaction() as connection:
        rows = connection.execute(
            "SELECT id FROM orders o WHERE business_id = ? AND store_id = ? AND status = 'pendiente' "
            "AND hold_until > ? AND hold_until <= ? "
            "AND NOT EXISTS (SELECT 1 FROM order_events e WHERE e.order_id = o.id AND e.detail = ?)",
            (book.business_id, book.store_id, utc_text(now), utc_text(now + WARN_BEFORE), WARNING),
        ).fetchall()
        for row in rows:
            connection.execute("INSERT INTO order_events VALUES (?, ?, 'pendiente', ?)", (row["id"], utc_text(now), WARNING))
    return len(rows)


def notices(book: OrderBook, after: int = 0) -> list[dict]:
    """Eventos que se avisan al cliente (por vencer o vencido) con rowid mayor que ``after``."""
    with book.transaction() as connection:
        rows = connection.execute(
            "SELECT e.rowid AS id, e.order_id, e.status, e.detail, o.session_id, o.hold_until FROM order_events e "
            "JOIN orders o ON o.id = e.order_id WHERE e.rowid > ? AND o.business_id = ? AND o.store_id = ? "
            "AND (e.status = 'vencido' OR e.detail = ?) ORDER BY e.rowid",
            (after, book.business_id, book.store_id, WARNING),
        ).fetchall()
    return [{"id": row["id"], "pedido": row["order_id"], "session_id": row["session_id"], "estado": row["status"],
             "detalle": row["detail"], "aparta_hasta": local_text(row["hold_until"])} for row in rows]


def last_event(book: OrderBook) -> int:
    with book.transaction() as connection:
        return connection.execute("SELECT COALESCE(MAX(rowid), 0) FROM order_events").fetchone()[0]


def sweep(book: OrderBook, sessions: SessionStore, after: int) -> int:
    """Un barrido: vence, avisa lo que está por vencer y entrega los avisos nuevos. Devuelve el último evento visto."""
    book.expire_due()
    warn_due(book)
    for event in notices(book, after):
        # Una sesión ya borrada no recibe el aviso; el pedido igual quedó vencido para el tendero.
        sessions.notify(event["session_id"], notice_text(event))
        after = event["id"]
    return after


class Watcher:
    """Barrido periódico en un hilo; empieza después del último evento para no repetir avisos viejos."""

    def __init__(self, book: OrderBook, sessions: SessionStore, interval: float = SWEEP_SECONDS):
        self.book, self.sessions, self.interval = book, sessions, interval
        self.after = last_event(book)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="vigilancia-pedidos", daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.after = sweep(self.book, self.sessions, self.after)
            except Exception as exc:  # noqa: BLE001
                # Un barrido fallido (base ocupada o borrada) no debe tumbar el visor: se reintenta en el siguiente.
                print(f"Vigilancia de pedidos: barrido fallido ({type(exc).__name__}).")

    def start(self) -> "Watcher":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
