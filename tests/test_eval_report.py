from asistendero.evaluacion.eval_report import comparison_markdown, summarize


def call(input_tokens, cached, usd="0.001000"):
    return {"type": "model_response", "details": {"input_tokens": input_tokens, "output_tokens": 40,
                                                  "cached_input_tokens": cached, "cost": {"usd": usd}}}


def report(cases):
    return {"cases": cases, "model": "grok-4.20-0309-non-reasoning", "prompt_version": "prueba", "commit": "abc1234",
            "passed": sum(case["passed"] for case in cases), "total": len(cases), "model_calls": 4, "elapsed_ms": 100}


def case(case_id, **fields):
    return {"id": case_id, "passed": True, "model_calls": 1, "elapsed_ms": 10, "cost": {"usd": "0.002"},
            "input_tokens": 0, "cached_input_tokens": 0, **fields}


def test_a_call_counts_as_cached_only_when_the_fixed_prompt_came_from_the_cache():
    # Como en la corrida del 24-10: casi todas reutilizan los 2.432 tokens del prompt fijo; la que cayó en un
    # servidor frío solo trae el primer bloque de 128 y no puede contar como acierto.
    cases = [
        case("A", events=[call(2800, 2432, "0.001000"), {"type": "route", "details": {}}]),
        case("B", turns=[{"events": [call(2900, 2560, "0.001200")]}, {"events": [call(2800, 128, "0.003000")]}]),
        case("C", clients=[{"passed": True, "model_calls": 1, "elapsed_ms": 10, "cost": {"usd": "0.0008"},
                            "turns": [{"events": [call(2700, 2432, "0.000800")]}]}]),
        # Un fallo de Grok no trae uso: no es una llamada sin caché ni cuesta cero.
        case("D", events=[{"type": "model_response", "details": {"error": {"code": "MODEL_TIMEOUT"}, "cost": None}}]),
    ]
    summary = summarize(report(cases))

    assert summary["calls_with_usage"] == 4
    assert summary["cache_covered_calls"] == 3 and summary["cache_covered_percent"] == 75.0
    assert summary["cost_per_call_usd"] == "0.001500"


def test_comparison_marks_an_old_report_without_the_metric_as_missing_not_zero():
    old = report([case("A")])
    old["summary"] = {key: value for key, value in summarize(old).items()
                      if key not in {"calls_with_usage", "cache_covered_calls", "cache_covered_percent",
                                     "cost_per_call_usd"}}
    new = report([case("A", events=[call(2800, 2432)])])
    new["summary"] = summarize(new)

    header, _, old_row, new_row, *_ = comparison_markdown([old, new]).splitlines()
    position = header.split(" | ").index("% llamadas con caché")
    assert old_row.split(" | ")[position] == "—"
    assert new_row.split(" | ")[position] == "100.0 %"
    assert "0.0 %" not in old_row.split(" | ")[position]


def _grok(phase, action, usd, cached=2432):
    event = call(2800, cached, usd)
    event["details"].update(phase=phase, action=action, duration_ms=1000)
    if usd is None:
        event["details"]["cost"] = None
    return event


