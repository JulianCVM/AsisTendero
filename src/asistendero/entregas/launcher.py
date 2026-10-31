"""Arranque de todo AsisTendero con un solo comando: el chat con su visor y la plataforma del tendero.

Ejecutar: python -m asistendero              (los dos, sobre la tienda del chat)
          python -m asistendero --demo       (los dos, sobre la tienda de demostración; ver demo.py)

Los dos servidores corren en el mismo proceso y comparten la base de la tienda, el libro de pedidos y las sesiones:
lo que un cliente pide en el chat aparece en el panel, y lo que el tendero responde al tomar una conversación llega
al chat. Si el catálogo ficticio no existe, se crea; si ya existe, nunca se reescribe.
"""

import os
from pathlib import Path
from threading import Thread

from asistendero.agente.conversacion.sessions import DEFAULT_SESSIONS_PATH, SessionStore
from asistendero.datos.demo import build_demo
from asistendero.datos.seed import DEFAULT_DB_PATH, create_mock_db
from asistendero.entregas.panel import tendero
from asistendero.entregas.visor import visual
from asistendero.tienda.inventario.inventory import Inventory
from asistendero.tienda.pedidos.order_watch import Watcher
from asistendero.tienda.pedidos.orders import OrderBook


VISOR_PORT = 8765
PANEL_PORT = 8766


def open_store(demo: bool, database: Path = DEFAULT_DB_PATH,
               sessions_path: Path = DEFAULT_SESSIONS_PATH) -> tuple[Inventory, SessionStore]:
    if demo:
        database, sessions_path = build_demo()
    elif not database.exists():
        create_mock_db(database)
        print(f"Catálogo ficticio creado en {database}")
    return Inventory(database), SessionStore(sessions_path)


def make_servers(visor_port: int, panel_port: int, inventory: Inventory, sessions: SessionStore):
    """Devuelve (visor, panel) con la misma tienda; si un puerto está ocupado, no deja el otro abierto."""
    orders = OrderBook(inventory.path)
    panel = tendero.make_server(panel_port, inventory, orders, sessions)
    try:
        visor = visual.make_server(visor_port, sessions, orders)
    except OSError:
        panel.server_close()
        raise
    return visor, panel


def run(demo: bool = False, visor_port: int = VISOR_PORT, panel_port: int = PANEL_PORT,
        database: Path = DEFAULT_DB_PATH, sessions_path: Path = DEFAULT_SESSIONS_PATH) -> int:
    inventory, sessions = open_store(demo, database, sessions_path)
    try:
        visor, panel = make_servers(visor_port, panel_port, inventory, sessions)
    except OSError:
        print(f"No se pudo abrir el puerto {panel_port} o {visor_port}: ¿ya hay otro AsisTendero abierto? "
              "Ciérralo con Ctrl+C en su terminal y vuelve a intentar.")
        return 1
    # Vence los pedidos sin confirmar a los 5 minutos y deja el aviso para cada cliente, sin llamar a Grok.
    watcher = Watcher(visor.orders, visor.sessions).start()
    Thread(target=panel.serve_forever, name="panel-tendero", daemon=True).start()
    print(f"Chat del cliente y traza:  http://127.0.0.1:{visor.server_port}/")
    print(f"Plataforma del tendero:    http://127.0.0.1:{panel.server_port}/")
    print(f"Página de presentación:    http://127.0.0.1:{panel.server_port}/inicio")
    if demo:
        print("Tienda de demostración: pedidos, ventas, proveedores y chats simulados.")
    if not os.getenv("GROK_API_KEY", "").strip():
        print("Falta GROK_API_KEY en .env: el chat y el asistente de bodega no podrán llamar a Grok; el resto funciona.")
    print("Ctrl+C para detener todo. Cada mensaje del chat y cada «Interpretar» del asistente llaman a Grok.")
    try:
        # El visor corre en el hilo principal para que Ctrl+C lo detenga también en Windows.
        visor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        watcher.stop()
        panel.shutdown()
        panel.server_close()
        visor.server_close()
    return 0
