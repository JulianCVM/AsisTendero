"""Grafo mínimo: valida entrada, consulta Grok y devuelve texto."""

from collections.abc import Callable
from typing import NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph


class AgentState(TypedDict):
    consulta: str
    respuesta: NotRequired[str]


def build_graph(responder: Callable[[str], str]):
    """Inyecta el proveedor del modelo para probar el flujo sin llamadas pagadas."""

    def validar_entrada(state: AgentState) -> dict[str, str]:
        consulta = state["consulta"].strip()
        if not consulta:
            raise ValueError("La consulta no puede estar vacía.")
        if len(consulta) > 2000:
            raise ValueError("La consulta supera el límite de 2000 caracteres.")
        return {"consulta": consulta}

    def consultar_grok(state: AgentState) -> dict[str, str]:
        return {"respuesta": responder(state["consulta"])}

    builder = StateGraph(AgentState)
    builder.add_node("validar_entrada", validar_entrada)
    builder.add_node("consultar_grok", consultar_grok)
    builder.add_edge(START, "validar_entrada")
    builder.add_edge("validar_entrada", "consultar_grok")
    builder.add_edge("consultar_grok", END)
    return builder.compile()
