"""Un turno de chat: contexto de la sesión → mismo grafo trazado → memoria del turno."""

from collections.abc import Callable

from asistendero.graph import Planner, ToolExecutor
from asistendero.grok import decide_with_grok
from asistendero.sessions import SessionStore, remembered_products
from asistendero.tracing import run_traced


def run_turn(
    store: SessionStore,
    session_id: str,
    message: str,
    emit: Callable[[dict], None] = lambda event: None,
    tool_executor: ToolExecutor | None = None,
    planner: Planner = decide_with_grok,
) -> dict:
    """Ejecuta un mensaje dentro de una sesión y guarda el turno filtrado; lanza SessionError si no existe."""
    context = store.context(session_id)
    result = run_traced(message, emit, tool_executor, planner,
                        context=context if context["turnos"] or context["productos"] else None)
    products = remembered_products(result.get("referencia", ""), result.get("tool_calls", []))
    turn = store.record(session_id, result["consulta"], result["respuesta"], result["estado"], products)
    emit({"type": "session", "run_id": result["run_id"], "session_id": session_id, "turno": turn,
          "productos_recordados": [item["sku"] for item in products]})
    result.update(session_id=session_id, turno=turn)
    return result
