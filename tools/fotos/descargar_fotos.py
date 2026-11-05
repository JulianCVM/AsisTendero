r"""Descarga una foto de referencia por familia del catálogo desde Wikimedia Commons, solo con licencia libre.

Uso (desde la raíz del repositorio; no llama a Grok):

    .venv\Scripts\python tools\fotos\descargar_fotos.py              # las familias que falten
    .venv\Scripts\python tools\fotos\descargar_fotos.py MAR CEM      # rehacer solo esas
    .venv\Scripts\python tools\fotos\descargar_fotos.py --todas      # rehacer todas
    .venv\Scripts\python tools\fotos\descargar_fotos.py --hoja       # hoja de contacto para revisarlas
    .venv\Scripts\python tools\fotos\descargar_fotos.py --candidatos MAR "claw hammer"   # opciones numeradas

Cada foto se reduce a 320 px de lado mayor, se guarda como JPEG sin metadatos (los EXIF pueden traer ubicación) y
se anota en ``fotos.json`` con su autor, licencia, fuente y huella perceptual. ``CREDITOS.md`` se rehace desde el
manifiesto: las licencias CC BY y CC BY-SA exigen nombrar al autor y la licencia.

Se descarta lo que no sea CC0, dominio público, CC BY o CC BY-SA (nada NC, ND ni «uso legítimo»), y los archivos
cuyo título sugiera un logo o una marca. Aun así, la hoja de contacto se revisa a ojo: una foto con una marca
visible se cambia con un término más genérico en ``TERMS``.
"""

from html import unescape
from io import BytesIO
import json
from pathlib import Path
import re
import sys
import time
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from asistendero.datos.seed import MARKET_PRODUCTS, PRODUCTS  # noqa: E402
from asistendero.tienda.catalogo.product_photos import MANIFEST, PHOTOS_DIR, dhash  # noqa: E402

API = "https://commons.wikimedia.org/w/api.php"
# Wikimedia pide un agente con forma de contacto: https://meta.wikimedia.org/wiki/User-Agent_policy
AGENT = "AsisTendero/0.1 (https://github.com/JulianCVM/AsisTendero; catalogo ficticio de demostracion)"
MAX_SIDE = 320
FREE = re.compile(r"^(?:CC0|Public domain|PD\b|CC BY(?:-SA)? \d)", re.I)
BRANDED = re.compile(
    r"logo|brand|marca|coca|pepsi|nestl|colgate|unilever|sony|duracell|bosch|stanley|truper|varta|champs|vessor|"
    r"pattex|gorilla|white king|loctite|sika|makita|dewalt|philips|osram|energizer|knorr|kellogg|heinz|maggi|"
    r"nescaf|lipton|dove|palmolive|gillette|pampers|huggies|kotex|always|whiskas|pedigree|purina|ikea|wd-40", re.I)
# Palabras del término que no ayudan a reconocer el objeto en el título del archivo.
FILLER = {"of", "and", "the", "for", "with", "can", "bag", "box", "bottle", "tin", "set", "mix", "glass", "pack"}

