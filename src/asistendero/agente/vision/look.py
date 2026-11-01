"""Convertir la foto del cliente en unas pocas palabras, gastando lo mínimo.

1. La huella de la foto se compara con las del catálogo (``closest_family``): si es la misma foto o casi (un
   cliente que reenvía la que le mandó la tienda), se sabe la familia sin llamar a Grok.
2. Si no, una sola llamada a Grok con la foto reducida (``detail: low``) y un JSON corto de salida.

Lo que sale de aquí son atributos (``ImageAttributePayload``): el servidor busca con ellos en el catálogo y responde
con lo que devuelvan las herramientas. Grok nunca elige el SKU, el precio ni las existencias.
"""

from dataclasses import dataclass
import os
from time import perf_counter

from asistendero.agente.modelo import grok
from asistendero.agente.vision.attributes import (
    VISION_SYSTEM_PROMPT, ImageAttributePayload, VisionOutputError, parse_vision_output,
)
from asistendero.agente.vision.photo import read_photo
from asistendero.tienda.catalogo import product_photos

# La salida es un JSON de seis campos cortos: 200 tokens sobran y acotan el costo si Grok se extiende.
VISION_MAX_TOKENS = 200
# Grok cobra una imagen por tiles; con «low» la manda en una sola de baja resolución, que basta para reconocer el
# tipo de producto. Las medidas finas casi nunca se leen en una foto: se preguntan.
IMAGE_DETAIL = "low"
VISION_INSTRUCTION = "Atributos visibles del producto de esta foto, en el JSON indicado."


@dataclass(frozen=True)
class Look:
    """Lo que se vio en la foto y cómo: ``llamada`` es el uso de Grok (None si bastó la huella).

    ``limpieza`` y ``cotejo`` cuentan a la traza qué se hizo con la foto (tamaños, metadatos y la huella contra las
    fotos del catálogo); son None si llegaron atributos ya armados.
    """

    payload: ImageAttributePayload
    llamada: dict | None
    huella: dict | None
    limpieza: dict | None = None
    cotejo: dict | None = None


def vision_model() -> str:
    """El modelo de la visión: ``GROK_VISION_MODEL`` o el del agente; ``_complete`` rechaza lo que no sea Grok 4.x."""
    return os.getenv("GROK_VISION_MODEL", "").strip() or grok.current_model()


def _by_fingerprint(photo, business: str | None) -> tuple[Look | None, dict]:
    """La familia reconocida por la huella (o None) y el cotejo completo para la traza."""
    entries = product_photos.manifest()
    families = {family for family, entry in entries.items() if business is None or entry.get("negocio") == business}
    report = product_photos.fingerprint_report(photo.fingerprint, families)
    traced = {"limpieza": photo.cleaning(), "cotejo": report}
    family = report["familia"]
    if family is None:
        return None, traced
    payload = ImageAttributePayload(tipo_producto=entries[family]["producto"], confianza_visual="alta", familia=family)
    return Look(payload=payload, llamada=None, huella={"familia": family, "distancia": report["mas_cercana"]},
                **traced), traced


def look_at(image: str | ImageAttributePayload, business: str | None = None) -> Look:
    """Los atributos de la foto. Lanza ``PhotoRejected`` si la foto no sirve y ``ModelError`` si Grok falla.

    ``business`` («ferreteria» o «mercado») limita la huella a las fotos de esa tienda. Un ``ImageAttributePayload``
    ya armado pasa tal cual: lo usan las pruebas y un caso de evaluación con atributos fijos, sin gastar en Grok.
    """
    if isinstance(image, ImageAttributePayload):
        return Look(payload=image, llamada=image.usage, huella=None)
    photo = read_photo(image)
    known, traced = _by_fingerprint(photo, business)
    if known is not None:
        return known
    model = vision_model()
    started = perf_counter()
    content = [
        {"type": "text", "text": VISION_INSTRUCTION},
        {"type": "image_url", "image_url": {"url": photo.data_uri(), "detail": IMAGE_DETAIL}},
    ]
    raw, used_model, input_tokens, output_tokens, cached, ticks = grok._complete(
        VISION_SYSTEM_PROMPT, None, user_content=content, max_tokens=VISION_MAX_TOKENS, model=model,
    )
    usage = {"model": used_model, "input_tokens": input_tokens, "output_tokens": output_tokens,
             "cached_input_tokens": cached, "reported_cost_usd_ticks": ticks,
             "duration_ms": round((perf_counter() - started) * 1000)}
    try:
        payload = parse_vision_output(raw, usage=usage)
    except VisionOutputError as exc:
        # La llamada ya se pagó: se registra su uso y la foto queda como no identificada (se pide la muestra).
        usage["error"] = {"code": "VISION_INVALID_OUTPUT", "message": str(exc)}
        payload = ImageAttributePayload(confianza_visual="baja", usage=usage)
    return Look(payload=payload, llamada=usage, huella=None, **traced)
