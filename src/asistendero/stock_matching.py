"""Quién es cada producto y cada proveedor que nombró el tendero, y si habló de algo que ya llegó o que va a llegar.

Grok describe el producto con palabras; aquí se busca en el catálogo de la sede con las mismas reglas del agente de
clientes (``MockCatalog.search``, ``closest_named`` e ``is_distinguished``). Nunca se elige un parecido en silencio:
si el texto no distingue uno solo, se pregunta con hasta tres opciones. Un SKU que mande Grok solo vale si salió de
los pedidos abiertos que se le mostraron y el texto nombra ese producto.
"""

from contextlib import closing
from dataclasses import dataclass
import re
import sqlite3

from asistendero.catalog import MockCatalog, Product, covers, tokens
from asistendero.product_fit import closest_named, said_about
from asistendero.purchasing_rules import SUPPLIER_ID
from asistendero.search import ProductQuery, without_quantities
from asistendero.validation import is_distinguished, normalize_text


MAX_OPTIONS = 3
# Todas las variantes que empatan, no solo las primeras: con un tope corto, «galones de pintura» dejaba fuera los
# otros colores y quedaba una sola opción que nadie eligió.
SEARCH_LIMIT = 60
# Sobre texto normalizado. «mañana llegan», «el jueves traen», «van a mandar»: una llegada que todavía no pasó.
FUTURE_ARRIVAL = re.compile(
    r"\b(?:manana|pasado manana|la (?:otra|proxima) semana|(?:el|este|el proximo) (?:lunes|martes|miercoles|jueves"
    r"|viernes|sabado|domingo)|van a (?:llegar|traer|mandar|enviar|despachar)|llegaran|llegara|traeran|traera"
    r"|mandaran|mandara|enviaran|vendran|vendra)\b")
# «ya llegaron», «recibí», «trajeron»: lo dicho en pasado sí está en la bodega.
PAST_ARRIVAL = re.compile(r"\b(?:llegaron|llego|recibi|recibimos|recibieron|trajeron|trajo|mandaron|mando|enviaron"
                          r"|entregaron|entrego|dejaron|descargaron|ya llegan?)\b")


@dataclass(frozen=True)
class Match:
    """Un producto identificado (``product``) o el motivo por el que no se pudo (``warning``)."""

    product: Product | None
    warning: str | None = None


def _named(product: Product) -> str:
    return f"{product.name} {product.variant}"


def _mentions(text: str, product: Product) -> bool:
    return bool(tokens(text) & tokens(f"{_named(product)} {product.unit}"))


def _aliases(catalog: MockCatalog, skus: list[str]) -> dict[str, str]:
    """Términos de búsqueda de esos SKU, en solo lectura y filtrados por la sede del catálogo."""
    marks = ", ".join("?" * len(skus))
    with closing(sqlite3.connect(catalog.path.as_uri() + "?mode=ro", uri=True)) as connection:
        rows = connection.execute(f"SELECT sku, search_terms FROM products WHERE business_id = ? AND store_id = ? "
                                  f"AND sku IN ({marks})", (catalog.business_id, catalog.store_id, *skus))
        return {sku: terms.replace("|", " ") for sku, terms in rows}


def _covered(catalog: MockCatalog, text: str, products: list[Product]) -> list[Product]:
    """Los productos que tienen cada palabra que dijo el tendero: «tornillos de oro» no es cualquier tornillo.

    La búsqueda del agente de clientes acepta coincidencias parciales y luego pregunta; aquí una palabra sin
    respaldo descarta el producto, porque el cambio lo escribe el tendero en su bodega.
    """
    said = without_quantities(text)
    aliases = _aliases(catalog, [product.sku for product in products]) if products else {}
    return [product for product in products
            if covers(said, tokens(f"{_named(product)} {product.unit} {aliases.get(product.sku, '')}"))]


def identify(catalog: MockCatalog, message: str, operation: dict, offered: set[str], pending: set[str]) -> Match:
    """El producto de una operación.

    ``offered`` son los SKU de los pedidos abiertos que vio Grok; ``pending``, los que pueden desempatar: entre
    variantes que el texto no distingue («bultos de cemento» es el de 25 o el de 50 kg), la única que está pendiente
    en un pedido abierto es la que llegó o la que se reprograma.
    """
    text = operation["producto"]
    sku = operation.get("sku")
    if sku and sku in offered:
        product = catalog.get(sku)
        if product is not None and _mentions(text, product):
            return Match(product)
    result = catalog.search(ProductQuery(text=text), limit=SEARCH_LIMIT)
    candidates = _covered(catalog, text, list(result.matches))
    if not candidates:
        return Match(None, f"No identifiqué «{text}» en el catálogo; escríbelo como aparece en el inventario.")
    # «los 5 galones de pintura» es cuánto llegó, no el cuñete de 5 galones; «cuñete de 5 galones» sí es medida.
    said = without_quantities(message)
    leaders = closest_named(said, text, candidates) or candidates
    chosen = leaders if len(leaders) == 1 else [item for item in leaders if is_distinguished(said, text, item,
                                                                                            leaders)]
    if len(chosen) != 1:
        waiting = [item for item in (chosen or leaders) if item.sku in pending]
        chosen = waiting if len(waiting) == 1 else chosen
    if len(chosen) == 1:
        return Match(chosen[0])
    options = ", ".join(_named(item) for item in (chosen or leaders)[:MAX_OPTIONS])
    return Match(None, f"¿Cuál de estos es «{text}»?: {options}. Dilo con la medida o la presentación.")


def find_supplier(suppliers: list[dict], text: str | None) -> tuple[dict | None, str | None]:
    """(proveedor, advertencia): por código PV-001, nombre exacto o el único cuyo nombre contiene lo dicho."""
    if not text:
        return None, None
    key = normalize_text(text.strip())
    if SUPPLIER_ID.match(text.strip()):
        exact = [item for item in suppliers if item["proveedor"] == text.strip()]
    else:
        exact = [item for item in suppliers if normalize_text(item["nombre"]) == key]
    said = tokens(text)
    found = exact or [item for item in suppliers if said and (said <= tokens(item["nombre"])
                                                              or tokens(item["nombre"]) <= said)]
    if len(found) == 1:
        return found[0], None
    if found:
        names = ", ".join(item["nombre"] for item in found[:MAX_OPTIONS])
        return None, f"¿Cuál proveedor es «{text}»?: {names}."
    return None, f"No tengo el proveedor «{text}»; agrégalo en Abastecimiento y vuelve a contármelo."


def sounds_future(message: str, product_text: str) -> bool:
    """La parte del mensaje que habla del producto anuncia una llegada y no dice que ya llegó."""
    clause = normalize_text(said_about(message, product_text))
    return bool(FUTURE_ARRIVAL.search(clause)) and not PAST_ARRIVAL.search(clause)
