"""Fotos de referencia del catálogo: una por familia de producto, con su licencia y su huella perceptual.

El catálogo es ficticio; las fotos son ilustrativas del tipo de producto (un martillo, un bulto de cemento), no del
producto de una marca. Vienen de Wikimedia Commons con licencia libre (``tools/fotos/descargar_fotos.py``) y su
autor, licencia y fuente quedan en ``fotos.json`` y en ``datos/fotos/CREDITOS.md``.

Una familia es el prefijo del SKU (``MAR`` de ``MAR-20``): las variantes de un martillo se ven iguales. Cada foto
guarda una huella de 64 bits (diferencia de brillo entre vecinos, «dHash»): si el cliente manda una foto que se
parece a una del catálogo, se reconoce la familia sin llamar a Grok. La huella no distingue medidas: la medida
siempre se pregunta o la dice el cliente.
"""

from functools import lru_cache
import json
from pathlib import Path

from PIL import Image

PHOTOS_DIR = Path(__file__).resolve().parents[2] / "datos" / "fotos"
MANIFEST = PHOTOS_DIR / "fotos.json"
PHOTO_ROUTE = "/fotos/"
HASH_BITS = 64
# Distancia de Hamming máxima entre huellas para dar por hecho que es la misma foto (recortada, comprimida o con
# otro tamaño). Con 64 bits, dos fotos distintas del catálogo quedan a más de 20; 10 deja margen sin confundirlas.
SAME_PHOTO_DISTANCE = 10


def dhash(image: Image.Image) -> str:
    """Huella de 64 bits en hexadecimal: 9×8 en grises, un bit por cada par de vecinos que se oscurece."""
    small = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    # En escala de grises cada píxel es un byte (getdata queda obsoleto en Pillow 14).
    pixels = small.tobytes()
    bits = 0
    for row in range(8):
        for column in range(8):
            left, right = pixels[row * 9 + column], pixels[row * 9 + column + 1]
            bits = (bits << 1) | (left > right)
    return f"{bits:016x}"


def distance(first: str, second: str) -> int:
    return bin(int(first, 16) ^ int(second, 16)).count("1")


@lru_cache(maxsize=1)
def manifest() -> dict[str, dict]:
    """Familia → foto. Sin el archivo no hay fotos: el agente responde igual, sin imágenes."""
    if not MANIFEST.is_file():
        return {}
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def family_of(sku: str) -> str:
    return sku.split("-", 1)[0].upper()


def photo_of(sku: str) -> dict | None:
    """La referencia compacta de la foto de un SKU: lo único que viaja al cliente, nunca los bytes."""
    entry = manifest().get(family_of(sku))
    if entry is None:
        return None
    return {"foto": family_of(sku), "url": PHOTO_ROUTE + entry["archivo"], "credito": entry["credito"]}


def photo_file(name: str) -> Path | None:
    """El archivo de una foto del manifiesto por su nombre; None si no está (nada fuera de la carpeta)."""
    known = {entry["archivo"] for entry in manifest().values()}
    return PHOTOS_DIR / name if name in known else None


def closest_family(fingerprint: str, families: set[str] | None = None) -> tuple[str, int] | None:
    """La familia cuya foto se parece a la huella dada, si está a ``SAME_PHOTO_DISTANCE`` o menos."""
    best = None
    for family, entry in manifest().items():
        if families is not None and family not in families:
            continue
        gap = distance(fingerprint, entry["huella"])
        if gap <= SAME_PHOTO_DISTANCE and (best is None or gap < best[1]):
            best = (family, gap)
    return best
