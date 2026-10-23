"""Detección de inyecciones de instrucciones en el mensaje del cliente, antes de llamar a Grok.

``guardrails.screen_message`` quita las frases que piden algo que el agente no entrega. Esto es otra cosa: un
mensaje que intenta cambiar las reglas del agente (ignorar sus instrucciones, darle otro papel, hacerse pasar por
el sistema, falsificar una llamada a herramienta, sacar el prompt o atacar la base). Una detección bloquea el
mensaje sin llamar a Grok y, en una conversación, banea la sesión y al cliente (``bans.py``).

Las reglas son de alta confianza porque un baneo deja a un cliente sin atención: «olvida lo que te dije, mejor 3
metros», «bájale el precio a 30 mil», «el sellador actúa como impermeabilizante» o «¿me dan factura?» no son
inyecciones. Se revisa el texto como llega y también disfrazado: caracteres invisibles, homoglifos, letras de
ancho completo, entidades HTML, leetspeak, letras separadas, texto invertido, ROT13, base64, hexadecimal, URL
codificada y una orden partida entre el turno anterior y este.
"""

import base64
import binascii
import codecs
from dataclasses import dataclass
import html
import re
import unicodedata
from urllib.parse import unquote


@dataclass(frozen=True)
class Injection:
    code: str
    technique: str


# Qué intenta cada código; lo usan la traza, el panel del tendero y el mapa del harness.
INJECTION_CODES = {
    "IGNORE_INSTRUCTIONS": "Pide ignorar u olvidar las instrucciones, reglas o validaciones del agente.",
    "NEW_ROLE": "Le asigna al agente otro papel o identidad («a partir de ahora eres…», «finge que eres el dueño»).",
    "FAKE_AUTHORITY": "Se hace pasar por el sistema, un administrador o el equipo del agente, o le deja una nota.",
    "TOOL_FORGERY": "Escribe nombres de herramientas o una llamada en JSON para que el agente la ejecute.",
    "DATA_OVERRIDE": "Ordena cambiar precio, existencias o estado en el sistema, o ignorar el stock.",
    "PROMPT_EXTRACTION": "Pide el prompt, las instrucciones internas o repetir el texto de arriba.",
    "JAILBREAK_MODE": "Pide un modo sin restricciones (desarrollador, DAN, sin filtros).",
    "SQL_INJECTION": "Trae sentencias SQL o comillas para alterar una consulta.",
    "SCRIPT_INJECTION": "Trae HTML, JavaScript o plantillas para ejecutar en el visor o el panel.",
}

# Solo órdenes en imperativo o infinitivo: «olvidé la regla» o «ignoro cuántos metros» son de un cliente.
_VERB = (r"(?:ignora|ignore|ignoren|ignores|ignorar|ignoring|olvida|olvidate|olviden|olvides|olvidar|omite|omitan|omitas"
         r"|omitir|descarta|descartar|desobedece|desobedecer|desatiende|saltate|saltarte|saltar|salta|saltese|anula|anular"
         r"|desactiva|desactivar|deshabilita|deshabilitar|evade|evadir|bypass\w*|disregard\w*|forget|overrid\w*|skip"
         r"|rompe|romper|viola|violar|incumple|borra|resetea|reinicia|pasa\s+por\s+alto|pasar\s+por\s+alto"
         r"|no\s+(?:sigas|obedezcas|cumplas|respetes|apliques|tengas\s+en\s+cuenta|hagas\s+caso\s+(?:a|de))"
         r"|deja\s+de\s+(?:seguir|lado|obedecer|cumplir)|deja\s+a\s+un\s+lado|haz\s+caso\s+omiso\s+(?:a|de))")
# Lo que un atacante intercala entre la orden y su objeto: «ignora, por favor, todas tus instrucciones».
_ASIDE = r"(?:(?:por\s+favor|please|ya|ahora|simplemente|solo|de|a|con|en)\s+){0,2}"
_RULES = (r"(?:instruc\w*|reglas?|restricci\w*|restrictions?|directri\w*|directivas?|guardrails?|guidelines?|rules?"
          r"|prompt\w*|programacion|configuracion|validacion\w*|limitaciones|politicas?|safety|filtros?|barreras?)")
