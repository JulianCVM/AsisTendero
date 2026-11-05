"""Pictogramas de materiales: plomería, obra gris, pinturas, eléctricos y maderas.

Cada forma recibe un tono (``t``) y devuelve fragmentos SVG sobre un lienzo de 96 x 96. El contorno lo pone el
grupo que arma ``product_art.product_svg`` (tinta petróleo, trazo de 3 y extremos redondeados), así que aquí solo
se elige el relleno. Nada de texto: así ningún dato del catálogo llega al SVG y no hay nada que escapar.
"""

INK = "#173B4A"
AMBER = "#E9A23B"
PAPER = "#FFFDF8"
STEEL = "#B7C4CA"
STEEL_DARK = "#7D8F98"
WOOD = "#C98D52"
WOOD_LIGHT = "#E3B77F"
KRAFT = "#E6D3A8"
WATER = "#4E9BC9"
GLASS = "#FFE8A8"


def shade(d: str, opacity: str = ".16") -> str:
    """Sombra translúcida: da el segundo tono sobre cualquier color sin calcular uno nuevo."""
    return f'<path d="{d}" fill="{INK}" fill-opacity="{opacity}" stroke="none"/>'


def thick(d: str, color: str, width: int, cap: str = "round") -> str:
    """Trazo grueso con contorno: primero la tinta, encima el color, para tubos, cables y mangos."""
    return (f'<path d="{d}" stroke="{INK}" stroke-width="{width + 5}" stroke-linecap="{cap}"/>'
            f'<path d="{d}" stroke="{color}" stroke-width="{width}" stroke-linecap="{cap}"/>')


def thick_circle(cx: float, cy: float, r: float, color: str, width: int) -> str:
    return (f'<circle cx="{cx}" cy="{cy}" r="{r}" stroke="{INK}" stroke-width="{width + 5}"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" stroke="{color}" stroke-width="{width}"/>')


def ring(cx: float, cy: float, outer: float, inner: float, fill: str) -> str:
    """Anillo con hueco real (evenodd): el fondo de la categoría se ve a través."""
    def circle(r: float) -> str:
        return f"M{cx - r} {cy}a{r} {r} 0 1 0 {2 * r} 0a{r} {r} 0 1 0 {-2 * r} 0z"
    return f'<path d="{circle(outer)}{circle(inner)}" fill="{fill}" fill-rule="evenodd"/>'


def turned(angle: int, body: str) -> str:
    return f'<g transform="rotate({angle} 48 48)">{body}</g>'


