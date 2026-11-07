"""Copia publicable de una corrida sobre el inventario real: sin precios ni existencias de la tienda.

Las respuestas del agente dicen el precio («a $5.140 c/u») y lo que queda («solo me quedan 2»), y los motivos de la
bodega comparan existencias. Esos valores son de Ferretería Carluz y no van al repositorio público (como el Excel,
que vive en ``.local/carluz/``). La corrida completa se queda en local; al repositorio sube esta copia, con cada
cifra sensible cambiada por ``[valor]`` o ``[n]``. El resto (estado, herramientas, errores, costo, tokens) no cambia,
así que la matriz de capacidades sale igual de las dos. Uso::

    python -m asistendero.evaluacion.publicar_bitacora CARPETA_COMPLETA CARPETA_PUBLICA
"""

import argparse
import csv
import json
from pathlib import Path
import re
import shutil

MONEY = re.compile(r"\$\s?\d[\d.,]*")
# Cifras con punto de miles sin «$» («sube la llave a 29.500»): en estas colas son precios.
THOUSANDS = re.compile(r"(?<![\w.,/$-])\d{1,3}(?:\.\d{3})+(?![\d,])")
STOCK = re.compile(r"\b(quedan?|queda|quedar[ií]an?|tenemos|tengo|hay|existencias?|inventario:?|bodega|qued[oó] en)"
                   r"(\s+(?:de\s+|solo\s+)?)(\d+)", re.IGNORECASE)
# En un motivo cualquier cifra suelta puede ser una existencia («bodega 3 → 5»); SKU, fechas y horas se conservan.
NUMBER = re.compile(r"(?<![\w:/.,-])\d+(?:[.,]\d+)?(?![\w:/-])")
TEXT_FIELDS = ("respuesta", "entrada", "mensaje", "query")
REASON_FIELDS = ("motivos",)
# Lo que el caso esperaba encontrar en la base tras confirmar (cola de bodega): existencias y precios reales.
VALUE_KEYS = {"stock", "precio", "stock_nuevo", "precio_nuevo", "pendiente"}


def mask_text(text: str) -> str:
    """El texto con precios y existencias cambiados por ``$[valor]``, ``[valor]`` y ``[n]``."""
    text = MONEY.sub("$[valor]", text)
    text = THOUSANDS.sub("[valor]", text)
    return STOCK.sub(lambda match: f"{match.group(1)}{match.group(2)}[n]", text)


def mask_reason(text: str) -> str:
    return NUMBER.sub("[n]", mask_text(text))


def mask_entry(value, key: str = ""):
    """Copia enmascarada de un registro de la bitácora o de la cola, a cualquier profundidad."""
    if isinstance(value, dict):
        return {name: "[n]" if name in VALUE_KEYS and isinstance(item, (int, float)) else mask_entry(item, name)
                for name, item in value.items()}
    if isinstance(value, list):
        return [mask_entry(item, key) for item in value]
    if isinstance(value, str) and key in TEXT_FIELDS:
        return mask_text(value)
    if isinstance(value, str) and key in REASON_FIELDS:
        return mask_reason(value)
    return value


def publish(source: Path, target: Path) -> list[str]:
    """Escribe en ``target`` la copia publicable de la corrida de ``source``; devuelve los archivos escritos."""
    source, target = Path(source), Path(target)
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for name in ("bitacora.jsonl",):
        if (source / name).exists():
            with (source / name).open(encoding="utf-8") as handle:
                rows = [json.dumps(mask_entry(json.loads(line)), ensure_ascii=False) for line in handle if line.strip()]
            (target / name).write_text("\n".join(rows) + "\n", encoding="utf-8")
            written.append(name)
    if (source / "cola.json").exists():
        queue = json.loads((source / "cola.json").read_text(encoding="utf-8"))
        (target / "cola.json").write_text(json.dumps(mask_entry(queue), ensure_ascii=False, indent=1) + "\n",
                                          encoding="utf-8")
        written.append("cola.json")
    if (source / "bitacora.csv").exists():
        with (source / "bitacora.csv").open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fields, rows = reader.fieldnames or [], list(reader)
        with (target / "bitacora.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({name: mask_reason(value) if name in REASON_FIELDS
                                 else mask_text(value) if name in TEXT_FIELDS else value for name, value in row.items()})
        written.append("bitacora.csv")
    # El resumen y el estado solo llevan conteos, costo y hora: se copian tal cual.
    for name in ("RESUMEN.md", "estado.json"):
        if (source / name).exists():
            shutil.copyfile(source / name, target / name)
            written.append(name)
    return written


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Copia publicable de una corrida, sin precios ni existencias reales.")
    parser.add_argument("completa", type=Path)
    parser.add_argument("publica", type=Path)
    args = parser.parse_args(argv)
    print("Escribí:", ", ".join(publish(args.completa, args.publica)))


if __name__ == "__main__":
    main()
