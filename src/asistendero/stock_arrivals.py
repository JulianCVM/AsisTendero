"""Cierra las llegadas, fechas nuevas y pedidos al proveedor que juntó ``ProposalBuilder`` (``stock_operations.py``).

Se arman al final porque dependen de todo el mensaje: lo que llegó sin pedido entra como adicional a una llegada
que el mismo mensaje cargó a un pedido, y la fecha nueva de un pedido muestra lo que seguirá pendiente después de
lo que llegó en esta misma propuesta.
"""

from asistendero.purchasing import PurchasingError

RECEPTION_KEYS = ("sku", "nombre", "variante", "unidad", "stock_antes", "recibido", "stock_despues", "pendiente",
                  "adicional", "cantidad_adicional")


def reception_lines(preview: dict) -> list[dict]:
    """Las líneas de una recepción (real o vista previa) con solo lo que muestra la propuesta; sin costos."""
    return [{key: line[key] for key in RECEPTION_KEYS} for line in preview["lineas"]]


def _attach_loose(builder) -> None:
    """Lo que llegó sin pedido ni proveedor va a la primera llegada del mensaje («el proveedor mandó de más»)."""
    for operation, product, quantity in builder.loose:
        name = f"{product.name} {product.variant}"
        target = next((item for key, item in builder.arrivals.items() if key[0] == "oc"),
                      next(iter(builder.arrivals.values()), None))
        if target is None:
            builder._fail(operation, f"¿Quién trajo {name}? No está en ningún pedido abierto; dime el proveedor "
                                     "para registrar la llegada.")
        elif builder._claim("stock", product.sku, operation, name):
            target["lineas"].append({"sku": product.sku, "cantidad": quantity})


def arrival_operations(builder) -> list[dict]:
    """Una operación por llegada con su vista previa; si la recepción no se puede registrar, queda no aplicable."""
    _attach_loose(builder)
    operations = []
    for arrival in builder.arrivals.values():
        title = (f"Llegada del pedido {arrival['oc']} · {arrival['proveedor']}" if arrival["oc"]
                 else f"Llegada sin pedido · {arrival['proveedor']}")
        operation = {"tipo": "recepcion", "titulo": title, "aplicable": False, "oc": arrival["oc"],
                     "proveedor": arrival["proveedor"], "lineas": []}
        try:
            preview = builder.purchasing.receive(None if arrival["oc"] else arrival["proveedor"], arrival["lineas"],
                                                 oc=arrival["oc"], nota=builder.origin, apply=False)
        except PurchasingError as error:
            builder.warnings.append(f"{title}: {error}")
        else:
            operation.update(aplicable=True, lineas=reception_lines(preview))
        operations.append(operation)
    return operations


def _received(arrivals: list[dict], oc: str, sku: str) -> int:
    return sum(line["recibido"] for arrival in arrivals if arrival["aplicable"] and arrival["oc"] == oc
               for line in arrival["lineas"] if line["sku"] == sku)


def move_operations(builder, arrivals: list[dict]) -> list[dict]:
    """Fecha nueva por pedido. La fecha es de todo el pedido: se listan todas sus líneas que seguirán pendientes."""
    operations = []
    for oc, move in builder.moves.items():
        order = move["order"]
        if order["fecha_estimada"] == move["fecha_nueva"]:
            builder.warnings.append(f"El pedido {oc} ya está para el {move['fecha_nueva']}; no hay nada que cambiar.")
            continue
        lines = []
        for line in order["lineas"]:
            left = line["pendiente"] - _received(arrivals, oc, line["sku"])
            if left > 0:
                lines.append({"sku": line["sku"], "nombre": line["nombre"], "variante": line["variante"],
                              "unidad": line["unidad"], "pendiente": left})
        if not lines:
            builder.warnings.append(f"El pedido {oc} queda completo con lo que llegó; no hay entrega que reprogramar.")
            continue
        for sku, said in move["dichos"].items():
            line = next((item for item in lines if item["sku"] == sku), None)
            if line and isinstance(said, int) and said > line["pendiente"]:
                builder.warnings.append(f"El pedido {oc} tiene {line['pendiente']} pendientes de {line['nombre']} "
                                        f"{line['variante']} y dijiste {said}; si llega de más, regístralo al llegar.")
        others = [f"{line['nombre']} {line['variante']}" for line in lines if line["sku"] not in move["dichos"]]
        if others:
            builder.warnings.append(f"La fecha nueva es de todo el pedido {oc}; también mueve: {', '.join(others)}.")
        operations.append({"tipo": "programar_entrega", "titulo": f"Nueva fecha del pedido {oc}", "aplicable": True,
                           "oc": oc, "proveedor": order["proveedor"], "fecha_antes": order["fecha_estimada"],
                           "fecha_nueva": move["fecha_nueva"], "lineas": lines})
    return operations


def purchase_operations(builder) -> list[dict]:
    return [{"tipo": "pedido_proveedor", "titulo": f"Pedido a {group['proveedor']}", "aplicable": True,
             "proveedor": group["proveedor"], "fecha_estimada": group["fecha_estimada"], "lineas": group["lineas"]}
            for group in builder.purchases.values() if group["lineas"]]
