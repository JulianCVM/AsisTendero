"""Punto de unión entre el grafo y las herramientas del servidor."""

from asistendero.catalog import MockCatalog
from asistendero.graph import ToolExecutor
from asistendero.grok import ORDER_TOOLS
from asistendero.observations import error_envelope
from asistendero.orders import OrderBook


def catalog_executor(catalog: MockCatalog, orders: OrderBook | None = None, session_id: str | None = None) -> ToolExecutor:
    """Fija el catálogo, el libro de pedidos y la sesión del servidor; Grok solo elige nombre y argumentos."""
    from asistendero.order_tools import execute_order_tool
    from asistendero.tools import SOURCE, execute_tool

    def execute(name: str, arguments: dict) -> dict:
        if name in ORDER_TOOLS:
            if orders is None or session_id is None:
                return error_envelope("error", "SESSION_REQUIRED",
                                      "Los pedidos solo se registran dentro de una conversación con sesión.", SOURCE)
            return execute_order_tool(name, arguments, book=orders, session_id=session_id)
        return execute_tool(name, arguments, catalog=catalog)

    return execute
