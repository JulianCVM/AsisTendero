"""Evaluación con casos sintéticos de uno o varios turnos; las llamadas pagadas exigen --live."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from dotenv import load_dotenv

from asistendero.catalog import MockCatalog
from asistendero.chat import run_turn
from asistendero.eval_report import comparison_markdown, summarize
from asistendero.executor import catalog_executor
from asistendero.graph import Planner, ToolExecutor
from asistendero.grok import DEFAULT_MODEL, PROMPT_VERSION, current_model, decide_with_grok, decision_from_raw
from asistendero.pricing import run_cost
from asistendero.sessions import SessionStore
from asistendero.tracing import run_traced
from asistendero.validation import grounded_products


DEFAULT_CASES_PATH = Path("evaluation/cases.json")
INVALID_LOCAL_BASE_URL = "http://127.0.0.1:9/v1"
FAILURE_QUERY = "Necesito 2 metros de tubo PVC de 1/2 para agua"
# Texto que no es una decisión JSON; recorre el mismo parse_decision que una respuesta real de Grok.
INVALID_MODEL_OUTPUT = "Claro, el tubo cuesta $1.000 y ya te lo aparté."


def git_state() -> dict:
    """Commit evaluado y si src/ tenía cambios sin commit: sin esto la evidencia no se puede reproducir."""
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                                check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "src"], capture_output=True, text=True,
                               check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "src_dirty": None}
    return {"commit": commit, "src_dirty": bool(dirty)}


def _selected_skus(reference: str, tool_calls: list[dict]) -> list[str]:
    skus: list[str] = []
    for call in tool_calls:
        if not call["executed"]:
            continue
        if call["requested_tool"] == "consultar_disponibilidad":
            skus.append(call["arguments"]["sku"])
        elif call["requested_tool"] == "calcular_cotizacion_informativa":
            skus.extend(line["sku"] for line in call["arguments"]["lines"])
    skus.extend(grounded_products(reference, tool_calls).keys())
    return list(dict.fromkeys(skus))


def _verdict(check: dict, result: dict, selected_skus: list[str]) -> list[str]:
    """Motivos por los que un resultado no cumple lo esperado; vacío si pasa."""
    reasons = []
    expected = check["expected_status"]
    if result["estado"] not in (expected if isinstance(expected, list) else [expected]):
        reasons.append(f"estado {result['estado']}")
    for sku in ([check["expected_sku"]] if check.get("expected_sku") else []) + check.get("expected_skus", []):
        if sku not in selected_skus:
            reasons.append(f"falta {sku}")
    tool_calls = result.get("tool_calls", [])
    executed = {call["requested_tool"] for call in tool_calls if call["executed"]}
    reasons += [f"no ejecutó {name}" for name in check.get("expected_tools", []) if name not in executed]
    response = result["respuesta"].casefold()
    reasons += [f"no dice «{text}»" for text in check.get("must_include", []) if text.casefold() not in response]
    reasons += [f"dice «{text}»" for text in check.get("must_not_include", []) if text.casefold() in response]
    if "max_model_calls" in check and result["model_calls"] > check["max_model_calls"]:
        reasons.append(f"{result['model_calls']} llamadas a Grok")
    expected_error = check.get("expected_error_code")
    if expected_error:
        codes = {(call["response"].get("error") or {}).get("code") for call in tool_calls}
        if result.get("error"):
            codes.add(result["error"].get("code"))
        if expected_error not in codes:
            reasons.append(f"sin {expected_error}")
    return reasons


def _record(check: dict, result: dict, events: list[dict]) -> dict:
    final_details = next(event["details"] for event in reversed(events) if event["type"] == "final")
    tool_calls = result.get("tool_calls", [])
    selected_skus = _selected_skus(result.get("referencia", ""), tool_calls)
    reasons = _verdict(check, result, selected_skus)
    return {
        "query": check["query"],
        "run_id": result["run_id"],
        "expected_status": check["expected_status"],
        "actual_status": result["estado"],
        "expected_sku": check.get("expected_sku"),
        "expected_skus": check.get("expected_skus"),
        "expected_error_code": check.get("expected_error_code"),
        "selected_skus": selected_skus,
        "passed": not reasons,
        "fail_reasons": reasons,
        "response": result["respuesta"],
        "model_called": result["model_called"],
        "model_calls": result["model_calls"],
        "tools": final_details["tools_requested"],
        "tools_executed": final_details["tools_executed"],
        "tool_calls": [
            {
                "step": call["step"],
                "requested_tool": call["requested_tool"],
                "executed": call["executed"],
                "status": call["response"].get("status"),
                "error": call["response"].get("error"),
                "duration_ms": call["duration_ms"],
            }
            for call in tool_calls
        ],
        "error": result.get("error"),
        "input_tokens": final_details["input_tokens"],
        "output_tokens": final_details["output_tokens"],
        "cached_input_tokens": final_details["cached_input_tokens"],
        "total_tokens": final_details["total_tokens"],
        "cost": final_details["cost"],
        "elapsed_ms": final_details["duration_ms"],
        "events": events,
    }


def _run_record(case: dict, *, executor: ToolExecutor, planner: Planner) -> dict:
    events: list[dict] = []
    result = run_traced(case["query"], events.append, executor, planner)
    return {"id": case["id"], "suite": case.get("suite", "s2"), **_record(case, result, events)}


def _sum(values: list) -> int | None:
    known = [value for value in values if isinstance(value, int)]
    return sum(known) if known else None


def _run_conversation(case: dict, *, executor: ToolExecutor, planner: Planner) -> dict:
    """Varios turnos en una sesión temporal: el caso pasa solo si pasa cada turno."""
    with tempfile.TemporaryDirectory() as folder:
        store = SessionStore(Path(folder) / "sessions.sqlite3")
        session_id = store.create()
        turns = []
        for turn in case["turns"]:
            events: list[dict] = []
            result = run_turn(store, session_id, turn["query"], events.append, executor, planner)
            turns.append(_record(turn, result, events))
    return {
        "id": case["id"],
        "suite": case.get("suite", "conversacion"),
        "query": " / ".join(turn["query"] for turn in case["turns"]),
        "expected_status": [turn["expected_status"] for turn in turns],
        "actual_status": [turn["actual_status"] for turn in turns],
        "passed": all(turn["passed"] for turn in turns),
        "fail_reasons": [f"turno {index}: {reason}" for index, turn in enumerate(turns, 1) for reason in turn["fail_reasons"]],
        "response": turns[-1]["response"],
        "model_calls": sum(turn["model_calls"] for turn in turns),
        "tools": [name for turn in turns for name in turn["tools"]],
        "tools_executed": [name for turn in turns for name in turn["tools_executed"]],
        "input_tokens": _sum([turn["input_tokens"] for turn in turns]),
        "output_tokens": _sum([turn["output_tokens"] for turn in turns]),
        "cached_input_tokens": _sum([turn["cached_input_tokens"] for turn in turns]),
        "total_tokens": _sum([turn["total_tokens"] for turn in turns]),
        "cost": run_cost([turn["cost"] for turn in turns if turn["model_calls"]]),
        "elapsed_ms": sum(turn["elapsed_ms"] for turn in turns),
        "turns": turns,
    }


def run_controlled_failures(
    *,
    catalog: MockCatalog,
    planner: Planner = decide_with_grok,
) -> list[dict]:
    """Fallos controlados: catálogo ausente, modelo inaccesible y salida inválida del modelo.

    Solo F-01 llama a Grok; F-02 apunta a un puerto local cerrado y F-03 no sale a la red.
    """
    missing_catalog = MockCatalog(catalog.path.parent / "missing_catalog_s2_failure.sqlite3")
    catalog_failure = _run_record(
        {
            "id": "F-01-CATALOG_UNAVAILABLE",
            "query": FAILURE_QUERY,
            "expected_status": "tool_error",
            "expected_error_code": "CATALOG_UNAVAILABLE",
        },
        executor=catalog_executor(missing_catalog),
        planner=planner,
    )
    previous_url = os.environ.get("GROK_BASE_URL")
    previous_key = os.environ.get("GROK_API_KEY")
    os.environ["GROK_BASE_URL"] = INVALID_LOCAL_BASE_URL
    if not (previous_key or "").strip():
        os.environ["GROK_API_KEY"] = "clave-local-prueba-fallo"
    try:
        model_failure = _run_record(
            {
                "id": "F-02-MODEL_UNAVAILABLE",
                "query": FAILURE_QUERY,
                "expected_status": "model_error",
                "expected_error_code": "MODEL_UNAVAILABLE",
            },
            executor=catalog_executor(catalog),
            planner=decide_with_grok,
        )
    finally:
        if previous_url is None:
            os.environ.pop("GROK_BASE_URL", None)
        else:
            os.environ["GROK_BASE_URL"] = previous_url
        if previous_key is None:
            os.environ.pop("GROK_API_KEY", None)
        else:
            os.environ["GROK_API_KEY"] = previous_key
    invalid_output = _run_record(
        {
            "id": "F-03-MODEL_INVALID_OUTPUT",
            "query": FAILURE_QUERY,
            "expected_status": "model_invalid",
            "expected_error_code": "MODEL_INVALID_OUTPUT",
        },
        executor=catalog_executor(catalog),
        planner=lambda *_: decision_from_raw(INVALID_MODEL_OUTPUT, model=DEFAULT_MODEL),
    )
    return [catalog_failure, model_failure, invalid_output]


def _parse_skip(raw_skip: list[str] | None) -> set[str]:
    skipped: set[str] = set()
    for entry in raw_skip or []:
        for item in entry.split(","):
            if item.strip():
                skipped.add(item.strip())
    return skipped


def evaluate_cases(
    cases: list[dict],
    *,
    catalog: MockCatalog,
    planner: Planner = decide_with_grok,
    skip_ids: set[str] | None = None,
    include_failures: bool = False,
) -> dict:
    """Ejecuta una lista de casos sobre el grafo trazado y construye el reporte de métricas."""
    skipped = skip_ids or set()
    selected_cases = [case for case in cases if case["id"] not in skipped]
    executor = catalog_executor(catalog)
    records = [
        (_run_conversation if "turns" in case else _run_record)(case, executor=executor, planner=planner)
        for case in selected_cases
    ]
    failures = run_controlled_failures(catalog=catalog, planner=planner) if include_failures else []

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": current_model(),
        "prompt_version": PROMPT_VERSION,
        "mock_db_sha256": hashlib.sha256(catalog.path.read_bytes()).hexdigest(),
        "skipped_ids": sorted(skipped),
        "passed": sum(record["passed"] for record in records),
        "total": len(records),
        "model_calls": sum(record["model_calls"] for record in records),
        "tool_calls": sum(len(record["tools"]) for record in records),
        "tools_executed": sum(len(record["tools_executed"]) for record in records),
        "input_tokens": sum(record["input_tokens"] or 0 for record in records),
        "output_tokens": sum(record["output_tokens"] or 0 for record in records),
        "cached_input_tokens": sum(record["cached_input_tokens"] or 0 for record in records),
        "elapsed_ms": sum(record["elapsed_ms"] for record in records),
        # Un caso rechazado antes de Grok no tiene llamadas: no es un costo desconocido sino cero.
        "cost": run_cost([record["cost"] for record in records if record["model_calls"]]),
        "cases": records,
        "controlled_failures": failures,
    }
    report["summary"] = summarize(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Evalúa el harness con casos sintéticos")
    parser.add_argument("--live", action="store_true", help="Hacer llamadas reales al modelo (consume cupo)")
    parser.add_argument("--limit", type=int, help="Máximo de casos; predeterminado: todos")
    parser.add_argument("--skip", nargs="*", default=[], help="IDs de casos a omitir (ej. --skip S2-02)")
    parser.add_argument("--suite", nargs="*", default=[],
                        help="Solo estas suites: s2, catalogo, tienda, seguridad, conversacion")
    parser.add_argument("--model", help="Modelo de Grok permitido por el reto (reemplaza GROK_MODEL)")
    parser.add_argument("--include-failures", action="store_true", help="Ejecutar también los 3 fallos controlados")
    parser.add_argument("--compare", nargs="+", metavar="REPORTE",
                        help="Tabla comparativa de reportes JSON ya generados; no llama a Grok")
    args = parser.parse_args()
    if args.compare:
        reports = [json.loads(Path(path).read_text(encoding="utf-8")) for path in args.compare]
        for report in reports:
            # Se recalcula con las reglas vigentes: así reportes viejos y nuevos se comparan igual.
            report["summary"] = summarize(report)
        print(comparison_markdown(reports))
        return 0
    if not args.live:
        print("Sin llamadas al modelo. Usa --live para ejecutar los casos sintéticos.")
        return 0
    # Se lee al empezar: una corrida larga no debe atribuirse a un commit hecho mientras corría.
    state = git_state()
    load_dotenv()
    if args.model:
        os.environ["GROK_MODEL"] = args.model
    catalog = MockCatalog()
    if not catalog.path.is_file():
        parser.error("Falta la base mock. Ejecuta: python -m asistendero.seed")
    all_cases = json.loads(DEFAULT_CASES_PATH.read_text(encoding="utf-8"))
    if args.suite:
        all_cases = [case for case in all_cases if case.get("suite") in set(args.suite)]
    limit = args.limit or len(all_cases)
    if not 1 <= limit <= len(all_cases):
        parser.error(f"--limit debe estar entre 1 y {len(all_cases)}")
    report = evaluate_cases(
        all_cases[:limit],
        catalog=catalog,
        skip_ids=_parse_skip(args.skip),
        include_failures=args.include_failures,
    )
    report.update(state)
    for record in report["cases"]:
        detail = f" — {'; '.join(record['fail_reasons'])}" if record["fail_reasons"] else ""
        print(f"{record['id']}: {'PASS' if record['passed'] else 'FAIL'} ({record['actual_status']}){detail}")
    for failure in report["controlled_failures"]:
        print(f"{failure['id']}: {'PASS' if failure['passed'] else 'FAIL'} ({failure['actual_status']})")
    report_path = Path(".local") / f"eval-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = report["summary"]
    print(f"Resultado: {report['passed']}/{report['total']} con {report['model']}. Costo: {summary['cost_usd']} USD "
          f"({summary['cost_per_task_usd']} por tarea). Reporte local: {report_path}")
    failures_ok = all(item["passed"] for item in report["controlled_failures"])
    return 0 if report["passed"] == report["total"] and failures_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
