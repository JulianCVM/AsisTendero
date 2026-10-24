"""Interfaz local del flujo de AsisTendero: un mensaje suelto o una conversación con sesión."""

import argparse
import os
import sys

from dotenv import load_dotenv

from asistendero.catalog import MockCatalog
from asistendero.chat import run_turn
from asistendero.executor import catalog_executor
from asistendero.graph import build_graph
from asistendero.grok import decide_with_grok
from asistendero.order_watch import last_event, sweep
from asistendero.orders import OrderBook
from asistendero.seed import DEFAULT_DB_PATH, upgrade_db
from asistendero.sessions import SessionError, SessionStore


EXIT_WORDS = {"salir", "exit", "chao"}


def _chat() -> int:
    store = SessionStore()
    session_id = store.create()
    orders = OrderBook()
    seen = last_event(orders)
    print("Conversación nueva con AsisTendero (datos de demostración). Escribe «salir» para terminar.")
    while True:
        # Sin hilo en la terminal: antes de cada mensaje se vence lo que pasó su plazo y se muestran los avisos.
        seen = sweep(orders, store, seen)
        for notice in store.take_notices(session_id):
            print(f"AsisTendero (aviso): {notice}\n")
        try:
            message = input("Cliente: ").strip()
        except EOFError:
            break
        if message.casefold() in EXIT_WORDS:
            break
        if not message:
            continue
        try:
            result = run_turn(store, session_id, message, orders=orders)
        except SessionError as exc:
            print(exc, file=sys.stderr)
            return 1
        except (ValueError, RuntimeError, FileNotFoundError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            continue
        except Exception as exc:
            # No mostrar mensajes de SDK/HTTP: podrían contener datos de la solicitud.
            print(f"Error al consultar Grok ({type(exc).__name__}). Revisa clave, modelo, red y créditos.", file=sys.stderr)
            continue
        print(f"AsisTendero: {result['respuesta']}\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="AsisTendero: Grok decide → herramientas del servidor → respuesta")
    parser.add_argument("mensaje", nargs="*", help="Mensaje de un cliente de ferretería")
    parser.add_argument("--chat", action="store_true", help="Conversación de varios turnos con memoria de sesión")
    parser.add_argument("--model", help="Modelo de Grok permitido por el reto (reemplaza GROK_MODEL)")
    args = parser.parse_args()

    load_dotenv()
    if args.model:
        os.environ["GROK_MODEL"] = args.model
    if args.chat:
        return _chat()
    consulta = " ".join(args.mensaje).strip()
    if not consulta:
        if not sys.stdin.isatty():
            parser.error("Escribe una consulta como argumento.")
        consulta = input("Consulta del cliente: ")

    try:
        # Una base creada antes del surtido no tiene la tabla: sin actualizarla, todo salía «sin fecha».
        catalog = MockCatalog(upgrade_db(DEFAULT_DB_PATH))
        result = build_graph(catalog_executor(catalog), decide_with_grok).invoke({"consulta": consulta})
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        # No mostrar mensajes de SDK/HTTP: podrían contener datos de la solicitud.
        print(f"Error al consultar Grok ({type(exc).__name__}). Revisa clave, modelo, red y créditos.", file=sys.stderr)
        return 1

    print(result["respuesta"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
