"""Resolución anafórica de turnos elípticos, memoria de especificaciones y navegación de opciones."""

import re

from asistendero.catalog import Product, covers, tokens
from asistendero.measures import SALE_UNITS, atom_support, canonical_text, contradicts, measures, split_atom
from asistendero.search import CLAUSE_BREAK, SALE_UNIT_NAME, negated_words, without_quantities
from asistendero.seed import PRODUCTS
from asistendero.store_replies import asks_assortment


RESTART = re.compile(
    r"\b(?:borr\w*\s+(?:la\s+lista|todo)|(?:empe[zc]|comen[zc])\w*\s+de\s+(?:nuevo|cero)|desde\s+cero"
    r"|(?:nueva|otra)\s+cotizacion)\b"
)


ACRONYMS = {"pvc": "PVC", "cpvc": "CPVC", "led": "LED", "awg": "AWG", "thhn": "THHN"}
MATERIAL_WORDS = {
    "pvc", "cpvc", "cobre", "acero", "hierro", "madera", "metal", "concreto", "plastico",
    "laton", "carnaza", "nitrilo", "caucho", "vinilo", "sintetico", "aluminio", "zinc", "pino", "algodon",
}
SALE_UNIT_TOKENS = {
    "metro", "metros", "bulto", "bultos", "galon", "galones", "unidad", "unidades",
    "libra", "libras", "rollo", "rollos", "par", "pares", "pliego", "pliegos", "bolsa", "bolsas", "caja", "cajas",
}
_ELLIPTICAL_FILLERS = {
    "deme", "dame", "quiero", "necesito", "busco", "porfa", "favor", "pues", "pue", "mejor", "entonces",
    "listo", "ok", "bueno", "dale", "si", "claro", "unos", "unas", "llevo", "lleva", "seria", "sea", "sean",
}
_VAGUE_ONLY = {
    "ese", "esa", "eso", "esos", "esas", "este", "esto", "estos", "estas", "aquel", "aquella", "aquello",
    "uno", "una", "unos", "unas", "cosa", "cosas", "mismo", "misma", "mismos", "mismas", "lo", "los",
    "producto", "productos", "referencia", "vez", "pasada", "anterior",
}
_STORE_OR_ORDER = re.compile(
    r"\b(?:horario|abiert[oa]s?|abren|cierran|ubicacion|direccion|donde\s+quedan|domicilio\w*|garantia\w*"
    r"|factura\w*|medios?\s+de\s+pago|confirm\w*|cancel\w*|pedido\w*|apartam\w*|recog\w*)\b"
)
_MODIFIER_START = re.compile(
    r"^(?:(?:el|la|los|las|un|una|unos|unas|ese|esa|esos|esas|mejor|pues|si)\s+)*"
    r"(?:de|del|para|en|con|tipo|color|calibre|talla|grano)\b"
)
_ASKS_WHAT_HAS = re.compile(r"\bque\s+(?:tiene|tienen|hay|vende|venden|maneja|manejan)\b")
_NEW_PRODUCT_OPENING = re.compile(r"\b(?:tienen?|tiene|hay|venden?|vende|manejan?|busco|cotiz\w*)\b")
ASKS_ALL_MEASURES = re.compile(
    r"\b(?:que|cuales|otras|todas\s+las)\s+(?:medidas|tamanos|calibres|presentaciones)\b"
)
_GALLON_FRACTION = re.compile(r"\b(1/(?:4|8|32))\s+de\s+galon\b")
_PRESENTATION = re.compile(r"\b(cunete(?:\s+de\s+5\s+galones)?|galon|bulto|bolsa|rollo|caja|pliego)s?\b")
_EXPLICIT_MEASURE = re.compile(
    r"(#?\d+(?:\s+\d+/\d+|/\d+|[.,]\d+)?\s*[x×]\s*#?\d+(?:\s+\d+/\d+|/\d+|[.,]\d+)?(?:\s*(?:pulgadas?|cm|mm|m|awg))?)"
    r"|(\b\d+(?:\s+\d+/\d+|/\d+|[.,]\d+)?\s*(?:pulgadas?|pulg|kg|kilos?|g|gr|gramos|cm|mm|w|vatios|watts|v|voltios"
    r"|a|amperios|ml|l|litros?|oz|onzas|awg|pies)\b)"
    r"|(\bde\s+\d+\s*(?:m|metros?)\b)"
    r"|(\b(?:calibre|grano)\s+\d{1,3}\b|\btalla\s+(?:\d{2}|s|m|l|xl)\b)"
    r"|(\bde\s+\d+/\d+\b(?!\s*de\s+galon))"
)
AFFIRMATIVE_DEMONSTRATIVE = re.compile(
    r"^(?:si\b[\s,]*)*(?:(?:dame|deme|quiero|llevo|mejor|pues|listo|dale|claro)\s+)*"
    r"(?:es[eao]|est[eo]|aquel(?:la|lo)?)(?:\s+mism[oa])?(?:\s+(?:esta\s+bien|por\s+favor|porfa|gracias))?[\s.!?]*$"
)
SHORT_OFFER_QUESTION = re.compile(r"¿te\s+cotizo\s+(?:el|los)\s+(\d+)\?", re.IGNORECASE)
AFFIRMATIVE_SHORT = re.compile(
    r"^(?:si|dale|listo|bueno|claro|de\s+una)\b(?:\s*,?\s*(?:cotiz\w*|es[oa]s?|los?\s+\d+|porfa|por\s+favor))*[\s.!?]*$"
)


