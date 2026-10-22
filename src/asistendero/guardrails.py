"""Barreras ante preguntas trampa e información delicada, aplicadas en código antes y después de Grok.

El prompt le pide a Grok no revelar instrucciones ni datos internos, pero esa orden no es una garantía.
Aquí está la defensa decisiva:

- ``screen_message`` quita del mensaje las frases que piden algo que el agente nunca entrega (sus
  instrucciones, la llave, datos internos, datos de otras personas o cifras privadas del negocio) y tapa
  los datos personales. Esas frases no llegan a Grok, a la traza ni a la memoria de la sesión.
- ``leaks`` revisa la respuesta final: si trae un fragmento del prompt, una llave o un dato interno, se
  descarta la redacción de Grok.
"""

from dataclasses import dataclass, field
import os
import re
import unicodedata


# Cada tema delicado, la regla que lo detecta y la respuesta fija que recibe el cliente.
SENSITIVE_TOPICS = {
    "PROMPT_DISCLOSURE": (
        r"\b(?:system\s*prompt|prompt|instrucciones\s+(?:internas|del\s+sistema|de\s+sistema|ocultas|originales)"
        r"|tus\s+(?:instrucciones|reglas|directrices|politicas)|configuracion\s+(?:interna|del\s+(?:agente|bot|sistema))"
        r"|modo\s+(?:desarrollador|developer|debug|dios)|jailbreak|\bdan\b)",
        "No puedo compartir mis instrucciones ni mi configuración interna.",
    ),
    "CREDENTIALS": (
        r"\b(?:api[\s_-]*key|llave\s+(?:de\s+(?:la\s+)?)?(?:api|grok|acceso|del\s+reto)|token|contrasen\w*|password"
        r"|clave\s+(?:de\s+(?:acceso|la\s+api|grok|administrador|admin|wifi)|secreta)|credencial\w*|grok_api_key)|(?<!\w)\.env\b",
        "No comparto llaves, contraseñas ni credenciales.",
    ),
    "INTERNAL_DATA": (
        r"\b(?:base\s+de\s+datos|sqlite|consulta\s+sql|\bsql\b|codigo\s+fuente|archivos?\s+internos?"
        r"|esquema\s+de\s+(?:la\s+)?base|servidor\s+(?:interno|de\s+la\s+tienda)|variables?\s+de\s+entorno|logs?\s+del\s+sistema)",
        "No puedo dar detalles técnicos internos del sistema.",
    ),
    "THIRD_PARTY_DATA": (
        r"\b(?:(?:datos|telefonos?|celular(?:es)?|direcci\w+|correos?|cedulas?|nombres?|compras?|pedidos?|historial)"
        r"\s+(?:del?\s+)?(?:los\s+|las\s+|la\s+|otros?\s+|otras?\s+|mis?\s+)?(?:clientes?|usuarios?|vecinos?|emplead\w+|trabajador\w*|duen\w+|propietari\w+)"
        r"|que\s+(?:compro|compraron|pidio|pidieron)\s+(?:el|la|los|las|otro|otra|otros|mi\s+vecin\w+)"
        r"|quien\s+(?:compro|compraron|pidio))",
        "No comparto datos de otros clientes ni del personal de la tienda.",
    ),
    "BUSINESS_PRIVATE": (
        r"\b(?:precio\s+de\s+(?:compra|costo|fabrica)|costo\s+(?:de\s+compra|real|interno)|margen(?:es)?"
        r"|ganancias?|utilidad(?:es)?\s+(?:de\s+la\s+tienda|del\s+negocio)|cuanto\s+(?:les|le)\s+(?:cuesta|costo)\s+a\s+ustedes"
        r"|proveedor(?:es)?|ventas\s+(?:del\s+(?:dia|mes)|de\s+hoy)|cuanto\s+(?:vende\w*|vendi\w*|gana\w*)|cuadre\s+de\s+caja)",
        "No tengo información privada del negocio, como costos, márgenes, proveedores o ventas.",
    ),
}
_TOPIC_PATTERNS = {code: re.compile(pattern) for code, (pattern, _) in SENSITIVE_TOPICS.items()}
# Frases cortas sin pedido de producto que pueden quedar tras quitar la parte delicada («hola», «por favor»).
FILLER = re.compile(r"^(?:\W|hola|buen[oa]s?\s*(?:dias|tardes|noches)?|por\s+favor|gracias|y|tambien|ademas|ok|oye|porfa)*$")
# El punto corta frase solo si lo sigue un espacio o el final: «$1.000» y «.env» no se parten.
SENTENCE_SPLIT = re.compile(r"(?<=[?!;\n])\s*|(?<=\.)(?=\s|$)\s*|,\s+(?=(?:y\s+)?(?:dime|dame|muestra|revela|ensena|pasame|cual|que|cuanto|quien)\b)")

