"""Evaluación con casos sintéticos de uno o varios turnos; las llamadas pagadas exigen --live."""

import argparse
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading

from dotenv import load_dotenv

from asistendero.catalog import MockCatalog
from asistendero.eval_checks import record
from asistendero.eval_report import comparison_markdown, record_cost, summarize
from asistendero.eval_sessions import SIM_START, StoreClock, run_clients, run_conversation, store_time, using_model
from asistendero.executor import catalog_executor
from asistendero.graph import Planner, ToolExecutor
from asistendero.grok import (
    ALLOWED_MODEL_FAMILIES, DEFAULT_MODEL, PROMPT_VERSION, current_model, decide_with_grok, decision_from_raw,
)
from asistendero.pricing import run_cost
from asistendero.tracing import run_traced


DEFAULT_CASES_PATH = Path("evaluation/cases.json")
SUITES = ("s2", "catalogo", "tienda", "seguridad", "conversacion", "ruido", "pedidos", "sesion_larga", "concurrencia",
          "extremos", "flujos", "variados")
# Más hilos no prueban nada nuevo y en S3 cinco corridas en paralelo agotaron la memoria del equipo.
MAX_CONCURRENCY = 6
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


def _run_record(case: dict, *, executor: ToolExecutor, planner: Planner) -> dict:
    events: list[dict] = []
    result = run_traced(case["query"], events.append, executor, planner)
    return {"id": case["id"], "suite": case.get("suite", "s2"), "model": current_model(), **record(case, result, events)}


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
    on_record: Callable[[dict], None] = lambda record: None,
    models: list[str] | None = None,
    concurrency: int = 1,
    budget_usd: Decimal | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict:
    """Ejecuta una lista de casos sobre el grafo trazado y construye el reporte de métricas.

    ``on_record`` recibe cada caso apenas termina: si la corrida se interrumpe, lo ya gastado queda registrado.
    ``models`` se reparte en rueda: el caso i (y, en un caso con clientes, el cliente j) usa un modelo distinto.
    ``concurrency`` casos corren a la vez. Con ``budget_usd`` no empieza ningún caso nuevo cuando lo gastado
    llega al tope; los casos que ya corrían terminan, así que el total puede pasarlo por lo que cuesta uno.
    ``clock`` fija la hora de la tienda (``StoreClock`` en una corrida real).
    """
    skipped = skip_ids or set()
    selected_cases = [case for case in cases if case["id"] not in skipped]
    executor = catalog_executor(catalog)
    rotation = list(models or [])
    lock = threading.Lock()
    spent = {"usd": Decimal(0)}
    over_budget: list[str] = []
    stop = threading.Event()

    def run(index: int, case: dict, folder: Path) -> dict | None:
        with lock:
            if stop.is_set():
                return None
            if budget_usd is not None and spent["usd"] >= budget_usd:
                over_budget.append(case["id"])
                return None
        # El caso i arranca la rueda en el modelo i: así cada modelo atiende a todos los tipos de cliente.
        turn = rotation[index % len(rotation):] + rotation[:index % len(rotation)] if rotation else []
        try:
            with using_model(turn[0] if turn else None):
                if "clients" in case:
                    clients = turn or [current_model()]
                    result = run_clients(case, catalog_path=catalog.path, folder=folder, planner=planner, models=clients)
                elif "turns" in case:
                    result = run_conversation(case, catalog_path=catalog.path, folder=folder, planner=planner)
                else:
                    result = _run_record(case, executor=executor, planner=planner)
        except BaseException:
            # Un caso que revienta (o un Ctrl-C) detiene la corrida: los casos en cola no deben seguir gastando.
            stop.set()
            raise
        with lock:
            spent["usd"] += record_cost(result) or 0
            on_record(result)
        return result

    with store_time(clock) if clock else nullcontext(), tempfile.TemporaryDirectory() as folder:
        pool = ThreadPoolExecutor(max_workers=max(1, concurrency))
        try:
            futures = [pool.submit(run, index, case, Path(folder)) for index, case in enumerate(selected_cases)]
            records = [result for future in futures if (result := future.result()) is not None]
        except BaseException:
            stop.set()
            pool.shutdown(wait=True, cancel_futures=True)
            raise
        pool.shutdown()
        failures = run_controlled_failures(catalog=catalog, planner=planner) if include_failures else []

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": current_model(),
        "prompt_version": PROMPT_VERSION,
        "mock_db_sha256": hashlib.sha256(catalog.path.read_bytes()).hexdigest(),
        "skipped_ids": sorted(skipped),
        # En un caso con clientes, cada cliente usa su modelo; el renglón del caso los junta en un texto.
        "models": sorted({unit["model"] for record in records for unit in record.get("clients", [record])}),
        "concurrency": concurrency,
        "budget_usd": None if budget_usd is None else str(budget_usd),
        "budget_skipped_ids": over_budget,
        "store_time_start": clock.start.isoformat(timespec="minutes") if isinstance(clock, StoreClock) else None,
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
    parser.add_argument("--suite", nargs="*", default=[], choices=SUITES, help="Solo estas suites")
    parser.add_argument("--model", help="Modelo de Grok permitido por el reto (reemplaza GROK_MODEL)")
    parser.add_argument("--models", nargs="+", metavar="MODELO",
                        help="Varios modelos en rueda: cada caso (o cliente simulado) usa el siguiente")
    parser.add_argument("--concurrency", type=int, default=1,
                        help=f"Casos a la vez, de 1 a {MAX_CONCURRENCY}; predeterminado: 1")
    parser.add_argument("--budget-usd", type=Decimal, metavar="USD",
                        help="Tope de gasto: no empieza casos nuevos al llegar a él")
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
    if not 1 <= args.concurrency <= MAX_CONCURRENCY:
        parser.error(f"--concurrency debe estar entre 1 y {MAX_CONCURRENCY}")
    for model in [args.model, *(args.models or [])]:
        if model and not model.startswith(ALLOWED_MODEL_FAMILIES):
            parser.error(f"{model} no es un modelo permitido por el reto (Grok 4.7, 4.6, 4.5 o 4.20)")
    if args.budget_usd is not None and args.budget_usd <= 0:
        parser.error("--budget-usd debe ser mayor que cero")
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
    started = datetime.now(timezone.utc)
    # Bitácora parcial, un renglón por caso: en S3 cinco corridas se cortaron por falta de memoria del equipo
    # sin dejar reporte, y su consumo no se pudo registrar.
    partial_path = Path(".local") / f"eval-{started:%Y%m%dT%H%M%S%fZ}.partial.jsonl"

    def log_partial(record: dict) -> None:
        line = {"id": record["id"], "model": record["model"], "prompt_version": PROMPT_VERSION, **state,
                "passed": record["passed"], "model_calls": record["model_calls"],
                "total_tokens": record.get("total_tokens"), "cost": record.get("cost")}
        with partial_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")

    report = evaluate_cases(
        all_cases[:limit],
        catalog=catalog,
        skip_ids=_parse_skip(args.skip),
        include_failures=args.include_failures,
        on_record=log_partial,
        models=args.models,
        concurrency=args.concurrency,
        budget_usd=args.budget_usd,
        clock=StoreClock(SIM_START),
    )
    report.update(state)
    for record in report["cases"]:
        detail = f" — {'; '.join(record['fail_reasons'])}" if record["fail_reasons"] else ""
        print(f"{record['id']}: {'PASS' if record['passed'] else 'FAIL'} ({record['actual_status']}){detail}")
    for failure in report["controlled_failures"]:
        print(f"{failure['id']}: {'PASS' if failure['passed'] else 'FAIL'} ({failure['actual_status']})")
    report_path = Path(".local") / f"eval-{started:%Y%m%dT%H%M%S%fZ}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = report["summary"]
    for model, values in summary["by_model"].items():
        print(f"  {model}: {values['passed']}/{values['total']} · {values['cost_usd']} USD · "
              f"{values['model_calls']} llamadas · {values['tokens']} tokens")
    if report["budget_skipped_ids"]:
        print(f"Sin correr por el tope de gasto: {', '.join(report['budget_skipped_ids'])}")
    print(f"Resultado: {report['passed']}/{report['total']} con {', '.join(report['models'])}. Costo: "
          f"{summary['cost_usd']} USD ({summary['cost_per_task_usd']} por tarea). Reporte local: {report_path}")
    failures_ok = all(item["passed"] for item in report["controlled_failures"])
    return 0 if report["passed"] == report["total"] and failures_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
