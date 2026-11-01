"""Las fotos que acompañan una respuesta: una referencia corta por producto, nunca los bytes.

Cada foto viaja como ``{"sku", "nombre", "foto", "url", "credito"}``: el cliente la pide por su ``url`` (la sirve
el visor desde ``datos/fotos``) y sabe de qué producto es por su ``sku``. Grok nunca las ve: no gastan tokens.

Solo se muestran productos que el catálogo devolvió en este turno: primero los cotizados y luego las coincidencias
de cada búsqueda. Las opciones cercanas no llevan foto, porque una foto haría pasar por equivalente lo que no lo es.
"""

from asistendero.agente.herramientas.observations import ToolCall, latest_quote, search_findings
from asistendero.tienda.catalogo.product_photos import family_of, photo_of

MAX_REPLY_PHOTOS = 3


def reply_photos(calls: list[ToolCall]) -> list[dict]:
    named: list[tuple[str, str]] = []
    quote, _ = latest_quote(calls)
    for line in (quote or {}).get("lines") or []:
        if isinstance(line, dict) and isinstance(line.get("sku"), str):
            named.append((line["sku"], " ".join(str(line.get(key) or "") for key in ("name", "variant")).strip()))
    for finding in search_findings(calls):
        named.extend((match.sku, f"{match.name} {match.variant}".strip()) for match in finding["matches"])
    photos: list[dict] = []
    families: set[str] = set()
    for sku, name in named:
        photo = photo_of(sku)
        if photo is None or family_of(sku) in families:
            continue
        families.add(family_of(sku))
        photos.append({"sku": sku, "nombre": name, **photo})
        if len(photos) == MAX_REPLY_PHOTOS:
            break
    return photos
