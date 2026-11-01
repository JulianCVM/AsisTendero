"""El turno con foto corre por el mismo grafo que un mensaje, pero lo planea el servidor, no Grok.

Lo que se vio en la foto ya está en el texto del turno como ``[Foto: tubo pvc 1/2 pulgada …]``. Con eso, el
servidor pide ``buscar_productos`` con esos atributos y deja que el grafo haga lo de siempre: validar que lo pedido
esté respaldado, auto-cotizar si el cliente dijo la cantidad y el producto es único, mostrar opciones si hay varias
medidas y responder con la salida determinista. No hay una segunda llamada a Grok.

Si la foto no se reconoce (sin tipo o con confianza baja), o el cliente ya mandó la misma foto
``MAX_VISION_CLARIFICATIONS`` veces seguidas sin que se resolviera, se le pide traer la muestra al mostrador.
"""

from asistendero.agente.modelo.grok import Decision
from asistendero.agente.vision.attributes import (
    MAX_VISION_CLARIFICATIONS, SAMPLE_COUNTER_TEMPLATE, SCREW_SAFEGUARD_TEMPLATE, ImageAttributePayload, search_item,
)
from asistendero.tienda.vocabulario import normalize_text

# Marca las decisiones que tomó el servidor: no son una llamada a Grok ni tienen costo.
SERVER_MODEL = "servidor"


def repeated_photo(summary: str, context: dict | None) -> int:
    """Cuántos turnos seguidos, contando hacia atrás, mandó el cliente esta misma foto."""
    count = 0
    for turn in reversed((context or {}).get("turnos") or []):
        if summary not in (turn.get("cliente") or ""):
            break
        count += 1
    return count


def fixed_reply(payload: ImageAttributePayload, text: str, context: dict | None) -> str | None:
    """La respuesta fija si la foto no alcanza para buscar; None si se busca en el catálogo."""
    if payload.tipo_producto and payload.confianza_visual != "baja":
        if repeated_photo(payload.semantic_summary(), context) >= MAX_VISION_CLARIFICATIONS:
            return SAMPLE_COUNTER_TEMPLATE
        return None
    asks_screw = "tornillo" in normalize_text(f"{text} {payload.tipo_producto or ''}")
    return SCREW_SAFEGUARD_TEMPLATE if asks_screw else SAMPLE_COUNTER_TEMPLATE


class PhotoPlanner:
    """Planificador del grafo para un turno con foto. ``without_model`` le dice al grafo y a la traza que no es Grok."""

    without_model = True

    def __init__(self, payload: ImageAttributePayload, reply: str | None):
        self.payload = payload
        self.reply = reply

    def __call__(self, message: str, observations: list[dict], remaining: int, **extra: object) -> Decision:
        if self.reply is None and not observations:
            return Decision(action="call_tool", intent="productos", tool="buscar_productos",
                            arguments={"items": [search_item(self.payload)]}, reply="", model=SERVER_MODEL)
        # Tras la búsqueda, una respuesta vacía deja la salida determinista armada con lo que devolvió el catálogo.
        return Decision(action="respond", intent="productos", tool=None, arguments=None, reply=self.reply or "",
                        model=SERVER_MODEL)
