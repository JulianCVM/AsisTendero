"""Cuál de varios productos distintos describe el cliente con sus propias palabras.

``is_distinguished`` elige entre variantes de un mismo nombre. Cuando la búsqueda trae productos de nombres
distintos (en la suite variados, «ladrillos» trajo el ladrillo y el mortero, y «rodillo de 9 pulgadas» la bandeja
de 9 pulgadas), cada uno era el único de su nombre y se preguntaba una presentación que el cliente ya había dicho.
"""

from asistendero.tienda.catalogo.catalog import Product, tokens
from asistendero.tienda.catalogo.measures import UNITS, atom_support, contradicts, measures, split_atom
from asistendero.tienda.catalogo.search import CLAUSE_BREAK


def said_about(message: str, text: str) -> str:
    """La parte del mensaje que habla del artículo; sin coincidencias, todo el mensaje.

    Solo palabras del cliente: el texto de Grok sirve para ubicar la parte, nunca para elegir. Si no, «broca para
    concreto» escrito por Grok elegiría por el cliente que solo dijo «broca de 1/4».
    """
    words = tokens(text)
    clauses = [part for part in CLAUSE_BREAK.split(message) if part.strip()]
    best = max(clauses, key=lambda part: len(tokens(part) & words), default="")
    return best if words & tokens(best) else message


def _words(product: Product) -> list[set[str]]:
    # Sin sinónimos del lado del producto: «cuñete» tiene a «galón» de sinónimo y con él «10 galones» elegía el
    # cuñete de 5 galones. Los sinónimos sí amplían lo que dijo el cliente («foco» dice «bombillo»).
    return [forms for word in f"{product.name} {product.variant}".split() if (forms := tokens(word, synonyms=False))]


def _hits(said: set[str], product: Product) -> int:
    return sum(bool(forms & said) for forms in _words(product))


def described_whole(message: str, text: str, product: Product) -> bool:
    """El cliente dijo cada palabra del nombre y la variante («pintura vinilo beige» y «galones»)."""
    return _hits(tokens(said_about(message, text)), product) == len(_words(product))


def closest_named(message: str, text: str, products: list[Product]) -> list[Product]:
    """Los productos cuyo sustantivo nombró el cliente y que tienen más palabras de nombre y variante dichas.

    Si el cliente no nombró el de ninguno («2 de PVC de 1/2 para agua» puede ser el tubo o el codo), no queda
    ninguno y decide la unidad de venta o se pregunta. En un empate gana el único que el cliente describió entero
    («galón» frente a «cuñete de 5 galones»); si no hay uno solo, quedan todos los empatados.
    """
    said = tokens(said_about(message, text))
    named = [product for product in products if tokens(product.name.split()[0], synonyms=False) & said]
    hits = {product.sku: _hits(said, product) for product in named}
    best = max(hits.values(), default=0)
    leaders = [product for product in named if hits[product.sku] == best]
    whole = [product for product in leaders if hits[product.sku] == len(_words(product))]
    return whole if len(leaders) > 1 and len(whole) == 1 else leaders


def _variant_elements(product: Product) -> tuple[set[str], set[str]]:
    """Átomos de medida y palabras de la variante, sin sinónimos («cuñete» no es «galón»).

    Una palabra de unidad sale de las palabras solo si ya viaja en un átomo: en «cuñete de 5 galones» la
    lleva ``5gal``, pero en la variante «galón» es justo lo que la distingue.
    """
    atoms = measures(product.variant)
    atom_units = {split_atom(atom)[1] for atom in atoms}
    words = {
        word for word in tokens(product.variant, synonyms=False)
        if not any(char.isdigit() for char in word) and word not in {"x", "de"}
        and not (word in UNITS and UNITS[word] in atom_units)
    }
    return atoms, words


def _support(
    product: Product, common: tuple[set[str], set[str]], said_atoms: set[str], said_words: set[str],
) -> tuple[int, int] | None:
    """(puntos de lo que el mensaje dice de la variante, -rasgos propios que no dice), o None si no le cabe."""
    atoms, words = _variant_elements(product)
    if contradicts(atoms, said_atoms):
        return None
    contrast_atoms, contrast_words = atoms - common[0], words - common[1]
    supports = [atom_support(atom, said_atoms) for atom in contrast_atoms]
    supports += [2 if word in said_words else 0 for word in contrast_words]
    if sum(supports):
        return sum(supports), -supports.count(0)
    # Una variante sin rasgos propios frente a sus pares vale si el mensaje nombra algo de ella.
    if not supports and (words & said_words or atoms & said_atoms):
        return 0, 0
    return None


def is_distinguished(original: str, item_query: str, selected: Product, candidates: list[Product]) -> bool:
    """La variante es la única que el mensaje describe mejor entre las de su mismo nombre.

    Solo cuenta lo que dicen a la vez el mensaje original y el artículo que extrajo Grok. Las medidas se
    comparan como átomos (``measures``): «2 tornillos de 1/4 x 1» elige 1/4 x 1 aunque haya un 2 suelto.
    """
    original_numbers = {split_atom(atom)[0] for atom in measures(original)} | {
        atom for atom in measures(original) if "x" in atom.lstrip("#")}
    said_atoms = {atom for atom in measures(item_query) if atom in original_numbers or split_atom(atom)[0] in original_numbers}
    said_words = tokens(original, synonyms=False) & tokens(item_query, synonyms=False)
    group = [item for item in candidates if item.name == selected.name]
    elements = [_variant_elements(item) for item in group]
    # La medida también puede estar en el nombre («Cable THHN calibre 14 AWG»): pedir 12 AWG la contradice.
    if contradicts(measures(f"{selected.name} {selected.variant}"), said_atoms):
        return False
    if len(group) == 1:
        # Un producto único vale salvo que el mensaje dé otra medida en la misma unidad.
        return not contradicts(elements[0][0], said_atoms)
    common = (set.intersection(*(atoms for atoms, _ in elements)), set.intersection(*(words for _, words in elements)))
    scores = {item.sku: _support(item, common, said_atoms, said_words) for item in group}
    fitting = {sku: score for sku, score in scores.items() if score is not None}
    if not fitting:
        return False
    best = max(fitting.values())
    return [sku for sku, score in fitting.items() if score == best] == [selected.sku]
