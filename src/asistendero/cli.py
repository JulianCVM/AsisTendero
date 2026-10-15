"""Interfaz local del flujo de Semana 1."""

import argparse
import sys

from dotenv import load_dotenv

from asistendero.catalog import MockCatalog
from asistendero.graph import build_graph
from asistendero.grok import decide_with_grok


def main() -> int:
    parser = argparse.ArgumentParser(description="AsisTendero: entrada → LangGraph → Grok → salida")
    parser.add_argument("mensaje", nargs="*", help="Consulta de un cliente de ferretería")
    args = parser.parse_args()

    load_dotenv()
    consulta = " ".join(args.mensaje).strip()
    if not consulta:
        if not sys.stdin.isatty():
            parser.error("Escribe una consulta como argumento.")
        consulta = input("Consulta del cliente: ")

    try:
        result = build_graph(MockCatalog(), decide_with_grok).invoke({"consulta": consulta})
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
