"""Los casos que manda un harness externo: se leen, se validan con sus límites y se vuelven turnos.

Formatos (``read_cases``):

- JSONL: un caso por línea.
- Un arreglo JSON de casos, o un objeto con la lista en ``casos`` o ``cases``.
- Texto plano (``.txt``): cada línea no vacía es un caso de un solo mensaje.

Un caso es un objeto con ``id`` (opcional: si falta, se numera) y su mensaje o sus turnos::

    {"id": "c1", "mensaje": "Busco tubo PVC de 1/2 para agua"}
    {"id": "c2", "turnos": ["Busco tubo PVC de 1/2", "dame 3 metros de ese"]}
    {"id": "c3", "turnos": [{"mensaje": "¿tienen esta?", "foto": "fotos/llave.jpg"}]}

Como el reto no publicó el formato de su harness, también se aceptan los nombres en inglés (``message``, ``input``,
``messages``, ``turns``, ``image``) y un turno al estilo de Chat Completions (``{"role": "user", "content": "..."}``;
los turnos con otro ``role`` se ignoran, porque las respuestas las da el agente). Un caso que no se entiende o que
pasa un límite queda con su motivo en ``error`` y no se ejecuta; nunca se recorta en silencio. El largo del mensaje
no se revisa aquí: lo valida el agente, como con cualquier cliente.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
import json
from pathlib import Path

from asistendero.agente.conversacion.sessions import MAX_TURNS_PER_SESSION
from asistendero.agente.vision.photo import MAX_PHOTO_BYTES

MAX_INPUT_BYTES = 20_000_000
MAX_CASES = 2000
MAX_ID_CHARS = 80
PHOTO_TYPES = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".webp": "webp"}
MESSAGE_KEYS = ("mensaje", "message", "input", "content", "text")
TURNS_KEYS = ("turnos", "turns", "messages", "mensajes")
PHOTO_KEYS = ("foto", "image", "imagen")


@dataclass
class Turn:
    message: str
    photo: str | None = None


@dataclass
class HarnessCase:
    id: str
    turns: list[Turn] = field(default_factory=list)
    error: str | None = None


class CaseError(ValueError):
    """Un caso que no se puede ejecutar; el mensaje dice qué corregir."""


def _first(item: dict, keys: tuple[str, ...]):
    return next((item[key] for key in keys if key in item), None)


def _photo(value: object, base: Path) -> str:
    """La foto como ``data:image/...;base64``: una ruta (relativa al archivo de casos) o un data URI ya armado."""
    if not isinstance(value, str) or not value.strip():
        raise CaseError("la foto debe ser una ruta o un data URI")
    if value.startswith("data:image/"):
        return value
    path = (base / value).resolve()
    kind = PHOTO_TYPES.get(path.suffix.lower())
    if kind is None:
        raise CaseError(f"la foto {value} no es JPEG, PNG ni WebP")
    if not path.is_file():
        raise CaseError(f"no existe la foto {value}")
    if path.stat().st_size > MAX_PHOTO_BYTES:
        raise CaseError(f"la foto {value} pasa de {MAX_PHOTO_BYTES} bytes")
    return f"data:image/{kind};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _turn(item: object, base: Path) -> Turn | None:
    if isinstance(item, str):
        return Turn(item)
    if not isinstance(item, dict):
        raise CaseError("cada turno debe ser un texto o un objeto")
    if item.get("role", "user") != "user":
        return None
    message = _first(item, MESSAGE_KEYS)
    photo = _first(item, PHOTO_KEYS)
    if message is None and photo is None:
        raise CaseError("un turno no trae mensaje ni foto")
    if message is not None and not isinstance(message, str):
        raise CaseError("el mensaje de un turno debe ser texto")
    return Turn(message or "", _photo(photo, base) if photo is not None else None)


def to_case(raw: object, index: int, base: Path) -> HarnessCase:
    """Un caso validado; si no se puede ejecutar, queda con ``error`` y sin turnos."""
    if isinstance(raw, str):
        raw = {"mensaje": raw}
    if not isinstance(raw, dict):
        return HarnessCase(f"caso-{index}", error="CASE_INVALID: el caso debe ser un objeto o un texto")
    case_id = str(raw.get("id", f"caso-{index}"))
    if len(case_id) > MAX_ID_CHARS:
        return HarnessCase(case_id[:MAX_ID_CHARS], error=f"CASE_INVALID: el id pasa de {MAX_ID_CHARS} caracteres")
    try:
        listed = _first(raw, TURNS_KEYS)
        if listed is None:
            listed = [raw]
        if not isinstance(listed, list):
            raise CaseError("los turnos deben ser una lista")
        turns = [turn for turn in (_turn(item, base) for item in listed) if turn is not None]
        if not turns:
            raise CaseError("el caso no trae ningún mensaje del cliente")
        if len(turns) > MAX_TURNS_PER_SESSION:
            raise CaseError(f"una conversación admite hasta {MAX_TURNS_PER_SESSION} turnos")
    except CaseError as error:
        return HarnessCase(case_id, error=f"CASE_INVALID: {error}")
    return HarnessCase(case_id, turns)


def _items(text: str, suffix: str) -> list:
    if suffix == ".txt":
        return [line.strip() for line in text.splitlines() if line.strip()]
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError as error:
        # Un documento JSON seguido de otro es JSONL: se lee línea a línea.
        if error.msg != "Extra data":
            raise
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(loaded, dict):
        listed = _first(loaded, ("casos", "cases"))
        return listed if isinstance(listed, list) else [loaded]
    return loaded if isinstance(loaded, list) else [loaded]


def read_cases(text: str, *, suffix: str = ".jsonl", base: Path = Path(".")) -> list[HarnessCase]:
    """Los casos de un archivo; lanza ValueError si el archivo entero no se entiende o pasa un límite."""
    if len(text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError(f"El archivo de casos pasa de {MAX_INPUT_BYTES} bytes; divídelo.")
    try:
        items = _items(text, suffix.lower())
    except json.JSONDecodeError as error:
        raise ValueError(f"El archivo de casos no es JSON ni JSONL válido (línea {error.lineno}).") from None
    if not items:
        raise ValueError("El archivo de casos está vacío.")
    if len(items) > MAX_CASES:
        raise ValueError(f"Hay {len(items)} casos y el máximo por corrida es {MAX_CASES}; divídelos.")
    cases = [to_case(item, index, base) for index, item in enumerate(items, 1)]
    seen: set[str] = set()
    for case in cases:
        if case.id in seen and case.error is None:
            case.turns, case.error = [], "CASE_INVALID: id repetido"
        seen.add(case.id)
    return cases
