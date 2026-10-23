"""Fixtures compartidas entre archivos de prueba."""

import pytest


@pytest.fixture
def without_injection_detector(monkeypatch):
    """Apaga el detector de inyecciones para probar las barreras de más adentro.

    El detector bloquea antes de Grok los ataques que reconoce; uno que no reconozca debe seguir sin poder cambiar
    precios, existencias ni pedidos. Las pruebas que usan esto comprueban esa segunda línea con el mismo ataque.
    """
    monkeypatch.setattr("asistendero.graph.detect_injection", lambda *_args, **_kwargs: None)
