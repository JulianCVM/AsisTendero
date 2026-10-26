"""Categorías ordenables y umbrales de existencias bajas del tendero: lo que cambian y lo que nunca tocan."""

from contextlib import closing
import sqlite3

import pytest

from asistendero import inventory
from asistendero.catalog import MockCatalog
from asistendero.catalog_admin import DEFAULT_LOW_STOCK, MAX_CATEGORY_CHARS, CatalogAdmin, CatalogError
from asistendero.product_art import category_color
from asistendero.seed import CATEGORIES, DEMO_BUSINESS_ID, DEMO_STORE_ID, create_mock_db


OTHER_STORE = "sede-norte"


@pytest.fixture
def db(tmp_path):
    return create_mock_db(tmp_path / "catalog.sqlite3")


def _products(path, store_id=DEMO_STORE_ID) -> list[tuple]:
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute("SELECT sku, category, price_cop, stock FROM products WHERE business_id = ? AND "
                                  "store_id = ? ORDER BY sku", (DEMO_BUSINESS_ID, store_id)).fetchall()


def _clone_store(path) -> None:
    """Copia los productos a una segunda sede del mismo negocio para comprobar que nada cruza de una a otra."""
    with sqlite3.connect(path) as connection:
        connection.execute("INSERT INTO products SELECT business_id, ?, sku, name, variant, unit, price_cop, stock, "
                           "search_terms, updated_at, category FROM products WHERE store_id = ?",
                           (OTHER_STORE, DEMO_STORE_ID))
    connection.close()


def test_first_read_fills_the_table_alphabetically_with_counts_and_colors(db):
    rows = CatalogAdmin(db).categories()
    names = [row["nombre"] for row in rows]
    assert names == sorted(set(CATEGORIES.values()))
    assert [row["posicion"] for row in rows] == list(range(1, len(rows) + 1))
    plumbing = next(row for row in rows if row["nombre"] == "Plomería")
    assert plumbing["productos"] == sum(1 for category in CATEGORIES.values() if category == "Plomería")
    assert 0 < plumbing["con_existencias"] <= plumbing["productos"]
    assert plumbing["color"] == category_color("Plomería")
    assert set(rows[0]) == {"nombre", "posicion", "productos", "con_existencias", "color"}


def test_rename_moves_the_products_and_the_agent_sees_the_new_name(db):
    _clone_store(db)
    before = _products(db)
    admin = CatalogAdmin(db)
    rows = admin.rename("Plomería", "Agua y tubería")

    assert "Agua y tubería" in [row["nombre"] for row in rows] and "Plomería" not in [row["nombre"] for row in rows]
    agent_view = {row["categoria"]: row["variantes"] for row in MockCatalog(db).categories()}
    assert "Plomería" not in agent_view and agent_view["Agua y tubería"] > 0
    after = _products(db)
    moved = [old for old, new in zip(before, after) if old[1] != new[1]]
    assert moved and all(old[1] == "Plomería" for old in moved)
    # Lo que no debe pasar: renombrar no toca precio ni existencias, ni la otra sede.
    assert [(sku, price, stock) for sku, _, price, stock in before] == [(sku, p, s) for sku, _, p, s in after]
    assert {category for _, category, _, _ in _products(db, OTHER_STORE)} >= {"Plomería"}
    history = admin.history()
    assert history[0]["accion"] == "renombrar_categoria"
    assert (history[0]["antes"], history[0]["despues"], history[0]["quien"]) == ("Plomería", "Agua y tubería",
                                                                               "tendero")
    assert history[0]["hora"].endswith("+00:00")


def test_duplicates_are_rejected_ignoring_case_and_accents(db):
    admin = CatalogAdmin(db)
    for attempt in ("plomeria", "  PLOMERÍA ", "Electricos"):
        with pytest.raises(CatalogError) as error:
            admin.create(attempt)
        assert error.value.code == "DUPLICATE_CATEGORY"
    with pytest.raises(CatalogError) as error:
        admin.rename("Maderas", "obra GRIS")
    assert error.value.code == "DUPLICATE_CATEGORY"
    # Corregir solo la forma del mismo nombre sí se puede.
    assert "MADERAS" in [row["nombre"] for row in admin.rename("Maderas", "MADERAS")]


@pytest.mark.parametrize("bad", ["", "   ", "x" * (MAX_CATEGORY_CHARS + 1), "Tab\tla\x00", None, 7])
def test_category_names_are_validated(db, bad):
    with pytest.raises(CatalogError) as error:
        CatalogAdmin(db).create(bad)
    assert error.value.code == "INVALID_ARGUMENT"