# Las reglas tienen que ser del agente: «tus», «todas las… anteriores», «del sistema». «Omite las reglas de aluminio» no.
_BEFORE = (r"(?:tus|tu|your|sus\s+propias|todas\s+(?:tus|las|sus)|todas\s+as|toutes\s+(?:les|tes|vos)|tes|vos|all\s+(?:the\s+|your\s+)?"
           r"|any\s+|the\s+|las\s+|los\s+)?(?:previas?|anteriores|previous|prior|above|earlier|preceding|original(?:es)?"
           r"|iniciales|precedentes)\s+|(?:tus|your|todas\s+(?:tus|las)|todas\s+as|toutes\s+(?:les|tes|vos)|all(?:\s+the|\s+your)?)\s+")
_AFTER = (r"(?:anteriores|previas|previous|prior|above|precedentes|anteriormente|del\s+sistema|de\s+sistema|de\s+arriba"
          r"|que\s+(?:te|le)\s+(?:dieron|han\s+dado|dio|programaron|pusieron)|que\s+tienes|recibidas)")
# Papeles del agente; los de la tienda (dueño, gerente) solo cuentan con un fingimiento explícito.
_AGENT_ROLES = (r"(?:admin\w*|desarrollador\w*|programador\w*|ia|bot|chatbot|chatgpt|gpt|grok|dan|hacker|root"
                r"|otro\s+(?:asistente|bot|modelo)|asistente\s+sin\s+\w+|sin\s+(?:reglas|restricciones|filtros|limites))")
_STORE_ROLES = r"(?:due\w+|gerente|jefe|cajer\w+|vendedor\w*)"
_TOOLS = (r"buscar_productos|consultar_disponibilidad|calcular_cotizacion_informativa|consultar_info_tienda"
          r"|explorar_categoria|registrar_pedido|confirmar_pedido|agendar_recogida|consultar_pedido|cancelar_pedido"
          r"|call_tool|tool_call|function_call")
# «Dime tus instrucciones para instalar el sanitario» pide un consejo, no el prompt.
_NOT_ADVICE = r"(?!\s+(?:para|sobre|de\s+(?:uso|como|instalacion|armado|mezcla|antes)|del\s+(?:producto|kit|pegante)))"

