"""Categorías ordenables y alertas de existencias bajas que administra el tendero.

Las categorías viven en ``products.category``: es la columna que lee ``explorar_categoria`` del agente. Esta tabla
solo agrega el orden en que el tendero quiere verlas y deja crear una vacía antes de cargarle productos. Renombrar
cambia la tabla y los productos de la sede en la misma transacción, así que el agente ve el nombre nuevo de
inmediato y nunca una categoría a medias. Precio y existencias no se tocan.

Los umbrales dicen desde cuántas unidades disponibles un producto pide surtido: uno global y, si el tendero quiere,
uno propio por SKU. Cada cambio queda en ``catalog_admin_events`` con la hora UTC, el antes y el después, y el actor
(«tendero» en el prototipo). Todo es ficticio y queda filtrado por negocio y sede.
"""

import re
import sqlite3
import unicodedata

from asistendero.catalog import RESERVED_SQL
from asistendero.product_art import category_color
from asistendero.stock_thresholds import DEFAULT_LOW_STOCK, CatalogError, StockThresholds
from asistendero.validation import normalize_text


__all__ = ["DEFAULT_LOW_STOCK", "MAX_CATEGORIES", "MAX_CATEGORY_CHARS", "CatalogAdmin", "CatalogError"]
MAX_CATEGORY_CHARS = 40
MAX_CATEGORIES = 100


def _key(name: str) -> str:
    """Clave para comparar nombres: «Plomería» y «plomeria » son la misma categoría."""
    return normalize_text(name).strip()


def _category_name(value: object) -> str:
    if not isinstance(value, str):
        raise CatalogError("INVALID_ARGUMENT", f"La categoría es un texto de 1 a {MAX_CATEGORY_CHARS} caracteres.")
    name = re.sub(r"\s+", " ", value.strip())
    if not 1 <= len(name) <= MAX_CATEGORY_CHARS or any(unicodedata.category(char) == "Cc" for char in name):
        raise CatalogError("INVALID_ARGUMENT", f"La categoría es un texto de 1 a {MAX_CATEGORY_CHARS} caracteres.")
    return name


