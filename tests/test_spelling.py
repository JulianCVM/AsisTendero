"""Mensajes con mala ortografía o lenguaje de chat: se entienden sin aflojar lo que el cliente debe decir."""

import pytest

from asistendero.catalog import MockCatalog
from asistendero.executor import catalog_executor
from asistendero.graph import build_graph
from asistendero.grok import Decision
from asistendero.seed import create_mock_db
from asistendero.spelling import heard_as, sound_key


PVC_HALF = {"text": "tubo PVC de 1/2 para agua", "product": "tubo", "material": "PVC", "measure": "1/2 pulgada", "use": "agua"}


def tool(name, **arguments):
    return Decision("call_tool", "productos", name, arguments, "")


class Script:
    def __init__(self, *steps):
        self.steps = list(steps)

    def __call__(self, message, observations, remaining, context=None):
        return self.steps.pop(0)


@pytest.fixture
def executor(tmp_path):
    return catalog_executor(MockCatalog(create_mock_db(tmp_path / "catalog.sqlite3")))


@pytest.mark.parametrize(("said", "extracted", "heard"), [
    ("tuvo pbc de 1/2 pa l agua", "tubo PVC agua", "tubo pvc de 1/2 para l agua"),
    ("2 vultos de sement gris", "cemento gris bulto", "2 bulto de cemento gris"),
    ("un bultico de cemnto", "cemento bulto", "un bulto de cemento"),
    ("una yave de paso", "llave paso", "una llave de paso"),
])
def test_words_that_sound_like_what_grok_extracted_count_as_said(said, extracted, heard):
    assert heard_as(said, extracted) == heard


@pytest.mark.parametrize(("said", "extracted"), [
    ("piso", "pino"),            # palabras cortas distintas: no se confunden
    ("tubo de 3/4", "1/2"),      # los números nunca se corrigen
    ("cable negro", "cable gris"),
    ("pvc", "cobre"),
])
def test_different_words_and_numbers_are_never_rewritten(said, extracted):
    assert heard_as(said, extracted) == said


def test_sound_key_follows_colombian_spanish():
    assert sound_key("vulto") == sound_key("bulto")
    assert sound_key("sierra") == sound_key("cierra")
    assert sound_key("hacha") == sound_key("acha")
    assert sound_key("pino") != sound_key("piso")


def test_misspelled_order_is_quoted_when_grok_understood_it(executor):
    # Sin leer el mensaje como suena, «tuvo pbc» no respaldaba material ni producto y no se podía cotizar.
    planner = Script(tool("buscar_productos", items=[PVC_HALF]),
                     tool("calcular_cotizacion_informativa", lines=[{"sku": "PVC-050", "quantity": 3}]),
                     Decision("respond", "productos", None, None, ""))
    result = build_graph(executor, planner).invoke({"consulta": "nesesito 3 metros de tuvo pbc de 1/2 pa l agua"})
    assert result["estado"] == "quoted"
    assert "Total informativo: $25.500 COP" in result["respuesta"]


def test_misspelling_never_fills_in_what_the_customer_did_not_say(executor):
    # «2 vultos de sement gris» no dice 25 ni 50 kg: se pregunta aunque Grok proponga el de 50 kg.
    planner = Script(tool("buscar_productos", items=[{"text": "cemento gris bulto de 50 kg", "product": "cemento",
                                                      "color": "gris", "presentation": "bulto", "measure": "50 kg"}]),
                     tool("calcular_cotizacion_informativa", lines=[{"sku": "CEM-050", "quantity": 2}]),
                     Decision("respond", "productos", None, None, ""))
    result = build_graph(executor, planner).invoke({"consulta": "2 vultos de sement gris"})
    assert result["tool_calls"][0]["arguments"]["items"][0].get("measure") is None
    assert result["tool_calls"][1]["response"]["error"]["code"] == "SKU_NOT_GROUNDED"
    assert result["estado"] == "clarify" and "$" not in result["respuesta"]
