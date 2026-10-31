from decimal import Decimal
from types import SimpleNamespace

from asistendero.agente.modelo import grok
from asistendero.observabilidad.pricing import call_cost, run_cost


def test_cost_prefers_api_reported_ticks_and_sums_two_calls():
    first = call_cost("grok-4.20-0309-non-reasoning", 400, 50, 0, 6_250_000)
    second = call_cost("grok-4.20-0309-non-reasoning", 700, 80, 0, 9_500_000)

    assert first["basis"] == "api_reported"
    assert Decimal(first["usd"]) == Decimal("0.000625")
    assert Decimal(run_cost([first, second])["usd"]) == Decimal("0.001575")


def test_public_estimate_counts_cached_tokens_and_missing_usage_is_not_zero():
    cost = call_cost("grok-4.20-0309-non-reasoning", 1000, 200, 400)

    assert cost["basis"] == "xai_public_estimate"
    assert Decimal(cost["usd"]) == Decimal("0.00133")
    assert call_cost("modelo-desconocido", 1000, 200) is None
    assert run_cost([cost, None]) is None


def test_grok_completion_reads_usage_from_api(monkeypatch):
    usage = SimpleNamespace(
        prompt_tokens=1000, completion_tokens=200,
        prompt_tokens_details=SimpleNamespace(cached_tokens=400),
        cost_in_usd_ticks=13_300_000,
    )
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}'))],
        model="grok-4.20-0309-non-reasoning", usage=usage,
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: response)))
    monkeypatch.setenv("GROK_API_KEY", "clave-falsa")
    monkeypatch.setattr(grok, "OpenAI", lambda **_: client)

    assert grok._complete("instrucciones", {"mensaje": "hola"}) == (
        '{"ok":true}', "grok-4.20-0309-non-reasoning", 1000, 200, 400, 13_300_000,
    )


def test_truststore_is_optional_but_a_failure_injecting_it_is_not_hidden():
    # En un proceso aparte: recargar grok aquí duplicaría ModelError para el resto de la suite.
    import subprocess
    import sys

    def import_grok(setup: str) -> subprocess.CompletedProcess:
        code = f"import sys, types\n{setup}\nimport asistendero.agente.modelo.grok\n"
        return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)

    assert import_grok("sys.modules['truststore'] = None").returncode == 0
    broken = import_grok(
        "fake = types.ModuleType('truststore')\n"
        "def inject_into_ssl():\n    raise RuntimeError('almacén de certificados roto')\n"
        "fake.inject_into_ssl = inject_into_ssl\nsys.modules['truststore'] = fake"
    )
    assert broken.returncode != 0 and "almacén de certificados roto" in broken.stderr