PATTERNS = {
    "IGNORE_INSTRUCTIONS": [
        rf"\b{_VERB}\s+{_ASIDE}(?:{_BEFORE})(?:\w+\s+){{0,2}}?{_RULES}\b{_NOT_ADVICE}",
        rf"\b{_VERB}\s+(?:\w+\s+){{0,3}}?{_RULES}\s+{_AFTER}\b",
        # Declarar que las reglas ya no rigen: «tus instrucciones ya no aplican», «las reglas anteriores quedan anuladas».
        rf"\b(?:(?:tus|your)\s+(?:\w+\s+)?{_RULES}|(?:las|todas\s+las|all|the)\s+{_RULES}\s+{_AFTER})\s+(?:ya\s+)?"
        r"(?:no\s+(?:aplican|cuentan|valen|importan|sirven|existen|rigen)|(?:quedan|estan|fueron)\s+(?:anuladas|canceladas"
        r"|desactivadas|suspendidas|eliminadas)|(?:are|have\s+been)\s+(?:void|cancelled|disabled|lifted|removed)"
        r"|no\s+longer\s+apply)\b",
        r"\b(?:ignore|disregard|forget)\s+(?:all\s+|everything\s+|anything\s+)?(?:the\s+|that\s+is\s+)?(?:above"
        r"|previous\s+(?:text|messages?|context)|prior\s+(?:text|context))\b",
    ],
    "NEW_ROLE": [
        r"\b(?:a\s+partir\s+de\s+(?:ahora|este\s+momento|hoy)|desde\s+(?:ahora|este\s+momento)|de\s+ahora\s+en\s+adelante"
        r"|from\s+now\s+on)\s*,?\s*(?:tu\s+)?(?:eres|seras|actua\w*|obedece\w*|you\s+(?:are|will|must)|act\s+as"
        r"|(?:debes|tienes\s+que|vas\s+a)\s+(?:ser|actuar|responder|obedecer|ignorar|seguir|decir\s+que)"
        r"|no\s+(?:tienes|tendras|sigues|hay)\s+(?:reglas|restricciones|limites|filtros))",
        r"\b(?:you\s+are\s+now|you\s+are\s+no\s+longer|act\s+as\s+(?:a|an|the|if)|pretend\s+(?:to\s+be|you\s+are|that\s+you)"
        r"|role[\s-]?play)\b",
        rf"\b(?:ahora\s+eres|ya\s+no\s+eres|eres\s+ahora|deja\s+de\s+ser)\s+(?:un|una|el|la|mi|tu)?\s*(?:{_AGENT_ROLES}|{_STORE_ROLES})\b",
        rf"\b(?:finge|fingir|simula|simular|imagina|haz\s+de\s+cuenta|hagamos\s+de\s+cuenta|juguemos\s+a|comportate"
        rf"|actua|actuar)\w*\s+(?:que\s+)?"
        rf"(?:eres|seas|fueras|ser|como\s+(?:si\s+fueras|un|una|el|la|mi))\s+(?:\w+\s+){{0,2}}?{_AGENT_ROLES}\b",
        rf"\b(?:finge|fingir|haz\s+de\s+cuenta|hagamos\s+de\s+cuenta|pretend)\w*\s+(?:que\s+)?(?:eres|seas|fueras|ser|you\s+are)"
        rf"\s+(?:\w+\s+){{0,2}}?(?:{_STORE_ROLES}|owner|manager|admin\w*)\b",
        r"\beres\s+dan\b|\bdo\s+anything\s+now\b",
    ],
    "FAKE_AUTHORITY": [
        # Una etiqueta de rol solo al empezar una frase o entre corchetes: «es para el sistema: 3 metros» es un cliente.
        r"(?:^|[.!?;:\n]\s*|[\[\(<{|#*>\"'`]\s*)(?:sistema|system|sys|admin|administrador|developer|desarrollador|root"
        r"|assistant)\s*(?:\]|>|:|\)|\||\})",
        r"(?<!\bel\s)(?<!\bdel\s)(?<!\bal\s)(?<!\bun\s)(?<!\bmi\s)(?<!\btu\s)(?<!\bsu\s)(?<!\bese\s)(?<!\beste\s)"
        r"(?<!\bnuestro\s)\bsistema\s+(?:cambia|marca|confirma|actualiza|ordena|autoriza|aprueba|establece|fija|anula"
        r"|cancela|aplica|asigna|elimina|borra)\b",
        r"<\|[a-z_]+\|>|\[/?inst\]|\[/?sys\]|<<\s*/?sys\s*>>|#{2,}\s*(?:system|instruction|sistema|instrucciones)"
        r"|```\s*(?:system|sistema)|<\s*/?\s*(?:system|sistema|instructions?|instrucciones|admin)\s*>",
        r"\bsoy\s+(?:tu|el|la)\s+(?:admin\w*|desarrollador\w*|programador\w*|creador\w*|operador\w*|supervisor\w*|due\w+)"
        r"\s+(?:del|de\s+este|de\s+esta)\s+(?:sistema|bot|agente|asistente|chat|ia|modelo)\b",
        r"\bsoy\s+tu\s+(?:admin\w*|desarrollador\w*|programador\w*|creador\w*|operador\w*)\b",
        r"\b(?:soy|somos)\s+(?:de|del\s+equipo\s+de)\s+(?:platica|xai|openai|anthropic)\b",
        r"\b(?:nuevas\s+instrucciones|new\s+instructions|instrucciones\s+actualizadas|updated\s+instructions"
        r"|orden\s+(?:del|de)\s+(?:sistema|administrador)|mensaje\s+(?:del|de)\s+(?:sistema|administrador)"
        r"|tienes\s+(?:permiso|autorizacion)\s+(?:especial|de\s+(?:admin\w*|root))"
        r"|te\s+autorizo\s+a\s+(?:ignorar|saltar|omitir|cambiar|desactivar)\w*|nuevo\s+prompt|new\s+prompt"
        r"|system\s+override|admin\s+override|override\s+(?:mode|protocol|del\s+sistema))\b",
        # Una conversación inventada: el cliente escribe también lo que «respondió» el asistente.
        r"\b(?:cliente|usuario|user|human|humano)\s*:[\s\S]{0,400}?\b(?:asistente|assistant|ai|bot|agente|asistendero)\s*:",
        r"\b(?:nota|mensaje|aviso|instruccion|orden|recordatorio|note|message)\s+(?:para|al|for|to)\s+(?:el\s+|la\s+|the\s+)?"
        r"(?:asistente|ia|modelo|bot|agente|ai|assistant|model|grok|llm|chatbot)\b",
    ],
    "TOOL_FORGERY": [
        rf"\b(?:{_TOOLS})\b",
        r"[\"']\s*(?:action|tool|tool_name|arguments|function|tool_calls|role)\s*[\"']\s*:",
    ],
    "DATA_OVERRIDE": [
        r"\b(?:precio|price|stock|existencias|inventario|descuento|discount|estado|status|reservation_created)_?\w*\s*(?:=|:=|=>|->)\s*[\w$\"']",
        r"\b(?:actualiza|modifica|cambia|edita|altera|sobrescribe|reescribe|update|change|set|overwrite)\w*\s+(?:el\s+|la\s+|los\s+"
        r"|las\s+|tu\s+|su\s+|the\s+)?(?:precio|precios|stock|inventario|existencias|base\s+de\s+datos|catalogo|price|prices"
        r"|database|catalog)\s+(?:en|del|de\s+la|de|in|of)\s+(?:el\s+|la\s+|the\s+)?(?:sistema|base|catalogo|bd|database|system|servidor)\b",
    ],
    "PROMPT_EXTRACTION": [
        r"\b(?:system\s*prompt|prompt\s+(?:del\s+sistema|de\s+sistema|inicial|original|oculto|completo)|tu\s+prompt|el\s+prompt"
        r"|mensaje\s+(?:de|del)\s+sistema|instrucciones\s+(?:internas|del\s+sistema|de\s+sistema|ocultas|secretas)"
        r"|tus\s+instrucciones\s+(?:originales|iniciales|exactas|completas|internas)|initial\s+prompt"
        r"|hidden\s+(?:prompt|instructions))\b",
        r"\b(?:repite|repetir|repeat|imprime|print|muestra\w*|show|copia|copy|pega|paste|escribe|write|revela\w*|reveal|recita"
        r"|dime|tell\s+me|output|traduce|translate)\s+(?:me\s+)?(?:todo\s+|all\s+|literalmente\s+|verbatim\s+|exactamente\s+)?"
        r"(?:lo\s+que\s+(?:esta|hay|dice|dicen|aparece)\s+(?:escrito\s+)?(?:arriba|antes|al\s+principio|en\s+tu\s+(?:mensaje|contexto))"
        r"|el\s+texto\s+(?:de\s+)?(?:arriba|anterior|inicial)|las\s+palabras\s+(?:de\s+)?arriba|(?:the\s+)?(?:text|words|everything)\s+above"
        rf"|tus\s+instrucciones{_NOT_ADVICE}|your\s+(?:instructions|prompt|rules)|tu\s+configuracion"
        r"|las\s+instrucciones\s+que\s+(?:te\s+dieron|recibiste|tienes))",
        rf"\b(?:cuales\s+son\s+tus\s+instrucciones{_NOT_ADVICE}|what\s+are\s+your\s+instructions)",
    ],
    "JAILBREAK_MODE": [
        r"\b(?:modo|mode)\s+(?:desarrollador|developer|debug|depuracion|dios|god|admin\w*|root|sudo|sin\s+restricciones"
        r"|sin\s+filtros?|sin\s+censura|jailbreak|dan|unrestricted|unfiltered)\b",
        r"\bjailbreak\w*|\bdeveloper\s+mode\b|\bdan\s+mode\b|\bsudo\s+[a-z]",
        r"\b(?:responde|responder|contesta|habla|actua|answer|respond|reply)\w*\s+(?:\w+\s+){0,2}?sin\s+(?:restricciones"
        r"|filtros?|censura|reglas|limites|limitaciones)\b|\bwithout\s+(?:any\s+)?(?:restrictions|filters|rules|limits)\b",
    ],
    "SQL_INJECTION": [
        r"\b(?:drop|truncate)\s+(?:table|database)\b|\bdelete\s+from\b|\binsert\s+into\b|\bupdate\s+\w+\s+set\b"
        r"|\bunion\s+(?:all\s+)?select\b|\bselect\s+[\w*,\s]+\s+from\b|'\s*or\s+'?\d+'?\s*=\s*'?\d+|\bor\s+1\s*=\s*1\b"
        r"|;\s*--|\bxp_cmdshell\b|\bsleep\s*\(\s*\d+\s*\)|\bpragma\s+\w+",
    ],
    "SCRIPT_INJECTION": [
        r"<\s*/?\s*(?:script|iframe|img|svg|object|embed|style|body)\b|\bjavascript\s*:|\bon(?:error|load|click|mouseover)\s*="
        r"|\{\{.*\}\}|\$\{.*\}|<%.*%>",
    ],
}
_COMPILED = [(code, re.compile(pattern)) for code, patterns in PATTERNS.items() for pattern in patterns]

