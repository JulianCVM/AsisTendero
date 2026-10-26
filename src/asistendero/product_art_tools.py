"""Pictogramas de herramientas, tornillería, abrasivos, cerrajería, aseo y seguridad industrial.

Mismo contrato que ``product_art_shapes``: cada forma recibe un tono y devuelve fragmentos SVG sin texto.
"""

from asistendero.product_art_shapes import (AMBER, INK, KRAFT, PAPER, STEEL, STEEL_DARK, WOOD, ring, shade, teeth,
                                            thick, turned)


BRASS = "#D9A441"
COPPER = "#D08A4C"


def screw(t: str) -> str:
    threads = "".join(f"M41 {y}l14-4" for y in (36, 44, 52, 60))
    return (f'<path d="M42 26h12v38l-6 12-6-12z" fill="{t}"/>'
            f'<path d="{threads}" stroke-width="2.5"/>'
            f'<rect x="32" y="16" width="32" height="10" rx="4" fill="{t}"/>')


def nail(t: str) -> str:
    return turned(-30, f'<path d="M45 26h6v42l-3 10-3-10z" fill="{t}"/>'
                       f'<rect x="34" y="18" width="28" height="8" rx="3" fill="{t}"/>')


def nut(t: str) -> str:
    hexagon = "M72 48L60 68.8H36L24 48L36 27.2H60z"
    hole = "M57 48a9 9 0 1 0-18 0a9 9 0 1 0 18 0z"
    return f'<path d="{hexagon}{hole}" fill="{t}" fill-rule="evenodd"/>' + shade("M60 27.2L72 48 60 68.8H52z")


def washer(t: str) -> str:
    return ring(48, 48, 26, 10, t)


def hammer(t: str) -> str:
    return turned(32, f'<rect x="43" y="34" width="10" height="48" rx="5" fill="{WOOD}"/>'
                      f'<path d="M34 20H66v14H34C28 34 22 38 18 44c0-14 8-24 16-24z" fill="{t}"/>'
                      f'<rect x="64" y="17" width="10" height="20" rx="2" fill="{t}"/>')


def pliers(t: str) -> str:
    return (thick("M44 52L32 82", t, 7) + thick("M52 52L64 82", t, 7)
            + f'<path d="M38 52L44 18q4-6 8 0l6 34z" fill="{STEEL}"/>'
            '<path d="M48 20v26" stroke-width="2"/>'
            f'<circle cx="48" cy="50" r="5" fill="{STEEL_DARK}"/>')


def screwdriver(t: str) -> str:
    return turned(40, f'<rect x="45.5" y="14" width="5" height="40" fill="{STEEL}"/>'
                      f'<path d="M45.5 14l1-4h3l1 4" fill="{STEEL}"/>'
                      f'<rect x="39" y="50" width="18" height="32" rx="8" fill="{t}"/>'
                      '<path d="M45 58v16M51 58v16" stroke-width="2"/>')


def wrench(t: str) -> str:
    head = "M44 11.6V22H52V11.6A13 13 0 1 1 44 11.6z"
    return turned(40, f'<rect x="43" y="30" width="10" height="52" rx="5" fill="{t}"/>'
                      f'<path d="{head}" fill="{t}"/><circle cx="48" cy="74" r="3" fill="{INK}"/>')


def hex_key(t: str) -> str:
    return (thick("M26 24h26v52", t, 8, "butt") + shade("M48 28h3v48h-3z")
            + f'<path d="M48 76l4 4" stroke="{INK}" stroke-width="2"/>')


def tape_measure(t: str) -> str:
    ticks = "".join(f"M{x} 58v4" for x in (64, 70, 76))
    return (f'<path d="M58 57h24v10H58z" fill="{PAPER}"/><path d="{ticks}" stroke-width="2"/>'
            '<path d="M82 54v16" stroke-width="3"/>'
            f'<rect x="14" y="26" width="46" height="46" rx="11" fill="{t}"/>'
            f'<circle cx="37" cy="49" r="11" fill="{PAPER}"/><circle cx="37" cy="49" r="3" fill="{INK}"/>')


