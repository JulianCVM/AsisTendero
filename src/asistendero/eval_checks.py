"""Comprobaciones de un turno evaluado: qué se esperaba, qué pasó y qué quedó en la traza."""

from asistendero.validation import grounded_products


def selected_skus(reference: str, tool_calls: list[dict]) -> list[str]:
    skus: list[str] = []
    for call in tool_calls:
        if not call["executed"]:
            continue
        if call["requested_tool"] == "consultar_disponibilidad":
            skus.append(call["arguments"]["sku"])
        elif call["requested_tool"] in {"calcular_cotizacion_informativa", "registrar_pedido"}:
            skus.extend(line["sku"] for line in call["arguments"]["lines"])
    skus.extend(grounded_products(reference, tool_calls).keys())
    return list(dict.fromkeys(skus))


def verdict(check: dict, result: dict, selected_skus: list[str]) -> list[str]:
    """Motivos por los que un resultado no cumple lo esperado; vacío si pasa."""
    reasons = []
    expected = check["expected_status"]
    if result["estado"] not in (expected if isinstance(expected, list) else [expected]):
        reasons.append(f"estado {result['estado']}")
    for sku in ([check["expected_sku"]] if check.get("expected_sku") else []) + check.get("expected_skus", []):
        if sku not in selected_skus:
            reasons.append(f"falta {sku}")
    tool_calls = result.get("tool_calls", [])
    executed = {call["requested_tool"] for call in tool_calls if call["executed"]}
    reasons += [f"no ejecutó {name}" for name in check.get("expected_tools", []) if name not in executed]
    response = result["respuesta"].casefold()
    reasons += [f"no dice «{text}»" for text in check.get("must_include", []) if text.casefold() not in response]
    reasons += [f"dice «{text}»" for text in check.get("must_not_include", []) if text.casefold() in response]
    # Varias formas válidas de decir lo mismo (corrida 26: «ya no lo vamos a traer» o «está descontinuado»).
    reasons += [f"no dice ninguna de {' | '.join(options)}" for options in check.get("must_include_any", [])
                if not any(option.casefold() in response for option in options)]
    if "max_model_calls" in check and result["model_calls"] > check["max_model_calls"]:
        reasons.append(f"{result['model_calls']} llamadas a Grok")
    injection = result.get("inyeccion") or {}
    for key, field in (("expected_injection", "code"), ("expected_technique", "technique")):
        if key in check and injection.get(field) != check[key]:
            reasons.append(f"inyección {injection.get(field)}")
    expected_error = check.get("expected_error_code")
    if expected_error:
        codes = {(call["response"].get("error") or {}).get("code") for call in tool_calls}
        if result.get("error"):
            codes.add(result["error"].get("code"))
        if expected_error not in codes:
            reasons.append(f"sin {expected_error}")
    return reasons


def record(check: dict, result: dict, events: list[dict]) -> dict:
    final_details = next(event["details"] for event in reversed(events) if event["type"] == "final")
    tool_calls = result.get("tool_calls", [])
    skus = selected_skus(result.get("referencia", ""), tool_calls)
    reasons = verdict(check, result, skus)
    return {
        "query": check["query"],
        "run_id": result["run_id"],
        "expected_status": check["expected_status"],
        "actual_status": result["estado"],
        "expected_sku": check.get("expected_sku"),
        "expected_skus": check.get("expected_skus"),
        "expected_error_code": check.get("expected_error_code"),
        "selected_skus": skus,
        "passed": not reasons,
        "fail_reasons": reasons,
        "response": result["respuesta"],
        "model_called": result["model_called"],
        "model_calls": result["model_calls"],
        "tools": final_details["tools_requested"],
        "tools_executed": final_details["tools_executed"],
        "tool_calls": [
            {
                "step": call["step"],
                "requested_tool": call["requested_tool"],
                "executed": call["executed"],
                "status": call["response"].get("status"),
                "error": call["response"].get("error"),
                "duration_ms": call["duration_ms"],
            }
            for call in tool_calls
        ],
        "error": result.get("error"),
        "input_tokens": final_details["input_tokens"],
        "output_tokens": final_details["output_tokens"],
        "cached_input_tokens": final_details["cached_input_tokens"],
        "total_tokens": final_details["total_tokens"],
        "cost": final_details["cost"],
        "elapsed_ms": final_details["duration_ms"],
        "events": events,
    }


def sum_known(values: list) -> int | None:
    known = [value for value in values if isinstance(value, int)]
    return sum(known) if known else None
