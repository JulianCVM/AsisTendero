"""Suites ampliacion, mercado y parafrasis (31-10-2026) con un Grok guionizado.

Si un caso no pasa aquí, el fallo está en el caso o en el harness, no en el modelo: así la corrida real mide solo
lo que decide Grok. Los casos de la tienda de mercado corren con su catálogo, sus pedidos y su prompt.
"""

from datetime import datetime
import json
from pathlib import Path

import pytest

from asistendero.agente.modelo.grok import Decision
from asistendero.agente.modelo.prompt import BUSINESS_KIND
from asistendero.datos.seed import create_mock_db
from asistendero.evaluacion import evaluate
from asistendero.evaluacion.eval_sessions import SIM_START
from asistendero.tienda.catalogo.catalog import MockCatalog

SUITES = {"ampliacion", "mercado", "parafrasis"}
MODEL = "grok-4.20-0309-non-reasoning"
PVC = {"product": "tubo", "material": "PVC", "measure": "1/2 pulgada", "use": "agua"}
CUBETA = {"product": "huevo", "presentation": "cubeta"}


def call(name, **arguments):
    return Decision("call_tool", "productos", name, arguments, "", MODEL, 100, 20)


def finish(intent="productos"):
    return Decision("respond", intent, None, None, "", MODEL, 80, 15)


def search(*items):
    return call("buscar_productos", items=[{"text": text, **fields} for text, fields in items])


def quote(*lines):
    return call("calcular_cotizacion_informativa", lines=[{"sku": sku, "quantity": quantity} for sku, quantity in lines])


def register(*lines):
    return call("registrar_pedido", lines=[{"sku": sku, "quantity": quantity} for sku, quantity in lines])


def info(tema):
    return [call("consultar_info_tienda", tema=tema), finish("tienda")]


def _pending(context, state):
    return [order["pedido"] for order in context.get("pedidos") or [] if order["estado"] == state]


def confirm(context):
    return call("confirmar_pedido", pedido=_pending(context, "pendiente")[0])


def schedule(fecha, hora):
    return lambda context: call("agendar_recogida", pedido=_pending(context, "confirmado")[0], fecha=fecha, hora=hora)


def quoted(text, fields, sku, quantity):
    return [search((text, fields)), quote((sku, quantity)), finish()]


def found(text, **fields):
    return [search((text, fields)), finish()]


