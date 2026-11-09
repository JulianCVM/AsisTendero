"""Punto de entrada para el harness del reto: corre casos ajenos contra AsisTendero y devuelve una línea JSON por caso.

Ejecutar: python -m asistendero.entregas.harness casos.jsonl
          python -m asistendero.entregas.harness casos.jsonl --salida resultados.jsonl --tienda carluz
          python -m asistendero.entregas.harness --mensaje "Busco tubo PVC de 1/2 para agua"
          python -m asistendero.entregas.harness - < casos.jsonl

Los formatos de entrada están en ``harness_casos.py``. Cada caso es una conversación nueva sobre una copia de la
tienda en una carpeta temporal: lo que un caso aparta no cambia otro, y la base original no se toca. Cada turno pasa
por ``run_turn``, igual que un cliente del visor (barreras, Grok, herramientas validadas y respuesta verificada), y
llama a Grok con la llave del ``.env``: **consume créditos**. Cada turno deja una línea en la bitácora de consumo
(``.local/harness/bitacora.jsonl``) con su costo, sin el texto del cliente.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from threading import Lock
from uuid import uuid4

from dotenv import load_dotenv

from asistendero.agente.conversacion.chat import run_turn
from asistendero.agente.conversacion.sessions import SessionError, SessionStore
from asistendero.agente.flujo.graph import Planner
from asistendero.agente.modelo.grok import ALLOWED_MODEL_FAMILIES, current_model, decide_with_grok
from asistendero.datos.importar_carluz import CARLUZ_DB_PATH
from asistendero.datos.seed import DEFAULT_DB_PATH, KNOWN_BUSINESSES, create_mock_db, upgrade_db
from asistendero.entregas.harness_casos import HarnessCase, Turn, read_cases
from asistendero.evaluacion.bitacora_carga import append
from asistendero.evaluacion.eval_sessions import using_model
from asistendero.tienda.pedidos.orders import OrderBook

DEFAULT_LOG = Path(".local") / "harness" / "bitacora.jsonl"
MAX_CONCURRENCY = 6
STORES = ("ferreteria", "mercado", "carluz")


def store_database(store: str) -> Path:
    """La base de la tienda: la ficticia se crea si falta; la real solo existe si se importó su Excel."""
    if store == "carluz":
        if not CARLUZ_DB_PATH.is_file():
            raise FileNotFoundError(f"No existe {CARLUZ_DB_PATH}. Impórtala con: "
                                    'python -m asistendero.datos.importar_carluz --xlsx "RUTA DEL EXCEL"')
        return CARLUZ_DB_PATH
    return upgrade_db(DEFAULT_DB_PATH) if DEFAULT_DB_PATH.is_file() else create_mock_db(DEFAULT_DB_PATH)


def _usd(cost: dict | None) -> str | None:
    return cost["usd"] if cost else None


def turn_output(index: int, turn: Turn, result: dict, events: list[dict]) -> dict:
    """Lo que el harness ve de un turno: respuesta, estado, herramientas, llamadas, tokens y costo."""
    final = next(event["details"] for event in reversed(events) if event["type"] == "final")
    calls = result.get("tool_calls", [])
    return {
        "turno": index,
        "mensaje": turn.message,
        "con_foto": turn.photo is not None,
        "respuesta": result["respuesta"],
        "estado": result["estado"],
        "error": (result.get("error") or {}).get("code"),
        "herramientas": [{"nombre": call["requested_tool"], "ejecutada": call["executed"],
                          "estado": call["response"].get("status"),
                          "error": (call["response"].get("error") or {}).get("code")} for call in calls],
        "barreras": final["barreras"],
        "llamadas_grok": final["model_calls"],
        "tokens": {"entrada": final["input_tokens"], "salida": final["output_tokens"],
                   "entrada_en_cache": final["cached_input_tokens"], "total": final["total_tokens"]},
        "costo_usd": _usd(final["cost"]),
        "base_costo": final["cost"]["basis"] if final["cost"] else None,
        "latencia_ms": final["duration_ms"],
        "run_id": result["run_id"],
        "prompt_version": final["prompt_version"],
        "imagenes": len(result.get("imagenes") or []),
    }


def _refused_turn(index: int, turn: Turn, code: str) -> dict:
    """Turno que no llegó al agente (sesión baneada o llena): no llama a Grok ni cuesta."""
    return {"turno": index, "mensaje": turn.message, "con_foto": turn.photo is not None, "respuesta": "",
            "estado": code, "error": code, "herramientas": [], "barreras": [], "llamadas_grok": 0,
            "tokens": {"entrada": None, "salida": None, "entrada_en_cache": None, "total": None},
            "costo_usd": None, "base_costo": None, "latencia_ms": 0, "run_id": None, "prompt_version": None,
            "imagenes": 0}


def case_totals(case: HarnessCase, store: str, turns: list[dict], error: str | None = None) -> dict:
    costs = [Decimal(turn["costo_usd"]) for turn in turns if turn["costo_usd"] is not None]
    return {"id": case.id, "tienda": store, "modelo": current_model(), "error": error, "turnos": turns,
            "llamadas_grok": sum(turn["llamadas_grok"] for turn in turns),
            "costo_usd": format(sum(costs, Decimal(0)), ".10f") if costs else None,
            "latencia_ms": sum(turn["latencia_ms"] for turn in turns)}


def run_case(case: HarnessCase, *, store: str, database: Path, folder: Path, planner: Planner,
             log: Callable[[str, dict], None]) -> dict:
    """Una conversación nueva sobre su propia copia de la tienda; un fallo inesperado termina en un estado seguro."""
    if case.error:
        return case_totals(case, store, [], case.error)
    copy = folder / f"{uuid4().hex}.sqlite3"
    shutil.copy(database, copy)
    book = OrderBook(copy, business_id=KNOWN_BUSINESSES[store])
    sessions = SessionStore(folder / f"{copy.stem}-sesiones.sqlite3")
    session_id = sessions.create()
    turns: list[dict] = []
    for index, turn in enumerate(case.turns, 1):
        events: list[dict] = []
        try:
            result = run_turn(sessions, session_id, turn.message, events.append, None, planner, orders=book,
                              image=turn.photo)
        except SessionError as error:
            turns.append(_refused_turn(index, turn, error.code))
            continue
        except Exception as error:  # noqa: BLE001 - el harness sigue con el caso siguiente
            # No se muestra el mensaje: los errores del SDK pueden traer datos de la solicitud.
            return case_totals(case, store, turns, f"HARNESS_FAILURE: {type(error).__name__}")
        turns.append(turn_output(index, turn, result, events))
        log(case.id, turns[-1])
    return case_totals(case, store, turns)


class ConsumptionLog:
    """Bitácora de consumo: una línea por turno con su costo y sin el texto del cliente."""

    def __init__(self, path: Path | None, store: str):
        self.path, self.store, self.run = path, store, uuid4().hex[:12]
        self.lock = Lock()
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, case_id: str, turn: dict) -> None:
        if self.path is None:
            return
        line = {"fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"), "corrida": self.run,
                "caso": case_id, "turno": turn["turno"], "tienda": self.store, "run_id": turn["run_id"],
                "modelo": current_model(), "prompt_version": turn["prompt_version"], "estado": turn["estado"],
                "llamadas_grok": turn["llamadas_grok"], "tokens_entrada": turn["tokens"]["entrada"],
                "tokens_salida": turn["tokens"]["salida"], "costo_usd": turn["costo_usd"],
                "base_costo": turn["base_costo"]}
        with self.lock:
            append(self.path, line)


def run_cases(cases: list[HarnessCase], *, store: str, write: Callable[[dict], None],
              planner: Planner = decide_with_grok, model: str | None = None,
              budget_usd: Decimal | None = None, concurrency: int = 1,
              log_path: Path | None = DEFAULT_LOG) -> dict:
    """Corre los casos y escribe cada resultado apenas termina; con tope, no empieza casos nuevos al llegar a él."""
    database = store_database(store)
    log = ConsumptionLog(log_path, store)
    spent, lock, totals = Decimal(0), Lock(), {"casos": 0, "turnos": 0, "llamadas_grok": 0, "omitidos": 0}
    # En Windows SQLite puede tardar en soltar un archivo: la carpeta temporal no debe tumbar la corrida al borrarse.
    temporary = tempfile.TemporaryDirectory(prefix="asistendero-harness-", ignore_cleanup_errors=True)
    folder = Path(temporary.name)

    def one(case: HarnessCase) -> None:
        nonlocal spent
        with lock:
            # Un caso inválido no gasta: se informa su motivo aunque ya se haya llegado al tope.
            over = budget_usd is not None and spent >= budget_usd and case.error is None
        with using_model(model):
            output = (case_totals(case, store, [], "BUDGET_REACHED") if over
                      else run_case(case, store=store, database=database, folder=folder, planner=planner, log=log))
        with lock:
            spent += Decimal(output["costo_usd"] or 0)
            totals["casos"] += 1
            totals["turnos"] += len(output["turnos"])
            totals["llamadas_grok"] += output["llamadas_grok"]
            totals["omitidos"] += over
            write(output)

    with temporary, ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(one, cases))
    return {**totals, "costo_usd": format(spent, ".10f"), "corrida": log.run}


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Corre casos de un harness contra AsisTendero (consume créditos).")
    parser.add_argument("casos", nargs="?", help="Archivo JSONL, JSON o .txt de casos; «-» lee la entrada estándar")
    parser.add_argument("--mensaje", help="Un solo mensaje, en vez de un archivo de casos")
    parser.add_argument("--salida", type=Path, help="Archivo JSONL de resultados; sin él, la salida estándar")
    parser.add_argument("--tienda", choices=STORES, default="ferreteria",
                        help="ferreteria y mercado son ficticias; carluz es el inventario real importado")
    parser.add_argument("--model", help="Modelo de Grok permitido por el reto (reemplaza GROK_MODEL)")
    parser.add_argument("--concurrencia", type=int, default=1, help=f"Casos a la vez, de 1 a {MAX_CONCURRENCY}")
    parser.add_argument("--budget-usd", type=Decimal, metavar="USD", help="No empieza casos nuevos al llegar al tope")
    parser.add_argument("--bitacora", type=Path, default=DEFAULT_LOG, help="Bitácora de consumo (JSONL)")
    args = parser.parse_args(argv)
    if (args.casos is None) == (args.mensaje is None):
        parser.error("Indica un archivo de casos o --mensaje, no los dos.")
    if not 1 <= args.concurrencia <= MAX_CONCURRENCY:
        parser.error(f"--concurrencia va de 1 a {MAX_CONCURRENCY}")
    if args.budget_usd is not None and args.budget_usd <= 0:
        parser.error("--budget-usd debe ser mayor que cero")
    if args.model and not args.model.startswith(ALLOWED_MODEL_FAMILIES):
        parser.error("El reto solo permite Grok 4.7, 4.6, 4.5 o 4.20.")
    return args


def _load(args: argparse.Namespace) -> list[HarnessCase]:
    if args.mensaje is not None:
        return read_cases(json.dumps({"id": "mensaje", "mensaje": args.mensaje}))
    if args.casos == "-":
        return read_cases(sys.stdin.read())
    path = Path(args.casos)
    if not path.is_file():
        raise ValueError(f"No existe el archivo de casos {path}.")
    return read_cases(path.read_text(encoding="utf-8"), suffix=path.suffix, base=path.parent)


def _utf8_streams() -> None:
    """Entrada y salida en UTF-8: la consola de Windows usa cp1252 y un «→» de la respuesta tumbaba la escritura."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None, planner: Planner = decide_with_grok) -> int:
    _utf8_streams()
    args = _arguments(argv)
    load_dotenv()
    if planner is decide_with_grok and not os.getenv("GROK_API_KEY", "").strip():
        print("Falta GROK_API_KEY. Cópiala en .env (ver .env.example) o en el entorno.", file=sys.stderr)
        return 2
    try:
        cases = _load(args)
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    out = args.salida.open("w", encoding="utf-8") if args.salida else sys.stdout

    def write(output: dict) -> None:
        out.write(json.dumps(output, ensure_ascii=False) + "\n")
        out.flush()

    try:
        summary = run_cases(cases, store=args.tienda, write=write, planner=planner, model=args.model,
                            budget_usd=args.budget_usd, concurrency=args.concurrencia, log_path=args.bitacora)
    except FileNotFoundError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    finally:
        if args.salida:
            out.close()
    print(json.dumps({"resumen": summary}, ensure_ascii=False), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