# Familia → término de búsqueda en Commons (en inglés hay muchas más fotos de objetos).
TERMS = {
    "PVC": "PVC pipe", "TOR": "wood screws", "CEM": "cement bag", "PIN": "white paint bucket",
    "CPV": "CPVC pipe", "SAN": "PVC drain pipe", "CON": "electrical conduit pipe", "COD": "PVC elbow fitting",
    "C45": "PVC 45 degree elbow", "TEE": "PVC tee fitting", "UNI": "PVC coupling fitting", "ADM": "PVC male adapter",
    "ADH": "PVC female adapter", "TAP": "PVC end cap", "REG": "ball valve", "LLT": "garden tap",
    "SOL": "PVC solvent cement", "LIM": "PVC primer can", "TEF": "PTFE thread seal tape", "MAB": "braided hose",
    "SIF": "sink trap", "DUC": "electric shower head", "CBL": "white cement", "MOR": "mortar mix bag",
    "PGC": "tile adhesive bag", "BOQ": "tile grout", "CAL": "hydrated lime", "ARE": "sand pile",
    "GRV": "gravel", "YES": "gypsum plaster", "EST": "wall putty", "IMP": "roof coating",
    "VAR": "rebar", "ALA": "tie wire", "MAL": "welded wire mesh", "LAD": "clay bricks",
    "BLQ": "concrete block", "TDR": "drywall screws", "TAU": "self-drilling screws", "CHZ": "wall plugs",
    "PER": "hex bolt", "TUE": "hex nut", "ARA": "flat washers", "PUN": "nails",
    "PAC": "steel nails", "GRA": "fence staples", "MAR": "claw hammer", "MAC": "club hammer",
    "ALI": "combination pliers", "PIC": "needle-nose pliers", "COR": "diagonal pliers", "DPA": "flat screwdriver",
    "DES": "Phillips screwdriver", "LLE": "adjustable wrench", "LLA": "pipe wrench", "FLX": "tape measure",
    "NIV": "spirit level", "SEG": "hacksaw", "HSE": "hacksaw blade", "SER": "hand saw",
    "PAL": "square shovel", "PIK": "pickaxe", "PLU": "brick trowel", "LLN": "plastering trowel",
    "CAR": "wheelbarrow", "ESP": "putty knife", "PIV": "paint can", "ESM": "enamel paint tin",
    "ANT": "red oxide primer", "THI": "paint thinner", "VRS": "white spirit", "SEL": "wood stain can",
    "BRO": "paintbrush", "ROD": "paint roller", "BAN": "paint tray", "CEN": "masking tape",
    "LIJ": "sandpaper", "DIS": "cutting disc", "BRC": "masonry drill bit", "BRM": "twist drill bits",
    "CAB": "electrical wire", "DUP": "electrical cord", "INT": "light switch", "TOM": "electrical outlet",
    "BOM": "LED light bulb", "PLA": "porcelain lamp socket", "CIN": "electrical tape", "EXT": "extension cord",
    "MUL": "power strip", "BRK": "circuit breaker", "CAJ": "electrical junction box", "CAN": "brass padlock",
    "CER": "door knob", "BIS": "door hinge", "PAS": "barrel bolt", "CAD": "steel chain",
    "SIL": "silicone sealant cartridge", "PIS": "caulking gun", "PCO": "contact adhesive", "PMA": "wood glue",
    "EPO": "epoxy putty", "ESX": "expanding foam", "MAN": "garden hose", "ESC": "broom",
    "REC": "dustpan", "BAL": "plastic bucket", "TIJ": "pruning shears", "GUA": "leather work gloves",
    "GNI": "nitrile gloves", "GAF": "safety glasses", "TPB": "surgical mask", "CAS": "hard hat",
    "PRH": "bolts", "TLA": "sheet metal screws", "BRD": "spade drill bit", "BRX": "SDS drill bit",
    "LED": "LED lamp", "REF": "LED floodlight", "ENC": "power cable", "RED": "pipe reducer fitting",
    "CSN": "drain pipe elbow", "YSN": "wye pipe fitting", "REJ": "floor drain", "GRL": "bathroom faucet",
    "GLP": "kitchen faucet", "VLL": "toilet fill valve", "LMA": "sanding paper", "LJM": "emery cloth",
    "JLL": "combination wrench set", "ALN": "hex key set", "TRI": "plywood", "LIS": "wooden slats",
    "TZN": "corrugated iron", "TPL": "corrugated plastic roofing", "ANG": "steel angle", "PLN": "black plastic sheeting",
    "BOT": "rubber boots", "GUC": "rubber gloves", "CHA": "high-visibility vest", "MNG": "hose reel",
    "ASP": "lawn sprinkler", "TRP": "mop", "TAB": "pine boards", "MDF": "medium-density fibreboard",
    "VMD": "wooden dowel", "PEI": "cyanoacrylate glue", "MSM": "wood filler", "SPU": "sealant gun cartridge",
    "RAS": "garden rake", "MCH": "machete", "FUM": "pressure sprayer", "CPI": "scrubbing brush",
    "CSO": "rim lock", "CHM": "cabinet lock", "MNJ": "door handle", "MIR": "door viewer",
    "TIM": "doorbell", "SEN": "motion detector", "CLV": "electrical plug", "LIN": "flashlight",
    "TJL": "tin snips", "CNC": "cold chisel", "ESD": "carpenter square", "CAU": "soldering iron",
    "PRE": "C-clamp", "PAU": "ear defenders", "CRT": "welding helmet", "TNQ": "plastic water tank",
    "FLO": "float valve", "LLV": "water tap valve", "POL": "shade net", "ADO": "concrete pavers",
    "BAR": "varnish", "AER": "spray paint can",
    "MARR": "white rice", "MLEN": "lentils", "MFRI": "red beans", "MGAR": "chickpeas",
    "MAZU": "white sugar", "MSAL": "table salt", "MPAN": "panela", "MACE": "vegetable oil bottle",
    "MPAS": "spaghetti", "MHAR": "arepa flour", "MHTR": "wheat flour", "MAVE": "rolled oats",
    "MCAF": "ground coffee", "MCHO": "chocolate tablet", "MATU": "canned tuna", "MSAR": "canned sardines",
    "MFEC": "corn starch", "MLEC": "milk bag", "MLDL": "milk carton", "MLPO": "powdered milk",
    "MHUE": "brown eggs", "MCUB": "egg tray", "MQUE": "fresh cheese", "MMAN": "butter",
    "MKUM": "kumis", "MYOG": "yogurt", "MPTA": "sliced bread", "MPAL": "bread rolls",
    "MARE": "arepa", "MGAS": "soda crackers", "MPAP": "potatoes", "MPCR": "papa criolla",
    "MCEB": "onions", "MCEL": "spring onions", "MTOM": "tomatoes", "MPLV": "green plantains",
    "MPLM": "ripe plantains", "MBAN": "bananas", "MLIM": "limes", "MYUC": "cassava roots",
    "MZAN": "carrots", "MAGU": "avocado", "MCIL": "coriander", "MGSC": "cola drink glass",
    "MGSN": "orange soda glass", "MAGB": "water sachet", "MAGT": "bottled water", "MJUG": "juice box",
    "MSAC": "sausages", "MJAM": "sliced ham", "MMOR": "mortadella", "MJBR": "laundry soap bar",
    "MDET": "laundry detergent powder", "MBLQ": "bleach bottle", "MLVL": "dish soap", "MESP": "kitchen sponge",
    "MPHI": "toilet paper", "MBOL": "garbage bags", "MSUA": "fabric softener", "MJTO": "bar of soap",
    "MCRD": "toothpaste", "MCHA": "shampoo", "MTOA": "sanitary napkin", "MPNL": "disposable diaper",
    "MPFR": "potato chips", "MCHT": "chocolate bar", "MMNI": "salted peanuts", "MCHU": "lollipop",
    "MVEL": "candles", "MFOS": "matches", "MPIL": "AA batteries", "MALP": "dry dog food",
}
# Fotos elegidas a ojo en la hoja de contacto: título exacto del archivo en Commons. Mandan sobre la búsqueda y
# hacen que la biblioteca se pueda rehacer igual.
ELEGIDAS: dict[str, str] = {
    "ADO": "File:Stippled cement paving blocks for texture.jpg",
    "ARA": "File:Washers.agr.jpg",
    "ARE": "File:Pile of Sand for Building in Anambra State.jpg",
    "BAN": "File:Paint Tray (1535689884).jpg",
    "BIS": "File:Door Hinge.jpg",
    "BOM": "File:LED light bulb ~171113.jpg",
    "BOQ": "File:Applying grout.jpg",
    "BRM": "File:Twist Drill Bit (6954956907).jpg",
    "BRO": "File:2000s Wistoba Chinex Plus professional trade paintbrush model 1508 50 mm width stainless steel ferrule.jpg",
    "CAB": "File:Drum Roll - geograph.org.uk - 1003165.jpg",
    "CAJ": "File:Cable junction box for maintaining electrical functional integrity according to DIN 4102 Part 12.JPG",
    "CEM": "File:Portland Type 1 paper bags of Taiwan Cement on Fu 2nd Street 20180501.jpg",
    "CEN": "File:A Roll of Masking Tape (32410678777).jpg",
    "CHM": "File:Bookcase cabinet door handles made by Loach & Clarke. One lock faceplate is stamped with a royal crown and the letters VR.png",
    "CON": "File:Rigid Non-Metallic Conduit 1.jpg",
    "CPV": "File:Pipeing.jpeg",
    "DIS": "File:Abrasive-Discs 41508-480x360 (5000494680).jpg",
    "DUP": "File:Power cord (817840840).jpg",
    "ESC": "File:Broomstick.jpg",
    "ESX": "File:Spray Polyurethane Foam Application.jpg",
    "FLX": "File:Measuring-tape.jpg",
    "GRV": "File:Gravel Stones.jpg",
    "LLT": "File:Outdoor water tap.jpg",
    "LMA": "File:Rough-Sandpaper- 28805-480x360 (4999892287).jpg",
    "MAGT": "File:Water bottle in room.jpg",
    "MAZU": "File:Granulated White Sugar with Large Crystals, Bright Side Light.jpg",
    "MBOL": "File:Black garbage bag.jpg",
    "MCEL": "File:Fresh scallions from Gorzynski Ornery Farm, Union Square Greenmarket, May 17 2025, Manhattan, New York.jpg",
    "MCHA": "File:Green shampoo bottle.jpg",
    "MCHU": "File:Transparent film wrapped swirl lollipop.jpg",
    "MDF": "File:MDF Sample.jpg",
    "MESP": "File:Cleaning sponge.jpg",
    "MFOS": "File:Closeup of match stick heads.jpg",
    "MGSC": "File:Glass of Cola.jpg",
    "MHUE": "File:Brown eggs in a deviled egg plate.jpg",
    "MJBR": "File:Savons en train de sécher par David Damour.jpg",
    "MLDL": "File:Milk carton clip art.png",
    "MLEC": "File:Milk Bag.jpg",
    "MPAN": "File:Panela.jpg",
    "MPAP": "File:Potato sprout, January 23, 2006.jpg",
    "MPHI": "File:Toilet paper roll.jpg",
    "MTOA": "File:Sanitary towel 1.jpg",
    "MYUC": "File:PeeLawPeeNam Cassava root Yuca Manioc.jpg",
    "NIV": "File:Tool-level.jpg",
    "PAL": "File:Shovel 2.jpg",
    "PIS": "File:Caulking.jpg",
    "PMA": "File:Wood glue.jpg",
    # Un tubo ancho de desagüe con su tapa. La visión real lo leyó como tubería PVC sanitaria (corrida 46); estaba en
    # PVC (presión, de 1/2 en adelante) y el «del de 1/2» siguiente terminaba en otra familia. La anterior de SAN era
    # una trampa en J, no un tubo.
    "SAN": "File:PVC pipe Example.jpg",
    "SEN": "File:Ranex Smartwares 6000.293 - board - motion sensor and photoresistor-5608.jpg",
    "SER": "File:Swedish hand saw No 315 by AB Stridsberg and Bioerck second half of 20th century.jpg",
    "TAB": "File:Pine plank fence 2019 G1.jpg",
    "TEE": "File:Tés de plomberie.jpg",
    "TEF": "File:PTFE seal tape.jpg",
    "TUE": "File:Hex nut.JPG",
    "TZN": "File:Seabees apply metal roofing sheets while reconstructing. (44604813675).jpg",
    "VRS": "File:White spirit.JPG",
}
# Familias sin una foto libre que muestre el producto sin confundirlo con otro: van sin foto, nunca con una parecida.
SIN_FOTO: set[str] = set((
    "AER ALA ANG ANT CBL CNC CPI ESD ESM EST FLO FUM LLV MAB MACE MAGB MBLQ MJUG MSUA PCO PEI PLN PUN SOL "
    "THI TLA TPL YES"
    # Auditoría con la visión real de Grok (01-11-2026): estas fotos muestran otro producto o uno ambiguo (válvulas
    # por limpiador, góndola por atún, mangos de hacha por maceta, un dibujo técnico por pasador…).
    " ADH ADM CAL CHA CLV CSO DES EPO IMP LIJ LIM MAC MATU MFEC MFRI MLPO MMNI MNJ MOR MSM PAS PAU PIV TIJ"
    # El tubo de presión de 1/2 en Commons sale gris (igual al conduit), azul de acueducto o transparente.
    " PVC"
).split())
# Si el término no da una foto libre que lo nombre en su título, se prueba este, más general.
FALLBACK = {
    "ADH": "PVC fitting", "ADM": "PVC pipe fitting", "ANT": "primer paint", "BOQ": "grout", "C45": "PVC elbow",
    "CPV": "CPVC", "CSN": "PVC elbow pipe", "DUC": "shower head", "LIM": "PVC cement", "LLN": "trowel",
    "MAB": "flexible hose", "MALP": "dog food", "MESP": "sponge", "MOR": "mortar", "UNI": "PVC coupling",
    "SOL": "PVC glue", "PGC": "tile adhesive", "YSN": "wye fitting",
}


