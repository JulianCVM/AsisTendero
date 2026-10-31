"""Bandeja de Hoy: lo que el tendero tiene que hacer, en una sola lista y de lo más urgente a lo menos.

Hoy mezclaba nueve bloques (cifras, avisos, cola de pedidos, plata del día, asistente, más vendidos, mercancía en
camino y por surtir), repetía cifras y no decía qué hacer primero. La bandeja junta solo lo accionable con un orden
fijo, que sale del servidor para que la pantalla no lo decida:

1. ``urgente``: un cliente pide hablar con el tendero; un pedido espera el «sí» y su apartado está corriendo (el que
   vence antes va primero).
2. ``revisar``: un pedido con algo pendiente del tendero (comprobante por verificar, venta sin cobrar, recogida
   atrasada).
3. ``hoy``: recogidas confirmadas para hoy o sin hora acordada, por hora.
4. ``aviso``: pedidos al proveedor atrasados y, en una sola línea, los productos agotados o por surtir.

Un pedido aparece una vez, con todos sus motivos. Una recogida de otro día no entra: está en Pedidos.
"""

PRIORITIES = ("urgente", "revisar", "hoy", "aviso")
MAX_ITEMS = 30


def _count(amount: int, one: str, many: str) -> str:
    return f"{amount} {one if amount == 1 else many}"


def _order_item(order: dict, priority: str, title: str, when: str | None) -> dict:
    return {"tipo": "pedido", "prioridad": priority, "titulo": title, "detalle": list(order["revisar"]),
            "enlace": "#pedidos", "hora": when, "pedido": order}


def work_queue(board: list[dict], chats: list[dict], purchases: list[dict], sold_out: int, low: int,
               today: str) -> list[dict]:
    """Lo accionable de hoy en orden: prioridad y, dentro de ella, la hora (lo que vence o pasa antes, primero)."""
    items = [{"tipo": "chat", "prioridad": "urgente", "titulo": f"El cliente {chat['id_corto']} pide hablar contigo",
              "detalle": [], "enlace": f"#conversaciones/{chat['id']}", "hora": chat["ultima_actividad"], "pedido": None}
             for chat in chats if chat["atencion"] == "requiere_humano"]
    for order in board:
        if order["estado"] == "pendiente":
            items.append(_order_item(order, "urgente", f"{order['pedido']} espera el «sí» del cliente",
                                     order["aparta_hasta"]))
        elif order["revisar"] and order["estado"] in ("confirmado", "entregado"):
            items.append(_order_item(order, "revisar", f"{order['pedido']}: {order['revisar'][0]}", order["creado"]))
        elif order["estado"] == "confirmado" and (order["recogida"] is None or order["recogida"].startswith(today)):
            title = (f"{order['pedido']} pasa a recoger a las {order['recogida'][11:16]}" if order["recogida"]
                     else f"{order['pedido']} está confirmado, sin hora de recogida")
            items.append(_order_item(order, "hoy", title, order["recogida"] or order["aparta_hasta"]))
    items += [{"tipo": "proveedor", "prioridad": "aviso", "titulo": f"{order['oc']} de {order['proveedor']} está atrasado",
               "detalle": [f"{order['pendiente']} unidades por llegar"], "enlace": "#inventario/abastecimiento",
               "hora": order["fecha_estimada"], "pedido": None} for order in purchases if order["atrasada"]]
    if sold_out or low:
        out, short = _count(sold_out, "producto agotado", "productos agotados"), _count(low, "por surtir", "por surtir")
        items.append({"tipo": "agotados", "prioridad": "aviso",
                      "titulo": out if sold_out else _count(low, "producto por surtir", "productos por surtir"),
                      "detalle": [f"y {short}"] if sold_out and low else [],
                      "enlace": "#inventario", "filtro": "agotado" if sold_out else "bajo", "hora": None, "pedido": None})
    items.sort(key=lambda item: (PRIORITIES.index(item["prioridad"]), item["hora"] or "9999"))
    return items[:MAX_ITEMS]
