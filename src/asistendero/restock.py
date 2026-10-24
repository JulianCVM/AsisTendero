"""Surtido: cuándo vuelve a llegar un producto o si ya no se trae, según lo que anotó el tendero.

Un cliente de barrio pregunta «veci, ¿cuándo le llegan más?» o «¿ya no van a traer de ese?». El dato lo pone el
tendero en su panel (``inventory.Inventory.update`` con ``surtido``) y vive en la tabla ``restocks``; el catálogo lo
entrega como ``Product.restock``, un texto con una de tres formas:

- un día de la semana («martes»): el proveedor surte ese día;
- una fecha ISO («2026-10-27»): el tendero sabe cuándo llega; una fecha pasada ya no dice nada;
- «descontinuado»: no se vuelve a traer.

Vacío es «sin dato». La respuesta lo dice solo si el cliente lo pregunta o si el producto está agotado (ahí sí sirve
sin preguntar); con existencias y sin pregunta, no se menciona. Grok nunca promete una llegada ni dice que algo se
dejó de traer sin ese dato (``restock_reply_ok``).
"""

from datetime import date, datetime, timedelta, timezone
import re

from asistendero.catalog import tokens
from asistendero.reply_text import gender_of
from asistendero.search import CLAUSE_BREAK

DISCONTINUED = "descontinuado"
WEEKDAYS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")
SHOWN_WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
BOGOTA = timezone(timedelta(hours=-5), "America/Bogota")
# El tendero anota surtidos cercanos; una fecha más lejana es casi siempre un error de digitación.
MAX_DAYS_AHEAD = 180
# Sobre texto normalizado (sin tildes ni mayúsculas).
ASKS_RESTOCK = re.compile(
    r"\bcuando\b[^?.!]{0,40}\b(?:llega|llegan|llegara|llegaran|vuelve|vuelven|traen|trae|surten|surte|tendra|tendran"
    r"|hay mas|reponen)\b|\b(?:van|vamos|vas) a (?:traer|volver a traer|tener)\b|\bya no (?:\w+ ){0,2}(?:traen|traer"
    r"|trae|manejan|maneja|venden)\b|\bdescontinu|\bvuelve a llegar|\bvuelven a llegar|\bsurtido\b"
    r"|\b(?:siguen|seguiran|vuelven a) (?:trayendo|traer)\b")
RESTOCK_VERB = re.compile(r"\b(?:llega|llegan|llegara|llegaran|vuelve a llegar|vuelven a llegar|surte|surten|surtimos"
                          r"|reponen|reponemos|traen|traemos|viene el proveedor)\b")
DISCONTINUED_CLAIM = re.compile(r"\bdescontinu|\bya no (?:\w+ ){0,3}(?:traer|traemos|traen|trae|manejamos|maneja)\b"
                                r"|\bno (?:\w+ ){0,2}(?:volvemos|vamos) a (?:volver a )?traer\b")
NO_KNOWLEDGE = re.compile(r"\bno (?:tengo|tenemos|se|sabemos|sabria|te puedo (?:asegurar|confirmar))\b|\bsin (?:fecha|dato)\b")
DAY_MONTH = re.compile(r"\b(\d{1,2})/(\d{1,2})\b")


def valid_plan(value: object) -> str:
    """El surtido limpio para guardar: día, fecha ISO, «descontinuado» o "" para borrarlo; ValueError si no."""
    if not isinstance(value, str):
        raise ValueError("El surtido es un día de la semana, una fecha AAAA-MM-DD, «descontinuado» o vacío.")
    text = value.strip().casefold()
    plain = text.translate(str.maketrans("áé", "ae"))
    if not text:
        return ""
    if plain == DISCONTINUED or plain in WEEKDAYS:
        return WEEKDAYS[WEEKDAYS.index(plain)] if plain in WEEKDAYS else DISCONTINUED
    try:
        day = date.fromisoformat(text)
    except ValueError:
        raise ValueError("El surtido es un día de la semana, una fecha AAAA-MM-DD, «descontinuado» o vacío.") from None
    today = datetime.now(BOGOTA).date()
    if not today <= day <= today + timedelta(days=MAX_DAYS_AHEAD):
        raise ValueError(f"La fecha de surtido va de hoy a {MAX_DAYS_AHEAD} días adelante.")
    return day.isoformat()


def plan_of(restock: str, today: date | None = None) -> tuple[str, str]:
    """(«dia» | «fecha» | «descontinuado» | «», valor) de un surtido; una fecha pasada cuenta como sin dato."""
    text = (restock or "").strip()
    if text == DISCONTINUED:
        return DISCONTINUED, text
    if text in WEEKDAYS:
        return "dia", text
    try:
        day = date.fromisoformat(text)
    except ValueError:
        return "", ""
    return ("fecha", text) if day >= (today or datetime.now(BOGOTA).date()) else ("", "")


