"""Reporte de costo por operación de una corrida real: por tarea, por mensaje, por llamada a Grok y por herramienta.

Lee un reporte JSON del evaluador (``.local/eval-*.json``) y escribe Markdown; no llama a Grok. El costo de cada
llamada es el que informó la API (``api_reported``); una llamada sin costo informado se cuenta aparte, nunca como
cero. Las herramientas corren en el servidor sobre SQLite: no tienen costo de API, solo latencia.

    python -m asistendero.evaluacion.eval_costs .local/eval-AAAAMMDDTHHMMSS.json --out evaluation/COSTOS_POR_TAREA.md
"""

import argparse
from decimal import Decimal
import json
from math import ceil
from pathlib import Path

from asistendero.evaluacion.eval_report import cache_figures, model_calls, record_cost

# Qué hace cada llamada a Grok, según la fase del grafo y lo que decidió.
OPERATIONS = {
    ("interpret", "call_tool"): "Interpretar el mensaje y pedir una herramienta",
    ("interpret", "respond"): "Interpretar el mensaje y responder sin herramientas",
    ("resolve", "call_tool"): "Leer lo observado y pedir otra herramienta",
    ("resolve", "respond"): "Leer lo observado y redactar la respuesta",
    # La llamada de visión no decide nada del grafo: solo devuelve los atributos de la foto (``look.look_at``).
    ("vision", None): "Mirar la foto del cliente (visión)",
}
PROJECTED_TASKS = 1000


def _usd(value: Decimal | None) -> str:
    return "—" if value is None else format(value, ".6f")


def _turns(record: dict) -> list[dict]:
    return [turn for unit in record.get("clients") or [record] for turn in unit.get("turns") or [unit]]


def _percentile(values: list[Decimal], share: float) -> Decimal:
    ordered = sorted(values)
    return ordered[max(ceil(share * len(ordered)) - 1, 0)]


def case_rows(report: dict) -> list[dict]:
    """Una fila por tarea: mensajes del cliente, llamadas, herramientas, tokens, costo y latencia."""
    rows = []
    for record in report["cases"]:
        calls = model_calls(record)
        tools = [call for turn in _turns(record) for call in turn.get("tool_calls") or []]
        rows.append({
            "id": record["id"], "suite": record.get("suite", ""), "negocio": record.get("negocio", "ferreteria"),
            "mensajes": len(_turns(record)), "llamadas": record.get("model_calls", 0),
            "herramientas": sum(1 for call in tools if call.get("executed")),
            "entrada": sum(call["input_tokens"] for call in calls),
            "cache": sum(call.get("cached_input_tokens") or 0 for call in calls),
            "salida": sum(call.get("output_tokens") or 0 for call in calls),
            "usd": record_cost(record), "ms": record.get("elapsed_ms", 0), "aprobado": record.get("passed", False),
        })
    return rows


def operation_rows(report: dict) -> list[dict]:
    """Cada tipo de llamada a Grok con cuántas hubo, su costo total y medio, sus tokens y su latencia media."""
    groups: dict[str, dict] = {}
    for record in report["cases"]:
        for call in model_calls(record):
            name = OPERATIONS.get((call.get("phase"), call.get("action")), "Otra llamada")
            group = groups.setdefault(name, {"operacion": name, "llamadas": 0, "sin_costo": 0, "usd": Decimal(0),
                                             "entrada": 0, "cache": 0, "salida": 0, "ms": 0})
            group["llamadas"] += 1
            usd = (call.get("cost") or {}).get("usd")
            if usd is None:
                group["sin_costo"] += 1
            else:
                group["usd"] += Decimal(usd)
            group["entrada"] += call["input_tokens"]
            group["cache"] += call.get("cached_input_tokens") or 0
            group["salida"] += call.get("output_tokens") or 0
            group["ms"] += call.get("duration_ms") or 0
    return sorted(groups.values(), key=lambda group: -group["llamadas"])


def tool_rows(report: dict) -> list[dict]:
    """Cada herramienta del servidor: solicitudes de Grok, cuántas se ejecutaron o rechazó la validación, latencia."""
    groups: dict[str, dict] = {}
    for record in report["cases"]:
        for turn in _turns(record):
            for call in turn.get("tool_calls") or []:
                group = groups.setdefault(call["requested_tool"], {"herramienta": call["requested_tool"],
                                                                  "pedidas": 0, "ejecutadas": 0, "ms": 0})
                group["pedidas"] += 1
                if call.get("executed"):
                    group["ejecutadas"] += 1
                    group["ms"] += call.get("duration_ms") or 0
    return sorted(groups.values(), key=lambda group: -group["pedidas"])


def _group_table(rows: list[dict], key: str, title: str) -> list[str]:
    lines = [f"| {title} | Tareas | Aprobadas | Llamadas a Grok | USD | USD por tarea |", "|---|---|---|---|---|---|"]
    for name in sorted({row[key] for row in rows}):
        group = [row for row in rows if row[key] == name]
        known = [row["usd"] for row in group if row["usd"] is not None]
        total = sum(known, Decimal(0))
        lines.append(f"| {name} | {len(group)} | {sum(row['aprobado'] for row in group)} | "
                     f"{sum(row['llamadas'] for row in group)} | {_usd(total)} | {_usd(total / len(known)) if known else '—'} |")
    return lines