SCRIPTS = {
    # Ferretería ampliada
    "¿Tienen tabla de pino de 1 x 10?": found("tabla de pino de 1 x 10", product="tabla", material="pino",
                                              measure="1 x 10 pulgadas"),
    "¿tienen tabla de pino de 1 x 12?": found("tabla de pino de 1 x 12", product="tabla", material="pino",
                                              measure="1 x 12 pulgadas"),
    "necesito 4 tablas de pino": found("tablas de pino", product="tabla", material="pino"),
    "Me regala el precio de 2 cerraduras de sobreponer": quoted("cerradura de sobreponer", {"product": "cerradura"},
                                                                "CSO-STD", 2),
    "una chapa para el cajón del escritorio": found("chapa para cajón", product="chapa", use="cajón"),
    "3 clavijas de 3 patas": quoted("clavija de 3 patas", {"product": "clavija", "measure": "3 patas"}, "CLV-3P", 3),
    "necesito 5 clavijas de 3 patas": quoted("clavija de 3 patas", {"product": "clavija", "measure": "3 patas"}, "CLV-3P", 5),
    "Cuánto vale el barniz por galón": found("barniz por galón", product="barniz", presentation="galón"),
    "2 aerosoles negros": quoted("aerosol negro", {"product": "aerosol", "color": "negro"}, "AER-NEG", 2),
    "un tanque de agua de 1000 litros y un flotador de 1/2": [
        search(("tanque de agua de 1000 litros", {"product": "tanque", "measure": "1000 litros"}),
               ("flotador de 1/2", {"product": "flotador", "measure": "1/2 pulgada"})),
        quote(("TNQ-1000", 1), ("FLO-12", 1)), finish()],
    "¿venden escuadra de carpintero?": found("escuadra de carpintero", product="escuadra"),
    "protector para los oídos tipo copa": found("protector para oídos tipo copa", product="protector", use="oídos",
                                                presentation="tipo copa"),
    "un machete": found("machete", product="machete"),
    "necesito un machete de 24 pulgadas": quoted("machete de 24 pulgadas", {"product": "machete", "measure": "24 pulgadas"},
                                                 "MCH-24", 1),
    "fumigadora de espalda": found("fumigadora de espalda", product="fumigadora"),
    "polisombra, 10 metros": quoted("polisombra", {"product": "polisombra"}, "POL-80", 10),
    "¿la cerradura de sobreponer sirve para una puerta de vidrio?": found(
        "cerradura de sobreponer para puerta de vidrio", product="cerradura", use="puerta de vidrio"),
    "necesito masilla para tapar huecos en madera de cedro": found("masilla para madera de cedro", product="masilla",
                                                                   material="madera", color="cedro"),
    "tiene cincel?": found("cincel", product="cincel"),
    "¿tienen sensor de movimiento?": found("sensor de movimiento", product="sensor"),
    "me llevo 2": [quote(("SEN-TEC", 2)), finish()],
    "sí, confirmo": [confirm, finish("pedido")],
    # Tienda de mercado
    "¿A qué hora abren el domingo?": info("horario"),
    "¿hacen domicilios?": info("domicilios"),
    "¿reciben tarjeta?": info("medios_pago"),
    "¿me fía hasta el viernes? le pago el sábado": info("pedidos"),
    "necesito una cubeta de huevos": quoted("cubeta de huevos", CUBETA, "MCUB-30", 1),
    "deme una docena de huevos": quoted("docena de huevos", {"product": "huevo"}, "MHUE-UNI", 12),
    "me vende una media libra de queso campesino": quoted("media libra de queso campesino",
                                                          {"product": "queso", "presentation": "media libra"}, "MQUE-MLB", 1),
    "2 libras de papa criolla y una de tomate": [
        search(("papa criolla", {"product": "papa", "color": "criolla"}), ("tomate", {"product": "tomate"})),
        quote(("MPCR-LB", 2), ("MTOM-LB", 1)), finish()],
    "una libra y media de papa pastusa": found("papa pastusa", product="papa"),
    "¿tienen aceite de 500?": found("aceite de 500 ml", product="aceite", presentation="500 ml"),
    "3 bolsas de leche entera de 1 litro": quoted("leche entera de 1 litro", {"product": "leche", "presentation": "1 litro"},
                                                  "MLEC-1L", 3),
    "un paquete de pañales talla 1": found("pañales talla 1", product="pañales", measure="talla 1"),
    "¿el yogur de fresa tiene azúcar? es para mi mamá que es diabética": found("yogur de fresa", product="yogur"),
    "¿el queso campesino está fresco? ¿de cuándo es?": found("queso campesino", product="queso"),
    "¿me manda 2 bolsas de arroz de 1 libra a la casa?": quoted("arroz de 1 libra",
                                                                {"product": "arroz", "presentation": "1 libra"}, "MARR-1LB", 2),
    "¿cuánto vale la gaseosa de 1,5?": found("gaseosa de 1,5 litros", product="gaseosa", presentation="1,5 litros"),
    "dos bolsas de agua y un paquete de papas de limón": [
        search(("agua en bolsa", {"product": "agua", "presentation": "bolsa"}),
               ("papas fritas de limón", {"product": "papas fritas", "use": "limón"})),
        quote(("MAGB-600", 2), ("MPFR-LIM", 1)), finish()],
    "una panela": found("panela", product="panela"),
    "me vende 4 limones y 3 bananos": [
        search(("limones", {"product": "limón"}), ("bananos", {"product": "banano"})),
        quote(("MLIM-UNI", 4), ("MBAN-UNI", 3)), finish()],
    "¿venden cerveza o cigarrillos?": [search(("cerveza", {"product": "cerveza"}), ("cigarrillos", {"product": "cigarrillos"})),
                                       finish()],
    "¿qué venden?": [call("explorar_categoria"), finish()],
    "necesito aceite": found("aceite", product="aceite"),
    "¿me hace un descuentico si llevo 2 cubetas de huevos?": quoted("cubetas de huevos", CUBETA, "MCUB-30", 2),
    "quiero 3 latas de atún": found("latas de atún", product="atún"),
    "3 latas de atún en agua": quoted("atún en agua", {"product": "atún", "presentation": "en agua"}, "MATU-AGU", 3),
    "¿cuándo les llega la fécula de maíz?": found("fécula de maíz", product="fécula"),
    "¿cuándo vuelve a llegar la leche en polvo?": found("leche en polvo", product="leche", presentation="en polvo"),
    "Necesito 10 velas": found("velas", product="velas"),
    "media docena de huevos": quoted("huevos", {"product": "huevo"}, "MHUE-UNI", 6),
    "¿el concentrado de perro también sirve para gatos?": found("concentrado para perro", product="alimento para perro"),
    "Necesito 2 paquetes de pan tajado blanco": quoted("pan tajado blanco", {"product": "pan tajado", "color": "blanco"},
                                                       "MPTA-BLA", 2),
    "me los llevo": [register(("MPTA-BLA", 2)), finish("pedido")],
    "paso hoy a las 6 de la tarde": [schedule("2026-10-21", "18:00"), finish("pedido")],
    "2 bolsas de arroz de 1 libra": quoted("arroz de 1 libra", {"product": "arroz", "presentation": "1 libra"}, "MARR-1LB", 2),
    "anótemelo en el cuaderno que el viernes le pago": info("pedidos"),
    "¿tienen queso campesino?": found("queso campesino", product="queso"),
    "deme una libra": [quote(("MQUE-1LB", 1)), finish()],
    "¿qué yogures tienen?": found("yogur", product="yogur"),
    "el de melocotón, 2": [quote(("MYOG-MEL", 2)), finish()],
    "3 libras de tomate": quoted("tomate", {"product": "tomate"}, "MTOM-LB", 3),
    "agréguele un atado de cilantro": [search(("cilantro", {"product": "cilantro"})),
                                       quote(("MTOM-LB", 3), ("MCIL-ATA", 1)), finish()],
    "¿cuánto es todo?": [quote(("MTOM-LB", 3), ("MCIL-ATA", 1)), finish()],
    "una cubeta de huevos": quoted("cubeta de huevos", CUBETA, "MCUB-30", 1),
    "apártemela y me la manda con el domiciliario": [register(("MCUB-30", 1)), finish("pedido")],
    "¿hay papel higiénico de 4 rollos?": found("papel higiénico de 4 rollos", product="papel higiénico",
                                               presentation="4 rollos"),
    # Paráfrasis
    "Necesito 3 metros de tubo PVC de 1/2 para agua": quoted("tubo PVC de 1/2 para agua", PVC, "PVC-050", 3),
    "me regala 3 metros de tubería pvc de media pulgada pa agua": quoted("tubería PVC de 1/2 para agua", PVC, "PVC-050", 3),
    "cuánto me salen tres metros de tubo de PVC de 1/2 para el agua": quoted("tubo de PVC de 1/2 para agua", PVC, "PVC-050", 3),
    "un tanque de agua de 1000 litros": quoted("tanque de agua de 1000 litros", {"product": "tanque", "measure": "1000 litros"},
                                               "TNQ-1000", 1),
    "necesito un tanque plástico de 1.000 litros": quoted("tanque plástico de 1.000 litros",
                                                          {"product": "tanque", "measure": "1000 litros"}, "TNQ-1000", 1),
    "1 tanque para agua de mil litros": quoted("tanque para agua de 1000 litros", {"product": "tanque", "measure": "1000 litros"},
                                               "TNQ-1000", 1),
    "2 brochas de 3 pulgadas": quoted("brochas de 3 pulgadas", {"product": "brocha", "measure": "3 pulgadas"}, "BRO-3", 2),
    "necesito dos brochas de 3 pulgadas": quoted("brochas de 3 pulgadas", {"product": "brocha", "measure": "3 pulgadas"},
                                                 "BRO-3", 2),
    "me vende 2 brochas de tres pulgadas": quoted("brochas de 3 pulgadas", {"product": "brocha", "measure": "3 pulgadas"},
                                                  "BRO-3", 2),
    "¿a qué hora abren?": info("horario"),
    "¿hasta qué hora atienden?": info("horario"),
    "¿cuál es el horario de atención?": info("horario"),
    "me vende un panal de huevos": quoted("panal de huevos", {"product": "huevo", "presentation": "panal"}, "MCUB-30", 1),
    "una cubeta de huevos AA por favor": quoted("cubeta de huevos AA", CUBETA, "MCUB-30", 1),
    "una docena de huevos": quoted("docena de huevos", {"product": "huevo"}, "MHUE-UNI", 12),
    "12 huevos": quoted("huevos", {"product": "huevo"}, "MHUE-UNI", 12),
    "deme doce huevos": quoted("huevos", {"product": "huevo"}, "MHUE-UNI", 12),
    "¿me fía?": info("pedidos"),
    "anótemelo y le pago el viernes": info("pedidos"),
    "¿me puede dar fiado hasta la quincena?": info("pedidos"),
    "¿me lo pueden llevar a la casa?": info("domicilios"),
    "¿tienen servicio a domicilio?": info("domicilios"),
}


