"""Pictogramas generados de los productos: SVG válido, seguro, determinista y con una forma propia por familia."""

from xml.etree import ElementTree

import pytest

from asistendero.catalog_data import FAMILIES
from asistendero.product_art import (ART_KINDS, CATEGORY_COLORS, CATEGORY_KINDS, DEFAULT_TINTS, FALLBACK_KIND,
                                     MAX_ART_TEXT, SHAPES, art_kind, art_tint, category_color, product_svg)
from asistendero.seed import CATEGORIES, PRODUCTS


SVG_NS = "{http://www.w3.org/2000/svg}"
NAMESPACE = 'xmlns="http://www.w3.org/2000/svg"'
FORBIDDEN = ("<script", "href", "http", "url(", "<image", "<foreignobject", "<text", "javascript", " on")


def _catalog() -> list[tuple[str, str, str]]:
    return [(name, variant, CATEGORIES[sku]) for sku, name, variant, *_ in PRODUCTS]


def _assert_safe_svg(svg: str) -> ElementTree.Element:
    root = ElementTree.fromstring(svg)
    assert root.tag == f"{SVG_NS}svg" and root.get("viewBox") == "0 0 96 96"
    # El único «http» permitido es el espacio de nombres de SVG, que no se descarga.
    body = svg.replace(NAMESPACE, "", 1).casefold()
    assert not [word for word in FORBIDDEN if word in body]
    return root


def test_every_catalog_product_draws_a_valid_and_safe_svg():
    products = _catalog()
    assert len(products) == len(PRODUCTS) > 250
    for name, variant, category in products:
        svg = product_svg(name, variant, category)
        _assert_safe_svg(svg)
        assert svg == product_svg(name, variant, category)
        # El nombre del producto nunca viaja dentro del SVG: no hay texto que escapar ni que filtrar.
        assert name.casefold() not in svg.casefold()


def test_families_get_their_own_shape_instead_of_the_category_fallback():
    # Sin categoría, un nombre que ninguna regla reconoce cae en el respaldo: así se cuentan.
    fallbacks = [name for _, name, *_ in FAMILIES if art_kind(name) == FALLBACK_KIND]
    assert len(fallbacks) <= 2, fallbacks
    # Y la variedad es real: no todo es un tubo o una caja.
    used = {art_kind(name, category) for _, name, _, category, _, _ in FAMILIES}
    assert len(used) >= 30


@pytest.mark.parametrize(("name", "kind"), [
    ("Llave terminal para jardín", "grifo"),
    ("Llave para tubo", "llave"),
    ("Tubo PVC conduit eléctrico", "tubo"),
    ("Pegante para cerámica", "saco"),
    ("Pegante de contacto", "frasco"),
    ("Cal hidratada", "saco"),
    ("Cable eléctrico THHN calibre 12 AWG", "cable"),
    ("Cinta aislante", "cinta"),
    ("Escoba plástica", "escoba"),
    ("Teja plástica traslúcida", "teja"),
    ("Plástico negro calibre 6", "plastico"),
    ("Juego de llaves Allen", "allen"),
])
def test_the_rule_order_resolves_shared_words(name, kind):
    assert art_kind(name) == kind


def test_unknown_names_fall_back_to_the_category_or_a_generic_package():
    assert art_kind("Producto sin palabra conocida", "Plomería") == CATEGORY_KINDS["Plomería"]
    assert art_kind("Producto sin palabra conocida", "Categoría nueva") == FALLBACK_KIND
    _assert_safe_svg(product_svg("Producto sin palabra conocida", "", "Categoría nueva"))
    # «cal» es una palabra entera: «calibre» no convierte un plástico en un saco de cal.
    assert art_kind("Calibre raro") == FALLBACK_KIND


def test_color_comes_from_the_name_or_variant_and_never_breaks_the_shape():
    beige = product_svg("Pintura vinilo beige", "galón", "Pinturas y acabados")
    red = product_svg("Pintura vinilo roja", "galón", "Pinturas y acabados")
    assert beige != red and "#E2CBA0" in beige and "#C9573F" in red
    assert art_tint("cable", "Cable eléctrico THHN calibre 14 AWG", "rojo") == "#C9573F"
    assert art_tint("chaleco", "Chaleco reflectivo", "verde limón") != art_tint("chaleco", "Chaleco reflectivo", "verde")
    # El material va antes que el color: el conduit es verde aunque la variante no lo diga.
    assert art_tint("tubo", "Tubo PVC conduit eléctrico", "1/2 pulgada") == "#7FB08A"


def test_special_characters_in_the_name_do_not_break_the_xml():
    tricky = ('Tubo <script>alert(1)</script> & "comillas" \'simples\' ]]> ñandú', 'x" onload="alert(1)',
              '<Plomería & "cía">')
    svg = product_svg(*tricky)
    _assert_safe_svg(svg)
    assert "alert" not in svg and "onload" not in svg


def test_inputs_out_of_bounds_are_rejected_not_trimmed():
    with pytest.raises(ValueError):
        product_svg("Tubo" * MAX_ART_TEXT, "", "Plomería")
    with pytest.raises(ValueError):
        product_svg(None, "", "Plomería")  # type: ignore[arg-type]


def test_every_category_has_a_soft_background_and_new_ones_get_a_stable_one():
    assert set(CATEGORIES.values()) <= set(CATEGORY_COLORS)
    for color in CATEGORY_COLORS.values():
        red, green, blue = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        # Fondo claro: el contorno petróleo (#173B4A) tiene que contrastar encima.
        assert min(red, green, blue) >= 0xB0
    assert category_color("Repuestos de moto") == category_color("repuestos de moto")
    assert category_color("Repuestos de moto").startswith("#")


def test_every_kind_draws_on_its_own():
    assert set(ART_KINDS) == set(SHAPES) == set(DEFAULT_TINTS)
    for kind in ART_KINDS:
        _assert_safe_svg(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96">'
                         f"<g>{SHAPES[kind](DEFAULT_TINTS[kind])}</g></svg>")
