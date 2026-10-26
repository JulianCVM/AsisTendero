"""Lo que lee el panel del tendero: cada ruta GET de ``tendero.py`` junta aquí los módulos de la tienda.

Solo lectura y sin Grok. Los productos del panel llevan su alerta de stock (``stock_thresholds``) y lo que viene en
camino de los pedidos al proveedor (``purchasing``); el catálogo de consulta muestra lo mismo que lee el asistente y
nunca costos de compra. Las conversaciones se leen con ``supervision`` y no exponen datos del cliente.
"""

from asistendero.catalog_admin import CatalogAdmin
from asistendero.handoff import ATTENTION_STATES
from asistendero.inventory import Inventory
from asistendero.orders import BOGOTA, ORDER_ID, OrderBook
from asistendero.payments import METHODS, PAYMENT_STATUSES, Payments
from asistendero.purchasing import Purchasing
from asistendero.sales import STATUSES, day_summary, order_board
from asistendero.sales_history import sales_history, sales_summary
from asistendero.sessions import SESSION_ID, SessionStore
from asistendero.supervision import conversation, conversations


MAX_QUERY = 60
STOCK_FILTERS = ("todos", "bajo", "agotado", "camino")
SHORT_SESSION = 8
ACTIVITY_SHOWN = 8
SUPERVISED = 200