class ScriptedGrok:
    """El paso sale del mensaje y de cuántas observaciones lleva el turno; anota con qué negocio se le llamó."""

    def __init__(self):
        self.kinds = {}

    def __call__(self, message, observations, remaining, context=None):
        if message not in SCRIPTS:
            pytest.fail(f"Sin guion para: {message!r}")
        self.kinds[message] = BUSINESS_KIND.get()
        steps = SCRIPTS[message]
        step = steps[min(len(observations), len(steps) - 1)]
        return step(context or {}) if callable(step) else step


def _cases():
    cases = json.loads(Path("evaluation/cases.json").read_text(encoding="utf-8"))
    return [case for case in cases if case["suite"] in SUITES]


def test_every_new_case_passes_with_a_scripted_grok(tmp_path):
    cases = _cases()
    assert {case["suite"] for case in cases} == SUITES and len(cases) >= 70
    catalog = MockCatalog(create_mock_db(tmp_path / "catalog.sqlite3"))
    planner = ScriptedGrok()
    report = evaluate.evaluate_cases(cases, catalog=catalog, planner=planner, clock=lambda: SIM_START)
    failed = {record["id"]: (record["fail_reasons"], record["response"][:200]) for record in report["cases"]
              if not record["passed"]}
    assert failed == {}
    # Cada caso corrió con el negocio y el prompt que dice: ningún mensaje de la tienda de mercado vio la ferretería.
    market = {turn["query"] for case in cases if case.get("negocio") == "mercado" for turn in case.get("turns", [case])}
    assert {planner.kinds[query] for query in market if query in planner.kinds} == {"mercado"}
    assert {record["prompt_version"] for record in report["cases"]} == {"s4-conversacion-v12", "mercado-v1"}
    assert report["prompt_versions"] == ["mercado-v1", "s4-conversacion-v12"]
    # Un guion correcto responde igual a las tres formas de pedir lo mismo.
    groups = report["summary"]["paraphrase_groups"]
    assert len(groups) == 8 and all(group["consistent"] for group in groups.values())


def test_a_market_case_never_sees_the_hardware_catalog(tmp_path):
    catalog = MockCatalog(create_mock_db(tmp_path / "catalog.sqlite3"))
    case = {"id": "X-01", "suite": "mercado", "negocio": "mercado", "query": "Necesito 3 metros de tubo PVC de 1/2 para agua",
            "expected_status": "quoted"}
    report = evaluate.evaluate_cases([case], catalog=catalog, planner=ScriptedGrok(), clock=lambda: SIM_START)
    record = report["cases"][0]
    # El guion pide el tubo de la ferretería; en la tienda de mercado ese SKU no existe y no se cotiza.
    assert not record["passed"] and "PVC-050" not in record["selected_skus"]
    assert "$25.500" not in record["response"] and record["prompt_version"] == "mercado-v1"


def test_store_clock_used_by_the_new_suites_is_a_weekday_morning():
    assert SIM_START.weekday() == 2 and SIM_START.hour == 9 and isinstance(SIM_START, datetime)
