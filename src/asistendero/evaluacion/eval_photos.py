"""Fotos de los casos de evaluación, armadas al correr el caso: el repositorio no guarda fotos nuevas.

Un turno de una conversación puede traer ``foto`` (ver ``eval_sessions.py``), con una de estas formas:

- ``{"catalogo": "MAR"}``: la foto de referencia de esa familia tal cual, como el cliente que reenvía la que le
  mandó la tienda. La huella la reconoce sin llamar a Grok.
- ``{"catalogo": "MAR", "como_cliente": true}``: la misma foto en espejo y con un recorte del 10 %. Es el mismo
  producto, pero la huella ya no lo reconoce y la mira Grok, como una foto tomada por el cliente.
- ``{"patron": true}``: una imagen que no es un producto (un degradado).
- ``{"enlace": "https://…"}``: un enlace en lugar de una foto; el servidor lo rechaza sin descargarlo.

Las fotos derivadas conservan la licencia y el crédito de la original (``datos/fotos/CREDITOS.md``).
"""

import base64
from io import BytesIO

from PIL import Image, ImageOps

from asistendero.tienda.catalogo.product_photos import PHOTOS_DIR, manifest

# Lo que se recorta de cada borde en una foto «del cliente»: basta para que la huella no la reconozca (medido: con
# 5 % ya se pierden 103 de 184) y deja el producto entero en el cuadro.
CUSTOMER_CROP = 0.10


def _data_uri(image: Image.Image) -> str:
    buffer = BytesIO()
    image.convert("RGB").save(buffer, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _as_customer(image: Image.Image) -> Image.Image:
    width, height = image.size
    left, top = round(width * CUSTOMER_CROP), round(height * CUSTOMER_CROP)
    return ImageOps.mirror(image.crop((left, top, width - left, height - top)))


def photo_for(spec: dict) -> str:
    """La foto del turno como la manda el visor (``data:image/jpeg;base64,…``), o el enlace tal cual."""
    if "enlace" in spec:
        return spec["enlace"]
    if spec.get("patron"):
        return _data_uri(Image.linear_gradient("L").resize((320, 240)))
    entry = manifest().get(spec.get("catalogo", ""))
    if entry is None:
        raise ValueError(f"La familia {spec.get('catalogo')!r} no tiene foto en la biblioteca.")
    with Image.open(PHOTOS_DIR / entry["archivo"]) as image:
        image.load()
        return _data_uri(_as_customer(image) if spec.get("como_cliente") else image)
