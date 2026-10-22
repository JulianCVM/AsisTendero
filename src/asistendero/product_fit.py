"""Cuál de varios productos distintos describe el cliente con sus propias palabras.

``is_distinguished`` elige entre variantes de un mismo nombre. Cuando la búsqueda trae productos de nombres
distintos (en la suite variados, «ladrillos» trajo el ladrillo y el mortero, y «rodillo de 9 pulgadas» la bandeja
de 9 pulgadas), cada uno era el único de su nombre y se preguntaba una presentación que el cliente ya había dicho.
"""

from asistendero.catalog import Product, tokens
from asistendero.search import CLAUSE_BREAK


def said_about(message: str, text: str) -> str:
    """La parte del mensaje que habla del artículo; sin coincidencias, todo el mensaje.

    Solo palabras del cliente: el texto de Grok sirve para ubicar la parte, nunca para elegir. Si no, «broca para
    concreto» escrito por Grok elegiría por el cliente que solo dijo «broca de 1/4».
    """
    words = tokens(text)
    clauses = [part for part in CLAUSE_BREAK.split(message) if part.strip()]
    best = max(clauses, key=lambda part: len(tokens(part) & words), default="")
    return best if words & tokens(best) else message


def closest_named(message: str, text: str, products: list[Product]) -> list[Product]:
    """Los productos cuyo sustantivo nombró el cliente y que tienen más palabras de nombre y variante dichas.

    Si el cliente no nombró el de ninguno («2 de PVC de 1/2 para agua» puede ser el tubo o el codo), quedan todos
    y se pregunta. En un empate gana el único que el cliente describió entero («galón» frente a «cuñete de 5
    galones»); si no hay uno solo, quedan todos.
    """
    # Los sinónimos amplían lo que dijo el cliente («foco» dice «bombillo»), no el producto: «cuñete» tiene a
    # «galón» de sinónimo y con él «10 galones» elegía el cuñete de 5 galones.
    said = tokens(said_about(message, text))
    products = [product for product in products if tokens(product.name.split()[0], synonyms=False) & said]
    if not products:
        return []
    described = {product.sku: [tokens(word, synonyms=False) for word in f"{product.name} {product.variant}".split()]
                 for product in products}
    described = {sku: [forms for forms in words if forms] for sku, words in described.items()}
    hits = {sku: sum(bool(forms & said) for forms in words) for sku, words in described.items()}
    best = max(hits.values(), default=0)
    leaders = [product for product in products if hits[product.sku] == best]
    exact = [product for product in leaders if hits[product.sku] == len(described[product.sku])]
    return exact if len(leaders) > 1 and len(exact) == 1 else leaders
