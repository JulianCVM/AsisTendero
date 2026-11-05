"""Archivos estáticos de las tres pantallas.

Cada pantalla tiene su carpeta en ``entregas/web``: ``visor``, ``panel`` y ``pagina`` (la página pública), y lo que
comparten (tema, fuentes y logo) vive en ``comun``. La URL no lo refleja: todo se sirve como ``/assets/<nombre>``,
así que un nombre existe en una sola carpeta (lo comprueba ``tests/test_arquitectura.py``) y cada servidor decide en su
propia tabla qué nombres sirve.
"""

from importlib.resources import files

FOLDERS = ("comun", "visor", "panel", "pagina")


def web_file(name: str) -> bytes:
    web = files("asistendero.entregas").joinpath("web")
    for folder in FOLDERS:
        candidate = web.joinpath(folder, name)
        if candidate.is_file():
            return candidate.read_bytes()
    raise FileNotFoundError(name)
