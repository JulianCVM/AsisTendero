import sqlite3

import pytest

from asistendero.catalog import MockCatalog, tokens
from asistendero.search import ProductQuery
from asistendero.seed import create_mock_db


@pytest.fixture
def catalog(tmp_path):
    return MockCatalog(create_mock_db(tmp_path / "catalog.sqlite3"))


def q(text, **fields):
    return ProductQuery(text, **fields)


def test_structured_filters_narrow_exact_match_and_keep_nearby_apart(catalog):
    exact = catalog.search(q("tubo PVC de 1/2 para agua", product="tubo", material="PVC", measure="1/2", use="agua"))
    assert [item.sku for item in exact.matches] == ["PVC-050"]
    assert not exact.nearby
    compact = q("cemento gris 50kg", product="cemento", measure="50 kg")
    assert compact.grounded("Busco cemento gris 50kg", tokens).measure == "50 kg"
    assert [item.sku for item in catalog.search(compact).matches] == ["CEM-050"]

    other_size = catalog.search(q("tubo PVC de 1 pulgada para agua", product="tubo", material="PVC", measure="1 pulgada", use="agua"))
    assert not other_size.matches
    assert {item.sku for item in other_size.nearby} == {"PVC-050", "PVC-075"}


def test_invented_structured_measure_is_dropped_by_grounding():
    request = q("tubo PVC para agua", product="tubo", material="PVC", measure="1/2")
    assert request.grounded("Busco tubo PVC para agua", tokens).measure is None


def test_search_caps_many_variants_and_other_material_is_only_nearby(catalog):
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

    copper = catalog.search(q("tubo de cobre de 1/2 para agua", product="tubo", material="cobre", measure="1/2", use="agua"))
    assert not copper.matches
    assert len(copper.nearby) <= 2


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
    product = catalog.get("PVC-050")
    assert (product.price_cop, product.stock) == (9100, 3)
    assert catalog.get("EXT-1") is None
    assert not catalog.search(q("taladro 20 V", product="taladro")).matches
