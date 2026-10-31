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