def _families() -> dict[str, tuple[str, str]]:
    """Familia → (negocio, nombre del primer producto)."""
    found = {}
    for business, rows in (("ferreteria", PRODUCTS), ("mercado", MARKET_PRODUCTS)):
        for row in rows:
            found.setdefault(row[0].split("-")[0], (business, row[1]))
    return found


def _get(params: dict) -> dict:
    request = Request(f"{API}?{urlencode({**params, 'format': 'json'})}", headers={"User-Agent": AGENT})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def _plain(html: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html or ""))).strip()


def _words(text: str) -> set[str]:
    """Raíces de 4 letras: «hammers» y «hammer» cuentan igual."""
    return {word[:4] for word in re.findall(r"[a-z]+", text.lower()) if len(word) >= 3}


def _key_words(term: str) -> set[str]:
    return _words(" ".join(word for word in term.split() if word.lower() not in FILLER)) or _words(term)


IMAGE_INFO = {"prop": "imageinfo", "iiprop": "url|extmetadata|mime", "iiurlwidth": 640}


def _candidate(page: dict) -> dict | None:
    """Los datos de un archivo de Commons, o None si su licencia no es libre o nombra una marca."""
    info = (page.get("imageinfo") or [{}])[0]
    meta = info.get("extmetadata") or {}
    license_name = _plain((meta.get("LicenseShortName") or {}).get("value", ""))
    if info.get("mime") not in {"image/jpeg", "image/png"} or not FREE.match(license_name):
        return None
    description = _plain((meta.get("ImageDescription") or {}).get("value", ""))
    if BRANDED.search(page["title"]) or BRANDED.search(description):
        return None
    return {"titulo": page["title"], "fuente": info.get("descriptionurl", ""), "url": info.get("thumburl") or info["url"],
            "autor": _plain((meta.get("Artist") or {}).get("value", "")) or "Autor sin nombre en Commons",
            "licencia": license_name, "licencia_url": _plain((meta.get("LicenseUrl") or {}).get("value", ""))}


