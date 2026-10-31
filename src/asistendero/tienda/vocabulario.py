"""Vocabulario común de la tienda: cómo se escribe un SKU, cómo se compara un texto y cómo se muestra un precio.

Lo usan la tienda (inventario, abastecimiento, categorías) y el agente (reglas y respuestas). Vive en la tienda
porque es el idioma del catálogo; el agente lo toma de aquí y la tienda nunca importa al agente.
"""

import re
import unicodedata

SKU_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,31}$")


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def format_cop(value: int) -> str:
    return f"${value:,}".replace(",", ".")