def level(t: str) -> str:
    return (f'<rect x="10" y="38" width="76" height="20" rx="4" fill="{t}"/>'
            + shade("M12 52h72v4H12z")
            + '<rect x="37" y="42" width="22" height="12" rx="6" fill="#BFE3B4"/>'
            f'<circle cx="50" cy="48" r="3" fill="{PAPER}" stroke="none"/>'
            '<path d="M44 42v12M52 42v12" stroke-width="2"/>')


def handsaw(t: str) -> str:
    return (f'<path d="M32 30L86 42v12L32 64z" fill="{t}"/>' + teeth(34, 84, 63)
            + f'<path d="M12 28h22v40H16a6 6 0 0 1-6-6V34a6 6 0 0 1 6-6z'
            'M17 38v18a3 3 0 0 0 3 3h7V35h-7a3 3 0 0 0-3 3z" fill="' + WOOD + '" fill-rule="evenodd"/>')


def hacksaw(t: str) -> str:
    return (thick("M24 62V30H76V62", t, 5) + '<path d="M24 62H76" stroke="' + STEEL_DARK + '" stroke-width="3"/>'
            + teeth(26, 74, 63) + f'<rect x="12" y="56" width="16" height="26" rx="6" fill="{AMBER}"/>')


def shovel(t: str) -> str:
    return turned(-20, thick("M48 14v40", WOOD, 5) + thick("M40 14h16", WOOD, 5)
                  + f'<path d="M34 50h28v18a10 10 0 0 1-10 10h-8a10 10 0 0 1-10-10z" fill="{t}"/>'
                  + shade("M52 52h8v16a8 8 0 0 1-8 8z"))


def trowel(t: str) -> str:
    return (f'<rect x="43" y="10" width="10" height="24" rx="5" fill="{WOOD}"/>'
            '<path d="M48 34v10" stroke-width="4"/>'
            f'<path d="M48 44L72 62Q48 88 24 62z" fill="{t}"/>' + shade("M48 46L70 62Q60 74 48 78z"))


def float_trowel(t: str) -> str:
    return (f'<rect x="12" y="54" width="72" height="14" rx="3" fill="{t}"/>' + shade("M14 62h68v4H14z")
            + '<path d="M36 54V44M60 54V44" stroke-width="4"/>'
            f'<rect x="28" y="32" width="40" height="12" rx="6" fill="{WOOD}"/>')


def putty_knife(t: str) -> str:
    return (f'<rect x="41" y="10" width="14" height="30" rx="6" fill="{WOOD}"/>'
            f'<rect x="38" y="38" width="20" height="8" rx="2" fill="{STEEL_DARK}"/>'
            f'<path d="M40 46h16l14 32H26z" fill="{t}"/>')


def wheelbarrow(t: str) -> str:
    return ('<path d="M28 70L54 58M52 58l6 16M60 46l26-8" stroke-width="4"/>'
            f'<path d="M12 36h56l-8 22H26z" fill="{t}"/>' + shade("M50 38h16l-7 18h-9z")
            + f'<circle cx="28" cy="70" r="10" fill="{INK}"/><circle cx="28" cy="70" r="4" fill="{STEEL}"/>')


def sandpaper(t: str) -> str:
    grains = "".join(f'<circle cx="{x}" cy="{y}" r="1.6" fill="{PAPER}" fill-opacity=".6" stroke="none"/>'
                     for x in (30, 42, 54, 66) for y in (30, 44, 58))
    return turned(-12, f'<path d="M22 18h52v46L60 78H22z" fill="{t}"/>{grains}'
                       f'<path d="M74 64L60 78V64z" fill="{KRAFT}"/>')


