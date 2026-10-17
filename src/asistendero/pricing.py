"""Costo visible del modelo; la pasarela del reto puede tener otra facturación."""

from decimal import Decimal


USD_TICKS = Decimal(10_000_000_000)
MILLION = Decimal(1_000_000)
PRICING_URL = "https://docs.x.ai/developers/pricing"

# USD por millón de tokens (entrada, entrada en caché, salida).
# Tarifas públicas globales consultadas el 17-10-2026; no son tarifas confirmadas de Platica.
PUBLIC_RATES = {
    "grok-4.20-0309-non-reasoning": (("1.25", "0.20", "2.50"), ("2.50", "0.40", "5.00")),
    "grok-4.20-0309-reasoning": (("1.25", "0.20", "2.50"), ("2.50", "0.40", "5.00")),
    "grok-4.3": (("1.25", "0.20", "2.50"), ("2.50", "0.40", "5.00")),
    "grok-4.5": (("2.00", "0.30", "6.00"), ("4.00", "0.60", "12.00")),
    "grok-4.6": (("2.00", "0.50", "6.00"), ("4.00", "1.00", "12.00")),
    "grok-4.7": (("2.00", "0.50", "6.00"), ("4.00", "1.00", "12.00")),
}


def _valid_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def call_cost(
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    cached_input_tokens: int | None = None,
    reported_cost_usd_ticks: int | None = None,
) -> dict | None:
    """Prefiere costo informado por API; si falta, calcula referencia pública xAI."""
    if _valid_count(reported_cost_usd_ticks):
        return {
            "usd": format(Decimal(reported_cost_usd_ticks) / USD_TICKS, ".10f"),
            "basis": "api_reported",
            "model": model,
        }
    if model not in PUBLIC_RATES or not _valid_count(input_tokens) or not _valid_count(output_tokens):
        return None
    if cached_input_tokens is not None and (
        not _valid_count(cached_input_tokens) or cached_input_tokens > input_tokens
    ):
        return None
    cached = cached_input_tokens or 0
    short_rates, long_rates = PUBLIC_RATES[model]
    input_rate, cached_rate, output_rate = (
        long_rates if input_tokens >= 200_000 else short_rates
    )
    usd = (
        Decimal(input_tokens - cached) * Decimal(input_rate)
        + Decimal(cached) * Decimal(cached_rate)
        + Decimal(output_tokens) * Decimal(output_rate)
    ) / MILLION
    return {
        "usd": format(usd, ".10f"),
        "basis": "xai_public_estimate",
        "model": model,
        "cached_tokens_known": cached_input_tokens is not None,
        "pricing_url": PRICING_URL,
    }


def run_cost(costs: list[dict | None]) -> dict | None:
    """Una ejecución solo tiene total si se conoce el costo de todas sus llamadas."""
    if not costs or any(cost is None for cost in costs):
        return None
    bases = {cost["basis"] for cost in costs if cost is not None}
    return {
        "usd": format(sum((Decimal(cost["usd"]) for cost in costs if cost is not None), Decimal(0)), ".10f"),
        "basis": bases.pop() if len(bases) == 1 else "mixed",
        "calls": len(costs),
    }