def _build_catalog_index() -> tuple[dict[str, str], dict[str, set[str]]]:
    canonical_head: dict[str, str] = {}
    family_words: dict[str, set[str]] = {}
    for row in PRODUCTS:
        first = canonical_text(row[1].split()[0])
        base = first[:-1] if first.endswith("s") and first not in {"guantes", "gafas", "botas"} else first
        for tok in tokens(first):
            canonical_head.setdefault(tok, base)
        family_words.setdefault(base, set()).update(tokens(f"{row[1]} {row[2]} {row[6].replace('|', ' ')}"))
    return canonical_head, family_words


_CANONICAL_HEAD, _FAMILY_WORDS = _build_catalog_index()


def _format_subject(head: str, materials: list[str]) -> str:
    formatted = [ACRONYMS.get(word, word) for word in materials]
    return " ".join([head, *formatted]).strip()


def _heads_in_text(text: str) -> list[str]:
    found: list[str] = []
    for raw in re.findall(r"[a-z0-9]+", canonical_text(without_quantities(text))):
        for tok in tokens(raw):
            if tok in _CANONICAL_HEAD and _CANONICAL_HEAD[tok] not in found:
                found.append(_CANONICAL_HEAD[tok])
    return found


def previous_product_subject(context: dict | None) -> tuple[str, str] | None:
    """(frase_producto, cabeza_canonica) activa del turno inmediato anterior o desambiguación vigente."""
    if not context:
        return None
    opciones = context.get("opciones") or []
    turns = context.get("turnos") or []
    if len(opciones) == 1:
        group = opciones[0]
        group_text = str(group.get("grupo") or "")
        recent_text = f"{turns[-1].get('cliente', '')} {turns[-1].get('asistente', '')}" if turns else group_text
        if not turns or "?" in (turns[-1].get("asistente") or "") or (tokens(group_text) & tokens(recent_text)):
            heads = _heads_in_text(group_text)
            if not heads and group.get("opciones"):
                heads = _heads_in_text(group["opciones"][0].get("nombre") or "")
            if heads:
                head = heads[0]
                refused = negated_words(canonical_text(group_text), tokens)
                mats = [w for w in re.findall(r"[a-z]+", canonical_text(group_text))
                        if w in MATERIAL_WORDS and w in _FAMILY_WORDS.get(head, set()) and w not in refused]
                unique_mats = list(dict.fromkeys(mats))
                return _format_subject(head, unique_mats), head
    if turns:
        last_client = str(turns[-1].get("cliente") or "")
        heads = _heads_in_text(last_client)
        if len(heads) == 1:
            head = heads[0]
            refused = negated_words(canonical_text(last_client), tokens)
            mats = [w for w in re.findall(r"[a-z]+", canonical_text(last_client))
                    if w in MATERIAL_WORDS and w in _FAMILY_WORDS.get(head, set()) and w not in refused]
            return _format_subject(head, list(dict.fromkeys(mats))), head
    return None