class CatalogAdmin(StockThresholds):
    """Categorías ordenables (aquí) y umbrales de existencias bajas (heredados de ``StockThresholds``)."""

    def _sync(self, connection: sqlite3.Connection) -> list[str]:
        """Nombres en orden; las categorías de productos que aún no están en la tabla entran al final, en orden
        alfabético. La primera vez eso llena la tabla entera; después recoge las que trae un producto nuevo."""
        known = [row[0] for row in connection.execute(
            "SELECT name FROM categories WHERE business_id = ? AND store_id = ? ORDER BY position, name", self._scope)]
        present = set(known)
        missing = [row[0] for row in connection.execute(
            "SELECT DISTINCT category FROM products WHERE business_id = ? AND store_id = ? ORDER BY category",
            self._scope) if row[0] not in present]
        if missing:
            connection.executemany("INSERT INTO categories VALUES (?, ?, ?, ?)",
                                   [(*self._scope, name, len(known) + index + 1) for index, name in enumerate(missing)])
        return known + missing

    def _renumber(self, connection: sqlite3.Connection, names: list[str]) -> None:
        connection.executemany("UPDATE categories SET position = ? WHERE business_id = ? AND store_id = ? AND name = ?",
                               [(index + 1, *self._scope, name) for index, name in enumerate(names)])

    def _existing(self, names: list[str], name: object) -> str:
        wanted = _category_name(name)
        if wanted not in names:
            raise CatalogError("CATEGORY_NOT_FOUND", f"No existe la categoría «{wanted}».")
        return wanted

    def categories(self) -> list[dict]:
        """Categorías en el orden del tendero, con cuántos productos tienen y cuántos se pueden vender por el chat."""
        def read(connection: sqlite3.Connection) -> list[dict]:
            names = self._sync(connection)
            counts = {row["category"]: row for row in connection.execute(
                f"SELECT category, COUNT(*) AS products, SUM(stock - {RESERVED_SQL} > 0) AS available "
                "FROM products WHERE business_id = ? AND store_id = ? GROUP BY category", self._scope)}
            return [{"nombre": name, "posicion": index + 1,
                     "productos": counts[name]["products"] if name in counts else 0,
                     "con_existencias": counts[name]["available"] if name in counts else 0,
                     "color": category_color(name)} for index, name in enumerate(names)]
        return self._run(read)

    def create(self, nombre: str) -> list[dict]:
        """Crea una categoría vacía al final de la lista."""
        name = _category_name(nombre)

        def insert(connection: sqlite3.Connection) -> None:
            names = self._sync(connection)
            self._reject_duplicate(names, name)
            if len(names) >= MAX_CATEGORIES:
                raise CatalogError("TOO_MANY_CATEGORIES", f"Caben hasta {MAX_CATEGORIES} categorías.")
            connection.execute("INSERT INTO categories VALUES (?, ?, ?, ?)", (*self._scope, name, len(names) + 1))
            self._log(connection, "crear_categoria", None, name)

        self._run(insert)
        return self.categories()

    @staticmethod
    def _reject_duplicate(names: list[str], name: str, allowed: str = "") -> None:
        clash = next((other for other in names if _key(other) == _key(name) and other != allowed), None)
        if clash:
            raise CatalogError("DUPLICATE_CATEGORY", f"Ya existe la categoría «{clash}».")

    def rename(self, nombre: str, nuevo: str) -> list[dict]:
        """Renombra la categoría y sus productos de la sede; precio y existencias quedan igual."""
        new_name = _category_name(nuevo)

        def apply(connection: sqlite3.Connection) -> None:
            names = self._sync(connection)
            old_name = self._existing(names, nombre)
            if old_name == new_name:
                return
            # Cambiar solo mayúsculas o tildes de la misma categoría está permitido; chocar con otra, no.
            self._reject_duplicate(names, new_name, allowed=old_name)
            connection.execute("UPDATE categories SET name = ? WHERE business_id = ? AND store_id = ? AND name = ?",
                               (new_name, *self._scope, old_name))
            connection.execute("UPDATE products SET category = ? WHERE business_id = ? AND store_id = ? "
                               "AND category = ?", (new_name, *self._scope, old_name))
            self._log(connection, "renombrar_categoria", old_name, new_name)

        self._run(apply)
        return self.categories()

    def move(self, nombre: str, posicion: int) -> list[dict]:
        """Lleva la categoría a la posición pedida (1 es la primera) y corre las demás."""
        def apply(connection: sqlite3.Connection) -> None:
            names = self._sync(connection)
            name = self._existing(names, nombre)
            if not isinstance(posicion, int) or isinstance(posicion, bool) or not 1 <= posicion <= len(names):
                raise CatalogError("INVALID_ARGUMENT", f"La posición va de 1 a {len(names)}.")
            before = names.index(name) + 1
            if before == posicion:
                return
            names.remove(name)
            names.insert(posicion - 1, name)
            self._renumber(connection, names)
            self._log(connection, "mover_categoria", f"{name}: {before}", f"{name}: {posicion}")

        self._run(apply)
        return self.categories()

    def delete(self, nombre: str) -> list[dict]:
        """Borra una categoría solo si no le queda ningún producto: nunca deja productos sin categoría."""
        def apply(connection: sqlite3.Connection) -> None:
            names = self._sync(connection)
            name = self._existing(names, nombre)
            used = connection.execute("SELECT COUNT(*) FROM products WHERE business_id = ? AND store_id = ? "
                                      "AND category = ?", (*self._scope, name)).fetchone()[0]
            if used:
                raise CatalogError("CATEGORY_NOT_EMPTY", f"«{name}» tiene {used} productos: muévelos o renómbrala "
                                                         "antes de borrarla.")
            connection.execute("DELETE FROM categories WHERE business_id = ? AND store_id = ? AND name = ?",
                               (*self._scope, name))
            names.remove(name)
            self._renumber(connection, names)
            self._log(connection, "borrar_categoria", name, None)

        self._run(apply)
        return self.categories()