def _candidates(term: str, strict: bool = True, limit: int = 30) -> list[dict]:
    """Archivos libres para el término.

    ``strict`` exige que el título nombre lo buscado: todas las palabras del objeto, o todas menos una con tres o
    más. La búsqueda de Commons mira también la descripción y devolvía paisajes, vías férreas y esferas.
    """
    wanted = _key_words(term)
    needed = max(1, len(wanted) - (len(wanted) >= 3)) if strict else 0
    data = _get({"action": "query", "generator": "search", "gsrsearch": f"{term} filetype:bitmap",
                 "gsrnamespace": 6, "gsrlimit": limit, **IMAGE_INFO})
    pages = sorted((data.get("query") or {}).get("pages", {}).values(), key=lambda page: page.get("index", 99))
    found = []
    for page in pages:
        candidate = _candidate(page)
        score = len(wanted & _words(page["title"]))
        if candidate is not None and score >= needed:
            found.append({**candidate, "puntaje": score})
    # Más palabras del término en el título primero; a igual puntaje, el orden de relevancia de Commons.
    return sorted(found, key=lambda candidate: -candidate["puntaje"])


def _by_title(title: str) -> dict | None:
    data = _get({"action": "query", "titles": title, **IMAGE_INFO})
    pages = list((data.get("query") or {}).get("pages", {}).values())
    return _candidate(pages[0]) if pages and "missing" not in pages[0] else None


