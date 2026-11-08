"""Importa el inventario real de Ferretería Carluz a una base local, fuera del repositorio.

Ejecutar: python -m asistendero.datos.importar_carluz --xlsx "RUTA\\INVENTARIO CARLUZ.xlsx"

Crea ``.local/carluz/tienda.sqlite3`` (``.local/`` no se sube) con el mismo esquema de la tienda ficticia, sin mezclar
un solo producto de demostración. La tabla ``real_import`` guarda cada fila tal como venía y qué se hizo con ella:
con eso la importación cuadra contra el total del Excel y cualquier decisión se puede revisar.
"""

import argparse
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

from asistendero.datos.carluz import (
    CARLUZ_BUSINESS_ID, RECONCILE_TOLERANCE_COP, SHEET, CatalogItem, SourceRow, build_catalog, clean_description,
    is_merchandise, parse_quantity,
)
from asistendero.datos.carluz_vocabulario import OTHER_CATEGORY
from asistendero.datos.hoja_xlsx import WorkbookError, read_sheet
from asistendero.datos.seed import DEMO_STORE_ID, REAL_IMPORT_SCHEMA, create_tables, upgrade_db


CARLUZ_DIR = Path(".local/carluz")
CARLUZ_DB_PATH = CARLUZ_DIR / "tienda.sqlite3"
CARLUZ_SESSIONS_PATH = CARLUZ_DIR / "sesiones.sqlite3"
# Lo que dio la tienda el 07-11-2026. El horario llegó incompleto (solo la pausa del mediodía): se dice así y no se
# completa. Domicilios, garantías y lo demás no se dieron: el agente responde que no tiene el dato.
STORE_INFO = {
    "nombre": {"texto": "Ferretería Carluz"},
    "ubicacion": {"texto": "Carrera 10E # 30-06, Floridablanca, Santander (código postal 681002)."},
    "horario": {"texto": "Al mediodía la tienda cierra a las 11:55 a. m. y vuelve a abrir a las 2:00 p. m. La hora "
                         "de apertura en la mañana y la de cierre en la tarde se confirman con la tienda.",
                "pausa": ["11:55", "14:00"]},
    "medios_pago": {"texto": "En el mostrador se recibe efectivo y transferencia. Este asistente no cobra ni recibe "
                             "pagos."},
}
HEADER = {"A": "ITEM", "B": "DESCRIPCION"}


class ImportRejected(ValueError):
    """La hoja no se puede importar con confianza; no se crea ninguna base."""


def _number(raw: str | None) -> float | None:
    try:
        return float(raw) if raw is not None else None
    except ValueError:
        return None


def source_rows(path: Path) -> list[SourceRow]:
    """Las filas de mercancía y de activos de la hoja. Lo que no se entiende detiene la importación: no se adivina."""
    sheet = read_sheet(path, SHEET)
    start = next((index for index, (_, cells) in enumerate(sheet)
                  if all(cells.get(column, "").strip().upper() == title for column, title in HEADER.items())), None)
    if start is None:
        raise ImportRejected(f"La hoja «{SHEET}» no tiene las columnas ITEM y DESCRIPCION.")
    rows = []
    for number, cells in sheet[start + 1:]:
        if not cells.get("B", "").strip():
            continue  # la fila final de TOTAL no tiene descripción
        item, value = _number(cells.get("A")), _number(cells.get("C"))
        quantity = parse_quantity(cells.get("D", ""))
        if item is None or value is None or quantity is None or value < 0:
            raise ImportRejected(f"La fila {number} no tiene ítem, valor o cantidad legibles: corrígela en el Excel.")
        rows.append(SourceRow(int(item), clean_description(cells["B"]), value, quantity, _number(cells.get("E"))))
    if not rows:
        raise ImportRejected(f"La hoja «{SHEET}» no tiene filas.")
    mismatched = [row.item for row in rows if row.line_total is not None
                  and abs(row.value * row.quantity - row.line_total) > RECONCILE_TOLERANCE_COP]
    if mismatched:
        raise ImportRejected(f"En los ítems {mismatched[:10]} el TOTAL no da cantidad × valor: revisa esas cantidades.")
    return rows


