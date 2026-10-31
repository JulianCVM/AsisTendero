"""Reglas de dependencia entre los paquetes de asistendero (ver docs/ARQUITECTURA.md).

Cada paquete importa solo los que están por debajo de él:

    entregas → evaluacion → observabilidad → agente → tienda → datos

`entregas` puede usarlo todo y nadie lo importa; la base de `datos` (catálogo ficticio y esquema) no importa nada del
paquete. Los cruces que todavía existen están en ``KNOWN_CROSSINGS`` con el motivo: la lista solo puede achicarse,
porque la prueba falla tanto con un cruce nuevo como con uno anotado que ya desapareció.
"""

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "asistendero"
ORDER = ("datos", "tienda", "agente", "observabilidad", "evaluacion", "entregas")

# (módulo que importa, módulo importado) → por qué sigue ahí. Se cortan moviendo la pieza a la capa que le toca.
KNOWN_CROSSINGS = {
    # El chat del visor y la terminal corre el turno con su traza.
    ("chat", "tracing"): "un turno de chat se ejecuta trazado",
    # La demo arma conversaciones con los módulos reales para que el panel muestre lo mismo que vería en uso.
    ("demo", "handoff"): "la demo simula atención humana",
    ("demo", "sessions"): "la demo crea conversaciones",
    ("demo", "reply_text"): "formato de moneda en el agente",
    # La tienda usa piezas que hoy viven en el agente: vocabulario del catálogo, formato de moneda y avisos.
    ("purchasing", "restock"): "estado de surtido en el agente",
    ("purchasing_rules", "validation"): "patrón de SKU en el agente",
    ("purchasing_rules", "restock"): "plazo de surtido en el agente",
    ("stock_apply", "reply_text"): "formato de moneda en el agente",
    ("stock_operations", "reply_text"): "formato de moneda en el agente",
    ("stock_matching", "product_fit"): "parecido de nombres en el agente",
    ("stock_matching", "search"): "búsqueda del catálogo en el agente",
    ("stock_matching", "validation"): "normalización de texto en el agente",
    ("stock_assistant", "grok"): "el asistente de bodega usa el cliente de Grok del agente",
    ("stock_assistant", "validation"): "patrón de SKU en el agente",
    ("stock_assistant", "pricing"): "costo de la llamada a Grok",
    ("stock_proposal", "restock"): "días de surtido en el agente",
    ("catalog", "measures"): "medidas del catálogo en el agente",
    ("catalog", "search"): "búsqueda del catálogo en el agente",
    ("catalog_admin", "validation"): "normalización de texto en el agente",
    ("product_art", "validation"): "normalización de texto en el agente",
    ("stock_thresholds", "validation"): "patrón de SKU en el agente",
    ("inventory", "validation"): "patrón de SKU en el agente",
    ("inventory", "restock"): "plan de surtido en el agente",
    ("order_watch", "sessions"): "el aviso de vencimiento se deja en la sesión",
    ("order_watch", "order_replies"): "texto del aviso de vencimiento",
    ("orders", "tools"): "reloj de la tienda en las herramientas",
    ("supervision", "handoff"): "estados de atención humana",
    ("supervision", "sessions"): "conversaciones guardadas",
    ("supervision", "injection"): "códigos de bloqueo",
    ("payments", "guardrails"): "borrado de datos personales en el comprobante",
}


def _imports() -> set[tuple[str, str, str, str]]:
    """(paquete, módulo) de quien importa y de lo importado, para cada importación interna entre paquetes."""
    found = set()
    for path in PACKAGE.rglob("*.py"):
        if "__pycache__" in path.parts or path.parent == PACKAGE:
            continue
        layer = path.relative_to(PACKAGE).parts[0]
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.ImportFrom) or not (node.module or "").startswith("asistendero."):
                continue
            parts = node.module.split(".")
            # «from asistendero.agente.conversacion import handoff» importa el módulo handoff.
            targets = [parts[-1]] if len(parts) > 2 and (PACKAGE.joinpath(*parts[1:]).with_suffix(".py")).exists() \
                else [alias.name for alias in node.names]
            for target in targets:
                found.add((layer, path.stem, parts[1], target))
    return found


def test_the_package_has_one_folder_per_layer_and_no_loose_modules():
    loose = {path.name for path in PACKAGE.glob("*.py")} - {"__init__.py", "__main__.py"}
    assert not loose, f"Módulos sueltos en src/asistendero: {sorted(loose)}; van en el paquete de su función."
    assert {path.name for path in PACKAGE.iterdir() if (path / "__init__.py").exists()} == set(ORDER)
    # Ningún nombre de módulo se repite: la documentación los nombra sin la ruta.
    names = [path.name for path in PACKAGE.rglob("*.py") if path.name not in ("__init__.py", "__main__.py")]
    assert len(names) == len(set(names))


def test_each_layer_imports_only_the_ones_below_it_or_a_known_crossing():
    crossings = set()
    for layer, module, target_layer, target in _imports():
        if target_layer == layer or ORDER.index(target_layer) < ORDER.index(layer):
            continue
        if module == "demo" and target_layer == "tienda":
            continue  # la demo se arma con los módulos reales de la tienda
        crossings.add((module, target))
    new = crossings - KNOWN_CROSSINGS.keys()
    gone = KNOWN_CROSSINGS.keys() - crossings
    assert not new, f"Importaciones hacia arriba sin anotar: {sorted(new)}"
    assert not gone, f"Cruces anotados que ya no existen; bórralos de KNOWN_CROSSINGS: {sorted(gone)}"


def test_nobody_imports_the_entry_points_and_the_data_base_imports_nothing():
    for layer, module, target_layer, _ in _imports():
        assert target_layer != "entregas" or layer == "entregas", module
        if module in ("seed", "catalog_data"):
            assert target_layer == "datos", module


def test_the_tests_find_a_crossing_when_one_appears():
    # Sin esto, un fallo del recorrido (otra raíz, otro patrón de importación) dejaría pasar todo en silencio.
    found = _imports()
    assert ("tienda", "inventory", "agente", "validation") in found
    assert ("agente", "chat", "observabilidad", "tracing") in found
    assert ("datos", "demo", "agente", "handoff") in found


def test_every_screen_file_lives_in_one_folder_and_each_server_finds_what_it_serves():
    from asistendero.entregas.estaticos import FOLDERS, web_file
    from asistendero.entregas.panel import tendero
    from asistendero.entregas.visor import visual

    web = PACKAGE / "entregas" / "web"
    assert {path.name for path in web.iterdir() if path.is_dir()} == set(FOLDERS)
    names = [path.name for path in web.glob("*/*")]
    assert len(names) == len(set(names)), "Un nombre en dos carpetas: /assets/<nombre> no sabría cuál servir."
    served = [name for name, _ in tendero.ASSETS.values()] + list(tendero.PAGES.values())
    served += [name for name, _ in visual.TraceHandler._assets.values()] + ["index.html"]
    for name in served:
        assert web_file(name), name
    # Cada pantalla sirve sus archivos y los comunes, nunca los de otra.
    for name, _ in visual.TraceHandler._assets.values():
        assert (web / "visor" / name).exists() or (web / "comun" / name).exists(), name
    for name in [name for name, _ in tendero.ASSETS.values()] + list(tendero.PAGES.values()):
        assert not (web / "visor" / name).exists(), name