def _download(url: str) -> Image.Image:
    with urlopen(Request(url, headers={"User-Agent": AGENT}), timeout=60) as response:
        image = Image.open(BytesIO(response.read()))
        image.load()
    image = image.convert("RGB")
    image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    return image


def fetch(family: str, business: str, name: str) -> dict | None:
    """La foto elegida a ojo (``ELEGIDAS``) o, si no hay, la primera libre que nombre el término."""
    if family in SIN_FOTO:
        return None
    if family in ELEGIDAS:
        candidate = _by_title(ELEGIDAS[family])
        if candidate is None:
            raise SystemExit(f"{family}: {ELEGIDAS[family]} ya no está en Commons o su licencia no es libre")
        return _save(family, business, name, candidate, "elegida a ojo")
    for term in (TERMS[family], FALLBACK.get(family)):
        for candidate in _candidates(term) if term else []:
            entry = _save(family, business, name, candidate, term)
            if entry is not None:
                return entry
    return None


def _save(family: str, business: str, name: str, candidate: dict, term: str) -> dict | None:
    try:
        image = _download(candidate["url"])
    except OSError as error:
        print(f"  {family}: no se pudo leer {candidate['titulo']} ({type(error).__name__})")
        return None
    # Con prefijo: «CON», «AUX» o «PRN» solos son nombres reservados de Windows y git no los puede leer.
    archivo = f"foto-{family}.jpg"
    # Sin exif ni icc: el JPEG solo lleva los píxeles.
    image.save(PHOTOS_DIR / archivo, "JPEG", quality=80, optimize=True)
    credit = f"{candidate['autor']} · {candidate['licencia']} · Wikimedia Commons"
    return {"archivo": archivo, "negocio": business, "producto": name, "busqueda": term,
            **{key: candidate[key] for key in ("titulo", "fuente", "autor", "licencia", "licencia_url")},
            "credito": credit, "huella": dhash(image), "ancho": image.width, "alto": image.height}