# Letras separadas («i g n o r a  t u s  i n s t r u c c i o n e s»): se juntan y se buscan estas raíces.
SPACED_RUN = re.compile(r"(?:\b\w\b[^\w\n]{1,3}){4,}\b\w\b")
SQUASHED = re.compile(
    r"(?:ignor|olvid|omit|disregard|forget)\w{0,14}(?:instruc|regla|rules|prompt|restric)|systemprompt|promptdelsistema"
    r"|mododesarrollador|developermode|jailbreak|doanythingnow|nuevasinstrucciones|newinstructions|modosinrestricciones"
)
INVISIBLE = re.compile("[­͏؜ᅟᅠ឴឵᠎​-‏‪-‮⁠-⁤⁦-⁯﻿]")
HOMOGLYPHS = str.maketrans({
    "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p", "с": "c", "т": "t", "у": "y",
    "х": "x", "і": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "ɡ": "g", "ӏ": "l", "ԛ": "q", "ԝ": "w",
    "А": "a", "В": "b", "Е": "e", "К": "k", "М": "m", "Н": "h", "О": "o", "Р": "p", "С": "c", "Т": "t", "Х": "x",
    "І": "i", "Ј": "j", "Ѕ": "s",
    "α": "a", "ο": "o", "ρ": "p", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "τ": "t", "υ": "u", "χ": "x",
    "Α": "a", "Β": "b", "Ε": "e", "Ι": "i", "Κ": "k", "Μ": "m", "Ν": "n", "Ο": "o", "Ρ": "p", "Τ": "t", "Χ": "x",
})
LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i", "|": "l"})
# Etiquetas Unicode (U+E0020 a U+E007E): invisibles en pantalla, cada una es una letra ASCII escondida.
TAGS = re.compile("[\U000E0000-\U000E007F]")
SEPARATORS = re.compile(r"[._\-*~·•,;'\"=+|/\\]+")
ENCODED = re.compile(r"[A-Za-z0-9+/_-]{16,}={0,2}")
MAX_DECODED = 4


