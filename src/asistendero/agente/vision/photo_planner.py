"""El turno con foto corre por el mismo grafo que un mensaje, pero lo planea el servidor, no Grok.

Lo que se vio en la foto ya está en el texto del turno como ``[Foto: tubo pvc 1/2 pulgada …]``. Con eso, el
servidor pide ``buscar_productos`` con esos atributos y deja que el grafo haga lo de siempre: validar que lo pedido
esté respaldado, auto-cotizar si el cliente dijo la cantidad y el producto es único, mostrar opciones si hay varias
medidas y responder con la salida determinista. No hay una segunda llamada a Grok.

Si la foto no se reconoce (sin tipo o con confianza baja), o el cliente ya mandó la misma foto
``MAX_VISION_CLARIFICATIONS`` veces seguidas sin que se resolviera, se le pide traer la muestra al mostrador.
"""

from collections.abc import Callable
from dataclasses import replace

from asistendero.agente.modelo.grok import Decision
from asistendero.agente.vision.attributes import (
    MAX_VISION_CLARIFICATIONS, SAMPLE_COUNTER_TEMPLATE, SCREW_SAFEGUARD_TEMPLATE, ImageAttributePayload, search_item,
)
from asistendero.tienda.vocabulario import normalize_text

# Marca las decisiones que tomó el servidor: no son una llamada a Grok ni tienen costo.
SERVER_MODEL = "servidor"
# Lo que Grok supone al mirar (de qué está hecho, para qué sirve, de qué color), no algo que el cliente haya pedido;
# a la derecha, el campo de la búsqueda que lo usaría.
GUESSED = {"material": "material", "presentacion_uso": "presentation", "color_acabado": "color"}


def backed_payload(payload: ImageAttributePayload, has_exact: Callable[[dict], bool] | None) -> ImageAttributePayload:
    """Lo visto en la foto, sin lo supuesto que dejaría sin ningún producto exacto lo que el catálogo sí tiene.

    Prueba real del 31-10-2026: la foto de un martillo de uña volvió «acero» y «uña para extraer clavos»; el catálogo
    no los nombra y la respuesta fue «así como lo pides no lo manejo… es de otro material». Y como el turno guardaba
    «[Foto: martillo acero …]», el turno siguiente volvía a buscar con «acero» (memoria de especificaciones y
    contexto de Grok). Si el catálogo sí lo nombra (el tubo PVC para agua), se queda y acota. Es la regla de la
    búsqueda con «2 libras»: el dato dudoso se suelta solo si no deja ningún exacto. Si ni el tipo de producto tiene
    exactos, no se toca: la respuesta de opciones cercanas es la correcta.
    """
    guessed = {attr: getattr(payload, attr) for attr in GUESSED if getattr(payload, attr)}
    if has_exact is None or not guessed:
        return payload
    bare = replace(payload, **dict.fromkeys(guessed))
    base = search_item(bare)
    if not has_exact(base):
        return payload
    kept = {attr: value for attr, value in guessed.items() if has_exact({**base, GUESSED[attr]: value})}
    if kept and not has_exact({**base, **{GUESSED[attr]: value for attr, value in kept.items()}}):
        kept = {}
    return replace(bare, **kept)


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