def is_elliptical_turn(message: str, context: dict | None) -> tuple[str, str] | None:
    """Devuelve (frase_producto, cabeza) si el mensaje es un turno breve/elíptico dependiente del anterior."""
    subject_info = previous_product_subject(context)
    if subject_info is None:
        return None
    subject, head = subject_info
    norm = canonical_text(message).strip()
    if not norm or asks_assortment(norm) or _STORE_OR_ORDER.search(norm):
        return None
    if head in tokens(message):
        return None
    clean = without_quantities(norm)
    words = tokens(clean) - _ELLIPTICAL_FILLERS - _VAGUE_ONLY
    msg_atoms = measures(clean)
    if not words and not msg_atoms:
        return None
    family_words = _FAMILY_WORDS.get(head, set())
    option_words = set().union(
        *(tokens(f"{opt.get('nombre', '')} {opt.get('variante', '')}")
          for grp in ((context or {}).get("opciones") or [])
          for opt in (grp.get("opciones") or []) + (grp.get("restantes") or [])),
        set(),
    )
    known_modifiers = family_words | option_words | SALE_UNIT_TOKENS
    foreign_heads = {w for w in words if w in _CANONICAL_HEAD and _CANONICAL_HEAD[w] != head}
    if any(w not in known_modifiers for w in foreign_heads):
        return None
    if foreign_heads and (_ASKS_WHAT_HAS.search(clean) or _NEW_PRODUCT_OPENING.search(clean)):
        return None
    starts_modifier = bool(_MODIFIER_START.match(clean)) and not _ASKS_WHAT_HAS.search(clean)
    matches_family = bool(words & (family_words | option_words | MATERIAL_WORDS))
    has_measure = bool(msg_atoms) and not _NEW_PRODUCT_OPENING.search(clean)
    return (subject, head) if (starts_modifier or matches_family or has_measure) else None


def enrich_elliptical_text(item_text: str, message: str, context: dict | None) -> tuple[str, str | None]:
    """Hereda el producto del turno inmediato anterior en búsquedas elípticas («de concreto» → «broca concreto»)."""
    elliptical = is_elliptical_turn(message, context)
    if elliptical is None:
        return item_text.strip(), None
    subject, head = elliptical
    item_heads = {h for h in _heads_in_text(item_text) if h != head and h not in _FAMILY_WORDS.get(head, set())}
    if item_heads:
        return item_text.strip(), None
    if head in tokens(item_text):
        missing = [word for word in subject.split() if not (tokens(word) & tokens(item_text))]
        return (f"{' '.join(missing)} {item_text.strip()}".strip() if missing else item_text.strip()), head
    strip_leading = {"de", "del", "para", "el", "la", "los", "las", "ese", "esa", "un", "una"}
    raw_parts = item_text.strip().split()
    while raw_parts and canonical_text(raw_parts[0]) in strip_leading:
        raw_parts.pop(0)
    cleaned_parts = [part for part in raw_parts if canonical_text(part) not in {"de", "del", "para"}]
    tail = " ".join(cleaned_parts or raw_parts).strip() or item_text.strip()
    return f"{subject} {tail}".strip(), head


def _clause_spec(clause: str, head: str) -> dict[str, str]:
    clean = without_quantities(canonical_text(clause))
    spec: dict[str, str] = {}
    if ASKS_ALL_MEASURES.search(clean):
        spec["reset_medida"] = "1"
    family = _FAMILY_WORDS.get(head, set())
    gal_frac = _GALLON_FRACTION.findall(clean)
    if gal_frac:
        spec["presentacion"] = f"{gal_frac[-1]} de galón"
    else:
        pres = [m for m in _PRESENTATION.findall(clean) if m in family or m in {"galon", "cunete"}]
        if pres:
            last_pres = pres[-1]
            if last_pres.startswith("cunete"):
                spec["presentacion"] = "cuñete"
            elif last_pres == "galon":
                spec["presentacion"] = "galón"
            else:
                spec["presentacion"] = last_pres
    cleaned_for_measure = _GALLON_FRACTION.sub(" ", clean)
    found_measures = [next(g for g in match.groups() if g) for match in _EXPLICIT_MEASURE.finditer(cleaned_for_measure)]
    if found_measures and "reset_medida" not in spec:
        raw_m = found_measures[-1].strip()
        if raw_m.startswith("de "):
            raw_m = raw_m[3:].strip()
            if re.fullmatch(r"\d+/\d+", raw_m) and "pulgada" in family:
                raw_m = f"{raw_m} pulgada"
            elif re.search(r"\bmetros?\b", raw_m):
                raw_m = re.sub(r"\bmetros?\b", "m", raw_m)
        elif raw_m.startswith("calibre ") and "awg" in family:
            raw_m = f"{raw_m.split()[1]} AWG"
        spec["medida"] = raw_m
    refused = negated_words(clean, tokens)
    mats = [w for w in re.findall(r"[a-z]+", clean) if w in MATERIAL_WORDS and w in family and w not in refused]
    if mats:
        chosen_mat = "cpvc" if "cpvc" in mats else mats[-1]
        spec["material"] = ACRONYMS.get(chosen_mat, chosen_mat)
    return spec


