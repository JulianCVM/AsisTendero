"""Modo desatendido (S4): procesa la cola de carga durante horas, sin nadie, y deja una bitácora por tarea.

    python -m asistendero.evaluacion.desatendido preparar --tareas 1300
    python -m asistendero.evaluacion.desatendido correr --horas 12.25 --budget-usd 25 --supervisar
    python -m asistendero.evaluacion.desatendido resumen

- **Ritmo fijo:** la tarea i arranca a ``inicio + i × intervalo``, con el intervalo que reparte la cola en las horas
  pedidas. Así la llave consume de forma pareja durante toda la ventana, sin ráfagas ni relleno.
- **Reanudable:** lo hecho se lee de la bitácora; si el proceso se cae, el supervisor lo vuelve a lanzar y sigue con la
  tarea siguiente, en el mismo horario. Una tarea no se repite ni se reintenta: el reglamento castiga inflar el consumo.
- **Recuperación:** un fallo de Grok termina en el estado seguro del grafo y queda anotado con su código; tras varios
  seguidos, el proceso espera (sin llamar a nadie) antes de seguir. Una excepción no detiene la cola.
- **Tope de gasto:** al llegar a ``--budget-usd`` no empieza más tareas.
- **Bitácora:** ``evaluation/s4_carga/bitacora.jsonl`` (una línea por tarea y por evento), ``bitacora.csv`` y
  ``RESUMEN.md``. Nunca lleva la llave.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

from asistendero.agente.modelo.grok import current_model, decide_with_grok
from asistendero.agente.reglas.context_resolution import load_catalog_words
from asistendero.datos.carluz import CARLUZ_BUSINESS_ID
from asistendero.datos.importar_carluz import CARLUZ_DB_PATH, CARLUZ_DIR
from asistendero.datos.seed import upgrade_db
from asistendero.evaluacion.bitacora_carga import (
    BITACORA, COLA, DONE, ESTADO, append, done_ids, events_of, write_summary,
)
from asistendero.evaluacion.carga_carluz import build_queue
from asistendero.evaluacion.eval_report import record_cost
from asistendero.evaluacion.evaluate import evaluate_cases, git_state
from asistendero.tienda import reloj
from asistendero.tienda.catalogo.catalog import MockCatalog

RUN_DB = CARLUZ_DIR / "carga" / "tienda.sqlite3"
MODEL_FAILURES = {"model_error", "model_invalid", "limit_reached"}
PAUSE_AFTER = 3          # fallos de Grok seguidos antes de esperar
MAX_PAUSE_S = 600
MAX_RESTARTS = 50
RESTART_WAIT_S = 30
SUMMARY_EVERY = 25
MAX_RESPONSE_CHARS = 1500


def _now() -> datetime:
    return datetime.now(timezone.utc)


def keep_awake() -> None:
    """Windows suspende el equipo inactivo y la corrida se cortaría: se le pide que siga despierto."""
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED


def _codes(record: dict) -> list[str]:
    codes = [(call.get("error") or {}).get("code") for call in record.get("tool_calls", [])]
    for turn in record.get("turns", []):
        codes += [(call.get("error") or {}).get("code") for call in turn.get("tool_calls", [])]
    # Una conversación trae un estado por turno.
    status = record.get("actual_status")
    if MODEL_FAILURES & (set(status) if isinstance(status, list) else {status}):
        codes.append("MODEL_FAILURE")
    return list(dict.fromkeys(code for code in codes if code))


def recovery(codes: list[str]) -> str:
    """Cómo siguió el agente después de cada error: lo pide la bitácora de S4."""
    if not codes:
        return ""
    if "MODEL_FAILURE" in codes:
        return "Grok falló o no respondió: el grafo cerró en un estado seguro, sin precio inventado, y la cola siguió."
    return (f"La herramienta devolvió {', '.join(codes)}: Grok recibió la observación y respondió con ella, "
            "sin inventar precio ni existencias.")


def _product_reason(task: dict, record: dict) -> list[str]:
    """Si el agente dijo que tiene el producto pedido, debe ser ese y no otro parecido."""
    wanted = task.get("productos")
    if not wanted or record.get("actual_status") not in ("found", "quoted"):
        return []
    return [] if set(wanted) & set(record.get("selected_skus") or []) else ["eligió otro producto"]


def entry(task: dict, record: dict, started: datetime, state: dict) -> dict:
    reasons = list(record.get("fail_reasons", [])) + _product_reason(task, record)
    codes = _codes(record)
    return {
        "tipo": "tarea", "id": task["id"], "clase": task["tipo"],
        "inicio": started.isoformat(), "fin": _now().isoformat(),
        "entrada": record.get("query") or task.get("query"),
        "resultado": record.get("actual_status"), "esperado": task.get("expected_status") or "conversación",
        "exito": not reasons, "motivos": reasons,
        "respuesta": (record.get("response") or "")[:MAX_RESPONSE_CHARS],
        "llamadas_grok": record.get("model_calls"),
        "tokens_entrada": record.get("input_tokens"), "tokens_salida": record.get("output_tokens"),
        # El costo de un caso es {"usd", "basis", "calls"}; la bitácora guarda solo los dólares (lo midió la API).
        "costo_usd": str(cost) if (cost := record_cost(record)) is not None else None,
        "errores": codes, "recuperacion": recovery(codes),
        "duracion_ms": record.get("elapsed_ms"), "modelo": record.get("model") or current_model(),
        "prompt_version": record.get("prompt_version"), "commit": state["commit"],
    }


def failed_entry(task: dict, error: BaseException, started: datetime, state: dict) -> dict:
    # Un error de programa no puede tumbar una corrida de doce horas: se registra como tarea fallida y se sigue.
    return {
        "tipo": "tarea", "id": task["id"], "clase": task["tipo"], "inicio": started.isoformat(),
        "fin": _now().isoformat(), "entrada": task.get("query") or task["turns"][0]["query"],
        "resultado": "excepcion", "esperado": task.get("expected_status") or "conversación", "exito": False,
        "motivos": [type(error).__name__], "respuesta": "", "llamadas_grok": None, "tokens_entrada": None,
        "tokens_salida": None, "costo_usd": None, "errores": ["RUNNER_EXCEPTION"],
        "recuperacion": "Excepción en la tarea: se registró como fallida y la cola siguió con la siguiente.",
        "duracion_ms": None, "modelo": current_model(), "prompt_version": None, "commit": state["commit"],
    }


def run_task(task: dict, catalog: MockCatalog, planner) -> dict:
    report = evaluate_cases([task], catalog=catalog, planner=planner)
    return report["cases"][0]


def _start_state(hours: float, total: int, folder: Path) -> dict:
    path = folder / ESTADO
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    state = {"inicio": _now().isoformat(), "horas": hours, "tareas": total,
             "intervalo_s": hours * 3600 / total, **git_state(), "modelo": current_model()}
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def work(folder: Path, hours: float, budget: Decimal, planner=decide_with_grok, sleep=time.sleep,
         database: Path = RUN_DB) -> int:
    queue = json.loads((folder / COLA).read_text(encoding="utf-8"))
    state = _start_state(hours, len(queue), folder)
    done = done_ids(folder / BITACORA)
    spent = sum((Decimal(line["costo_usd"]) for line in events_of(folder / BITACORA)
                 if line["tipo"] == "tarea" and line.get("costo_usd")), Decimal(0))
    catalog = MockCatalog(upgrade_db(database), CARLUZ_BUSINESS_ID)
    load_catalog_words("carluz", catalog.word_rows())
    start = datetime.fromisoformat(state["inicio"])
    append(folder / BITACORA, {"tipo": "evento", "hora": _now().isoformat(), "evento": "arranque",
                               "detalle": f"{len(done)} de {len(queue)} tareas ya hechas; gasto {spent} USD"})
    failures_in_a_row = 0
    for index, task in enumerate(queue):
        if task["id"] in done:
            continue
        if spent >= budget:
            append(folder / BITACORA, {"tipo": "evento", "hora": _now().isoformat(), "evento": "tope_de_gasto",
                                       "detalle": f"{spent} USD de {budget}: no se empiezan más tareas"})
            break
        wait = (start + timedelta(seconds=index * state["intervalo_s"]) - _now()).total_seconds()
        if wait > 0:
            sleep(wait)
        started = _now()
        try:
            line = entry(task, run_task(task, catalog, planner), started, state)
        except Exception as error:  # noqa: BLE001 - ver failed_entry
            line = failed_entry(task, error, started, state)
        append(folder / BITACORA, line)
        spent += Decimal(line["costo_usd"] or 0)
        failures_in_a_row = failures_in_a_row + 1 if "MODEL_FAILURE" in line["errores"] else 0
        if failures_in_a_row >= PAUSE_AFTER:
            pause = min(MAX_PAUSE_S, 60 * 2 ** (failures_in_a_row - PAUSE_AFTER))
            append(folder / BITACORA, {"tipo": "evento", "hora": _now().isoformat(), "evento": "pausa",
                                       "detalle": f"{failures_in_a_row} fallos de Grok seguidos: espera {pause} s"})
            sleep(pause)
        if (index + 1) % SUMMARY_EVERY == 0:
            write_summary(folder)
    append(folder / BITACORA, {"tipo": "evento", "hora": _now().isoformat(), "evento": "fin", "detalle": ""})
    write_summary(folder)
    (folder / DONE).write_text(_now().isoformat(), encoding="utf-8")
    return 0


def supervise(arguments: list[str], folder: Path, sleep=time.sleep, launch=subprocess.run) -> int:
    """Relanza el trabajo si el proceso se cae: «doce horas sin que nadie lo reinicie a mano»."""
    for attempt in range(MAX_RESTARTS + 1):
        code = launch([sys.executable, "-m", "asistendero.evaluacion.desatendido", *arguments]).returncode
        if code == 0 or (folder / DONE).is_file():
            return 0
        append(folder / BITACORA, {"tipo": "evento", "hora": _now().isoformat(), "evento": "reinicio_automatico",
                                   "detalle": f"el proceso terminó con código {code}; intento {attempt + 1}"})
        sleep(RESTART_WAIT_S)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Semana de carga S4 sobre el inventario real de Carluz")
    sub = parser.add_subparsers(dest="orden", required=True)
    prepare = sub.add_parser("preparar", help="Arma la cola de tareas distintas (no llama a Grok)")
    prepare.add_argument("--tareas", type=int, default=1300)
    prepare.add_argument("--semilla", type=int, default=7)
    run = sub.add_parser("correr", help="Procesa la cola con Grok real (consume créditos del reto)")
    run.add_argument("--horas", type=float, default=12.25)
    run.add_argument("--budget-usd", type=Decimal, required=True)
    run.add_argument("--supervisar", action="store_true", help="Relanza el proceso si se cae")
    sub.add_parser("resumen", help="Rehace bitacora.csv y RESUMEN.md desde la bitácora")
    parser.add_argument("--carpeta", type=Path, default=Path("evaluation/s4_carga"))
    args = parser.parse_args()
    folder: Path = args.carpeta
    folder.mkdir(parents=True, exist_ok=True)
    if args.orden == "preparar":
        if (folder / BITACORA).exists():
            parser.error(f"Ya hay una bitácora en {folder}: la cola no se cambia a mitad de una corrida.")
        if not CARLUZ_DB_PATH.is_file():
            parser.error(f"No existe {CARLUZ_DB_PATH}: impórtala con python -m asistendero.datos.importar_carluz")
        queue = build_queue(CARLUZ_DB_PATH, args.tareas, args.semilla)
        (folder / COLA).write_text(json.dumps(queue, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{len(queue)} tareas distintas en {folder / COLA}")
        return 0
    if args.orden == "resumen":
        write_summary(folder)
        print(f"{folder / 'RESUMEN.md'}")
        return 0
    if args.budget_usd <= 0 or not 0 < args.horas <= 48:
        parser.error("--budget-usd debe ser mayor que cero y --horas ir de 0 a 48")
    keep_awake()
    if args.supervisar:
        rest = ["--carpeta", str(folder), "correr", "--horas", str(args.horas), "--budget-usd", str(args.budget_usd)]
        return supervise(rest, folder)
    load_dotenv()
    if not RUN_DB.is_file():
        # La corrida aparta pedidos de prueba: trabaja sobre una copia para no tocar la base de la tienda.
        RUN_DB.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(CARLUZ_DB_PATH, RUN_DB)
    return work(folder, args.horas, args.budget_usd)


if __name__ == "__main__":
    raise SystemExit(main())