def disc(t: str) -> str:
    return (ring(48, 48, 30, 5, t) + ring(48, 48, 14, 5, AMBER)
            + '<path d="M48 18v6M78 48h-6M48 78v-6M18 48h6" stroke-width="2" stroke-opacity=".5"/>')


def drill_bit(t: str) -> str:
    flutes = "".join(f"M43 {y}l10-5" for y in (44, 52, 60, 68))
    return turned(35, f'<rect x="43" y="10" width="10" height="28" rx="2" fill="{STEEL}"/>'
                      f'<path d="M43 38h10v32l-5 10-5-10z" fill="{STEEL_DARK}"/>'
                      f'<path d="{flutes}" stroke-width="2"/><path d="M43 70h10l-5 10z" fill="{t}"/>')


def padlock(t: str) -> str:
    return (thick("M34 44V32a14 14 0 0 1 28 0v12", STEEL, 5)
            + f'<rect x="22" y="42" width="52" height="38" rx="7" fill="{t}"/>' + shade("M60 44h12v34H60z")
            + f'<circle cx="48" cy="57" r="4.5" fill="{INK}"/><path d="M46 59h4l1 9h-6z" fill="{INK}"/>')


def doorknob(t: str) -> str:
    return (f'<rect x="62" y="26" width="14" height="44" rx="3" fill="{STEEL}"/>'
            f'<rect x="56" y="42" width="10" height="12" rx="2" fill="{STEEL_DARK}"/>'
            f'<circle cx="38" cy="48" r="20" fill="{t}"/><circle cx="38" cy="48" r="11" fill="#EBC877"/>'
            '<path d="M38 44v8" stroke-width="3"/>')


def latch(t: str) -> str:
    return (f'<rect x="14" y="32" width="46" height="24" rx="4" fill="{t}"/>'
            + thick("M24 44H80", STEEL, 4)
            + f'<circle cx="42" cy="32" r="6" fill="{AMBER}"/><path d="M42 38v6" stroke-width="4"/>'
            f'<rect x="72" y="34" width="10" height="28" rx="3" fill="{t}"/>')


def hinge(t: str) -> str:
    holes = "".join(f'<circle cx="{x}" cy="{y}" r="3" fill="{INK}"/>' for x in (30, 66) for y in (36, 60))
    return (f'<rect x="18" y="24" width="28" height="48" rx="3" fill="{t}"/>'
            f'<rect x="50" y="24" width="28" height="48" rx="3" fill="{t}"/>'
            f'<rect x="43" y="20" width="10" height="56" rx="5" fill="#E8A86E"/>{holes}')


def chain(t: str) -> str:
    links = "".join(f'<ellipse cx="{c}" cy="{96 - c}" rx="13" ry="7" transform="rotate(-45 {c} {96 - c})" '
                    f'stroke="{INK}" stroke-width="9"/><ellipse cx="{c}" cy="{96 - c}" rx="13" ry="7" '
                    f'transform="rotate(-45 {c} {96 - c})" stroke="{t}" stroke-width="4"/>' for c in (28, 52, 76))
    return links + thick("M35 61L45 51", t, 4) + thick("M59 37L69 27", t, 4)


def cartridge(t: str) -> str:
    return turned(30, f'<path d="M45 30l2-18h2l2 18z" fill="{PAPER}"/>'
                      f'<rect x="37" y="30" width="22" height="46" rx="4" fill="{t}"/>'
                      + shade("M51 32h6v42h-6z")
                      + f'<rect x="35" y="72" width="26" height="8" rx="2" fill="{STEEL}"/>')


def broom(t: str) -> str:
    bristles = "".join(f"M{x} 66v10" for x in (34, 42, 50, 58))
    return turned(18, thick("M48 10v42", WOOD, 4)
                  + f'<rect x="30" y="50" width="36" height="10" rx="3" fill="{AMBER}"/>'
                  f'<path d="M30 60h36l6 20H24z" fill="{t}"/><path d="{bristles}" stroke-width="2"/>')