# Datos personales que el cliente puede escribir y que no hacen falta para cotizar.
PERSONAL_DATA = [
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    re.compile(r"(?<![\d$.,])(?:\+?57\s?)?3\d{2}[\s-]?\d{3}[\s-]?\d{4}(?![\d])"),
    re.compile(r"\b(?:c\.?\s?c\.?|cedula|nit|documento)\s*(?:no\.?|numero|#)?\s*:?\s*[\d.\s-]{6,15}\d", re.I),
    re.compile(r"(?<![\d$.,])\d(?:[\s-]?\d){12,18}(?!\d)"),
]
REDACTED = "[dato personal omitido]"


@dataclass(frozen=True)
class Screening:
    """Resultado de revisar un mensaje antes de mandarlo a Grok."""

    consulta: str
    codes: tuple[str, ...] = ()
    redacted: bool = False
    removed: tuple[str, ...] = field(default=(), repr=False)

    @property
    def refusal(self) -> str:
        """Respuesta fija para la parte del mensaje que no se atiende; vacía si no hubo nada delicado."""
        return " ".join(SENSITIVE_TOPICS[code][1] for code in self.codes)


def _plain(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def sensitive_topics(text: str) -> list[str]:
    plain = _plain(text)
    return [code for code, pattern in _TOPIC_PATTERNS.items() if pattern.search(plain)]


def redact_personal_data(text: str) -> tuple[str, bool]:
    redacted = text
    for pattern in PERSONAL_DATA:
        redacted = pattern.sub(REDACTED, redacted)
    return redacted, redacted != text


def screen_message(message: str) -> Screening:
    """Quita las frases delicadas y tapa los datos personales; lo que queda es lo que ve Grok."""
    text, redacted = redact_personal_data(message)
    kept, removed, codes = [], [], []
    for sentence in SENTENCE_SPLIT.split(text):
        if not sentence or not sentence.strip():
            continue
        found = sensitive_topics(sentence)
        if found:
            removed.append(sentence.strip())
            codes.extend(code for code in found if code not in codes)
        else:
            kept.append(sentence.strip())
    remainder = " ".join(kept).strip(" ,;")
    if FILLER.match(_plain(remainder)):
        remainder = ""
    return Screening(remainder if codes else text.strip() if not remainder else remainder,
                     tuple(codes), redacted, tuple(removed))


# Lo que nunca debe aparecer en una respuesta al cliente, aunque Grok lo escriba.
INTERNAL_MARKERS = re.compile(
    r"grok_api_key|api\.reto\.pltk|mock_catalog|\.sqlite|search_terms|business_id|store_id|prompt_version"
    r"|buscar_productos|consultar_disponibilidad|calcular_cotizacion|consultar_info_tienda|explorar_categoria"
    r"|_not_grounded|_required\b|\b(?:xai|sk)-[a-z0-9_-]{8,}",
)
SHINGLE = 7


def _shingles(text: str) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z0-9]+", _plain(text))
    return {tuple(words[index:index + SHINGLE]) for index in range(len(words) - SHINGLE + 1)}


def leaks(reply: str, prompt: str) -> bool:
    """True si la respuesta trae un fragmento del prompt, la llave configurada o un dato interno."""
    plain = _plain(reply)
    if INTERNAL_MARKERS.search(plain):
        return True
    key = os.getenv("GROK_API_KEY", "").strip()
    if len(key) >= 8 and key.casefold() in reply.casefold():
        return True
    # Siete palabras seguidas del prompt no aparecen por casualidad en una respuesta de ferretería.
    return bool(_shingles(reply) & _prompt_shingles(prompt))


_PROMPT_CACHE: dict[str, set[tuple[str, ...]]] = {}


def _prompt_shingles(prompt: str) -> set[tuple[str, ...]]:
    if prompt not in _PROMPT_CACHE:
        _PROMPT_CACHE[prompt] = _shingles(prompt)
    return _PROMPT_CACHE[prompt]