def asks_restock(normalized_message: str) -> bool:
    return bool(ASKS_RESTOCK.search(normalized_message))


def restock_subjects(normalized_message: str, queries: list[str]) -> set[int]:
    """Índices de las búsquedas por las que el cliente preguntó el surtido.

    Z-25 (suite fallas): en «¿tienen candado de 40 mm, cuándo les llega el martillo de 16 oz?» la pregunta es del
    martillo, y la respuesta decía «no tengo fecha» también del candado. Si la parte que pregunta no nombra ningún
    producto («¿y cuándo le llegan más?»), la pregunta vale para todos.
    """
    asking = [part for part in CLAUSE_BREAK.split(normalized_message) if ASKS_RESTOCK.search(part)]
    named = {index for index, query in enumerate(queries) for part in asking if tokens(query) & tokens(part)}
    return named or set(range(len(queries)))


def _when(kind: str, value: str) -> str:
    if kind == "dia":
        return f"los {SHOWN_WEEKDAYS[WEEKDAYS.index(value)]}, cuando viene el proveedor"
    day = date.fromisoformat(value)
    return f"el {SHOWN_WEEKDAYS[day.weekday()]} {day:%d/%m}"


def restock_sentence(name: str, restock: str, asked: bool, stock: int, today: date | None = None) -> str:
    """Lo que se dice del surtido de un producto, o "" si no toca decirlo.

    Agotado, va en la misma frase («El martillo … está agotado por ahora, pero me llega los martes…»); con
    existencias, solo si el cliente preguntó.
    """
    kind, value = plan_of(restock, today)
    feminine, plural = gender_of(name)
    the = ("las" if plural else "la") if feminine else ("los" if plural else "el")
    it = ("las" if plural else "la") if feminine else ("los" if plural else "lo")
    out = "agotad" + ("a" if feminine else "o") + ("s" if plural else "")
    is_, arrives, comes = ("están", "llegan", "vuelven") if plural else ("está", "llega", "vuelve")
    subject = f"{the.capitalize()} {name}"
    if stock <= 0:
        if kind == DISCONTINUED:
            return f"{subject} {is_} {out} y ya no {it} vamos a volver a traer."
        if kind:
            return f"{subject} {is_} {out} por ahora, pero me {arrives} {_when(kind, value)}."
        unknown = (f" y no tengo fecha de cuándo {comes} a llegar; en el mostrador te pueden averiguar" if asked
                   else " por ahora")
        return f"{subject} {is_} {out}{unknown}."
    if not asked:
        return ""
    if kind == DISCONTINUED:
        return f"{subject} ya no {it} vamos a volver a traer; lo que queda es lo último."
    if kind:
        return f"{subject} me {arrives} {_when(kind, value)}."
    return (f"No tengo fecha de cuándo {comes} a llegar {the} {name}; en el mostrador te pueden averiguar con el "
            "proveedor.")


def restock_reply_ok(normalized_reply: str, restocks: list[str], today: date | None = None) -> bool:
    """La redacción de Grok solo afirma una llegada o que algo ya no se trae si un surtido observado lo dice.

    ``restocks`` son los ``Product.restock`` de lo observado en la ejecución. Una frase que reconoce no saber («no
    tengo fecha») siempre vale; una llegada sin día ni fecha («pronto», «la otra semana») nunca.
    """
    plans = [plan_of(restock, today) for restock in restocks]
    days = {value for kind, value in plans if kind == "dia"}
    days |= {WEEKDAYS[date.fromisoformat(value).weekday()] for kind, value in plans if kind == "fecha"}
    dates = {(date.fromisoformat(value).day, date.fromisoformat(value).month) for kind, value in plans if kind == "fecha"}
    discontinued = any(kind == DISCONTINUED for kind, _ in plans)
    for sentence in re.split(r"[.!?¡¿\n;]", normalized_reply):
        if NO_KNOWLEDGE.search(sentence):
            continue
        if DISCONTINUED_CLAIM.search(sentence):
            if not discontinued:
                return False
            continue
        if not RESTOCK_VERB.search(sentence):
            continue
        said_days = {day for day in WEEKDAYS if re.search(rf"\b{day}\b", sentence)}
        said_dates = {(int(day), int(month)) for day, month in DAY_MONTH.findall(sentence)}
        if not said_days | said_dates or not said_days <= days or not said_dates <= dates:
            return False
    return True