def extract_turn_specs(message: str) -> dict[str, dict[str, str]]:
    """Especificaciones (medida, material, presentación) que el cliente fijó por producto en este mensaje."""
    specs: dict[str, dict[str, str]] = {}
    clauses = [part.strip() for part in CLAUSE_BREAK.split(message) if part.strip()]
    last_head: str | None = None
    for clause in clauses:
        heads = _heads_in_text(clause)
        head = heads[0] if len(heads) == 1 else (last_head if not heads and last_head else None)
        if not head:
            continue
        last_head = head
        extracted = _clause_spec(clause, head)
        if extracted:
            specs.setdefault(head, {}).update(extracted)
    return specs


def updated_specs(previous: dict | None, message: str, context: dict | None = None) -> dict[str, dict[str, str]]:
    """Actualiza las especificaciones recordadas de la sesión; permite sobreescribir o reiniciar la conversación."""
    base: dict[str, dict[str, str]] = {}
    if not RESTART.search(canonical_text(message)):
        base = {head: dict(values) for head, values in (previous or {}).items() if isinstance(values, dict)}
    turn_specs = extract_turn_specs(message)
    elliptical = is_elliptical_turn(message, context)
    if not turn_specs and elliptical is not None:
        _, head = elliptical
        extracted = _clause_spec(message, head)
        if extracted:
            turn_specs[head] = extracted
    for head, changes in turn_specs.items():
        entry = dict(base.get(head) or {})
        if changes.get("reset_medida"):
            entry.pop("medida", None)
        for key in ("medida", "material", "presentacion"):
            if changes.get(key):
                entry[key] = changes[key]
        if entry:
            base[head] = entry
        else:
            base.pop(head, None)
    return base


def specs_from_context(context: dict | None) -> dict[str, dict[str, str]]:
    """Especificaciones vigentes en la sesión (de la tabla persistida o reconstruidas de los turnos)."""
    if not context:
        return {}
    if "especificaciones" in context:
        return {
            head: {k: v for k, v in stored.items() if isinstance(v, str) and v}
            for head, stored in (context.get("especificaciones") or {}).items()
            if isinstance(stored, dict)
        }
    specs: dict[str, dict[str, str]] = {}
    for turn in context.get("turnos") or []:
        if isinstance(turn, dict) and turn.get("cliente"):
            specs = updated_specs(specs, str(turn["cliente"]))
    return specs


def remembered_spec_for_item(
    item_text: str, product_field: str | None, current_message: str, context: dict | None,
) -> dict[str, str]:
    """Especificación recordada aplicable al artículo actual cuando el turno no la contradice ni pide todas."""
    all_specs = specs_from_context(context)
    if not all_specs:
        return {}
    heads = _heads_in_text(product_field or "") or _heads_in_text(item_text)
    if len(heads) != 1 or heads[0] not in all_specs:
        return {}
    head = heads[0]
    remembered = dict(all_specs[head])
    norm_current = canonical_text(current_message)
    if ASKS_ALL_MEASURES.search(norm_current):
        remembered.pop("medida", None)
    current_specs = extract_turn_specs(current_message).get(head) or _clause_spec(current_message, head)
    if current_specs.get("reset_medida") or current_specs.get("medida"):
        remembered.pop("medida", None)
    if current_specs.get("material"):
        remembered.pop("material", None)
    if current_specs.get("presentacion"):
        remembered.pop("presentacion", None)
    return remembered


