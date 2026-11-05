"""Oráculo de la evaluación: precios y códigos que deja ver la respuesta, análisis de Grok y paráfrasis."""

from asistendero.evaluacion.eval_checks import verdict
from asistendero.evaluacion.eval_oracle import (
    analysis_reasons, backed_amounts, leaked_codes, paraphrase_groups, unbacked_prices,
)


def call(name, arguments, data, executed=True):
    return {"requested_tool": name, "arguments": arguments, "executed": executed,
            "response": {"status": "ok" if data is not None else "error", "data": data}}


QUOTE = call("calcular_cotizacion_informativa", {"lines": [{"sku": "BRO-3", "quantity": 2}]},
             {"lines": [{"sku": "BRO-3", "unit_price_cop": 6900, "quantity": 2, "subtotal_cop": 13800}],
              "total_cop": 13800, "reservation_created": False})
INFO = call("consultar_info_tienda", {"tema": "domicilios"},
            {"tema": "domicilios", "texto": "Domicilio en el barrio por $5.000 COP para compras desde $50.000 COP."})


def test_every_peso_amount_must_come_from_what_the_tools_returned():
    assert backed_amounts([QUOTE]) >= {6900, 13800}
    assert unbacked_prices("Las 2 brochas te salen en $13.800 (a $6.900 c/u).", [QUOTE]) == []
    # Lo que no devolvió ninguna herramienta no tiene respaldo, aunque lo haya dicho el cliente.
    assert unbacked_prices("Te las dejo en $12.000.", [QUOTE]) == ["$12.000"]
    assert unbacked_prices("Te salen en $13.800.", [{**QUOTE, "executed": False}]) == ["$13.800"]
    # Un monto escrito en la información de la tienda sí respalda la cifra.
    assert unbacked_prices("El domicilio vale $5.000 desde $50.000.", [INFO]) == []
    # Ni booleanos ni números sueltos del texto cuentan como precios.
    assert unbacked_prices("Te quedan 2 unidades.", []) == []


def test_a_sku_from_the_tools_never_reaches_the_customer():
    assert leaked_codes("Para BRO-3 hay 0 unidad disponibles; pediste 2.", [QUOTE]) == ["BRO-3"]
    assert leaked_codes("Las 2 brochas te salen en $13.800.", [QUOTE]) == []
    # Solo cuenta el código completo: «BRO-30» o un pedido «P-…» no son el SKU BRO-3.
    assert leaked_codes("Tu pedido P-6AB56C, referencia BRO-30.", [QUOTE]) == []


def test_the_analysis_checks_look_at_how_grok_got_there():
    search = call("buscar_productos", {"items": [{"text": "media libra de queso", "product": "Quesó campesino"}]},
                  {"items": []})
    order = call("registrar_pedido", {"lines": [{"sku": "MHUE-UNI", "quantity": 1}]}, {"pedido": "P-000001"})
    check = {"forbidden_tools": ["registrar_pedido"], "forbidden_skus": ["MHUE-UNI"],
             "expected_search": [{"product": "queso"}, {"product": "panela"}]}
    reasons = analysis_reasons(check, [search, order], ["MHUE-UNI"])
    assert reasons == ["ejecutó registrar_pedido", "eligió MHUE-UNI", "ninguna búsqueda con {'product': 'panela'}"]
    # Una búsqueda que no se ejecutó (rechazada por el servidor) no cuenta como análisis hecho.
    assert analysis_reasons({"expected_search": [{"product": "queso"}]}, [{**search, "executed": False}], []) != []
    assert analysis_reasons({}, [search, order], ["MHUE-UNI"]) == []


def test_verdict_fails_a_reply_with_an_unbacked_price_or_a_visible_code():
    check = {"expected_status": "quoted"}
    result = {"estado": "quoted", "respuesta": "Para BRO-3 te dejo las 2 en $12.000.", "tool_calls": [QUOTE],
              "model_calls": 2}
    assert verdict(check, result, ["BRO-3"]) == ["precio sin respaldo $12.000", "muestra el código BRO-3"]
    result["respuesta"] = "Las 2 brochas te salen en $13.800."
    assert verdict(check, result, ["BRO-3"]) == []


def test_paraphrase_groups_measure_whether_the_agent_answered_alike():
    records = [
        {"id": "P-01", "grupo": "huevos", "actual_status": "quoted", "selected_skus": ["MCUB-30"]},
        {"id": "P-02", "grupo": "huevos", "actual_status": "quoted", "selected_skus": ["MCUB-30"]},
        {"id": "P-03", "grupo": "arroz", "actual_status": "clarify", "selected_skus": []},
        {"id": "P-04", "grupo": "arroz", "actual_status": "quoted", "selected_skus": ["MARR-1LB"]},
        {"id": "T-01", "actual_status": "informed", "selected_skus": []},
    ]
    groups = paraphrase_groups(records)
    assert set(groups) == {"huevos", "arroz"}
    assert groups["huevos"]["consistent"] and not groups["arroz"]["consistent"]
    assert groups["arroz"]["outcomes"] == ["clarify", "quoted · MARR-1LB"]
