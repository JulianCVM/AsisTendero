"""Un turno de chat: contexto de la sesión → mismo grafo trazado → memoria del turno."""

from collections.abc import Callable

from asistendero.catalog import MockCatalog
from asistendero.executor import catalog_executor
from asistendero.graph import Planner, ToolExecutor
from asistendero.grok import decide_with_grok
from asistendero.guardrails import redact_personal_data
from asistendero.orders import ACTIVE, WEEKDAYS, OrderBook
from asistendero.choices import shown_options
from asistendero.sessions import SessionStore, remembered_products
from asistendero.shopping_list import updated_list
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


def ban_session(store: SessionStore, session_id: str, injection: dict, message: str,
                orders: OrderBook | None) -> list[str]:
    """Banea la sesión y cancela sus pedidos activos: un cliente baneado no deja unidades apartadas."""
    store.ban(session_id, injection["code"], injection["technique"], redact_personal_data(message)[0])
    if orders is None:
        return []
    active = [order["pedido"] for order in orders.session_orders(session_id, limit=50) if order["estado"] in ACTIVE]
    for order_id in active:
        orders.cancel(order_id, session_id, by="servidor tras un intento de inyección")
    return active


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

    Si el mensaje intentaba inyectar instrucciones, el grafo lo bloquea sin Grok y aquí se banea la sesión.

    Con ``orders`` el turno puede registrar, confirmar, agendar o cancelar pedidos de esta sesión; sin
    ``tool_executor`` se usa el catálogo del mismo archivo que el libro de pedidos.
    """
    context = session_context(store, session_id, orders)
    if tool_executor is None:
        catalog = MockCatalog(orders.path) if orders is not None else MockCatalog()
        tool_executor = catalog_executor(catalog, orders, session_id)
    result = run_traced(message, emit, tool_executor, planner, context=context)
    products = remembered_products(result.get("referencia", ""), result.get("tool_calls", []))
    shopping = updated_list(context.get("lista") or [], result["consulta"], result.get("tool_calls", []))
    options = shown_options(result.get("referencia", ""), result.get("tool_calls", []), result["consulta"])
    turn = store.record(session_id, result["consulta"], result["respuesta"], result["estado"], products, shopping,
                        options)
    injection = result.get("inyeccion")
    if injection:
        cancelled = ban_session(store, session_id, injection, message, orders)
        emit({"type": "ban", "run_id": result["run_id"], "session_id": session_id,
              "details": {**injection, "pedidos_cancelados": cancelled}})
    emit({"type": "session", "run_id": result["run_id"], "session_id": session_id, "turno": turn,
          "productos_recordados": [item["sku"] for item in products],
          "lista": [{"sku": item["sku"], "cantidad": item["cantidad"]} for item in shopping],
          "bloqueada": bool(injection)})
    result.update(session_id=session_id, turno=turn)
    return result
