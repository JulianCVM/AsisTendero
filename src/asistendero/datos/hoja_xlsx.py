"""Lee una hoja de un .xlsx con la biblioteca estándar: un inventario no justifica una dependencia nueva.

Solo abre la hoja que se le nombra. Un libro real trae otras (en el de Carluz, una oculta con proveedores y
facturas) y esas nunca se leen. Los archivos llegan de afuera: se rechazan pasado el tamaño, nunca se recortan.
"""

from pathlib import Path
import re
from xml.etree import ElementTree
import zipfile


MAX_FILE_BYTES = 20 * 1024 * 1024
# Lo que puede ocupar una parte del libro ya descomprimida: un .xlsx de inventario pesa unos pocos MB.
MAX_PART_BYTES = 100 * 1024 * 1024
MAX_ROWS = 20_000

_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_RELATION = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_COLUMN = re.compile(r"[A-Z]+")


class WorkbookError(ValueError):
    """El libro no se pudo leer; el mensaje dice qué hacer y no trae contenido del archivo."""


def _part(book: zipfile.ZipFile, name: str) -> ElementTree.Element:
    try:
        info = book.getinfo(name)
    except KeyError as exc:
        raise WorkbookError(f"Al libro le falta la parte {name}: ábrelo en Excel y guárdalo de nuevo.") from exc
    if info.file_size > MAX_PART_BYTES:
        raise WorkbookError(f"La parte {name} supera el máximo de {MAX_PART_BYTES} bytes.")
    return ElementTree.fromstring(book.read(name))


def _sheet_part(book: zipfile.ZipFile, sheet: str) -> str:
    """La parte del libro que tiene la hoja; el nombre se compara sin espacios («INVENTARIO REAL »)."""
    wanted = sheet.strip().casefold()
    relation = next((item.get(_RELATION) for item in _part(book, "xl/workbook.xml").iter(f"{_MAIN}sheet")
                     if (item.get("name") or "").strip().casefold() == wanted), None)
    if relation is None:
        raise WorkbookError(f"El libro no tiene una hoja llamada «{sheet}».")
    for item in _part(book, "xl/_rels/workbook.xml.rels"):
        if item.get("Id") == relation:
            target = (item.get("Target") or "").lstrip("/")
            return target if target.startswith("xl/") else f"xl/{target}"
    raise WorkbookError(f"La hoja «{sheet}» no tiene contenido: ábrela en Excel y guarda el libro de nuevo.")


def _shared_strings(book: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in book.namelist():
        return []
    return ["".join(text.text or "" for text in item.iter(f"{_MAIN}t"))
            for item in _part(book, "xl/sharedStrings.xml")]


def _cell_value(cell: ElementTree.Element, strings: list[str]) -> str | None:
    kind = cell.get("t")
    if kind == "inlineStr":
        return "".join(text.text or "" for text in cell.iter(f"{_MAIN}t"))
    value = cell.find(f"{_MAIN}v")
    if value is None or value.text is None:
        return None
    if kind != "s":
        return value.text
    try:
        return strings[int(value.text)]
    except (ValueError, IndexError) as exc:
        raise WorkbookError("Una celda apunta a un texto que no existe: guarda el libro de nuevo.") from exc


def read_sheet(path: Path, sheet: str) -> list[tuple[int, dict[str, str]]]:
    """Las filas con datos de la hoja como (número de fila, {columna: texto}), tal como están escritas."""
    if not path.is_file():
        raise WorkbookError(f"No existe el archivo {path}.")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise WorkbookError(f"El archivo supera el máximo de {MAX_FILE_BYTES} bytes.")
    try:
        with zipfile.ZipFile(path) as book:
            strings = _shared_strings(book)
            root = _part(book, _sheet_part(book, sheet))
    except (zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise WorkbookError("El archivo no es un .xlsx válido: ábrelo en Excel y guárdalo de nuevo.") from exc
    rows = []
    for row in root.iter(f"{_MAIN}row"):
        cells = {}
        for cell in row.findall(f"{_MAIN}c"):
            value = _cell_value(cell, strings)
            if value is not None:
                cells[_COLUMN.match(cell.get("r", "A")).group()] = value
        if cells:
            rows.append((int(row.get("r", "0")), cells))
        if len(rows) > MAX_ROWS:
            raise WorkbookError(f"La hoja supera el máximo de {MAX_ROWS} filas.")
    return rows
