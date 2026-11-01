"""La foto que manda el cliente: se valida, se limpia y se reduce antes de mirarla.

Llega como ``data:image/...;base64,...`` (o el base64 solo). Antes de cualquier otra cosa:

- se rechaza lo que no sea JPEG, PNG o WebP, lo que pese más de ``MAX_PHOTO_BYTES`` y lo que tenga más de
  ``MAX_PHOTO_PIXELS`` (una imagen pequeña en bytes puede descomprimirse en gigas);
- se vuelve a guardar como JPEG sin metadatos: las fotos del celular traen EXIF con la ubicación, un dato personal;
- se reduce a ``VISION_SIDE`` px de lado mayor: los tokens de una imagen crecen con su resolución, y para
  reconocer un tubo o un martillo basta con poca;
- se calcula su huella (``dhash``), que compara la foto con las del catálogo sin llamar a Grok.

Nunca se descarga una imagen por URL: el servidor no sale a internet por lo que mande el cliente.
"""

import base64
import binascii
from dataclasses import dataclass
from io import BytesIO
import re

from PIL import Image, UnidentifiedImageError

from asistendero.tienda.catalogo.product_photos import dhash

MAX_PHOTO_BYTES = 1_500_000
MAX_PHOTO_PIXELS = 4096 * 4096
# Lo que el navegador manda ya reducido a 1024 px en JPEG; el base64 pesa 4/3 de los bytes.
MAX_PHOTO_CHARS = MAX_PHOTO_BYTES * 4 // 3 + 64
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
VISION_SIDE = 512
JPEG_QUALITY = 80
DATA_URI = re.compile(r"^data:image/(?:jpeg|jpg|png|webp);base64,(?P<data>[A-Za-z0-9+/=\s]+)$", re.I)
RAW_BASE64 = re.compile(r"^[A-Za-z0-9+/=\s]+$")


class PhotoRejected(ValueError):
    """La foto no se puede usar; ``code`` es estable y el mensaje dice qué hacer."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Photo:
    jpeg: bytes
    fingerprint: str
    width: int
    height: int

    def data_uri(self) -> str:
        return "data:image/jpeg;base64," + base64.b64encode(self.jpeg).decode("ascii")


def _decode(data: str) -> bytes:
    if not isinstance(data, str) or len(data) > MAX_PHOTO_CHARS:
        raise PhotoRejected("PHOTO_TOO_LARGE", "La foto pesa demasiado: mándala más pequeña (menos de 1,5 MB).")
    match = DATA_URI.match(data.strip())
    encoded = match.group("data") if match else data.strip()
    if not match and not RAW_BASE64.match(encoded):
        raise PhotoRejected("PHOTO_FORMAT", "Solo recibo fotos JPEG, PNG o WebP adjuntas, no enlaces.")
    try:
        raw = base64.b64decode(re.sub(r"\s+", "", encoded), validate=True)
    except (binascii.Error, ValueError):
        raise PhotoRejected("PHOTO_UNREADABLE", "No pude abrir la foto. Intenta adjuntarla de nuevo.") from None
    if len(raw) > MAX_PHOTO_BYTES:
        raise PhotoRejected("PHOTO_TOO_LARGE", "La foto pesa demasiado: mándala más pequeña (menos de 1,5 MB).")
    return raw


def read_photo(data: str) -> Photo:
    """La foto lista para mirar, o ``PhotoRejected`` con un código estable."""
    raw = _decode(data)
    try:
        image = Image.open(BytesIO(raw))
        if image.format not in ALLOWED_FORMATS:
            raise PhotoRejected("PHOTO_FORMAT", "Solo recibo fotos JPEG, PNG o WebP.")
        # El tamaño se lee del encabezado, antes de descomprimir los píxeles.
        if image.width * image.height > MAX_PHOTO_PIXELS:
            raise PhotoRejected("PHOTO_TOO_LARGE", "La foto tiene demasiados píxeles: mándala más pequeña.")
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise PhotoRejected("PHOTO_UNREADABLE", "No pude abrir la foto. Intenta adjuntarla de nuevo.") from None
    image = image.convert("RGB")
    image.thumbnail((VISION_SIDE, VISION_SIDE), Image.Resampling.LANCZOS)
    buffer = BytesIO()
    # Un JPEG nuevo, sin exif ni perfil: solo los píxeles.
    image.save(buffer, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return Photo(jpeg=buffer.getvalue(), fingerprint=dhash(image), width=image.width, height=image.height)
