import sqlite3

import pytest

from asistendero.catalog import MAX_MATCHES, MockCatalog, tokens
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
            "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("demo-ferreteria", "sede-unica", f"PVC-{size:03}", "Tubo PVC presión para agua",
                 f"{size} pulgadas", "metro", 10000, 2, "tubo|pvc|agua", "2026-10-15T00:00:00-05:00", "Plomería")
                for size in range(2, 12)
            ],
        )
    broad = catalog.search(q("tubo PVC para agua", product="tubo", material="PVC", use="agua"))
    # Las variantes empatadas del mismo producto se muestran juntas hasta el tope, nunca las 12.
    assert len(broad.matches) == MAX_MATCHES
    assert {product.name for product in broad.matches} == {"Tubo PVC presión para agua"}
    assert not broad.nearby
    distinguished = catalog.search(q("tubo PVC de 1/2 para agua", product="tubo", material="PVC", measure="1/2 pulgada", use="agua"))
    assert len(distinguished.matches) <= 3

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
            "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("otro-negocio", "sede-unica", "EXT-1", "Taladro especial", "20 V", "unidad", 1000, 1,
             "taladro", "2026-10-15T00:00:00-05:00", "Herramientas eléctricas"),
        )
    product = catalog.get("PVC-050")
    assert (product.price_cop, product.stock) == (9100, 3)
    assert catalog.get("EXT-1") is None
    assert not catalog.search(q("taladro 20 V", product="taladro")).matches


def test_measures_separate_sizes_from_quantities():
    from asistendero.measures import measures

    assert measures("Necesito tornillo para madera 1/4 x 2 pulgadas") == {"1/4x2", "2in"}
    assert measures("2 tornillos de 1/4 x 1") == {"2", "1/4x1"}
    assert measures("2 bisagras de 3 1/2\"") == {"2", "3-1/2in"}
    assert measures("tubo PVC de media pulgada") == {"1/2in"}
    assert measures("cemento gris de 50 kg") == {"50kg"}


def _selected(catalog, message, **item):
    from asistendero.tools import execute_tool
    from asistendero.validation import grounded_products, validate_request

    arguments = validate_request("buscar_productos", {"items": [item]}, message, [])
    response = execute_tool("buscar_productos", arguments, catalog=catalog)
    call = {"requested_tool": "buscar_productos", "arguments": arguments, "response": response, "executed": True}
    return sorted(grounded_products(message, [call]))


@pytest.mark.parametrize("message, item, expected", [
    # Un número suelto que es cantidad («2 tornillos») no elige la variante 1/4 x 2.
    ("Necesito 2 tornillos para madera de 1/4 x 1", {"text": "2 tornillos para madera de 1/4 x 1", "product": "tornillo", "use": "madera"}, ["TOR-025-1"]),
    ("Necesito tornillo para madera 1/4 x 2 pulgadas", {"text": "tornillo para madera 1/4 x 2 pulgadas", "product": "tornillo", "measure": "1/4 x 2 pulgadas"}, ["TOR-025-2"]),
    # Falta el diámetro: hay 1/4 x 2 y 3/16 x 2, así que no se elige.
    ("Tornillo para madera de 2 pulgadas", {"text": "tornillo para madera de 2 pulgadas", "product": "tornillo", "use": "madera"}, []),
    ("Quiero 2 bisagras de 3 pulgadas", {"text": "2 bisagras de 3 pulgadas", "product": "bisagra"}, ["BIS-3"]),
    ("Una bisagra de 3 1/2", {"text": "bisagra de 3 1/2", "product": "bisagra"}, ["BIS-312"]),
    ("Necesito 2 galones de pintura blanca de vinilo", {"text": "2 galones de pintura blanca de vinilo", "product": "pintura", "color": "blanca"}, ["PIN-BLA"]),
    ("Busco pintura blanca de vinilo", {"text": "pintura blanca de vinilo", "product": "pintura", "color": "blanca"}, []),
    ("Necesito 1 cuñete de pintura blanca", {"text": "1 cuñete de pintura blanca", "product": "pintura", "color": "blanca"}, ["PIN-BLA-C5"]),
    # «2 metros» separa el tubo de los codos y tees de 1/2 que también son de PVC para agua.
    ("Necesito 2 metros de PVC de 1/2 para agua", {"text": "2 metros de PVC de 1/2 para agua", "material": "PVC", "measure": "1/2 pulgada", "use": "agua"}, ["PVC-050"]),
    ("Un bulto de cemento gris de 50", {"text": "bulto de cemento gris de 50", "product": "cemento", "color": "gris"}, ["CEM-050"]),
    ("Bombillo LED de 9 W luz cálida", {"text": "bombillo LED de 9 W luz cálida", "product": "bombillo"}, ["BOM-09C"]),
    ("Bombillo LED de 9 W", {"text": "bombillo LED de 9 W", "product": "bombillo"}, []),
])
def test_large_catalog_selects_only_the_variant_the_message_describes(catalog, message, item, expected):
    assert _selected(catalog, message, **item) == expected


def test_large_catalog_is_fictional_and_keeps_s2_rows(catalog):
    from asistendero.seed import PRODUCTS

    assert len(PRODUCTS) >= 350
    legacy = {row[0]: row[4:6] for row in PRODUCTS[:6]}
    assert legacy == {"PVC-050": (8500, 12), "PVC-075": (11500, 7), "TOR-025-1": (350, 80), "TOR-025-2": (520, 0),
                      "CEM-050": (39500, 9), "PIN-BLA": (56000, 4)}
    # S2-05 y S2-08 siguen sin coincidencia exacta.
    assert not catalog.search(q("tubo PVC de 1 pulgada para agua", product="tubo", material="PVC", measure="1 pulgada", use="agua")).matches
    assert not catalog.search(q("taladro de 20 V", product="taladro", measure="20 V")).matches


def test_plural_filter_covers_singular_variant(catalog):
    # «galones» cubre la variante «galón»: en la primera corrida S3 solo quedaba el cuñete de 5 galones.
    result = catalog.search(q("pintura blanca en galones", product="pintura", color="blanca", presentation="galones"))
    assert "PIN-BLA" in {product.sku for product in result.matches}
