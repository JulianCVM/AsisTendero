"""El comando único: `python -m asistendero` sin argumentos arranca el chat y el panel sobre la misma tienda."""

import http.client
import socket
import sqlite3
from threading import Thread

import pytest

from asistendero import cli, launcher
from asistendero.seed import create_mock_db


def _get(server, path):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    connection.request("GET", path)
    response = connection.getresponse()
    body = response.read()
    connection.close()
    return response.status, body


def test_both_servers_share_the_store_so_the_panel_sees_what_the_chat_does(tmp_path):
    inventory, sessions = launcher.open_store(False, tmp_path / "tienda.sqlite3", tmp_path / "sesiones.sqlite3")
    visor, panel = launcher.make_servers(0, 0, inventory, sessions)
    threads = [Thread(target=server.serve_forever, daemon=True) for server in (visor, panel)]
    for thread in threads:
        thread.start()
    try:
        assert visor.orders is panel.orders and visor.sessions is panel.sessions
        assert panel.orders.path == inventory.path == (tmp_path / "tienda.sqlite3").resolve()
        # Un cliente que pide al tendero desde el chat aparece en la supervisión del panel.
        session_id = visor.sessions.create()
        visor.sessions.record(session_id, "quiero hablar con el dueño", "Le aviso al tendero.", "handoff", [])
        status, body = _get(panel, "/api/conversaciones")
        assert status == 200 and session_id.encode() in body
        assert _get(visor, "/")[0] == 200
        assert _get(panel, "/")[0] == 200
    finally:
        for server in (visor, panel):
            server.shutdown()
            server.server_close()


def test_the_catalog_is_created_when_missing_and_never_rewritten(tmp_path, capsys):
    database = tmp_path / "tienda.sqlite3"
    launcher.open_store(False, database, tmp_path / "sesiones.sqlite3")
    assert database.is_file() and "Catálogo ficticio creado" in capsys.readouterr().out

    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE products SET price_cop = 1234 WHERE sku = (SELECT MIN(sku) FROM products)")
    launcher.open_store(False, database, tmp_path / "sesiones.sqlite3")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM products WHERE price_cop = 1234").fetchone()[0] == 1
    assert "Catálogo ficticio creado" not in capsys.readouterr().out


def test_a_busy_port_stops_with_a_clear_message_and_leaves_no_server_open(tmp_path, capsys):
    create_mock_db(tmp_path / "tienda.sqlite3")
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        taken = busy.getsockname()[1]
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            free = probe.getsockname()[1]
        result = launcher.run(visor_port=taken, panel_port=free, database=tmp_path / "tienda.sqlite3",
                              sessions_path=tmp_path / "sesiones.sqlite3")
    assert result == 1 and "¿ya hay otro AsisTendero abierto?" in capsys.readouterr().out
    # El panel alcanzó a abrir su puerto antes del fallo del visor: debe haberlo soltado.
    with socket.socket() as again:
        again.bind(("127.0.0.1", free))


def test_without_arguments_the_cli_starts_everything_instead_of_asking(monkeypatch):
    started = []
    monkeypatch.setattr(launcher, "run", lambda demo: started.append(demo) or 0)
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("no debe pedir una consulta"))
    monkeypatch.setattr("sys.argv", ["asistendero"])
    assert cli.main() == 0
    monkeypatch.setattr("sys.argv", ["asistendero", "--demo"])
    assert cli.main() == 0
    assert started == [False, True]


@pytest.mark.parametrize("argv", [["--demo", "¿tienen martillos?"], ["--demo", "--chat"]])
def test_demo_only_applies_to_the_full_start(monkeypatch, argv):
    monkeypatch.setattr(launcher, "run", lambda demo: pytest.fail("no debe arrancar nada"))
    monkeypatch.setattr("sys.argv", ["asistendero", *argv])
    with pytest.raises(SystemExit) as stop:
        cli.main()
    assert stop.value.code == 2
