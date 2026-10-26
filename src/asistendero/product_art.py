"""Imagen representativa de un producto del catálogo: un pictograma SVG generado, sin fotos ni marcas.

El catálogo es ficticio y no tiene fotos; una foto de internet sería de un producto real y de una marca. Por eso
cada producto se dibuja con una forma genérica elegida por las palabras de su nombre (tubo, saco, martillo…), con
el color que diga el nombre o la variante (pintura beige, cable rojo) y un fondo suave propio de su categoría.

El SVG es autocontenido y determinista: sin scripts, sin enlaces, sin imágenes externas y sin texto. El nombre solo
sirve para elegir la forma y el tono; nunca se copia al SVG, así que no hay nada del catálogo que escapar. Con
``default-src 'self'`` el panel no puede usar un ``data:``; debe servirlo desde una ruta propia como
``image/svg+xml`` o insertarlo como nodo, nunca con ``innerHTML``.
"""

import hashlib
import re

from asistendero.product_art_shapes import (AMBER, GLASS, INK, KRAFT, PAPER, SHAPES as MATERIAL_SHAPES, STEEL,
                                            STEEL_DARK, WATER, WOOD)
from asistendero.product_art_tools import BRASS, COPPER, SHAPES as TOOL_SHAPES
from asistendero.validation import normalize_text


SHAPES = {**MATERIAL_SHAPES, **TOOL_SHAPES}
ART_KINDS = tuple(sorted(SHAPES))

# Tono de cada forma cuando el nombre no trae un color: el del material de verdad, no el de una marca.
DEFAULT_TINTS = {
    "tubo": "#EEF1F0", "accesorio": "#EEF1F0", "grifo": AMBER, "manguera": "#5E9E6E", "ducha": PAPER,
    "rejilla": STEEL, "saco": AMBER, "arena": "#E3C98F", "ladrillo": "#C8664A", "bloque": "#A9ADA8",
    "varilla": STEEL_DARK, "malla": STEEL_DARK, "teja": STEEL, "galon": AMBER, "frasco": "#8FB9D6",
    "aerosol": "#E9EEF0", "brocha": AMBER, "rodillo": AMBER, "cinta": "#E9D9A6", "cable": "#2D3438",
    "interruptor": "#E6EAEC", "toma": "#E6EAEC", "caja": "#F0A04B", "bombillo": GLASS,
    "reflector": GLASS, "extension": "#E6EAEC", "breaker": AMBER, "madera": WOOD, "plastico": "#2D3438",
    "paquete": KRAFT,
    "tornillo": STEEL, "puntilla": STEEL, "tuerca": STEEL, "arandela": STEEL, "martillo": STEEL,
    "alicate": AMBER, "destornillador": AMBER, "llave": STEEL, "allen": STEEL_DARK, "flexometro": AMBER,
    "nivel": AMBER, "serrucho": STEEL, "segueta": "#3E7CA6", "pala": STEEL_DARK, "palustre": STEEL,
    "llana": STEEL, "espatula": STEEL, "carretilla": "#4F8A5B", "lija": "#C9A66B", "disco": "#55636B",
    "broca": AMBER, "candado": BRASS, "cerradura": BRASS, "pasador": STEEL, "bisagra": COPPER,
    "cadena": STEEL, "silicona": PAPER, "escoba": "#E7C46A", "balde": WATER, "guantes": "#D6AE77",
    "gafas": "#BFDCEB", "casco": "#F2C94C", "tapabocas": PAPER, "botas": "#33414A",
    "chaleco": "#EE8A3A",
}