def _report(rows: list[SourceRow], products: list[CatalogItem], excluded: list[SourceRow]) -> dict:
    """Totales agregados, sin descripciones de productos: es lo que se puede citar como evidencia."""
    value = lambda selected: round(sum(row.value * row.quantity for row in selected), 2)
    merchandise = [row for row in rows if is_merchandise(row)]
    categories: dict[str, int] = {}
    for product in products:
        categories[product.category] = categories.get(product.category, 0) + 1
    return {
        "filas_hoja": len(rows),
        "productos": len(products),
        "filas_excluidas": len(excluded),
        "filas_unidas": len(merchandise) - len(products),
        "valor_hoja_cop": value(rows),
        "valor_mercancia_cop": value(merchandise),
        "valor_excluido_cop": value(excluded),
        "cantidades_fraccionarias": sum(row.quantity != int(row.quantity) for row in merchandise),
        "productos_sin_existencias_enteras": sum(product.stock == 0 for product in products),
        "valores_con_decimales": sum(row.value != int(row.value) for row in merchandise),
        "sin_categoria": categories.get(OTHER_CATEGORY, 0),
        "con_sinonimos": sum(bool(product.search_terms) for product in products),
        "con_variante": sum(bool(product.variant) for product in products),
        "unidades": _count(product.unit for product in products),
        "categorias": dict(sorted(categories.items(), key=lambda item: -item[1])),
    }


def _count(values) -> dict[str, int]:
    counted: dict[str, int] = {}
    for value in values:
        counted[value] = counted.get(value, 0) + 1
    return dict(sorted(counted.items(), key=lambda item: -item[1]))


def _write(path: Path, rows: list[SourceRow], products: list[CatalogItem], source_name: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    sku_of = {item: product.sku for product in products for item in product.items}
    with closing(sqlite3.connect(path)) as connection, connection:
        create_tables(connection)
        connection.executescript(REAL_IMPORT_SCHEMA)
        connection.executemany(
            "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(CARLUZ_BUSINESS_ID, DEMO_STORE_ID, product.sku, product.name, product.variant, product.unit,
              product.price_cop, product.stock, product.search_terms, now, product.category) for product in products],
        )
        connection.executemany(
            "INSERT INTO store_info VALUES (?, ?, ?, ?)",
            [(CARLUZ_BUSINESS_ID, DEMO_STORE_ID, topic, json.dumps(content, ensure_ascii=False))
             for topic, content in STORE_INFO.items()],
        )
        connection.executemany(
            "INSERT INTO real_import VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(row.item, row.description, row.value, row.quantity, sku_of.get(row.item), source_name, now)
             for row in rows],
        )


def import_inventory(xlsx: Path, database: Path = CARLUZ_DB_PATH, replace: bool = False) -> dict:
    """Crea la base y devuelve el reporte. Una base existente puede tener cambios del tendero: no se pisa sin pedirlo."""
    database = database.resolve()
    if database.exists() and not replace:
        raise ImportRejected(f"Ya existe {database}: usa --reemplazar para rehacerla (se pierden sus pedidos y cambios).")
    rows = source_rows(xlsx)
    products, excluded = build_catalog(rows)
    database.parent.mkdir(parents=True, exist_ok=True)
    temporary = database.with_suffix(".nueva")
    temporary.unlink(missing_ok=True)
    try:
        _write(temporary, rows, products, xlsx.name)
        upgrade_db(temporary)
        temporary.replace(database)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return _report(rows, products, excluded)


def main() -> int:
    parser = argparse.ArgumentParser(description="Importa el inventario real de Ferretería Carluz a .local/")
    parser.add_argument("--xlsx", type=Path, required=True, help="Ruta del Excel con la hoja INVENTARIO REAL")
    parser.add_argument("--db", type=Path, default=CARLUZ_DB_PATH, help="Base a crear; predeterminada en .local/carluz")
    parser.add_argument("--reemplazar", action="store_true", help="Rehace una base existente y pierde sus cambios")
    args = parser.parse_args()
    try:
        report = import_inventory(args.xlsx, args.db, args.reemplazar)
    except (WorkbookError, ImportRejected, OSError) as exc:
        print(f"No se importó: {exc}", file=sys.stderr)
        return 1
    args.db.with_name("importacion.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
