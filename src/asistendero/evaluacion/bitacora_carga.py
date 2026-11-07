"""Bitácora de la semana de carga: JSONL que se escribe línea a línea, y el CSV y el resumen que salen de ella.

La JSONL es la fuente: cada línea se escribe y se vacía al disco apenas termina la tarea, así que un corte de luz pierde
como mucho la tarea en curso. El CSV y ``RESUMEN.md`` se rehacen desde ella cuando se quiera.
"""

from __future__ import annotations

import csv
import json
import os
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path

BITACORA = "bitacora.jsonl"
COLA = "cola.json"
ESTADO = "estado.json"
DONE = "terminada.txt"
CSV_FIELDS = ("id", "clase", "inicio", "fin", "entrada", "resultado", "exito", "motivos", "costo_usd",
              "llamadas_grok", "tokens_entrada", "tokens_salida", "errores", "recuperacion", "duracion_ms",
              "modelo", "prompt_version", "commit", "respuesta")


def append(path: Path, line: dict) -> None:
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(line, ensure_ascii=False) + "\n")
        file.flush()
        os.fsync(file.fileno())


def events_of(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            lines.append(json.loads(raw))
        except json.JSONDecodeError:
            # Solo puede pasar con la última línea de un corte a mitad de escritura: esa tarea se vuelve a hacer.
            continue
    return lines


def done_ids(path: Path) -> set[str]:
    return {line["id"] for line in events_of(path) if line.get("tipo") == "tarea"}


def summary(lines: list[dict]) -> dict:
    tasks = [line for line in lines if line.get("tipo") == "tarea"]
    events = [line for line in lines if line.get("tipo") == "evento"]
    costs = [Decimal(line["costo_usd"]) for line in tasks if line.get("costo_usd")]
    total = sum(costs, Decimal(0))
    passed = sum(bool(line["exito"]) for line in tasks)
    hours = 0.0
    if tasks:
        first = min(datetime.fromisoformat(line["inicio"]) for line in tasks)
        last = max(datetime.fromisoformat(line["fin"]) for line in tasks)
        hours = (last - first).total_seconds() / 3600
    by_kind: dict[str, list[int]] = {}
    for line in tasks:
        by_kind.setdefault(line["clase"], [0, 0])
        by_kind[line["clase"]][0] += 1
        by_kind[line["clase"]][1] += bool(line["exito"])
    return {
        "unidades": len(tasks), "exitosas": passed, "tasa_exito": passed / len(tasks) if tasks else 0.0,
        "costo_total_usd": total, "costo_por_tarea_usd": total / len(tasks) if tasks else Decimal(0),
        "horas_continuas": hours, "llamadas_grok": sum(line.get("llamadas_grok") or 0 for line in tasks),
        "errores": Counter(code for line in tasks for code in line.get("errores", [])),
        "motivos": Counter(reason for line in tasks for reason in line.get("motivos", [])),
        "por_clase": by_kind,
        "eventos": Counter(line["evento"] for line in events),
        "commits": sorted({line["commit"] for line in tasks if line.get("commit")}),
        "modelos": sorted({line["modelo"] for line in tasks if line.get("modelo")}),
    }


def summary_markdown(data: dict) -> str:
    lines = [
        "# Semana de carga S4: resumen de la corrida desatendida", "",
        "Generado desde `bitacora.jsonl` con `python -m asistendero.evaluacion.desatendido resumen`. Inventario real "
        "de Ferretería Carluz; consultas de cliente simuladas, todas distintas (`cola.json`).", "",
        "| Medida | Valor |", "|---|---|",
        f"| Unidades de trabajo terminadas | {data['unidades']} |",
        f"| Exitosas | {data['exitosas']} ({data['tasa_exito']:.1%}) |",
        f"| Costo total | {data['costo_total_usd']:.6f} USD |",
        f"| Costo por tarea | {data['costo_por_tarea_usd']:.6f} USD |",
        f"| Horas entre la primera y la última tarea | {data['horas_continuas']:.2f} |",
        f"| Llamadas a Grok | {data['llamadas_grok']} |",
        f"| Commit | {', '.join(data['commits']) or '—'} |",
        f"| Modelo | {', '.join(data['modelos']) or '—'} |",
        "", "## Por clase de tarea", "", "| Clase | Tareas | Exitosas |", "|---|---|---|",
        *[f"| {kind} | {count} | {ok} |" for kind, (count, ok) in sorted(data["por_clase"].items())],
        "", "## Errores y motivos de falla", "",
        *([f"- `{code}`: {count}" for code, count in data["errores"].most_common()] or ["- Ninguno"]),
        *[f"- {reason}: {count}" for reason, count in data["motivos"].most_common(15)],
        "", "## Eventos del proceso", "",
        *([f"- {name}: {count}" for name, count in sorted(data["eventos"].items())] or ["- Ninguno"]),
        "",
    ]
    return "\n".join(lines)


def write_summary(folder: Path) -> dict:
    lines = events_of(folder / BITACORA)
    tasks = [line for line in lines if line.get("tipo") == "tarea"]
    with (folder / "bitacora.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for line in tasks:
            writer.writerow({**line, "motivos": "; ".join(line.get("motivos", [])),
                             "errores": "; ".join(line.get("errores", []))})
    data = summary(lines)
    (folder / "RESUMEN.md").write_text(summary_markdown(data), encoding="utf-8")
    return data
