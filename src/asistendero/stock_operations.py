"""Arma la propuesta del asistente de bodega: qué cambiaría cada operación, con antes y después, sin escribir nada.

Cada operación que interpretó Grok pasa por ``stock_matching.identify``; lo que no se puede aplicar (producto ambiguo
o inexistente, cantidad o proveedor que faltan, una fecha inválida) queda como operación «no aplicable» con su
advertencia, para que el tendero vea qué no se hará y por qué. Las reglas que mandan sobre lo que diga Grok:

- Una ``recepcion`` con fecha posterior a hoy, o cuyo texto anuncia una llegada («mañana llegan 30»), no suma a la
  bodega: queda como advertencia.
- Una llegada va contra el pedido abierto que tiene ese SKU pendiente (el de la ``oc`` dicha o el de fecha más
  próxima). Lo que llegó sin pedido en el mismo mensaje entra a esa misma llegada como adicional; sin pedido ni
  proveedor, no hay a quién cargarlo y se pregunta.
- La vista de cada llegada sale de ``Purchasing.receive(..., apply=False)``: el mismo código que la aplicará.
- Un mismo SKU no puede cambiar dos veces su bodega o su precio en una propuesta: la segunda se pregunta.
"""

from datetime import date

from asistendero.catalog import MockCatalog, Product
from asistendero.inventory import MAX_PRICE_COP, MAX_STOCK
from asistendero.purchasing import Purchasing, PurchasingError
from asistendero.purchasing_rules import MAX_QUANTITY, expected_date
from asistendero.reply_text import format_cop
from asistendero.stock_arrivals import arrival_operations, move_operations, purchase_operations
from asistendero.stock_matching import find_supplier, identify, sounds_future

EXTRA_KEYS = {"recepcion": ("oc", "proveedor"), "pedido_proveedor": ("proveedor", "fecha_estimada"),
              "programar_entrega": ("oc", "proveedor", "fecha_antes", "fecha_nueva")}
TITLES = {"recepcion": "Llegada", "pedido_proveedor": "Pedido al proveedor", "programar_entrega": "Nueva fecha",
          "cambio_precio": "Cambio de precio", "correccion_stock": "Conteo de bodega", "consulta": "Consulta"}
# Un precio que cambia más que esto suele ser un cero de más o de menos al dictar.
PRICE_JUMP = 0.5


def base_line(row: dict) -> dict:
    return {"sku": row["sku"], "nombre": row["nombre"], "variante": row["variante"], "unidad": row["unidad"]}


def stock_row(purchasing: Purchasing, sku: str) -> dict | None:
    """Precio, existencias físicas y apartadas de un SKU, como las ve el panel del tendero."""
    return next((item for item in purchasing.inventory.products(sku) if item["sku"] == sku), None)


def _count(value: object, minimum: int, maximum: int) -> int | None:
    return value if isinstance(value, int) and minimum <= value <= maximum else None


