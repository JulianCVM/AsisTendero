"""Matriz de capacidades a partir de las bitácoras del modo desatendido: antes y después de los arreglos.

Lee solo lo que la corrida registró (éxito, turnos, costo reportado por la API) y nunca las respuestas: las tablas
no llevan precios ni existencias del inventario real. Uso::

    python -m asistendero.evaluacion.cobertura_reporte evaluation/s4_cobertura/corrida_1 evaluation/s4_cobertura/corrida_2
"""

import argparse
from decimal import Decimal
import json
from pathlib import Path


def tasks_of(folder: Path) -> list[dict]:
    """Las tareas de una corrida, sin los eventos (arranque, pausa, fin)."""
    with (Path(folder) / "bitacora.jsonl").open(encoding="utf-8") as handle:
        return [entry for line in handle if line.strip() and (entry := json.loads(line))["tipo"] == "tarea"]


def by_capability(tasks: list[dict]) -> dict[str, dict]:
    """Por clase de tarea: conversaciones, aciertos, turnos, turnos bien y costo en USD."""
    table: dict[str, dict] = {}
    for task in tasks:
        row = table.setdefault(task["clase"], {"n": 0, "ok": 0, "turnos": 0, "turnos_ok": 0, "usd": Decimal(0)})
        turns = task.get("turnos") or []
        row["n"] += 1
        row["ok"] += bool(task["exito"])
        row["turnos"] += len(turns)
        row["turnos_ok"] += sum(bool(turn["exito"]) for turn in turns)
        row["usd"] += Decimal(str(task.get("costo_usd") or 0))
    return table


def _total(table: dict[str, dict]) -> dict:
    return {key: sum((row[key] for row in table.values()), Decimal(0) if key == "usd" else 0)
            for key in ("n", "ok", "turnos", "turnos_ok", "usd")}


def _rate(ok: int, n: int) -> str:
    return f"{ok}/{n} ({ok / n:.0%})" if n else "—"


def comparison_markdown(before: list[dict], after: list[dict] | None = None) -> str:
    """Tabla por capacidad; con ``after``, las dos corridas lado a lado y el costo de cada una."""
    first = by_capability(before)
    second = by_capability(after) if after is not None else None
    header = "| Capacidad | Conversaciones | Turnos | Costo USD |"
    if second is not None:
        header = "| Capacidad | Antes | Después | Turnos antes | Turnos después | Costo antes | Costo después |"
    lines = [header, "|" + "---|" * (header.count("|") - 1)]
    order = sorted(first, key=lambda name: (first[name]["ok"] / first[name]["n"], name))
    for name, row in [*((name, first[name]) for name in order), ("**Total**", _total(first))]:
        cells = [name, _rate(row["ok"], row["n"]), _rate(row["turnos_ok"], row["turnos"]), f"{row['usd']:.4f}"]
        if second is not None:
            other = _total(second) if name == "**Total**" else second.get(name, {"n": 0, "ok": 0, "turnos": 0,
                                                                                 "turnos_ok": 0, "usd": Decimal(0)})
            cells = [name, cells[1], _rate(other["ok"], other["n"]), cells[2],
                     _rate(other["turnos_ok"], other["turnos"]), cells[3], f"{other['usd']:.4f}"]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Matriz de capacidades de una corrida (o dos, antes y después).")
    parser.add_argument("antes", type=Path)
    parser.add_argument("despues", type=Path, nargs="?")
    args = parser.parse_args(argv)
    print(comparison_markdown(tasks_of(args.antes), tasks_of(args.despues) if args.despues else None), end="")


if __name__ == "__main__":
    main()
