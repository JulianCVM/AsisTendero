"""Lo que cambia el panel del tendero: cada ruta POST de ``tendero.py`` valida su cuerpo y llama al módulo dueño.

Cada ruta acepta solo las claves que conoce: una clave de más se rechaza en vez de ignorarse, así un error del panel
no pasa en silencio. Precio y stock los escriben solo ``inventory.py`` (directo o a través de ``purchasing.py``) y
el asistente de bodega, y este solo cuando el tendero confirma su propuesta.
"""

from asistendero import handoff
from asistendero.sessions import SESSION_ID


def _body(body: dict, required: set[str], optional: set[str] = frozenset()) -> dict:
    missing, extra = required - set(body), set(body) - required - optional
    if missing or extra:
        names = ", ".join(sorted(required)) + (f" (y opcionalmente {', '.join(sorted(optional))})" if optional else "")
        raise ValueError(f"Envía solo: {names}.")
    return body


def _session(body: dict) -> str:
    session_id = body.get("sesion")
    if not isinstance(session_id, str) or not SESSION_ID.match(session_id):
        raise ValueError("Envía el código completo de la conversación.")
    return session_id


class PanelActions:
    def __init__(self, server):
        self.server = server

    def run(self, path: str, body: dict) -> dict | None:
        action = ROUTES.get(path)
        return None if action is None else action(self, body)

    def update_product(self, body: dict) -> dict:
        sku = body.pop("sku", None)
        if not isinstance(sku, str):
            raise ValueError("Falta el SKU.")
        # La alerta es del tendero, no del producto: vive en stock_thresholds y no toca el catálogo del asistente.
        if "alerta" in body:
            self.server.admin.set_threshold(sku, body.pop("alerta"))
        if body:
            return {"producto": self.server.inventory.update(sku, body)}
        return {"sku": sku}

    def new_product(self, body: dict) -> dict:
        return {"producto": self.server.inventory.add(body)}

    def order(self, body: dict, deliver: bool) -> dict:
        order_id = _body(body, {"pedido"})["pedido"]
        if not isinstance(order_id, str):
            raise ValueError("Envía solo el código del pedido.")
        orders = self.server.orders
        return {"pedido": orders.deliver(order_id) if deliver else orders.cancel(order_id, by="tendero")}

    def payment(self, body: dict) -> dict:
        body = _body(body, {"pedido", "metodo", "estado"}, {"referencia", "fuente"})
        return {"pago": self.server.payments.register(body["pedido"], body["metodo"], body["estado"],
                                                      body.get("referencia", ""), body.get("fuente"), actor="tendero")}

    def purchase(self, body: dict) -> dict:
        body = _body(body, {"proveedor", "lineas"}, {"fecha_estimada", "nota"})
        return {"pedido": self.server.purchasing.create_order(body["proveedor"], body["lineas"],
                                                              body.get("fecha_estimada"), body.get("nota", ""))}

    def reschedule(self, body: dict) -> dict:
        body = _body(body, {"oc", "fecha_estimada"}, {"motivo"})
        return {"pedido": self.server.purchasing.reschedule(body["oc"], body["fecha_estimada"], body.get("motivo", ""))}

    def cancel_purchase(self, body: dict) -> dict:
        body = _body(body, {"oc", "motivo"})
        return {"pedido": self.server.purchasing.cancel_order(body["oc"], body["motivo"])}

    def receipt(self, body: dict) -> dict:
        body = _body(body, {"lineas", "aplicar"}, {"proveedor", "oc", "nota"})
        if not isinstance(body["aplicar"], bool):
            raise ValueError("«aplicar» es true para guardar o false para ver la vista previa.")
        return self.server.purchasing.receive(body.get("proveedor"), body["lineas"], body.get("oc") or None,
                                              body.get("nota", ""), apply=body["aplicar"])

    def category(self, body: dict, action: str) -> dict:
        admin = self.server.admin
        if action == "crear":
            result = admin.create(_body(body, {"nombre"})["nombre"])
        elif action == "renombrar":
            body = _body(body, {"nombre", "nuevo"})
            result = admin.rename(body["nombre"], body["nuevo"])
        elif action == "mover":
            body = _body(body, {"nombre", "posicion"})
            result = admin.move(body["nombre"], body["posicion"])
        else:
            result = admin.delete(_body(body, {"nombre"})["nombre"])
        return {"categorias": result}

    def thresholds(self, body: dict) -> dict:
        if "general" in body:
            return self.server.admin.set_global(_body(body, {"general"})["general"])
        body = _body(body, {"sku", "alerta"})
        return self.server.admin.set_threshold(body["sku"], body["alerta"])

    def attention(self, body: dict, action: str) -> dict:
        store = self.server.sessions
        if action == "responder":
            session_id = _session(_body(body, {"sesion", "texto"}))
            return handoff.staff_reply(store, session_id, body["texto"])
        if action == "bloquear":
            session_id = _session(_body(body, {"sesion", "motivo"}))
            return {"sesion": session_id,
                    "pedidos_cancelados": handoff.ban_manually(store, session_id, body["motivo"], self.server.orders)}
        change = {"tomar": handoff.take_over, "devolver": handoff.release, "finalizar": handoff.finish}[action]
        return change(store, _session(_body(body, {"sesion"})))

    def unban(self, body: dict) -> dict:
        session_id = _session(_body(body, {"sesion"}))
        if not self.server.sessions.unban(session_id):
            raise ValueError("Esa conversación no está bloqueada.")
        return {"sesion": session_id}

    def assistant(self, body: dict, action: str) -> dict:
        assistant = self.server.assistant
        if action == "interpretar":
            return {"propuesta": assistant.propose(_body(body, {"texto"})["texto"])}
        proposal_id = _body(body, {"id"})["id"]
        if not isinstance(proposal_id, str):
            raise ValueError("Envía el código de la propuesta.")
        return assistant.apply(proposal_id) if action == "aplicar" else assistant.discard(proposal_id)


ROUTES = {
    "/api/inventario/actualizar": PanelActions.update_product,
    "/api/inventario/nuevo": PanelActions.new_product,
    "/api/pedidos/entregar": lambda self, body: self.order(body, deliver=True),
    "/api/pedidos/cancelar": lambda self, body: self.order(body, deliver=False),
    "/api/pagos/registrar": PanelActions.payment,
    "/api/abastecimiento/pedido": PanelActions.purchase,
    "/api/abastecimiento/reprogramar": PanelActions.reschedule,
    "/api/abastecimiento/cancelar": PanelActions.cancel_purchase,
    "/api/abastecimiento/recepcion": PanelActions.receipt,
    "/api/alertas": PanelActions.thresholds,
    "/api/bloqueos/levantar": PanelActions.unban,
    **{f"/api/categorias/{name}": (lambda name: lambda self, body: self.category(body, name))(name)
       for name in ("crear", "renombrar", "mover", "borrar")},
    **{f"/api/conversaciones/{name}": (lambda name: lambda self, body: self.attention(body, name))(name)
       for name in ("tomar", "devolver", "finalizar", "responder", "bloquear")},
    **{f"/api/asistente/{name}": (lambda name: lambda self, body: self.assistant(body, name))(name)
       for name in ("interpretar", "aplicar", "descartar")},
}