class ProposalBuilder:
    def __init__(self, purchasing: Purchasing, catalog: MockCatalog, message: str, today: date, origin: str,
                 suppliers: list[dict], open_orders: list[dict], pending: dict[str, dict]):
        self.purchasing, self.catalog, self.message = purchasing, catalog, message
        self.today, self.origin = today, origin
        self.suppliers, self.orders, self.pending = suppliers, open_orders, pending
        self.offered = {line["sku"] for order in open_orders for line in order["lineas"] if line["pendiente"] > 0}
        self.warnings: list[str] = []
        self.failed: list[dict] = []
        self.touched: set[tuple[str, str]] = set()
        self.arrivals: dict[tuple, dict] = {}
        self.loose: list[tuple[dict, Product, int]] = []
        self.purchases: dict[tuple, dict] = {}
        self.moves: dict[str, dict] = {}
        self.singles: list[dict] = []
        self.queries: list[dict] = []

    def _fail(self, operation: dict, warning: str, **extra: object) -> None:
        tipo = operation["tipo"]
        self.warnings.append(warning)
        self.failed.append({"tipo": tipo, "titulo": f"{TITLES[tipo]}: «{operation['producto']}»", "aplicable": False,
                            "lineas": [], **{key: extra.get(key) for key in EXTRA_KEYS.get(tipo, ())}})

    def _claim(self, field: str, sku: str, operation: dict, name: str) -> bool:
        if (field, sku) in self.touched:
            self._fail(operation, f"{name} aparece dos veces en el mensaje; cuéntamelo en un solo cambio.")
            return False
        self.touched.add((field, sku))
        return True

    def add(self, operation: dict) -> None:
        match = identify(self.catalog, self.message, operation, self.offered, set(self.pending))
        if match.product is None:
            self._fail(operation, match.warning, fecha_nueva=operation["fecha"])
            return
        getattr(self, f"_{operation['tipo']}")(operation, match.product)

    def _order_for(self, operation: dict, sku: str, supplier: dict | None) -> tuple[dict | None, str | None]:
        """El pedido abierto de la operación: el de su ``oc`` o el de fecha más próxima con el SKU pendiente."""
        if operation["oc"]:
            order = next((item for item in self.orders if item["oc"] == operation["oc"]), None)
            if order is None:
                return None, f"No encuentro el pedido {operation['oc']} abierto."
            if supplier and order["proveedor_id"] != supplier["proveedor"]:
                return None, f"El pedido {operation['oc']} es de {order['proveedor']}, no de {supplier['nombre']}."
            return order, None
        waiting = [order for order in self.orders if (not supplier or order["proveedor_id"] == supplier["proveedor"])
                   and any(line["sku"] == sku and line["pendiente"] > 0 for line in order["lineas"])]
        waiting.sort(key=lambda order: (order["fecha_estimada"] or "9999-12-31", order["oc"]))
        return (waiting[0] if waiting else None), None

    def _supplier(self, operation: dict) -> tuple[dict | None, bool]:
        """(proveedor, válido): sin proveedor dicho es válido; uno dicho que no se identifica, no."""
        supplier, warning = find_supplier(self.suppliers, operation["proveedor"])
        if warning:
            self._fail(operation, warning)
        return supplier, warning is None

    def _recepcion(self, operation: dict, product: Product) -> None:
        name = f"{product.name} {product.variant}"
        quantity = _count(operation["cantidad"], 1, MAX_QUANTITY)
        if (operation["fecha"] and operation["fecha"] > self.today.isoformat()) or sounds_future(
                self.message, operation["producto"]):
            self.warnings.append(f"Eso parece una entrega futura de {name}: no lo sumo a la bodega hasta que llegue. "
                                 "Si quieres, dime para cuándo y te propongo la fecha de entrega.")
            return
        if quantity is None:
            self._fail(operation, f"Dime cuántas unidades de {name} llegaron (un entero mayor que 0).")
            return
        supplier, valid = self._supplier(operation)
        if not valid:
            return
        order, warning = self._order_for(operation, product.sku, supplier)
        if warning:
            self._fail(operation, warning)
            return
        if order is None and supplier is None:
            self.loose.append((operation, product, quantity))
            return
        key = ("oc", order["oc"]) if order else ("proveedor", supplier["proveedor"])
        arrival = self.arrivals.setdefault(key, {"oc": order["oc"] if order else None,
                                                 "proveedor": order["proveedor"] if order else supplier["nombre"],
                                                 "lineas": []})
        if self._claim("stock", product.sku, operation, name):
            arrival["lineas"].append({"sku": product.sku, "cantidad": quantity})

    def _pedido_proveedor(self, operation: dict, product: Product) -> None:
        name = f"{product.name} {product.variant}"
        supplier, valid = self._supplier(operation)
        if not valid:
            return
        if supplier is None:
            self._fail(operation, f"¿A qué proveedor le pediste {name}? Dime su nombre.")
            return
        quantity = _count(operation["cantidad"], 1, MAX_QUANTITY)
        if quantity is None:
            self._fail(operation, f"Dime cuántas unidades de {name} pediste (un entero mayor que 0).",
                       proveedor=supplier["nombre"])
            return
        try:
            day = expected_date(operation["fecha"], self.today)
        except PurchasingError as error:
            self._fail(operation, f"{name}: {error}", proveedor=supplier["nombre"])
            return
        group = self.purchases.setdefault((supplier["proveedor"], day), {"proveedor": supplier["nombre"],
                                                                          "fecha_estimada": day, "lineas": []})
        if self._claim("pedido", product.sku, operation, name):
            group["lineas"].append({**base_line(stock_row(self.purchasing, product.sku)), "cantidad": quantity})

    def _programar_entrega(self, operation: dict, product: Product) -> None:
        name = f"{product.name} {product.variant}"
        try:
            day = expected_date(operation["fecha"], self.today)
        except PurchasingError as error:
            self._fail(operation, f"{name}: {error}", fecha_nueva=operation["fecha"])
            return
        if day is None:
            self._fail(operation, f"¿Para qué fecha llega {name}?")
            return
        supplier, valid = self._supplier(operation)
        if not valid:
            return
        order, warning = self._order_for(operation, product.sku, supplier)
        if warning:
            self._fail(operation, warning, fecha_nueva=day)
            return
        if order is None:
            self.warnings.append(f"No hay un pedido abierto de {name}; te lo propongo como pedido nuevo al proveedor.")
            self._pedido_proveedor({**operation, "fecha": day}, product)
            return
        move = self.moves.setdefault(order["oc"], {"order": order, "fecha_nueva": day, "dichos": {}})
        if move["fecha_nueva"] != day:
            self._fail(operation, f"Diste dos fechas para el pedido {order['oc']}; dime una sola.", oc=order["oc"])
            return
        move["dichos"][product.sku] = operation["cantidad"]

    def _cambio_precio(self, operation: dict, product: Product) -> None:
        row = stock_row(self.purchasing, product.sku)
        name = f"{product.name} {product.variant}"
        price = _count(operation["precio_cop"], 1, MAX_PRICE_COP)
        if price is None:
            self._fail(operation, f"Dime el precio nuevo de {name} en pesos (un entero de 1 a {MAX_PRICE_COP:,})."
                       .replace(",", "."))
            return
        if price == row["precio_cop"]:
            self.warnings.append(f"{name} ya cuesta {format_cop(price)}; no hay nada que cambiar.")
            return
        if not self._claim("precio", product.sku, operation, name):
            return
        if row["precio_cop"] and abs(price - row["precio_cop"]) > PRICE_JUMP * row["precio_cop"]:
            self.warnings.append(f"El precio de {name} cambia más del 50 % ({format_cop(row['precio_cop'])} → "
                                 f"{format_cop(price)}); revísalo antes de confirmar.")
        self.singles.append({"tipo": "cambio_precio", "titulo": f"Precio de {name}", "aplicable": True, "lineas": [
            {**base_line(row), "precio_antes": row["precio_cop"], "precio_nuevo": price}]})

    def _correccion_stock(self, operation: dict, product: Product) -> None:
        row = stock_row(self.purchasing, product.sku)
        name = f"{product.name} {product.variant}"
        counted = _count(operation["cantidad"], 0, MAX_STOCK)
        if counted is None:
            self._fail(operation, f"Dime cuántas unidades de {name} contaste (un entero de 0 en adelante).")
            return
        if counted < row["apartado"]:
            self._fail(operation, f"{name} tiene {row['apartado']} apartadas en pedidos; el conteo no puede quedar "
                                  "por debajo. Entrega o cancela esos pedidos primero.")
            return
        if counted == row["stock"]:
            self.warnings.append(f"La bodega ya tiene {counted} de {name}; no hay nada que corregir.")
            return
        if self._claim("stock", product.sku, operation, name):
            self.singles.append({"tipo": "correccion_stock", "titulo": f"Conteo de {name}", "aplicable": True,
                                 "lineas": [{**base_line(row), "stock_antes": row["stock"], "stock_nuevo": counted,
                                             "apartado": row["apartado"]}]})

    def _consulta(self, operation: dict, product: Product) -> None:
        row = stock_row(self.purchasing, product.sku)
        if any(line["sku"] == row["sku"] for line in self.queries):
            return
        self.queries.append({**base_line(row), "stock": row["stock"], "apartado": row["apartado"],
                             "disponible": row["disponible"], "precio_cop": row["precio_cop"],
                             "en_camino": self.pending.get(row["sku"], {}).get("pendiente", 0)})

    def build(self, operations: list[dict]) -> tuple[list[dict], list[str]]:
        """(operaciones, advertencias): llegadas primero, porque las fechas nuevas descuentan lo que llegó."""
        for operation in operations:
            self.add(operation)
        arrivals = arrival_operations(self)
        built = [*arrivals, *move_operations(self, arrivals), *purchase_operations(self), *self.singles]
        if self.queries:
            built.append({"tipo": "consulta", "titulo": TITLES["consulta"], "aplicable": False, "lineas": self.queries})
        return [*built, *self.failed], self.warnings
