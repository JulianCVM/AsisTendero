"""Un turno de chat: contexto de la sesión → mismo grafo trazado → memoria del turno."""

from collections.abc import Callable

from asistendero.catalog import MockCatalog
from asistendero.executor import catalog_executor
from asistendero.graph import Planner, ToolExecutor
from asistendero.grok import decide_with_grok
from asistendero.orders import WEEKDAYS, OrderBook
from asistendero.sessions import SessionStore, remembered_products
from asistendero.tracing import run_traced


def order_context(orders: list[dict]) -> list[dict]:
    """Pedidos de la sesión para Grok: estado, líneas y horas, sin precios (se releen con la herramienta)."""
    return [
        {"pedido": order["pedido"], "estado": order["estado"],
         "lineas": [{"sku": line["sku"], "nombre": line["nombre"], "variante": line["variante"],
                     "cantidad": line["cantidad"], "unidad": line["unidad"]} for line in order["lineas"]],
         "aparta_hasta": order["aparta_hasta"], "recogida": order["recogida"], "nota": order["nota"]}
        for order in orders
    ]


def session_context(store: SessionStore, session_id: str, orders: OrderBook | None) -> dict:
    """Lo que Grok sabe de la conversación: turnos, productos, hora de la tienda y pedidos del cliente."""
    context = store.context(session_id)
    if orders is not None:
        now = orders.clock()
        # Sin la hora, «mañana a las 4» no se puede convertir en una fecha de recogida.
        context["ahora"] = f"{now.strftime('%Y-%m-%d %H:%M')} ({WEEKDAYS[now.weekday()]})"
        context["pedidos"] = order_context(orders.session_orders(session_id))
    return context


def run_turn(
    store: SessionStore,
    session_id: str,
    message: str,
    emit: Callable[[dict], None] = lambda event: None,
    tool_executor: ToolExecutor | None = None,
    planner: Planner = decide_with_grok,
    orders: OrderBook | None = None,
) -> dict:
    """Ejecuta un mensaje dentro de una sesión y guarda el turno filtrado; lanza SessionError si no existe.

    Con ``orders`` el turno puede registrar, confirmar, agendar o cancelar pedidos de esta sesión; sin
    ``tool_executor`` se usa el catálogo del mismo archivo que el libro de pedidos.
    """
    context = session_context(store, session_id, orders)
    if tool_executor is None:
        catalog = MockCatalog(orders.path) if orders is not None else MockCatalog()
        tool_executor = catalog_executor(catalog, orders, session_id)
    result = run_traced(message, emit, tool_executor, planner, context=context)
    products = remembered_products(result.get("referencia", ""), result.get("tool_calls", []))
    turn = store.record(session_id, result["consulta"], result["respuesta"], result["estado"], products)
    emit({"type": "session", "run_id": result["run_id"], "session_id": session_id, "turno": turn,
          "productos_recordados": [item["sku"] for item in products]})
    result.update(session_id=session_id, turno=turn)
    return result