def _matches_measure(product: Product, measure_text: str) -> bool:
    prod_text = f"{product.name} {product.variant}"
    norm_measure = canonical_text(measure_text)
    if norm_measure.startswith(("talla ", "grano ")):
        return covers(norm_measure, tokens(prod_text, synonyms=False))
    spec_atoms = measures(measure_text)
    if not spec_atoms:
        return covers(measure_text, tokens(prod_text, synonyms=False))
    prod_atoms = measures(prod_text)
    if contradicts(prod_atoms, spec_atoms):
        return False
    specific = [a for a in spec_atoms if (split_atom(a)[1] and split_atom(a)[1] not in SALE_UNITS) or "/" in a or "x" in a]
    targets = specific or list(spec_atoms)
    return all(atom in prod_atoms or atom_support(atom, prod_atoms) > 0 for atom in targets)


def filter_matches_by_spec(matches: list[Product], spec: dict[str, str]) -> list[Product]:
    """Filtra variantes por la especificación ya acordada en la sesión si al menos una variante la cumple."""
    if not matches or not spec:
        return matches
    result = list(matches)
    if spec.get("material"):
        mat_tokens = tokens(spec["material"], synonyms=False)
        narrowed = [p for p in result if mat_tokens <= tokens(f"{p.name} {p.variant}", synonyms=False)]
        if narrowed:
            result = narrowed
    if spec.get("medida"):
        narrowed = [p for p in result if _matches_measure(p, spec["medida"])]
        if narrowed:
            result = narrowed
    if spec.get("presentacion"):
        pres = canonical_text(spec["presentacion"])
        if pres == "galon":
            narrowed = [
                p for p in result
                if "galon" in tokens(p.variant, synonyms=False)
                and "1/4" not in p.variant and "1/8" not in p.variant and "1/32" not in p.variant
                and "cunete" not in canonical_text(p.variant)
            ]
        else:
            narrowed = [p for p in result if covers(pres, tokens(p.variant, synonyms=False))]
        if narrowed:
            result = narrowed
    return result


def affirms_active_item(message: str, context: dict | None) -> dict | None:
    """Producto u opción única que el cliente confirma con «sí, esa» / «ese mismo» sin ambigüedad."""
    if not context:
        return None
    norm = " ".join(canonical_text(message).split())
    if not AFFIRMATIVE_DEMONSTRATIVE.match(norm):
        return None
    groups = context.get("opciones") or []
    if len(groups) == 1 and len(groups[0].get("opciones") or []) == 1:
        return groups[0]["opciones"][0]
    turns = context.get("turnos") or []
    if groups:
        if len(groups) == 1 and turns:
            for turn in reversed(turns):
                last_words = tokens(canonical_text(turn.get("asistente") or ""), synonyms=False)
                singled = [
                    opt for opt in (groups[0].get("opciones") or [])
                    if opt.get("nombre") and tokens(f"{opt['nombre']} {opt.get('variante', '')}", synonyms=False) <= last_words
                ]
                if len(singled) == 1:
                    return singled[0]
                if len(singled) > 1:
                    break
        products = [item for item in (context.get("productos") or []) if item.get("sku") and item.get("nombre")]
        in_group = [
            opt for opt in (groups[0].get("opciones") or [])
            if any(p["sku"] == opt.get("sku") for p in products)
        ] if len(groups) == 1 else []
        if len(in_group) == 1:
            return in_group[0]
        return None
    products = [item for item in (context.get("productos") or []) if item.get("sku") and item.get("nombre")]
    if len(products) == 1:
        return products[0]
    if turns and products:
        last_assistant = tokens(canonical_text(turns[-1].get("asistente") or ""))
        mentioned = [item for item in products if tokens(item["nombre"].split()[0], synonyms=False) & last_assistant]
        if len(mentioned) == 1:
            return mentioned[0]
    return None