def test_the_cost_report_adds_up_by_operation_task_and_tool_and_never_counts_a_missing_cost_as_zero():
    from decimal import Decimal
    from asistendero.evaluacion.eval_costs import case_rows, cost_report_markdown, operation_rows, tool_rows

    search = {"requested_tool": "buscar_productos", "executed": True, "duration_ms": 12}
    rejected = {"requested_tool": "registrar_pedido", "executed": False, "duration_ms": 0}
    cases = [
        case("A", suite="mercado", negocio="mercado", model_calls=2, cost={"usd": "0.0020"}, tool_calls=[search],
             events=[_grok("interpret", "call_tool", "0.0009"), _grok("resolve", "respond", "0.0011")]),
        case("B", suite="flujos", model_calls=2, cost={"usd": "0.0030"},
             turns=[{"tool_calls": [search, rejected], "events": [_grok("interpret", "call_tool", "0.0012")]},
                    {"tool_calls": [], "events": [_grok("resolve", "respond", "0.0018")]}]),
        # Rechazado antes de Grok: cuesta cero. Una llamada sin costo informado no suma, pero se cuenta aparte.
        case("C", suite="inyeccion", model_calls=0, cost=None),
        case("D", suite="flujos", model_calls=1, cost=None, events=[_grok("interpret", "respond", None)]),
    ]
    full = report(cases)

    rows = {row["id"]: row for row in case_rows(full)}
    assert rows["B"]["mensajes"] == 2 and rows["B"]["herramientas"] == 1 and rows["B"]["usd"] == Decimal("0.0030")
    assert rows["C"]["usd"] == 0 and rows["D"]["usd"] is None
    operations = {group["operacion"]: group for group in operation_rows(full)}
    assert operations["Interpretar el mensaje y pedir una herramienta"]["usd"] == Decimal("0.0021")
    assert operations["Leer lo observado y redactar la respuesta"]["llamadas"] == 2
    unknown = operations["Interpretar el mensaje y responder sin herramientas"]
    assert unknown["llamadas"] == 1 and unknown["sin_costo"] == 1 and unknown["usd"] == 0
    tools = {group["herramienta"]: group for group in tool_rows(full)}
    assert (tools["buscar_productos"]["pedidas"], tools["registrar_pedido"]["ejecutadas"]) == (2, 0)

    markdown = cost_report_markdown(full)
    # Tres tareas con costo conocido (A, B y la C, que no llamó a Grok): 0,005 USD en total.
    assert "| Costo total | 0.005000 USD |" in markdown and "para 3 de 4 tareas" in markdown
    assert "| Costo medio por tarea | 0.001667 USD |" in markdown
    assert "| Proyección a 1.000 tareas con esta mezcla | 1.666667 USD |" in markdown
    assert "| D | flujos | ferreteria | 1 | 1 | 0 | 2800 (2432) | 40 | — |" in markdown
    assert "| Interpretar el mensaje y responder sin herramientas | 1 | 0.000000 | — |" in markdown


def test_the_vision_call_of_a_photo_is_its_own_operation_and_not_another_call():
    from asistendero.evaluacion.eval_costs import operation_rows

    vision = call(900, 0, "0.0004")
    vision["details"].update(phase="vision", duration_ms=1500)  # como lo emite tracing: sin «action»
    full = report([case("F", suite="fotos", events=[vision, _grok("interpret", "respond", "0.0010")])])
    operations = {group["operacion"]: group for group in operation_rows(full)}
    assert operations["Mirar la foto del cliente (visión)"]["llamadas"] == 1
    assert "Otra llamada" not in operations


def test_batches_of_one_run_add_up_and_never_mix_commits_dirty_trees_or_repeated_cases():
    import pytest
    from asistendero.evaluacion.eval_costs import cost_report_markdown, merged_report

    def batch(cases, **fields):
        return {**report(cases), "commit": "abc1234", "model": "grok-4.20-0309-non-reasoning", "src_dirty": False,
                "created_at": "2026-11-01T20:00:00", "prompt_versions": ["s4-conversacion-v12"],
                "passed": sum(item["passed"] for item in cases), "total": len(cases), **fields}

    first = batch([case("A", cost={"usd": "0.0020"}), case("B", cost={"usd": "0.0010"}, passed=False)])
    second = batch([case("M", negocio="mercado", cost={"usd": "0.0030"})], created_at="2026-11-01T19:00:00",
                   prompt_versions=["mercado-v1"])
    merged = merged_report([first, second])
    assert (merged["total"], merged["passed"], [item["id"] for item in merged["cases"]]) == (3, 2, ["A", "B", "M"])
    assert merged["created_at"] == "2026-11-01T19:00:00"
    assert merged["prompt_versions"] == ["mercado-v1", "s4-conversacion-v12"]
    assert "| Costo total | 0.006000 USD |" in cost_report_markdown(merged)

    # Lo que no es la misma corrida no se suma: otro commit, cambios sin commit o un caso medido dos veces.
    with pytest.raises(ValueError, match="commit"):
        merged_report([first, batch([case("M")], commit="def5678")])
    with pytest.raises(ValueError, match="cambios sin commit"):
        merged_report([first, batch([case("M")], src_dirty=True)])
    with pytest.raises(ValueError, match="repetidos.*A"):
        merged_report([first, batch([case("A")])])