def test_create_move_and_delete_keep_a_contiguous_order(db):
    admin = CatalogAdmin(db)
    rows = admin.create("Repuestos de moto")
    assert rows[-1] == {"nombre": "Repuestos de moto", "posicion": len(rows), "productos": 0, "con_existencias": 0,
                        "color": category_color("Repuestos de moto")}
    rows = admin.move("Repuestos de moto", 1)
    assert [row["nombre"] for row in rows][:2] == ["Repuestos de moto", "Abrasivos y corte"]
    rows = admin.move("Abrasivos y corte", len(rows))
    assert rows[-1]["nombre"] == "Abrasivos y corte"
    assert [row["posicion"] for row in rows] == list(range(1, len(rows) + 1))
    for bad in (0, len(rows) + 1, True, "2"):
        with pytest.raises(CatalogError):
            admin.move("Maderas", bad)
    rows = admin.delete("Repuestos de moto")
    assert "Repuestos de moto" not in [row["nombre"] for row in rows]
    assert [row["posicion"] for row in rows] == list(range(1, len(rows) + 1))
    # Una nueva instancia lee el mismo orden: queda guardado, no en memoria.
    assert [row["nombre"] for row in CatalogAdmin(db).categories()] == [row["nombre"] for row in rows]
    assert [entry["accion"] for entry in admin.history()][:4] == ["borrar_categoria", "mover_categoria",
                                                                 "mover_categoria", "crear_categoria"]


def test_a_category_with_products_is_never_deleted(db):
    admin = CatalogAdmin(db)
    before = _products(db)
    with pytest.raises(CatalogError) as error:
        admin.delete("Maderas")
    assert error.value.code == "CATEGORY_NOT_EMPTY"
    assert "Maderas" in [row["nombre"] for row in admin.categories()] and _products(db) == before
    with pytest.raises(CatalogError) as error:
        admin.delete("No existe")
    assert error.value.code == "CATEGORY_NOT_FOUND"


def test_a_product_added_later_brings_its_category_to_the_end(db):
    admin = CatalogAdmin(db)
    admin.move("Maderas", 1)
    inventory.Inventory(db).add({"sku": "ZZZ-001", "nombre": "Repuesto ficticio", "variante": "único",
                                 "unidad": "unidad", "precio_cop": 1000, "stock": 3, "categoria": "Accesorios"})
    rows = admin.categories()
    assert rows[0]["nombre"] == "Maderas"
    assert rows[-1]["nombre"] == "Accesorios" and rows[-1]["productos"] == 1


def test_another_store_keeps_its_own_categories(db):
    _clone_store(db)
    CatalogAdmin(db).rename("Maderas", "Madera y tableros")
    CatalogAdmin(db).create("Solo en la sede única")
    other = [row["nombre"] for row in CatalogAdmin(db, store_id=OTHER_STORE).categories()]
    assert "Maderas" in other and "Madera y tableros" not in other and "Solo en la sede única" not in other


def test_global_and_own_thresholds(db):
    admin = CatalogAdmin(db)
    sku = "PVC-050"
    assert DEFAULT_LOW_STOCK == inventory.LOW_STOCK
    assert admin.thresholds() == {"global": DEFAULT_LOW_STOCK, "productos": {}}
    assert admin.threshold_for(sku) == DEFAULT_LOW_STOCK
    assert admin.set_global(8) == {"global": 8, "productos": {}}
    assert admin.set_threshold(sku, 20) == {"global": 8, "productos": {sku: 20}}
    assert (admin.threshold_for(sku), admin.threshold_for("PVC-075")) == (20, 8)
    assert admin.set_threshold(sku, 0)["productos"] == {sku: 0}
    assert admin.set_threshold(sku, None) == {"global": 8, "productos": {}}
    assert admin.threshold_for(sku) == 8
    assert [entry["accion"] for entry in admin.history()][:2] == ["umbral_producto", "umbral_producto"]
    assert admin.history()[0]["despues"] == f"{sku}: global"
    # Los umbrales no tocan existencias ni precios, ni los de otra sede.
    assert _products(db) == _products(create_mock_db(db.parent / "fresh.sqlite3"))
    assert CatalogAdmin(db, store_id=OTHER_STORE).thresholds() == {"global": DEFAULT_LOW_STOCK, "productos": {}}


@pytest.mark.parametrize("bad", [-1, 100_001, 2.5, "5", True])
def test_threshold_values_are_validated(db, bad):
    admin = CatalogAdmin(db)
    for change in (lambda: admin.set_global(bad), lambda: admin.set_threshold("PVC-050", bad)):
        with pytest.raises(CatalogError) as error:
            change()
        assert error.value.code == "INVALID_ARGUMENT"
    assert admin.thresholds() == {"global": DEFAULT_LOW_STOCK, "productos": {}}


def test_thresholds_need_an_existing_sku_of_this_store(db):
    _clone_store(db)
    with sqlite3.connect(db) as connection:
        connection.execute("INSERT INTO products SELECT business_id, ?, 'SOLO-NORTE', name, variant, unit, price_cop, "
                           "stock, search_terms, updated_at, category FROM products WHERE sku = 'PVC-050' AND store_id = ?",
                           (OTHER_STORE, DEMO_STORE_ID))
    connection.close()
    admin = CatalogAdmin(db)
    for sku, code in (("NO-EXISTE", "SKU_NOT_FOUND"), ("SOLO-NORTE", "SKU_NOT_FOUND"), ("pvc-050", "INVALID_ARGUMENT"),
                      ("'; DROP TABLE products; --", "INVALID_ARGUMENT")):
        with pytest.raises(CatalogError) as error:
            admin.set_threshold(sku, 3)
        assert error.value.code == code
        with pytest.raises(CatalogError):
            admin.threshold_for(sku)
    assert admin.thresholds()["productos"] == {}