# Palabras del nombre que eligen la forma, en orden: gana la primera regla que coincide. El orden importa donde
# dos reglas comparten palabra: «llave terminal» es un grifo antes de ser una llave, «llave para tubo» es una
# llave antes de ser un tubo y el «pegante para cerámica» es un saco, no un frasco.
RULES = (
    ("grifo", ("llave terminal", "grifo", "registro", "valvula")),
    ("allen", ("allen",)),
    ("llave", ("llave", "llaves")),
    ("manguera", ("manguera",)),
    ("ducha", ("ducha", "aspersor")),
    ("cinta", ("cinta",)),
    ("rejilla", ("rejilla",)),
    ("accesorio", ("codo", "tee", "union", "adaptador", "tapon", "reduccion", "yee", "sifon")),
    ("tubo", ("tubo",)),
    ("arena", ("arena", "gravilla")),
    ("saco", ("cemento", "mortero", "cal", "yeso", "ceramica", "boquilla")),
    ("ladrillo", ("ladrillo",)), ("bloque", ("bloque",)),
    ("varilla", ("varilla", "angulo")), ("malla", ("malla",)), ("teja", ("teja",)),
    ("cable", ("cable", "alambre")),
    ("tornillo", ("tornillo", "perno", "chazo")), ("puntilla", ("puntilla", "grapa")),
    ("tuerca", ("tuerca",)), ("arandela", ("arandela",)),
    ("martillo", ("martillo", "maceta")), ("alicate", ("alicate", "pinza", "cortafrio", "tijera")),
    ("destornillador", ("destornillador",)), ("flexometro", ("flexometro",)), ("nivel", ("nivel",)),
    ("serrucho", ("serrucho",)), ("segueta", ("segueta",)), ("pala", ("pala", "pica")),
    ("palustre", ("palustre",)), ("llana", ("llana",)), ("espatula", ("espatula",)),
    ("carretilla", ("carretilla",)), ("brocha", ("brocha",)), ("rodillo", ("rodillo", "bandeja")),
    ("silicona", ("silicona",)), ("aerosol", ("espuma",)),
    ("frasco", ("soldadura", "limpiador", "thinner", "varsol", "pegante", "masilla")),
    ("galon", ("pintura", "esmalte", "anticorrosivo", "sellador", "estuco", "impermeabilizante")),
    ("lija", ("lija",)), ("disco", ("disco",)), ("broca", ("broca",)),
    ("interruptor", ("interruptor",)), ("toma", ("toma",)), ("caja", ("caja",)),
    ("reflector", ("reflector",)), ("bombillo", ("bombillo", "plafon")), ("breaker", ("breaker",)),
    ("extension", ("extension", "multitoma")),
    ("candado", ("candado",)), ("cerradura", ("cerradura",)), ("pasador", ("pasador",)),
    ("bisagra", ("bisagra",)), ("cadena", ("cadena",)),
    ("escoba", ("escoba", "recogedor", "trapero")), ("balde", ("balde",)),
    ("guantes", ("guantes",)), ("gafas", ("gafas",)), ("casco", ("casco",)), ("tapabocas", ("tapabocas",)),
    ("botas", ("botas",)), ("chaleco", ("chaleco",)),
    ("madera", ("triplex", "liston")), ("plastico", ("plastico",)),
)

# Forma de respaldo cuando ninguna palabra coincide: la más típica de la categoría, o una caja si es nueva.
CATEGORY_KINDS = {
    "Plomería": "accesorio", "Obra gris": "saco", "Tornillería y fijación": "tornillo",
    "Herramientas manuales": "llave", "Pinturas y acabados": "galon", "Abrasivos y corte": "lija",
    "Eléctricos": "cable", "Cerrajería": "candado", "Adhesivos y sellantes": "frasco", "Jardín y aseo": "balde",
    "Seguridad industrial": "casco", "Maderas": "madera",
}
FALLBACK_KIND = "paquete"
# Los textos llegan del catálogo, que ya limita el nombre a 80 caracteres (inventory.py); esto es solo el tope propio.
MAX_ART_TEXT = 200

# Fondos suaves por categoría: claros para que el contorno petróleo contraste, y opacos para que el pictograma se
# vea igual sobre la crema del panel y sobre un fondo oscuro.
CATEGORY_COLORS = {
    "Plomería": "#DCEBF2", "Obra gris": "#E8E3DA", "Tornillería y fijación": "#E2E7EA",
    "Herramientas manuales": "#F7E6C8", "Pinturas y acabados": "#F4DEE0", "Abrasivos y corte": "#EFE5D2",
    "Eléctricos": "#F8EDB8", "Cerrajería": "#F0E2CC", "Adhesivos y sellantes": "#E5E1F1", "Jardín y aseo": "#DCEEDD",
    "Seguridad industrial": "#FBE2CC", "Maderas": "#EEDFC6",
}
# Para una categoría que cree el tendero: un tono de esta lista elegido por un resumen estable del nombre.
SPARE_COLORS = ("#E0ECE6", "#ECE4F2", "#F6E9D6", "#DDE8F3", "#F3E3E8", "#E9EED9")