def candidate_sheet(family: str, term: str, out: Path) -> None:
    """Hasta 12 opciones libres numeradas para elegir a ojo; el título elegido va a ``ELEGIDAS``."""
    found = _candidates(term, strict=False, limit=40)[:12]
    cell = 200
    sheet = Image.new("RGB", (4 * cell, max(1, -(-len(found) // 4)) * (cell + 16)), "white")
    draw = ImageDraw.Draw(sheet)
    for index, candidate in enumerate(found):
        print(f"  {index}: {candidate['titulo']} ({candidate['licencia']})")
        try:
            image = _download(candidate["url"])
        except OSError:
            continue
        image.thumbnail((cell - 6, cell - 6))
        x, y = (index % 4) * cell, (index // 4) * (cell + 16)
        sheet.paste(image, (x + 3, y + 3))
        draw.text((x + 4, y + cell), f"{family} {index}", fill="black")
    sheet.save(out)


def write_credits(entries: dict[str, dict]) -> None:
    lines = ["# Créditos de las fotos de referencia", "",
             "Fotos ilustrativas del tipo de producto, no del producto de una marca: el catálogo es ficticio. Todas "
             "vienen de [Wikimedia Commons](https://commons.wikimedia.org) con licencia libre y se redujeron a 320 px. "
             "La licencia MIT del repositorio cubre el código, no estas fotos: cada una conserva la suya.", "",
             "| Familia | Producto | Foto | Autor | Licencia |", "|---|---|---|---|---|"]
    for family, entry in sorted(entries.items()):
        author = entry["autor"].replace("|", "/")
        license_text = f"[{entry['licencia']}]({entry['licencia_url']})" if entry["licencia_url"] else entry["licencia"]
        lines.append(f"| {family} | {entry['producto']} | [{entry['titulo'].removeprefix('File:')}]({entry['fuente']}) "
                     f"| {author} | {license_text} |")
    (PHOTOS_DIR / "CREDITOS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def contact_sheet(entries: dict[str, dict], out: Path) -> None:
    """Todas las fotos en una cuadrícula con su familia, para revisarlas de una vez."""
    cell, columns = 120, 16
    rows = -(-len(entries) // columns)
    sheet = Image.new("RGB", (columns * cell, rows * (cell + 14)), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (family, entry) in enumerate(sorted(entries.items())):
        image = Image.open(PHOTOS_DIR / entry["archivo"])
        image.thumbnail((cell - 4, cell - 4))
        x, y = (index % columns) * cell, (index // columns) * (cell + 14)
        sheet.paste(image, (x + 2, y + 2))
        draw.text((x + 3, y + cell), family, fill="black")
    sheet.save(out)


def main(argv: list[str]) -> int:
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    entries = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.is_file() else {}
    if argv and argv[0] == "--candidatos":
        family = argv[1].upper()
        out = Path(argv[3]) if len(argv) > 3 else ROOT / ".local" / f"fotos-candidatos-{family}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        candidate_sheet(family, argv[2] if len(argv) > 2 else TERMS[family], out)
        print(out)
        return 0
    if argv and argv[0] == "--hoja":
        out = Path(argv[1]) if len(argv) > 1 else ROOT / ".local" / "fotos-hoja.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        contact_sheet(entries, out)
        print(out)
        return 0
    families = _families()
    missing = sorted(set(families) - set(TERMS))
    if missing:
        print(f"Faltan términos en TERMS para: {', '.join(missing)}")
        return 1
    if argv == ["--todas"]:
        argv = sorted(families)
    wanted = [family.upper() for family in argv] or [family for family in families if family not in entries]
    for family in wanted:
        business, name = families[family]
        try:
            entry = fetch(family, business, name)
        except (URLError, TimeoutError) as error:
            # Un corte de red no deja nada a medias: la familia conserva su foto y su huella, y se sigue.
            print(f"  {family}: sin conexión con Commons ({type(error).__name__}); se reintenta en otra corrida")
            continue
        if entry is None:
            print(f"  {family}: sin foto" + ("" if family in SIN_FOTO else f" libre para «{TERMS[family]}»"))
            entries.pop(family, None)
            (PHOTOS_DIR / f"foto-{family}.jpg").unlink(missing_ok=True)
        else:
            entries[family] = entry
            print(f"  {family}: {entry['titulo']} ({entry['licencia']})")
        # Cada familia queda escrita al terminar: el archivo y su huella nunca se separan.
        MANIFEST.write_text(json.dumps(dict(sorted(entries.items())), ensure_ascii=False, indent=1) + "\n",
                            encoding="utf-8")
        # Commons pide no saturar su API: una familia a la vez y una pausa corta.
        time.sleep(0.3)
    write_credits(entries)
    print(f"{len(entries)} fotos en {PHOTOS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