class PanelViews:
    def __init__(self, inventory: Inventory, orders: OrderBook, sessions: SessionStore, payments: Payments,
                 purchasing: Purchasing, admin: CatalogAdmin, assistant=None):
        self.inventory, self.orders, self.sessions = inventory, orders, sessions
        self.payments, self.purchasing, self.admin, self.assistant = payments, purchasing, admin, assistant

    def today(self) -> str:
        return self.orders.clock().astimezone(BOGOTA).strftime("%Y-%m-%d")

    def products(self, query: str = "", category: str = "", stock: str = "todos") -> list[dict]:
        if stock not in STOCK_FILTERS:
            raise ValueError(f"El filtro de existencias es uno de: {', '.join(STOCK_FILTERS)}.")
        limits = self.admin.thresholds()
        coming = self.purchasing.pending_by_sku()
        result = []
        for product in self.inventory.products(query[:MAX_QUERY], category[:MAX_QUERY]):
            own = limits["productos"].get(product["sku"])
            arriving = coming.get(product["sku"], {})
            product |= {"alerta": limits["global"] if own is None else own, "alerta_propia": own is not None,
                        "alerta_general": limits["global"], "en_camino": arriving.get("pendiente", 0),
                        "llega": arriving.get("llega")}
            if stock == "bajo" and product["disponible"] > product["alerta"]:
                continue
            if (stock == "agotado" and product["disponible"] > 0) or (stock == "camino" and not product["en_camino"]):
                continue
            result.append(product)
        return result

    def category_names(self) -> list[str]:
        return [category["nombre"] for category in self.admin.categories()]

    def inventory_page(self, params: dict) -> dict:
        stock = "bajo" if params.get("bajo") == "1" else params.get("estado") or "todos"
        return {"productos": self.products(params.get("q", ""), params.get("categoria", ""), stock),
                "categorias": self.category_names()}

    def catalog(self) -> dict:
        # Lo mismo que cotiza el asistente: precio y lo que queda para vender; sin costos ni datos internos.
        fields = ("sku", "nombre", "variante", "unidad", "precio_cop", "apartado", "disponible", "categoria", "surtido")
        return {"productos": [{key: product[key] for key in fields} for product in self.inventory.products()],
                "categorias": self.category_names()}

    def board(self, params: dict) -> dict:
        status = params.get("estado") or None
        if status is not None and status not in STATUSES:
            raise ValueError(f"El estado es uno de: {', '.join(STATUSES)}.")
        orders = order_board(self.orders, status, payments=self.payments)
        if params.get("revisar") == "1":
            orders = [order for order in orders if order["revisar"]]
        return {"pedidos": orders, "estados": list(STATUSES)}

    def _chats(self) -> list[dict]:
        return conversations(self.sessions, self.orders, limit=SUPERVISED)

    def summary(self) -> dict:
        day = self.today()
        base = day_summary(self.orders, day)
        board = order_board(self.orders, payments=self.payments)
        chats = self._chats()
        review = [order for order in board if order["revisar"]]
        open_orders = [order for order in self.purchasing.orders() if order["estado"] in ("pedido", "parcial")]
        return {
            **base,
            "por_recoger": [order for order in board if order["estado"] in ("pendiente", "confirmado")][:20],
            "revisar_pedidos": len(review),
            "dinero": sales_summary(self.orders, self.payments, day, day),
            "revisar": self._attention(review, chats, open_orders),
            "asistente": self._agent(day, board, chats),
            "en_camino": [{"oc": order["oc"], "proveedor": order["proveedor"], "pendiente": order["pendiente"],
                           "productos": sum(line["pendiente"] > 0 for line in order["lineas"]),
                           "fecha_estimada": order["fecha_estimada"], "atrasada": order["atrasada"]}
                          for order in sorted(open_orders, key=lambda item: item["fecha_estimada"] or "9999")][:6],
        }

    @staticmethod
    def _attention(review: list[dict], chats: list[dict], purchases: list[dict]) -> list[dict]:
        items = [{"tipo": "pedido", "texto": f"{order['pedido']}: {order['revisar'][0]}", "dato": None,
                  "enlace": "#pedidos"} for order in review[:5]]
        items += [{"tipo": "ayuda", "texto": f"El cliente {chat['id_corto']} pide hablar con el tendero", "dato": None,
                   "enlace": f"#conversaciones/{chat['id']}"} for chat in chats if chat["atencion"] == "requiere_humano"][:5]
        late = [order for order in purchases if order["atrasada"]]
        items += [{"tipo": "incidencia", "texto": f"{order['oc']} de {order['proveedor']} está atrasado",
                   "dato": f"{order['pendiente']} por llegar", "enlace": "#inventario/abastecimiento"} for order in late[:3]]
        return items

    @staticmethod
    def _agent(day: str, board: list[dict], chats: list[dict]) -> dict:
        today = [chat for chat in chats if (chat["ultima_actividad"] or "").startswith(day)]
        created = [order for order in board if (order["creado"] or "").startswith(day)]
        activity = [{"hora": order["creado"], "texto": f"Registró el pedido {order['pedido']} por chat",
                     "enlace": "#pedidos"} for order in created]
        activity += [{"hora": chat["bloqueo"]["desde"], "texto": f"Bloqueó la conversación {chat['id_corto']}",
                      "enlace": f"#conversaciones/{chat['id']}"}
                     for chat in today if chat["bloqueo"] and chat["bloqueo"]["tipo"] != "manual"]
        activity += [{"hora": chat["ultima_actividad"], "texto": f"El cliente {chat['id_corto']} pidió al tendero",
                      "enlace": f"#conversaciones/{chat['id']}"} for chat in today if chat["atencion"] == "requiere_humano"]
        return {"conversaciones": len(today), "mensajes": sum(chat["turnos"] for chat in today), "pedidos": len(created),
                "requieren_humano": sum(chat["atencion"] == "requiere_humano" for chat in chats),
                "atendidas_por_ti": sum(chat["atencion"] == "tendero" for chat in chats),
                "bloqueos": sum(chat["bloqueo"] is not None for chat in today),
                "incidencias": sum(chat["incidencias"] for chat in today),
                "actividad": sorted(activity, key=lambda item: item["hora"] or "", reverse=True)[:ACTIVITY_SHOWN]}

    def badges(self) -> dict:
        counts = day_summary(self.orders, self.today())["por_estado"]
        chats = self._chats()
        sold_out = sum(product["disponible"] <= 0 for product in self.inventory.products())
        unverified = sales_summary(self.orders, self.payments)["por_verificar"]["pagos"]
        return {"pedidos_activos": counts["pendiente"] + counts["confirmado"], "agotados": sold_out,
                "chats_atencion": sum(chat["atencion"] == "requiere_humano" for chat in chats),
                "bloqueos": sum(chat["bloqueo"] is not None and chat["bloqueo"]["tipo"] != "manual" for chat in chats),
                "pagos_por_verificar": unverified}

    def sales(self, params: dict) -> dict:
        filters = {key: params.get(key) or None for key in ("desde", "hasta", "metodo", "estado_pago", "estado_pedido")}
        return {"resumen": sales_summary(self.orders, self.payments, filters["desde"], filters["hasta"]),
                "transacciones": sales_history(self.orders, self.payments, **filters),
                "metodos": METHODS, "estados_pago": list(PAYMENT_STATUSES), "estados_pedido": list(STATUSES)}

    def supply(self) -> dict:
        return {"pedidos": self.purchasing.orders(), "recepciones": self.purchasing.receipts(),
                "proveedores": self.purchasing.suppliers()}

    def categories(self) -> dict:
        limits = self.admin.thresholds()
        own = [product for product in self.inventory.products() if product["sku"] in limits["productos"]]
        return {"categorias": self.admin.categories(), "alerta_general": limits["global"],
                "alertas": [{"sku": product["sku"], "nombre": product["nombre"], "variante": product["variante"],
                             "alerta": limits["productos"][product["sku"]]} for product in own]}

    def chats(self, params: dict) -> dict:
        state = params.get("estado") or None
        if state is not None and state not in ATTENTION_STATES:
            raise ValueError(f"El estado de atención es uno de: {', '.join(ATTENTION_STATES)}.")
        everything = self._chats()
        counts = {key: sum(chat["atencion"] == key for chat in everything) for key in ATTENTION_STATES}
        counts |= {"total": len(everything), "bloqueadas": sum(chat["bloqueo"] is not None for chat in everything)}
        query = params.get("q", "")[:MAX_QUERY]
        listed = everything if not query and state is None else conversations(
            self.sessions, self.orders, query=query, estado=state, limit=SUPERVISED)
        return {"conversaciones": listed, "conteo": counts}

    def chat(self, params: dict) -> dict:
        wanted = (params.get("id") or "").strip().lower()
        if not SESSION_ID.match(wanted):
            # Los pedidos y las ventas muestran la conversación abreviada: se busca la vigente que empiece así.
            if len(wanted) != SHORT_SESSION or ORDER_ID.match(wanted.upper()):
                raise ValueError("Envía el código de la conversación.")
            matches = [chat["id"] for chat in self._chats() if chat["id"].startswith(wanted)]
            if len(matches) != 1:
                raise ValueError("No encontré esa conversación; puede haber vencido.")
            wanted = matches[0]
        return {"conversacion": conversation(self.sessions, wanted, self.orders)}