# Colores que el nombre o la variante dicen de forma explícita. «verde limón» va antes que «verde».
COLOR_WORDS = (
    ("verde limon", "#C5DD4A"), ("blanco", "#F7F4EC"), ("blanca", "#F7F4EC"), ("beige", "#E2CBA0"),
    ("gris", "#9AA6AB"), ("amarillo", "#F2C94C"), ("amarilla", "#F2C94C"), ("azul", "#3E7CA6"),
    ("verde", "#4F8A5B"), ("rojo", "#C9573F"), ("roja", "#C9573F"), ("negro", "#2D3438"), ("negra", "#2D3438"),
    ("marfil", "#F0E4C4"), ("naranja", "#EE8A3A"), ("transparente", "#E3EEF2"), ("calida", "#FFD27A"),
    ("oscuro", "#4A5A63"),
)
# Tonos del material que dependen de una palabra y no son un color: el conduit verde, el CPVC crema, la lija de agua.
MATERIAL_WORDS = {
    "tubo": (("conduit", "#7FB08A"), ("cpvc", "#E5D3A1")),
    "manguera": (("abasto", STEEL),),
    "saco": (("cal", "#F7F4EC"), ("yeso", "#F7F4EC")),
    "arena": (("gravilla", "#B4AFA6"),),
    "teja": (("plastica", "#CDE8DE"),),
    "lija": (("agua", "#55636B"), ("metal", "#7E8FA6")),
    "disco": (("diamantado", STEEL),),
    "broca": (("metal", STEEL), ("madera", WOOD)),
    "guantes": (("nitrilo", "#5B8FD1"), ("caucho", "#E9C13B")),
    "frasco": (("thinner", "#BFD9E6"), ("varsol", "#BFD9E6"), ("contacto", AMBER)),
}


def _words(*parts: str) -> str:
    """Palabras normalizadas entre espacios, para buscar palabras o frases enteras («cal» no es «calibre»)."""
    return f" {' '.join(re.findall(r'[a-z0-9]+', normalize_text(' '.join(parts))))} "


def _has(text: str, phrase: str) -> bool:
    return f" {phrase} " in text


def art_kind(name: str, category: str = "") -> str:
    """Forma del pictograma según el nombre; si nada coincide, la de la categoría; si no, una caja genérica."""
    text = _words(name)
    for kind, phrases in RULES:
        if any(_has(text, phrase) for phrase in phrases):
            return kind
    return CATEGORY_KINDS.get(category, FALLBACK_KIND)


def category_color(category: str) -> str:
    """Fondo suave de la categoría; una categoría nueva recibe siempre el mismo tono de reserva."""
    if category in CATEGORY_COLORS:
        return CATEGORY_COLORS[category]
    digest = hashlib.sha256(normalize_text(category).encode()).digest()
    return SPARE_COLORS[digest[0] % len(SPARE_COLORS)]


def art_tint(kind: str, name: str, variant: str) -> str:
    """Tono de la forma: primero el del material («cpvc», «nitrilo»), luego un color dicho, si no el de la forma."""
    text = _words(name, variant)
    for phrase, color in MATERIAL_WORDS.get(kind, ()):
        if _has(text, phrase):
            return color
    for phrase, color in COLOR_WORDS:
        if _has(text, phrase):
            return color
    return DEFAULT_TINTS[kind]


def product_svg(name: str, variant: str, category: str) -> str:
    """SVG de 96 x 96 con el pictograma del producto sobre el fondo de su categoría; mismo dato, mismo SVG."""
    if not all(isinstance(part, str) and len(part) <= MAX_ART_TEXT for part in (name, variant, category)):
        raise ValueError(f"Nombre, variante y categoría son textos de hasta {MAX_ART_TEXT} caracteres.")
    kind = art_kind(name, category)
    body = SHAPES[kind](art_tint(kind, name, variant))
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" width="96" height="96" aria-hidden="true">'
            f'<rect width="96" height="96" rx="22" fill="{category_color(category)}"/>'
            f'<ellipse cx="48" cy="84" rx="28" ry="4" fill="{INK}" fill-opacity=".10"/>'
            f'<g fill="none" stroke="{INK}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">'
            f"{body}</g></svg>")
