import sqlite3

import pytest

from asistendero.catalog import MockCatalog
from asistendero.graph import build_graph
from asistendero.grok import Decision
from asistendero.seed import create_mock_db


@pytest.fixture
def catalog(tmp_path):
    return MockCatalog(create_mock_db(tmp_path / "catalog.sqlite3"))


def test_specific_variant_uses_db_facts_only(catalog):
    seen = []

    def choose(query, candidates):
        seen.append((query, [item.sku for item in candidates]))
        return Decision("PVC-050", "fake")

    result = build_graph(catalog, choose).invoke({"consulta": "  Busco tubo PVC de 1/2 para agua  "})
    assert seen[0][0] == "Busco tubo PVC de 1/2 para agua"
    assert "PVC-050" in seen[0][1]
    assert result["estado"] == "found"
    assert "$8.500 COP" in result["respuesta"]
    assert "12 metros" in result["respuesta"]
    assert "Datos simulados" in result["respuesta"]


def test_updated_mock_row_changes_response_without_prompt_change(catalog):
    with sqlite3.connect(catalog.path) as connection:
        connection.execute(
            "UPDATE products SET price_cop = 9100, stock = 3 WHERE business_id = ? AND store_id = ? AND sku = ?",
            ("demo-ferreteria", "sede-unica", "PVC-050"),
        )

    result = build_graph(catalog, lambda *_: Decision("PVC-050", "fake")).invoke({"consulta": "Tubo PVC 1/2 para agua"})
    assert "$9.100 COP" in result["respuesta"]
    assert "3 metros" in result["respuesta"]
    assert "$8.500" not in result["respuesta"]


def test_ambiguous_variant_is_not_forced_by_model(catalog):
    result = build_graph(catalog, lambda *_: Decision("PVC-050", "fake")).invoke({"consulta": "Busco tubo PVC para agua"})
    assert result["estado"] == "clarify"
    assert "¿Cuál medida" in result["respuesta"]
    assert "$" not in result["respuesta"]


def test_unknown_sku_cannot_create_price_or_stock(catalog):
    result = build_graph(catalog, lambda *_: Decision("INVENTADO", "fake")).invoke({"consulta": "Busco cemento gris"})
    assert result["estado"] == "clarify"
    assert "INVENTADO" not in result["respuesta"]
    assert "$" not in result["respuesta"]


def test_no_candidate_skips_model_and_isolates_business(catalog):
    with sqlite3.connect(catalog.path) as connection:
        connection.execute(
            "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("otro-negocio", "sede-unica", "EXT-1", "Taladro especial", "20 V", "unidad", 1000, 1, "taladro", "2026-10-15T00:00:00-05:00"),
        )

    def forbidden(*_):
        raise AssertionError("No debe llamar a Grok sin candidatos del negocio")

    result = build_graph(catalog, forbidden).invoke({"consulta": "taladro especial"})
    assert result["estado"] == "not_found"
    assert result["model_called"] is False


def test_empty_input_never_calls_model(catalog):
    with pytest.raises(ValueError, match="vacía"):
        build_graph(catalog, lambda *_: pytest.fail("No debe llamar a Grok")).invoke({"consulta": "  "})
