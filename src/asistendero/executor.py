"""Punto de unión entre el grafo y las herramientas del servidor."""

from asistendero.catalog import MockCatalog
from asistendero.graph import ToolExecutor


def catalog_executor(catalog: MockCatalog) -> ToolExecutor:
    """Fija el catálogo del servidor; Grok solo elige nombre y argumentos."""
    try:
        # tools.py llega con la rama de herramientas; la importación tardía permite probar el
        # grafo con ejecutores falsos antes de integrarla.
        from asistendero.tools import execute_tool
    except ImportError:
        raise RuntimeError("Las herramientas del servidor (asistendero.tools) aún no están integradas.") from None
    return lambda name, arguments: execute_tool(name, arguments, catalog=catalog)