def offered_short_quantity(message: str, context: dict | None) -> int | None:
    """Cantidad menor ofrecida en el turno anterior («¿Te cotizo los 4?») cuando el cliente acepta («sí, esos»)."""
    turns = (context or {}).get("turnos") or []
    if not turns:
        return None
    match = SHORT_OFFER_QUESTION.search(canonical_text(turns[-1].get("asistente") or ""))
    if not match:
        return None
    norm = " ".join(canonical_text(message).split())
    return int(match.group(1)) if AFFIRMATIVE_SHORT.match(norm) else None


_QUANTITY_QUESTION = re.compile(
    r"(?:\bcuant[oa]s?\b"
    r"|\bcuant[oa]\b[^?¿]*\b(?:necesit\w*|quier\w*|llev\w*|cotiz\w*|seri\w*|cantidad|metraje)\b"
    r"|\bque\s+(?:cantidad|metraje)\b"
    r"|\b(?:cotizo|cotizar|llevas?|quieres?|deseas?)\s+(?:(?:el|la|los|las)\s+)?\d+\b"
    r"|\bcotizo\s+una\s+cantidad\s+menor\b)"
)
_STOCK_MENTION = re.compile(
    r"\b(?:solo\s+(?:nos\s+)?quedan?|solo\s+tenemos|tenemos\s+\d+|quedan\s+\d+|\d+\s+disponibles?|\d+\s+en\s+(?:bodega|existencias?)|disponible\w*|existencias?)\b"
)
_MEASURE_QUESTION = re.compile(
    r"\bde\s+cuant[oa]s?\s+(?:pulgadas?|pulg|amperios?|amp|watts?|vatios?|voltios?|milimetros?|mm"
    r"|centimetros?|cm|kilos?|kilogramos?|kg|gramos?|gr|onzas?|oz|litros?|ml|grados?|pies|dientes|galon(?:es)?)\b"
)


def _atom_numbers(atoms: set[str]) -> set[str]:
    nums: set[str] = set()
    for atom in atoms:
        if "x" in atom.lstrip("#"):
            nums.update(atom.split("x"))
        else:
            num, _ = split_atom(atom)
            nums.add(num)
    return nums


def _variant_measure_support(variant: str, assistant_atoms: set[str]) -> int:
    var_atoms = measures(variant)
    if not var_atoms or not assistant_atoms:
        return 0
    asst_nums = _atom_numbers(assistant_atoms)
    total = 0
    for atom in var_atoms:
        support = atom_support(atom, assistant_atoms)
        if support == 0 and "x" in atom.lstrip("#"):
            parts = [part for part in atom.split("x") if part in asst_nums]
            if parts:
                support = 2 if any(f"{part}in" in assistant_atoms for part in parts) else 1
        total += support
    return total


def _item_fits_assistant(name: str, variant: str, assistant_norm: str) -> bool:
    var_atoms = measures(variant)
    asst_atoms = measures(assistant_norm)
    if contradicts(var_atoms, asst_atoms):
        return False
    if var_atoms:
        var_nums = _atom_numbers(var_atoms)
        for num in _atom_numbers(asst_atoms):
            if "/" in num and num not in var_nums:
                return False
    return True


