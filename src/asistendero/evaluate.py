"""Evaluación manual con casos sintéticos; las llamadas pagadas exigen --live."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from time import perf_counter

from dotenv import load_dotenv

from asistendero.catalog import MockCatalog
from asistendero.graph import build_graph
from asistendero.grok import PROMPT_VERSION, decide_with_grok


def main() -> int:
    parser = argparse.ArgumentParser(description="Evalúa el harness con casos sintéticos")
    parser.add_argument("--live", action="store_true", help="Hacer llamadas reales al modelo (consume cupo)")
    parser.add_argument("--limit", type=int, default=4, help="Máximo de casos; predeterminado: 4")
    args = parser.parse_args()
    if not args.live:
        print("Sin llamadas al modelo. Usa --live para ejecutar los casos sintéticos.")
        return 0
    load_dotenv()
    catalog = MockCatalog()
    if not catalog.path.is_file():
        parser.error("Falta la base mock. Ejecuta: python -m asistendero.seed")
    case_path = Path("evaluation/cases.json")
    all_cases = json.loads(case_path.read_text(encoding="utf-8"))
    if not 1 <= args.limit <= len(all_cases):
        parser.error(f"--limit debe estar entre 1 y {len(all_cases)}")
    cases = all_cases[:args.limit]
    graph = build_graph(catalog, decide_with_grok)
    records = []
    for case in cases:
        started = perf_counter()
        result = graph.invoke({"consulta": case["query"]})
        elapsed_ms = round((perf_counter() - started) * 1000)
        decision = result.get("decision")
        selected_sku = decision.selected_sku if decision else None
        passed = result["estado"] == case["expected_status"]
        if case.get("expected_sku"):
            passed = passed and selected_sku == case["expected_sku"]
        records.append({
            "id": case["id"], "query": case["query"], "expected_status": case["expected_status"],
            "actual_status": result["estado"], "expected_sku": case.get("expected_sku"),
            "selected_sku": selected_sku, "passed": passed, "response": result["respuesta"],
            "model_called": result["model_called"],
            "input_tokens": decision.input_tokens if decision else 0,
            "output_tokens": decision.output_tokens if decision else 0,
            "elapsed_ms": elapsed_ms,
        })
        print(f"{case['id']}: {'PASS' if passed else 'FAIL'} ({result['estado']})")

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": os.getenv("GROK_MODEL", "grok-4.20-0309-non-reasoning"),
        "prompt_version": PROMPT_VERSION,
        "mock_db_sha256": hashlib.sha256(catalog.path.read_bytes()).hexdigest(),
        "passed": sum(record["passed"] for record in records),
        "total": len(records),
        "model_calls": sum(record["model_called"] for record in records),
        "input_tokens": sum(record["input_tokens"] or 0 for record in records),
        "output_tokens": sum(record["output_tokens"] or 0 for record in records),
        "cases": records,
    }
    report_path = Path(".local") / f"eval-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Resultado: {report['passed']}/{report['total']}. Reporte local: {report_path}")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