def plain(text: str) -> str:
    """Minúsculas ASCII sin tildes, sin caracteres invisibles y con homoglifos y ancho completo resueltos."""
    text = unicodedata.normalize("NFKC", html.unescape(text))
    text = TAGS.sub("", INVISIBLE.sub("", text)).translate(HOMOGLYPHS).casefold()
    return "".join(char for char in unicodedata.normalize("NFKD", text) if not unicodedata.combining(char))


def _decoded(text: str) -> list[str]:
    """Segmentos en base64 o hexadecimal que se leen como texto: un atacante esconde ahí la orden."""
    found = []
    for token in ENCODED.findall(text)[:MAX_DECODED]:
        raw = None
        if re.fullmatch(r"(?:[0-9a-fA-F]{2})+", token):
            raw = bytes.fromhex(token)
        else:
            try:
                raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_" if "-" in token or "_" in token else None)
            except (binascii.Error, ValueError):
                continue
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if decoded.isprintable() and sum(char.isalpha() for char in decoded) >= len(decoded) // 2:
            found.append(decoded)
    return found


def _match(text: str) -> str | None:
    return next((code for code, pattern in _COMPILED if pattern.search(text)), None)


def _variants(message: str) -> list[tuple[str, str]]:
    base = plain(message)
    # Tildes y mayúsculas son escritura normal; solo es «disfrazado» lo que cambió por invisibles, homoglifos o entidades.
    simple = "".join(char for char in unicodedata.normalize("NFD", message.casefold()) if not unicodedata.combining(char))
    variants = [("texto" if base == simple else "disfrazado", base)]
    hidden = "".join(chr(ord(char) - 0xE0000) for char in TAGS.findall(message))
    if hidden:
        variants.append(("etiquetas ocultas", plain(hidden)))
    variants += [("separadores", " ".join(SEPARATORS.sub(" ", base).split())),
                 ("letras separadas", SPACED_RUN.sub(lambda run: re.sub(r"[^a-z0-9]", "", run.group()), base)),
                 ("url", plain(unquote(message))), ("leetspeak", base.translate(LEET)),
                 ("invertido", base[::-1]), ("rot13", codecs.encode(base, "rot13"))]
    variants += [("codificado", plain(decoded)) for decoded in _decoded(message)]
    return variants


