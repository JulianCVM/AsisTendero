"""Resumen de un reporte de evaluación: costo por tarea, por suite y comparación entre modelos.

Una tarea es un caso: un mensaje suelto o una conversación completa. El costo suma solo las llamadas con
costo conocido y lo dice (``cost_complete``): un dato ausente nunca se cuenta como cero.
"""

from decimal import Decimal


def record_cost(record: dict) -> Decimal | None:
    cost = record.get("cost")
    if cost:
        return Decimal(cost["usd"])
    # Un rechazo antes de Grok (refused) no llama al modelo: su costo es cero, no desconocido.
    return Decimal(0) if not record.get("model_calls") else None


def _records_events(record: dict) -> list[dict]:
    if "turns" in record:
        return [event for turn in record["turns"] for event in turn.get("events", [])]
    return record.get("events", [])


def _reminders(record: dict) -> int:
    return sum(1 for event in _records_events(record) if event["type"] == "route" and event["details"].get("aviso"))


def _per_task(total: Decimal | int, tasks: int, places: str) -> str:
    return format(Decimal(total) / tasks, places) if tasks else "0"


def summarize(report: dict) -> dict:
    records = report["cases"]
    costs = [record_cost(record) for record in records]
    known = sum((cost for cost in costs if cost is not None), Decimal(0))
    tokens = sum(record.get("total_tokens") or 0 for record in records)
    by_suite: dict[str, dict] = {}
    for record, cost in zip(records, costs):
        suite = by_suite.setdefault(record.get("suite", "s2"), {
            "passed": 0, "total": 0, "cost_usd": Decimal(0), "model_calls": 0, "tokens": 0, "reminders": 0})
        suite["passed"] += record["passed"]
        suite["total"] += 1
        suite["cost_usd"] += cost or 0
        suite["model_calls"] += record["model_calls"]
        suite["tokens"] += record.get("total_tokens") or 0
        suite["reminders"] += _reminders(record)
    tasks = len(records)
    failure_costs = [record_cost(record) for record in report.get("controlled_failures", [])]
    return {
        "tasks": tasks,
        "turns": sum(len(record.get("turns", [record])) for record in records),
        "cost_usd": format(known, ".6f"),
        "cost_complete": all(cost is not None for cost in costs),
        "cost_per_task_usd": _per_task(known, tasks, ".6f"),
        "tokens_per_task": _per_task(tokens, tasks, ".0f"),
        "model_calls_per_task": _per_task(report["model_calls"], tasks, ".2f"),
        "elapsed_ms_per_task": _per_task(report["elapsed_ms"], tasks, ".0f"),
        "reminders": sum(_reminders(record) for record in records),
        # Los fallos controlados también consumen (F-01 llama a Grok): cuentan en el consumo, no por tarea.
        "failures_cost_usd": format(sum((cost for cost in failure_costs if cost is not None), Decimal(0)), ".6f"),
        "failed_ids": [record["id"] for record in records if not record["passed"]],
        "by_suite": {
            name: {**values, "cost_usd": format(values["cost_usd"], ".6f")} for name, values in sorted(by_suite.items())
        },
        "by_model": _by_model(records, report.get("model")),
    }


def _by_model(records: list[dict], default: str | None) -> dict:
    """Aprobados y consumo por modelo; en un caso con clientes cuenta cada cliente con su propio modelo."""
    by_model: dict[str, dict] = {}
    for unit in (unit for record in records for unit in record.get("clients", [record])):
        values = by_model.setdefault(unit.get("model") or default or "?", {
            "passed": 0, "total": 0, "cost_usd": Decimal(0), "model_calls": 0, "tokens": 0, "elapsed_ms": 0})
        values["passed"] += unit["passed"]
        values["total"] += 1
        values["cost_usd"] += record_cost(unit) or 0
        values["model_calls"] += unit["model_calls"]
        values["tokens"] += unit.get("total_tokens") or 0
        values["elapsed_ms"] += unit["elapsed_ms"]
    return {name: {**values, "cost_usd": format(values["cost_usd"], ".6f")} for name, values in sorted(by_model.items())}


def comparison_markdown(reports: list[dict]) -> str:
    """Tabla para la evidencia: un renglón por reporte y, debajo, qué casos falló cada uno."""
    suites = sorted({name for report in reports for name in report["summary"]["by_suite"]})
    header = ["Modelo", "Prompt", "Commit", "Aprobados", *suites, "Costo USD", "USD/tarea", "Tokens/tarea",
              "Grok/tarea", "ms/tarea", "Avisos"]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for report in reports:
        summary = report["summary"]
        by_suite = summary["by_suite"]
        cells = [
            report["model"], report["prompt_version"], report.get("commit") or "—",
            f"{report['passed']}/{report['total']}",
            *[f"{by_suite[name]['passed']}/{by_suite[name]['total']}" if name in by_suite else "—" for name in suites],
            summary["cost_usd"] + ("" if summary["cost_complete"] else " (parcial)"),
            summary["cost_per_task_usd"], summary["tokens_per_task"], summary["model_calls_per_task"],
            summary["elapsed_ms_per_task"], str(summary["reminders"]),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    for report in reports:
        failed = report["summary"]["failed_ids"]
        reasons = {record["id"]: "; ".join(record.get("fail_reasons", [])) for record in report["cases"]}
        lines.append(f"- {report['model']}: " + (", ".join(f"{case} ({reasons[case]})" for case in failed)
                                                   if failed else "sin fallos"))
    return "\n".join(lines)
