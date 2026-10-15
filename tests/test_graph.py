import pytest

from asistendero.graph import build_graph


def test_graph_passes_trimmed_input_to_model_and_returns_answer():
    received = []

    def fake_model(consulta):
        received.append(consulta)
        return "¿Qué diámetro necesitas?"

    result = build_graph(fake_model).invoke({"consulta": "  Necesito tubo PVC  "})

    assert received == ["Necesito tubo PVC"]
    assert result["respuesta"] == "¿Qué diámetro necesitas?"


def test_empty_input_never_calls_model():
    def forbidden_model(_consulta):
        raise AssertionError("No se debe llamar al modelo")

    with pytest.raises(ValueError, match="vacía"):
        build_graph(forbidden_model).invoke({"consulta": "  "})