def teeth(x0: int, x1: int, y: int, size: int = 3) -> str:
    """Dientes de sierra en zigzag entre x0 y x1, hacia abajo desde y."""
    steps = "".join(f"l{size / 2:g} {size}l{size / 2:g} -{size}" for _ in range((x1 - x0) // size))
    return f'<path d="M{x0} {y}{steps}" stroke-width="2"/>'


def pipe(t: str) -> str:
    return (f'<rect x="14" y="36" width="58" height="24" rx="3" fill="{t}"/>'
            + shade("M16 51h56v7H16z")
            + f'<ellipse cx="72" cy="48" rx="8" ry="12" fill="{t}"/>'
            f'<ellipse cx="72" cy="48" rx="3.5" ry="6.5" fill="{INK}"/>')


def fitting(t: str) -> str:
    bend = "M26 34h18a12 12 0 0 1 12 12v18"
    return (thick(bend, t, 14, "butt")
            + f'<rect x="14" y="22" width="12" height="24" rx="2" fill="{t}"/>'
            f'<rect x="44" y="64" width="24" height="12" rx="2" fill="{t}"/>'
            + shade("M16 36h8v8h-8zM46 70h20v4H46z"))


def faucet(t: str) -> str:
    return (f'<rect x="14" y="38" width="20" height="12" rx="2" fill="{STEEL}"/>'
            f'<path d="M30 34h26a10 10 0 0 1 10 10v14H56v-6a2 2 0 0 0-2-2H30z" fill="{STEEL}"/>'
            f'<rect x="40" y="24" width="8" height="10" fill="{STEEL_DARK}"/>'
            f'<rect x="28" y="16" width="32" height="9" rx="4.5" fill="{t}"/>'
            f'<path d="M61 64c-3 4-5 7-5 9.5a5 5 0 0 0 10 0c0-2.5-2-5.5-5-9.5z" fill="{WATER}"/>')


def hose(t: str) -> str:
    return (thick_circle(46, 44, 22, t, 8) + thick_circle(46, 44, 10, t, 7)
            + thick("M62 60q8 8 12 14", t, 7)
            + f'<rect x="70" y="70" width="12" height="12" rx="3" fill="{AMBER}"/>')


def shower(t: str) -> str:
    return (thick("M22 16v8a8 8 0 0 0 8 8h24", STEEL, 5)
            + f'<path d="M42 34h32a4 4 0 0 1 4 4v2a4 4 0 0 1-4 4H42a4 4 0 0 1-4-4v-2a4 4 0 0 1 4-4z" fill="{t}"/>'
            f'<path d="M46 52l-3 7M58 52v8M70 52l3 7M44 68l-3 7M58 68v8M72 68l3 7" stroke="{WATER}" '
            'stroke-width="3.5"/>')


def grate(t: str) -> str:
    return (f'<rect x="20" y="20" width="56" height="56" rx="8" fill="{t}"/>'
            f'<path d="M34 32v32M44 32v32M54 32v32M64 32v32" stroke="{INK}" stroke-width="4"/>')


def sack(t: str) -> str:
    return (f'<path d="M30 22h36l4 6H26z" fill="{KRAFT}"/>'
            f'<path d="M26 28h44l4 44a6 6 0 0 1-6 6H28a6 6 0 0 1-6-6z" fill="{KRAFT}"/>'
            + shade("M64 30h5l3 42a4 4 0 0 1-4 4h-4z")
            + f'<rect x="31" y="44" width="34" height="18" rx="3" fill="{t}"/>'
            '<path d="M37 53h22" stroke-width="2.5"/>')


def pile(t: str) -> str:
    stones = ((34, 60), (46, 50), (58, 60), (44, 68), (68, 70), (26, 70), (55, 72), (50, 59))
    dots = "".join(f'<circle cx="{x}" cy="{y}" r="2.6" fill="{INK}" fill-opacity=".35" stroke="none"/>'
                   for x, y in stones)
    return f'<path d="M12 76c6-24 18-36 36-36s30 12 36 36z" fill="{t}"/>{dots}'


def bricks(t: str) -> str:
    return "".join(f'<rect x="{x}" y="{y}" width="30" height="16" rx="2" fill="{t}"/>'
                   for x, y in ((16, 58), (50, 58), (33, 40), (24, 22))) + shade("M18 68h26v4H18zM52 68h26v4H52z")


def block(t: str) -> str:
    return (f'<rect x="16" y="30" width="64" height="36" rx="3" fill="{t}"/>'
            f'<rect x="24" y="38" width="20" height="20" rx="2" fill="{INK}" fill-opacity=".35"/>'
            f'<rect x="52" y="38" width="20" height="20" rx="2" fill="{INK}" fill-opacity=".35"/>')


def rods(t: str) -> str:
    bars = "".join(thick(d, t, 5) for d in ("M14 64L64 18", "M22 72L72 26", "M30 80L80 34"))
    return bars + thick("M38 46l12 12", AMBER, 4)


def mesh(t: str) -> str:
    lines = "".join(f"M{v} 18V78M18 {v}H78" for v in (18, 33, 48, 63, 78))
    return f'<path d="{lines}" stroke="{INK}" stroke-width="6"/><path d="{lines}" stroke="{t}" stroke-width="3"/>'


def roof(t: str) -> str:
    waves = "".join("q6 -8 12 0" for _ in range(6))
    return (f'<path d="M12 40{waves}V70H12z" fill="{t}"/>'
            f'<path d="M24 40V70M36 40V70M48 40V70M60 40V70M72 40V70" stroke="{INK}" stroke-opacity=".35"/>')


def can(t: str) -> str:
    return (f'<path d="M24 30h48v40a6 6 0 0 1-6 6H30a6 6 0 0 1-6-6z" fill="#DDE4E7"/>'
            f'<rect x="24" y="44" width="48" height="20" fill="{t}"/>'
            f'<path d="M28 30Q48 4 68 30" stroke-width="3"/>'
            f'<ellipse cx="48" cy="30" rx="24" ry="6" fill="{STEEL}"/>'
            f'<path d="M58 36v4a3 3 0 0 0 6 0v-6" fill="{t}"/>')


def bottle(t: str) -> str:
    return (f'<rect x="41" y="18" width="14" height="12" rx="2" fill="{AMBER}"/>'
            f'<path d="M34 40q0-10 10-10h8q10 0 10 10v34a6 6 0 0 1-6 6H40a6 6 0 0 1-6-6z" fill="{t}"/>'
            f'<rect x="38" y="48" width="20" height="18" rx="2" fill="{PAPER}"/>'
            '<path d="M42 55h12M42 60h8" stroke-width="2"/>')


def aerosol(t: str) -> str:
    return (f'<rect x="40" y="16" width="16" height="12" rx="3" fill="{AMBER}"/>'
            '<path d="M54 20l14-6" stroke-width="3"/>'
            f'<path d="M34 36q0-8 14-8t14 8v40a4 4 0 0 1-4 4H38a4 4 0 0 1-4-4z" fill="{t}"/>'
            + shade("M54 34h6v42a3 3 0 0 1-3 3h-3z"))


def brush(t: str) -> str:
    return turned(30, f'<rect x="42" y="10" width="12" height="30" rx="6" fill="{WOOD}"/>'
                      f'<rect x="35" y="38" width="26" height="12" rx="2" fill="{STEEL}"/>'
                      f'<path d="M35 50h26v14q-13 8-26 0z" fill="{KRAFT}"/>'
                      f'<path d="M35 60h26v4q-13 8-26 0z" fill="{t}"/>')


def roller(t: str) -> str:
    return (f'<rect x="16" y="18" width="48" height="20" rx="10" fill="{t}"/>'
            + shade("M20 31h40v5H20z")
            + '<path d="M64 28h10v18H48v12" stroke-width="4"/>'
            f'<rect x="42" y="56" width="12" height="26" rx="6" fill="{INK}"/>')


def tape(t: str) -> str:
    return (f'<path d="M66 64l16 10-4 6-16-10z" fill="{t}"/>'
            + ring(46, 46, 26, 13, t) + ring(46, 46, 13, 9, KRAFT))


def coil(t: str) -> str:
    # Un brillo claro sobre cada vuelta: sin él, un cable negro se leía como un disco lleno.
    shine = "".join(f'<circle cx="46" cy="46" r="{r}" stroke="{PAPER}" stroke-opacity=".45" stroke-width="1.5" '
                    f'stroke-dasharray="10 8"/>' for r in (27, 15))
    return (thick_circle(46, 46, 27, t, 5) + thick_circle(46, 46, 15, t, 5) + shine
            + thick("M65 65q8 8 15 5", t, 4) + '<path d="M81 69l5-2" stroke="#C7783E" stroke-width="4"/>')


def switch(t: str) -> str:
    return (f'<rect x="26" y="14" width="44" height="68" rx="8" fill="{PAPER}"/>'
            f'<rect x="37" y="30" width="22" height="36" rx="4" fill="{t}"/>'
            + shade("M39 48h18v16H39z")
            + f'<circle cx="48" cy="21" r="2" fill="{INK}"/><circle cx="48" cy="75" r="2" fill="{INK}"/>')


def outlet(t: str) -> str:
    face = ("<circle cx='48' cy='{y}' r='11' fill='{t}'/>"
            "<path d='M44 {a}v6M52 {a}v6' stroke-width='2.5'/><circle cx='48' cy='{b}' r='1.5' fill='{ink}'/>")
    return (f'<rect x="26" y="12" width="44" height="72" rx="8" fill="{PAPER}"/>'
            + "".join(face.format(y=y, a=y - 6, b=y + 5, t=t, ink=INK) for y in (32, 64)))


def junction(t: str) -> str:
    return (f'<rect x="20" y="24" width="56" height="48" rx="6" fill="{t}"/>'
            f'<rect x="28" y="32" width="40" height="32" rx="3" fill="{PAPER}"/>'
            f'<circle cx="16" cy="48" r="5" fill="{STEEL}"/><circle cx="80" cy="48" r="5" fill="{STEEL}"/>')


def bulb(t: str) -> str:
    rays = "M14 30l-5-3M82 30l5-3M12 46H6M84 46h6M20 16l-4-4M76 16l4-4"
    return (f'<path d="{rays}" stroke="{AMBER}" stroke-width="3"/>'
            f'<path d="M48 14A22 22 0 0 1 62 53v7H34v-7A22 22 0 0 1 48 14z" fill="{t}"/>'
            f'<rect x="35" y="60" width="26" height="14" rx="3" fill="{STEEL}"/>'
            '<path d="M37 65h22M37 70h22" stroke-width="2"/><path d="M43 78h10" stroke-width="4"/>')


def floodlight(t: str) -> str:
    return ('<path d="M76 30l8-4M76 44h9M76 58l8 4" stroke-width="3" stroke="' + AMBER + '"/>'
            f'<rect x="14" y="22" width="60" height="42" rx="6" fill="{INK}"/>'
            f'<rect x="21" y="29" width="46" height="28" rx="3" fill="{t}"/>'
            '<path d="M44 64v10M30 78h28" stroke-width="4"/>')


def power_strip(t: str) -> str:
    sockets = "".join(f'<circle cx="{x}" cy="50" r="5.5" fill="{t}"/>' for x in (24, 38, 52))
    return (f'<rect x="12" y="38" width="54" height="24" rx="7" fill="{PAPER}"/>{sockets}'
            + thick("M66 50q12 0 12 12t4 14", INK, 1)
            + f'<rect x="74" y="72" width="14" height="10" rx="2" fill="{AMBER}"/>')


def breaker(t: str) -> str:
    return (f'<rect x="30" y="12" width="36" height="72" rx="5" fill="{PAPER}"/>'
            f'<rect x="39" y="34" width="18" height="26" rx="3" fill="{INK}"/>'
            f'<rect x="42" y="36" width="12" height="11" rx="2" fill="{t}"/>'
            '<path d="M38 22h20M38 72h20" stroke-width="2.5"/>')


def lumber(t: str) -> str:
    boards = "".join(f'<rect x="{x}" y="{y}" width="60" height="14" rx="2" fill="{fill}"/>'
                     for x, y, fill in ((18, 58, t), (14, 42, WOOD_LIGHT), (22, 26, t)))
    return boards + '<path d="M28 33q10-3 20 0t20 0M24 49q10-3 20 0t20 0M28 65q10-3 20 0t20 0" stroke-width="1.5" ' \
                    'stroke-opacity=".5"/>'


def sheet_roll(t: str) -> str:
    return (f'<path d="M20 40h48l10 38H30z" fill="{t}"/>' + shade("M24 44h42l3 10H27z", ".25")
            + f'<rect x="14" y="24" width="60" height="20" rx="10" fill="{t}"/>'
            f'<ellipse cx="64" cy="34" rx="5" ry="10" fill="{STEEL_DARK}"/>')


def box(t: str) -> str:
    return (f'<path d="M48 16l30 14v36L48 80 18 66V30z" fill="{t}"/>'
            + shade("M48 46l30-16v36L48 80z")
            + '<path d="M18 30l30 16 30-16M48 46v34" stroke-width="2.5"/>')


SHAPES = {
    "tubo": pipe, "accesorio": fitting, "grifo": faucet, "manguera": hose, "ducha": shower, "rejilla": grate,
    "saco": sack, "arena": pile, "ladrillo": bricks, "bloque": block, "varilla": rods, "malla": mesh, "teja": roof,
    "galon": can, "frasco": bottle, "aerosol": aerosol, "brocha": brush, "rodillo": roller, "cinta": tape,
    "cable": coil, "interruptor": switch, "toma": outlet, "caja": junction, "bombillo": bulb,
    "reflector": floodlight, "extension": power_strip, "breaker": breaker, "madera": lumber,
    "plastico": sheet_roll, "paquete": box,
}