def pending_quantity_target(context: dict | None) -> dict | None:
    """SKU activo por cuya cantidad o metraje preguntó directamente el asistente o cuyo stock se informó."""
    if not context:
        return None
    turns = context.get("turnos") or []
    if not turns:
        return None
    raw_assistant = str(turns[-1].get("asistente") or "")
    if "•" in raw_assistant:
        return None
    questions = re.findall(r"¿[^?¿]+\?|[^.!?\n]+\?", raw_assistant)
    has_quantity_question = any(
        _QUANTITY_QUESTION.search(q_norm := canonical_text(question)) and not _MEASURE_QUESTION.search(q_norm)
        for question in questions
    )
    has_stock_mention = bool(_STOCK_MENTION.search(canonical_text(raw_assistant)))
    if not (has_quantity_question or has_stock_mention):
        return None

    assistant_norm = canonical_text(raw_assistant)
    assistant_tokens = tokens(assistant_norm, synonyms=False)
    assistant_atoms = measures(assistant_norm)
    assistant_heads = _heads_in_text(assistant_norm)

    productos = [
        item for item in (context.get("productos") or [])
        if isinstance(item, dict) and item.get("sku") and item.get("nombre")
    ]
    named = [
        item for item in productos
        if (tokens(item["nombre"].split()[0], synonyms=False) & assistant_tokens)
        and _item_fits_assistant(item["nombre"], item.get("variante") or "", assistant_norm)
    ]
    if len(named) == 1:
        return named[0]
    if len(named) > 1:
        scored = [
            (
                (
                    _variant_measure_support(item.get("variante") or "", assistant_atoms),
                    len(tokens(f"{item['nombre']} {item.get('variante', '')}", synonyms=False) & assistant_tokens),
                ),
                item,
            )
            for item in named
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        if scored[0][0] > scored[1][0]:
            return scored[0][1]
        if not assistant_atoms and scored[0][1]["sku"] == productos[0]["sku"]:
            return productos[0]
    if not named and not assistant_heads and productos:
        if len(productos) == 1:
            return productos[0]
        unit_words = assistant_tokens & SALE_UNIT_TOKENS
        if unit_words:
            by_unit = [
                item for item in productos
                if tokens(f"{item.get('unidad', '')} {item.get('variante', '')}", synonyms=False) & unit_words
            ]
            if len(by_unit) == 1:
                return by_unit[0]
        prev_client = canonical_text(str(turns[-1].get("cliente") or ""))
        if tokens(productos[0]["nombre"].split()[0], synonyms=False) & tokens(prev_client, synonyms=False):
            return productos[0]

    pool = [
        opt for group in (context.get("opciones") or [])
        for opt in (group.get("opciones") or [])
        if isinstance(opt, dict) and opt.get("sku") and opt.get("nombre")
    ]
    if len(pool) == 1 and _item_fits_assistant(pool[0]["nombre"], pool[0].get("variante") or "", assistant_norm):
        if not assistant_heads or (tokens(pool[0]["nombre"].split()[0], synonyms=False) & assistant_tokens):
            return {k: pool[0][k] for k in ("sku", "nombre", "variante", "unidad") if k in pool[0]}
    if len(pool) > 1:
        compatible = [
            opt for opt in pool
            if (tokens(opt["nombre"].split()[0], synonyms=False) & assistant_tokens)
            and _item_fits_assistant(opt["nombre"], opt.get("variante") or "", assistant_norm)
        ]
        if len(compatible) == 1:
            return {k: compatible[0][k] for k in ("sku", "nombre", "variante", "unidad") if k in compatible[0]}
        if len(compatible) > 1:
            scored_opts = [
                (
                    (
                        _variant_measure_support(opt.get("variante") or "", assistant_atoms),
                        len(tokens(f"{opt['nombre']} {opt.get('variante', '')}", synonyms=False) & assistant_tokens),
                    ),
                    opt,
                )
                for opt in compatible
            ]
            scored_opts.sort(key=lambda pair: pair[0], reverse=True)
            best_score, best_opt = scored_opts[0]
            if best_score > scored_opts[1][0] and (
                best_score[0] > 0 or (tokens(best_opt.get("variante") or "", synonyms=False) & assistant_tokens)
            ):
                return {k: best_opt[k] for k in ("sku", "nombre", "variante", "unidad") if k in best_opt}

    if len(assistant_heads) == 1:
        head = next(iter(assistant_heads))
        candidates = []
        for sku, name, variant, unit, *_ in PRODUCTS:
            first = canonical_text(name.split()[0])
            row_head = first[:-1] if first.endswith("s") and first not in {"guantes", "gafas", "botas"} else first
            if row_head != head or not _item_fits_assistant(name, variant, assistant_norm):
                continue
            var_atoms = measures(variant)
            var_support = _variant_measure_support(variant, assistant_atoms)
            if var_atoms and var_support == 0:
                continue
            score = (
                len(tokens(name, synonyms=False) & assistant_tokens),
                var_support,
                len(tokens(variant, synonyms=False) & assistant_tokens),
            )
            candidates.append((score, {"sku": sku, "nombre": name, "variante": variant, "unidad": unit}))
        if len(candidates) == 1:
            return candidates[0][1]
        if len(candidates) > 1:
            candidates.sort(key=lambda pair: pair[0], reverse=True)
            if candidates[0][0] > candidates[1][0]:
                return candidates[0][1]
    return None