def detect_injection(message: str, previous: str = "") -> Injection | None:
    """La inyección del mensaje con su técnica, o None. ``previous`` es el turno anterior del cliente."""
    for technique, text in _variants(message):
        code = _match(text)
        if code:
            return Injection(code, technique)
        for run in SPACED_RUN.findall(text):
            if SQUASHED.search(re.sub(r"[^a-z]", "", run)):
                return Injection("IGNORE_INSTRUCTIONS", "letras separadas")
    if previous:
        # Una orden partida entre dos mensajes («ignora tus» / «instrucciones y…») solo aparece al juntarlos.
        code = _match(f"{plain(previous)} {plain(message)}")
        if code and not _match(plain(previous)):
            return Injection(code, "partida en turnos")
    return None


BLOCKED_REPLY = ("Tu mensaje trae instrucciones para cambiar cómo funciono y no las sigo: precios, existencias y "
                 "pedidos salen solo del catálogo y de lo que pides como cliente.")


def blocked_reply(context: dict | None) -> str:
    """Respuesta fija sin Grok; en una conversación avisa el bloqueo y los pedidos que se cancelan."""
    if context is None:
        return BLOCKED_REPLY
    active = [order["pedido"] for order in context.get("pedidos") or [] if order.get("estado") in ("pendiente", "confirmado")]
    cancelled = f" y se cancelan tus pedidos apartados ({', '.join(active)})" if active else ""
    return (f"{BLOCKED_REPLY} Por seguridad, esta conversación queda bloqueada{cancelled}. Si fue un error, "
            "pídele al tendero en el mostrador que la desbloquee.")
