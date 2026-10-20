"""Evaluación manual con casos sintéticos; las llamadas pagadas exigen --live."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from asistendero.catalog import MockCatalog
from asistendero.executor import catalog_executor
from asistendero.graph import Planner
from asistendero.grok import DEFAULT_MODEL, PROMPT_VERSION, decide_with_grok
from asistendero.pricing import run_cost
from asistendero.tracing import run_traced
from asistendero.validation import grounded_products


DEFAULT_CASES_PATH = Path("evaluation/cases.json")


def _selected_skus(query: str, tool_calls: list[dict]) -> list[str]:
    skus: list[str] = []
    for call in tool_calls:
        if not call["executed"]:
            continue
        if call["requested_tool"] == "consultar_disponibilidad":
            skus.append(call["arguments"]["sku"])
        elif call["requested_tool"] == "calcular_cotizacion_informativa":
            skus.extend(line["sku"] for line in call["arguments"]["lines"])
    skus.extend(grounded_products(query, tool_calls).keys())
    return list(dict.fromkeys(skus))


def evaluate_cases(
    cases: list[dict],
    *,
    catalog: MockCatalog,
    planner: Planner = decide_with_grok,
) -> dict:
    """Ejecuta una lista de casos sobre el grafo trazado y construye el reporte de métricas."""
    executor = catalog_executor(catalog)
    records = []
    for case in cases:
        events: list[dict] = []
        result = run_traced(case["query"], events.append, executor, planner)
        final_details = events[-1]["details"]
        tool_calls = result.get("tool_calls", [])
        selected_skus = _selected_skus(case["query"], tool_calls)
        passed = result["estado"] == case["expected_status"]
        if case.get("expected_sku"):
            passed = passed and case["expected_sku"] in selected_skus
        if case.get("expected_skus"):
            passed = passed and all(sku in selected_skus for sku in case["expected_skus"])

        records.append({
            "id": case["id"],
            "run_id": result["run_id"],
            "query": case["query"],
            "expected_status": case["expected_status"],
            "actual_status": result["estado"],
            "expected_sku": case.get("expected_sku"),
            "expected_skus": case.get("expected_skus"),
            "selected_skus": selected_skus,
            "passed": passed,
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
        })

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": os.getenv("GROK_MODEL", DEFAULT_MODEL),
        "prompt_version": PROMPT_VERSION,
        "mock_db_sha256": hashlib.sha256(catalog.path.read_bytes()).hexdigest(),
        "passed": sum(record["passed"] for record in records),
        "total": len(records),
        "model_calls": sum(record["model_calls"] for record in records),
        "tool_calls": sum(len(record["tools"]) for record in records),
        "tools_executed": sum(len(record["tools_executed"]) for record in records),
        "input_tokens": sum(record["input_tokens"] or 0 for record in records),
        "output_tokens": sum(record["output_tokens"] or 0 for record in records),
        "cached_input_tokens": sum(record["cached_input_tokens"] or 0 for record in records),
        "elapsed_ms": sum(record["elapsed_ms"] for record in records),
        "cost": run_cost([record["cost"] for record in records]),
        "cases": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evalúa el harness con casos sintéticos")
    parser.add_argument("--live", action="store_true", help="Hacer llamadas reales al modelo (consume cupo)")
    parser.add_argument("--limit", type=int, default=10, help="Máximo de casos; predeterminado: 10")
    args = parser.parse_args()
    if not args.live:
        print("Sin llamadas al modelo. Usa --live para ejecutar los casos sintéticos.")
        return 0
    load_dotenv()
    catalog = MockCatalog()
    if not catalog.path.is_file():
        parser.error("Falta la base mock. Ejecuta: python -m asistendero.seed")
    all_cases = json.loads(DEFAULT_CASES_PATH.read_text(encoding="utf-8"))
    if not 1 <= args.limit <= len(all_cases):
        parser.error(f"--limit debe estar entre 1 y {len(all_cases)}")
    report = evaluate_cases(all_cases[:args.limit], catalog=catalog)
    for record in report["cases"]:
        print(f"{record['id']}: {'PASS' if record['passed'] else 'FAIL'} ({record['actual_status']})")
    report_path = Path(".local") / f"eval-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Resultado: {report['passed']}/{report['total']}. Reporte local: {report_path}")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
