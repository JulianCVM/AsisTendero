"""Surtido que anota el tendero: cuándo vuelve a llegar un producto o si ya no se trae.

El dato vive en la tabla ``restocks`` y lo edita el panel (``inventory.Inventory.update`` con ``surtido``). Tiene una
de tres formas:

- un día de la semana («martes»): el proveedor surte ese día;
- una fecha ISO («2026-10-27»): el tendero sabe cuándo llega; una fecha pasada ya no dice nada;
- «descontinuado»: no se vuelve a traer.

Vacío es «sin dato». Qué puede afirmar el agente de esto está en ``agente/respuesta/restock.py``.
"""

from datetime import date, datetime, timedelta

from asistendero.tienda.reloj import BOGOTA, WEEKDAYS

DISCONTINUED = "descontinuado"
SHOWN_WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
# El tendero anota surtidos cercanos; una fecha más lejana es casi siempre un error de digitación.
MAX_DAYS_AHEAD = 180


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