def cost_report_markdown(report: dict) -> str:
    rows = case_rows(report)
    known = [row["usd"] for row in rows if row["usd"] is not None]
    total = sum(known, Decimal(0))
    messages = sum(row["mensajes"] for row in rows)
    calls = [call for record in report["cases"] for call in model_calls(record)]
    cache = cache_figures(calls)
    tokens_in = sum(row["entrada"] for row in rows)
    cached = sum(row["cache"] for row in rows)
    versions = ", ".join(f"`{version}`" for version in report.get("prompt_versions") or [report.get("prompt_version")])
    mean = total / len(known) if known else None
    lines = [
        "## Corrida", "",
        f"- Commit `{report.get('commit', '—')}` (árbol {'con cambios' if report.get('src_dirty') else 'limpio'}), "
        f"modelo `{report.get('model', '—')}`, prompt {versions}, inicio {report.get('created_at', '—')}.",
        f"- {len(rows)} tareas ({messages} mensajes del cliente), {report.get('passed', 0)} aprobadas. "
        f"Costo informado por la API para {len(known)} de {len(rows)} tareas.", "",
        "## Resumen", "",
        "| Medida | Valor |", "|---|---|",
        f"| Costo total | {_usd(total)} USD |",
        f"| Costo medio por tarea | {_usd(mean)} USD |",
        f"| Mediana, percentil 90 y máximo por tarea | {_usd(_percentile(known, 0.5)) if known else '—'} / "
        f"{_usd(_percentile(known, 0.9)) if known else '—'} / {_usd(max(known)) if known else '—'} USD |",
        f"| Costo medio por mensaje del cliente | {_usd(total / messages) if messages else '—'} USD |",
        f"| Costo medio por llamada a Grok | {cache['cost_per_call_usd'] or '—'} USD |",
        f"| Llamadas a Grok por tarea | {format(Decimal(sum(row['llamadas'] for row in rows)) / len(rows), '.2f') if rows else '—'} |",
        f"| Tokens de entrada desde la caché | {format(Decimal(cached) * 100 / tokens_in, '.1f') if tokens_in else '—'} % |",
        f"| Llamadas con el prompt fijo en caché | {cache['cache_covered_percent']} % |",
        f"| Tareas sin llamar a Grok (rechazos antes del modelo) | {sum(1 for row in rows if not row['llamadas'])} |",
        f"| Proyección a {PROJECTED_TASKS:,} tareas con esta mezcla | "
        f"{_usd(mean * PROJECTED_TASKS) if mean is not None else '—'} USD |".replace(",", "."), "",
        "## Costo por operación de Grok", "",
        "| Operación | Llamadas | USD total | USD por llamada | Tokens de entrada (caché) | Tokens de salida | ms por llamada |",
        "|---|---|---|---|---|---|---|",
    ]
    for group in operation_rows(report):
        priced = group["llamadas"] - group["sin_costo"]
        lines.append(f"| {group['operacion']} | {group['llamadas']} | {_usd(group['usd'])} | "
                     f"{_usd(group['usd'] / priced) if priced else '—'} | {group['entrada']} ({group['cache']}) | "
                     f"{group['salida']} | {group['ms'] // group['llamadas']} |")
    lines += ["", "## Herramientas del servidor (sin costo de API)", "",
              "| Herramienta | Pedidas por Grok | Ejecutadas | Rechazadas por la validación | ms por ejecución |",
              "|---|---|---|---|---|"]
    for group in tool_rows(report):
        lines.append(f"| `{group['herramienta']}` | {group['pedidas']} | {group['ejecutadas']} | "
                     f"{group['pedidas'] - group['ejecutadas']} | "
                     f"{group['ms'] // group['ejecutadas'] if group['ejecutadas'] else '—'} |")
    lines += ["", "## Por suite", "", *_group_table(rows, "suite", "Suite"),
              "", "## Por negocio", "", *_group_table(rows, "negocio", "Negocio"),
              "", "## Por tarea", "",
              "| Caso | Suite | Negocio | Mensajes | Llamadas | Herramientas | Tokens entrada (caché) | Tokens salida | "
              "USD | ms | Aprobado |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for row in rows:
        lines.append(f"| {row['id']} | {row['suite']} | {row['negocio']} | {row['mensajes']} | {row['llamadas']} | "
                     f"{row['herramientas']} | {row['entrada']} ({row['cache']}) | {row['salida']} | {_usd(row['usd'])} | "
                     f"{row['ms']} | {'sí' if row['aprobado'] else 'no'} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Reporte de costo por operación de una corrida; no llama a Grok")
    parser.add_argument("reporte", type=Path, help="Reporte JSON del evaluador (.local/eval-*.json)")
    parser.add_argument("--out", type=Path, help="Archivo Markdown de salida; sin él se imprime")
    args = parser.parse_args()
    markdown = cost_report_markdown(json.loads(args.reporte.read_text(encoding="utf-8")))
    if args.out:
        args.out.write_text(markdown, encoding="utf-8")
    else:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
