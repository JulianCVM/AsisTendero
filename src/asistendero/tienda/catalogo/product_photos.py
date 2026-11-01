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
# Distancia de Hamming máxima entre huellas para dar por hecho que es la misma foto. Medido con las 184 fotos del
# 01-11-2026: recomprimida o con la mitad o el doble de tamaño se reconocen las 184; con un 10 % más de brillo, 181;
# ninguna se confunde con otra familia, y las dos fotos más parecidas de familias distintas están a 9. Un recorte se
# aleja rápido (con 5 % de borde, 81 de 184): entonces no hay atajo y la foto va a Grok.
SAME_PHOTO_DISTANCE = 8


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
    """La familia cuya foto se parece a la huella dada, si está a ``SAME_PHOTO_DISTANCE`` o menos.

    Si dos familias quedan a esa distancia, la huella no decide entre ellas: None, y la foto va a Grok. Elegir la
    más cercana sería tomar una opción parecida por la pedida.
    """
    near = []
    for family, entry in manifest().items():
        if families is not None and family not in families:
            continue
        gap = distance(fingerprint, entry["huella"])
        if gap <= SAME_PHOTO_DISTANCE:
            near.append((family, gap))
    return near[0] if len(near) == 1 else None


def fingerprint_report(fingerprint: str, families: set[str] | None = None) -> dict:
    """Cómo salió el cotejo de la huella, para la traza: cuántas fotos se compararon y a qué distancia quedó la más
    cercana. ``familia`` es la que reconoció ``closest_family`` (None si ninguna o si hubo empate)."""
    gaps = [distance(fingerprint, entry["huella"]) for family, entry in manifest().items()
            if families is None or family in families]
    found = closest_family(fingerprint, families)
    return {"fotos": len(gaps), "mas_cercana": min(gaps) if gaps else None, "umbral": SAME_PHOTO_DISTANCE,
            "familia": found[0] if found else None}
