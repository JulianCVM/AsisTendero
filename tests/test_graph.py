import sqlite3

import pytest

from asistendero.catalog import MockCatalog, tokens
from asistendero.graph import build_graph
from asistendero.grok import Plan, Resolution
from asistendero.search import ProductQuery
from asistendero.seed import create_mock_db


@pytest.fixture
def catalog(tmp_path):
    return MockCatalog(create_mock_db(tmp_path / "catalog.sqlite3"))


def q(text, **fields):
    return ProductQuery(text, **fields)


def test_grok_receives_message_before_catalog_is_queried(catalog, monkeypatch):
    events = []
    original_search = catalog.search

    def search(request):
        events.append(("catalog", request.text))
        return original_search(request)

    monkeypatch.setattr(catalog, "search", search)

    def plan(message):
        events.append(("grok", message))
        return Plan("search_products", (q("tubo PVC de 1/2 para agua", product="tubo", material="PVC", measure="1/2 pulgada", use="agua"),), "productos", "")

    result = build_graph(
        catalog, plan, lambda *_: Resolution(("PVC-050",), "¡Hola, mi veci! Revisé el catálogo:")
    ).invoke({"consulta": "  Busco tubo PVC de 1/2 para agua  "})
    assert events == [("grok", "Busco tubo PVC de 1/2 para agua"), ("catalog", "tubo PVC de 1/2 para agua")]
    assert result["hallazgos"][0]["request"].measure == "1/2 pulgada"
    assert result["estado"] == "found"
    assert "$8.500 COP" in result["respuesta"]
    assert "12 metros" in result["respuesta"]
    assert result["model_calls"] == 2


def test_hours_are_answered_without_catalog_or_fabricated_schedule(catalog, monkeypatch):
    monkeypatch.setattr(catalog, "search", lambda *_: pytest.fail("No se debe consultar catálogo"))
    result = build_graph(
        catalog,
        lambda *_: Plan("respond", (), "horario", "Sí, estamos abiertos hasta las 8."),
        lambda *_: pytest.fail("No se necesita una segunda llamada"),
    ).invoke({"consulta": "¿Están atendiendo?"})
    assert result["estado"] == "answered"
    assert "No tengo un horario verificado" in result["respuesta"]
    assert "las 8" not in result["respuesta"]
    assert result["model_calls"] == 1


def test_hours_question_is_safe_when_grok_misclassifies_it_as_greeting(catalog, monkeypatch):
    monkeypatch.setattr(catalog, "search", lambda *_: pytest.fail("No se debe consultar catálogo"))
    result = build_graph(
        catalog,
        lambda *_: Plan("respond", (), "saludo", "¡Hola! Sí, estamos aquí para ayudarte."),
        lambda *_: pytest.fail("No se necesita una segunda llamada"),
    ).invoke({"consulta": "Hola, ¿están atendiendo en este momento?"})
    assert result["estado"] == "answered"
    assert "No tengo un horario verificado" in result["respuesta"]
    assert "Sí, estamos aquí" not in result["respuesta"]
    assert result["model_calls"] == 1


def test_multiple_products_use_separate_queries_and_one_response(catalog):
    observed = []

    def resolve(message, findings):
        observed.extend((item["query"], [p.sku for p in item["candidates"]]) for item in findings)
        return Resolution(("PVC-050", "CEM-050"), "Claro, revisé ambos productos:")

    result = build_graph(
        catalog,
        lambda *_: Plan("search_products", (q("tubo PVC de 1/2", product="tubo", material="PVC", measure="1/2"), q("cemento gris de 50 kg", product="cemento", measure="50 kg")), "productos", ""),
        resolve,
    ).invoke({"consulta": "Necesito un tubo PVC de 1/2 y un bulto de cemento gris de 50 kg"})
    assert len(observed) == 2
    assert "PVC-050" in observed[0][1]
    assert "CEM-050" in observed[1][1]
    assert "$8.500 COP" in result["respuesta"]
    assert "$39.500 COP" in result["respuesta"]
    assert result["estado"] == "found"


def test_ambiguous_or_invented_variant_never_gets_a_price(catalog):
    graph = build_graph(
        catalog,
        lambda *_: Plan("search_products", (q("tubo PVC para agua", product="tubo", material="PVC", use="agua"),), "productos", ""),
        lambda *_: Resolution(("PVC-050",), "Revisé el catálogo:"),
    )
    result = graph.invoke({"consulta": "Busco tubo PVC para agua"})
    assert result["estado"] == "clarify"
    assert "$" not in result["respuesta"]
    assert "medida" in result["respuesta"]

    unknown = build_graph(
        catalog,
        lambda *_: Plan("search_products", (q("cemento gris", product="cemento"),), "productos", ""),
        lambda *_: Resolution(("INVENTADO",), "Revisé el catálogo:"),
    ).invoke({"consulta": "Busco cemento gris"})
    assert unknown["estado"] == "clarify"
    assert "INVENTADO" not in unknown["respuesta"]


def test_no_match_still_starts_with_grok_and_does_not_invent_product(catalog):
    result = build_graph(
        catalog,
        lambda *_: Plan("search_products", (q("taladro 20 V", product="taladro", measure="20 V"),), "productos", ""),
        lambda _message, findings: Resolution((None,), "Revisé el catálogo:")
        if not findings[0]["candidates"] else pytest.fail("Producto inesperado"),
    ).invoke({"consulta": "¿Tienen un taladro de 20 V?"})
    assert result["estado"] == "not_found"
    assert "no encontré" in result["respuesta"].casefold()
    assert "$" not in result["respuesta"]