def bucket(t: str) -> str:
    return ('<path d="M26 34Q48 6 70 34" stroke-width="3"/>'
            f'<path d="M26 36h44l-5 38a4 4 0 0 1-4 4H35a4 4 0 0 1-4-4z" fill="{t}"/>'
            + shade("M58 38h11l-5 36a3 3 0 0 1-3 3h-3z")
            + f'<rect x="22" y="30" width="52" height="8" rx="3" fill="{t}"/>')


def glove(t: str) -> str:
    fingers = "".join(f'<rect x="{x}" y="{y}" width="9" height="{h}" rx="4.5" fill="{t}"/>'
                      for x, y, h in ((33, 22, 30), (42, 16, 34), (51, 18, 32), (60, 24, 26)))
    return (fingers + f'<rect x="18" y="40" width="9" height="26" rx="4.5" transform="rotate(-35 22 53)" fill="{t}"/>'
            f'<rect x="31" y="40" width="38" height="32" rx="9" fill="{t}"/>'
            f'<rect x="32" y="70" width="36" height="12" rx="3" fill="{t}"/>' + shade("M34 72h32v8H34z"))


def goggles(t: str) -> str:
    return ('<path d="M14 46l-4-6M82 46l4-6M44 47q4-5 8 0" stroke-width="3"/>'
            f'<rect x="14" y="36" width="30" height="24" rx="11" fill="{t}"/>'
            f'<rect x="52" y="36" width="30" height="24" rx="11" fill="{t}"/>'
            '<path d="M21 43l6-3M59 43l6-3" stroke="' + PAPER + '" stroke-width="3"/>')


def helmet(t: str) -> str:
    return (f'<path d="M20 64a28 28 0 0 1 56 0z" fill="{t}"/>' + shade("M42 37h12v27H42z", ".12")
            + f'<rect x="12" y="62" width="72" height="10" rx="5" fill="{t}"/>')


def mask(t: str) -> str:
    return ('<path d="M26 40q-14 8 0 18M70 40q14 8 0 18" stroke-width="3"/>'
            f'<path d="M26 36q22-10 44 0v22q-22 16-44 0z" fill="{t}"/>'
            '<path d="M30 46h36M30 54h36" stroke-width="2" stroke-opacity=".6"/>'
            f'<circle cx="60" cy="58" r="5" fill="{STEEL}"/>')


def boot(t: str) -> str:
    return (f'<path d="M28 14h26v40l20 10q8 4 8 12v4H28z" fill="{t}"/>'
            f'<rect x="26" y="14" width="30" height="8" rx="2" fill="{AMBER}"/>'
            f'<rect x="26" y="78" width="58" height="6" rx="3" fill="{INK}"/>')


def vest(t: str) -> str:
    stripes = f'<path d="M22 58h22M52 58h22M22 68h22M52 68h22" stroke="{STEEL}" stroke-width="4"/>'
    return (f'<path d="M32 16h8l6 22v42H20V34q0-8 6-12z" fill="{t}"/>'
            f'<path d="M64 16h-8l-6 22v42h26V34q0-8-6-12z" fill="{t}"/>{stripes}')


SHAPES = {
    "tornillo": screw, "puntilla": nail, "tuerca": nut, "arandela": washer, "martillo": hammer, "alicate": pliers,
    "destornillador": screwdriver, "llave": wrench, "allen": hex_key, "flexometro": tape_measure, "nivel": level,
    "serrucho": handsaw, "segueta": hacksaw, "pala": shovel, "palustre": trowel, "llana": float_trowel,
    "espatula": putty_knife, "carretilla": wheelbarrow, "lija": sandpaper, "disco": disc, "broca": drill_bit,
    "candado": padlock, "cerradura": doorknob, "pasador": latch, "bisagra": hinge, "cadena": chain,
    "silicona": cartridge, "escoba": broom, "balde": bucket, "guantes": glove, "gafas": goggles, "casco": helmet,
    "tapabocas": mask, "botas": boot, "chaleco": vest,
}