def test_database_facts_and_business_scope_remain_server_controlled(catalog):
    with sqlite3.connect(catalog.path) as connection:
        connection.execute(
            "UPDATE products SET price_cop = 9100, stock = 3 WHERE business_id = ? AND store_id = ? AND sku = ?",
            ("demo-ferreteria", "sede-unica", "PVC-050"),
        )
        connection.execute(
            "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("otro-negocio", "sede-unica", "EXT-1", "Taladro especial", "20 V", "unidad", 1000, 1,
             "taladro", "2026-10-15T00:00:00-05:00"),
        )
    result = build_graph(
        catalog,
        lambda *_: Plan("search_products", (q("tubo PVC de 1/2", product="tubo", material="PVC", measure="1/2"),), "productos", ""),
        lambda *_: Resolution(("PVC-050",), "Revisé el catálogo:"),
    ).invoke({"consulta": "Busco tubo PVC de 1/2"})
    assert "$9.100 COP" in result["respuesta"]
    assert "3 metros" in result["respuesta"]


def test_grounded_grok_answer_is_used_and_unsupported_answer_falls_back(catalog):
    planner = lambda *_: Plan("search_products", (q("tubo PVC de 1/2", product="tubo", material="PVC", measure="1/2"),), "productos", "")
    natural = "Hola, mi veci. Tubo PVC presión para agua 1/2 pulgada (SKU PVC-050): $8.500 COP por metro y hay 12 metros. Datos simulados."
    result = build_graph(catalog, planner, lambda *_: Resolution(("PVC-050",), natural)).invoke(
        {"consulta": "Busco tubo PVC de 1/2"}
    )
    assert result["respuesta"] == natural

    unsupported = natural.replace("$8.500", "$1")
    rejected = build_graph(catalog, planner, lambda *_: Resolution(("PVC-050",), unsupported)).invoke(
        {"consulta": "Busco tubo PVC de 1/2"}
    )
    assert "$8.500 COP" in rejected["respuesta"]
    assert "$1 COP" not in rejected["respuesta"]

    wrong_unit = natural.replace("12 metros", "12 unidades")
    corrected = build_graph(catalog, planner, lambda *_: Resolution(("PVC-050",), wrong_unit)).invoke(
        {"consulta": "Busco tubo PVC de 1/2"}
    )
    assert "12 metros disponibles" in corrected["respuesta"]
    assert "12 unidades" not in corrected["respuesta"]
    assert catalog.get("EXT-1") is None


def test_empty_input_never_calls_model(catalog):
    with pytest.raises(ValueError, match="vacía"):
        build_graph(
            catalog,
            lambda *_: pytest.fail("No debe llamar a Grok"),
            lambda *_: pytest.fail("No debe llamar a Grok"),
        ).invoke({"consulta": "  "})


def test_structured_filters_narrow_exact_match_and_show_nearby_without_prices(catalog):
    exact = catalog.search(q("tubo PVC de 1/2 para agua", product="tubo", material="PVC", measure="1/2", use="agua"))
    assert [item.sku for item in exact.matches] == ["PVC-050"]
    assert not exact.nearby
    compact = q("cemento gris 50kg", product="cemento", measure="50 kg")
    assert compact.grounded("Busco cemento gris 50kg", tokens).measure == "50 kg"
    assert [item.sku for item in catalog.search(compact).matches] == ["CEM-050"]

    result = build_graph(
        catalog,
        lambda *_: Plan("search_products", (q("tubo PVC de 1 pulgada para agua", product="tubo", material="PVC", measure="1 pulgada", use="agua"),), "productos", ""),
        lambda _message, findings: Resolution((None,), "")
        if not findings[0]["candidates"] else pytest.fail("Una medida diferente no es coincidencia exacta"),
    ).invoke({"consulta": "Busco tubo PVC de 1 pulgada para agua"})
    assert result["estado"] == "nearby"
    assert "1/2 pulgada" in result["respuesta"]
    assert "3/4 pulgada" in result["respuesta"]
    assert "$" not in result["respuesta"]


def test_invented_structured_measure_cannot_force_variant(catalog):
    result = build_graph(
        catalog,
        lambda *_: Plan("search_products", (q("tubo PVC para agua", product="tubo", material="PVC", measure="1/2"),), "productos", ""),
        lambda _message, findings: Resolution(("PVC-050",), ""),
    ).invoke({"consulta": "Busco tubo PVC para agua"})
    assert result["hallazgos"][0]["request"].measure is None
    assert result["estado"] == "clarify"
    assert "$" not in result["respuesta"]


def test_search_caps_many_variants_and_labels_other_material(catalog):
    with sqlite3.connect(catalog.path) as connection:
        connection.executemany(
            "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("demo-ferreteria", "sede-unica", f"PVC-{size:03}", "Tubo PVC presión para agua",
                 f"{size} pulgadas", "metro", 10000, 2, "tubo|pvc|agua", "2026-10-15T00:00:00-05:00")
                for size in range(2, 12)
            ],
        )
    broad = catalog.search(q("tubo PVC para agua", product="tubo", material="PVC", use="agua"))
    assert len(broad.matches) == 3
    assert not broad.nearby

    copper = build_graph(
        catalog,
        lambda *_: Plan("search_products", (q("tubo de cobre de 1/2 para agua", product="tubo", material="cobre", measure="1/2", use="agua"),), "productos", ""),
        lambda _message, findings: Resolution((None,), "")
        if not findings[0]["candidates"] else pytest.fail("PVC no coincide con cobre"),
    ).invoke({"consulta": "Busco tubo de cobre de 1/2 para agua"})
    assert copper["estado"] == "nearby"
    assert len(copper["hallazgos"][0]["nearby"]) <= 2
    assert "otro material" in copper["respuesta"]
    assert "$" not in copper["respuesta"]
