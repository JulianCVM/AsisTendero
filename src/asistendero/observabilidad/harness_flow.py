"""Nodos y conexiones del mapa de decisión del visor, atados a los nodos reales del grafo de ``graph.py``.

El mapa separa en dos etapas lo que el grafo hace dentro de un nodo: la ruta de ``next_node`` (que en LangGraph es
la arista condicional de ``interpret``) y la aduana y la bodega de ``retrieve`` (validar y ejecutar). Cada nodo dice
a qué nodo del grafo pertenece (``graph``) y cada conexión no interna corresponde a una arista real del grafo
compilado; ``tests/test_harness_info.py`` lo compara para que el mapa no se desactualice.
"""

from asistendero.agente.flujo.graph import MAX_MESSAGE_CHARS, MAX_TOOL_CALLS
from asistendero.agente.modelo.grok import MAX_ITEMS
from asistendero.agente.reglas.validation import MAX_QUANTITY


NODES = [
    {"id": "cliente", "graph": "__start__", "station": "Entrada", "title": "Mensaje del cliente", "code": "consulta",
     "layers": ["data"],
     "does": "El texto que escribe el cliente entra al flujo; en una conversación con memoria llega con sus turnos previos.",
     "receives": f"Texto libre de hasta {MAX_MESSAGE_CHARS} caracteres y, si hay sesión, el contexto que guardó el "
                 "servidor.",
     "decides": "Nada: el mensaje es un dato. Sus instrucciones no cambian reglas, precios ni existencias."},
    {"id": "validate", "graph": "validate", "station": "Puerta", "title": "Recibe el mensaje", "code": "validate",
     "layers": ["rule"],
     "does": "Revisa longitud, inyecciones, temas que no se entregan y datos personales antes de cualquier llamada a Grok.",
     "receives": "El mensaje del cliente y el último turno de la conversación, si lo hay.",
     "decides": "Si detecta una inyección o el mensaje solo pide lo que no se entrega, va directo a responder sin "
                "Grok. Si no, quita lo delicado y sigue con la torre."},
    {"id": "interpret", "graph": "interpret", "station": "Torre de Grok", "title": "Grok lee y decide", "code": "interpret",
     "layers": ["prompt", "model"],
     "does": "Grok recibe sus instrucciones, el mensaje, las observaciones ya obtenidas y los avisos del servidor.",
     "receives": "Prompt del sistema, mensaje filtrado, observaciones (las opciones cercanas sin precio) y las "
                 "llamadas que le quedan.",
     "decides": "Devuelve un JSON: respond con su redacción o call_tool con una herramienta y sus argumentos."},
    {"id": "route", "graph": "interpret", "station": "Cruce", "title": "El servidor elige la ruta", "code": "next_node",
     "layers": ["rule"],
     "does": "Lee la decisión de Grok y decide el siguiente paso; Grok no elige la ruta.",
     "receives": "La última decisión, las herramientas ya ejecutadas y los avisos enviados.",
     "decides": f"call_tool con llamadas disponibles va a la aduana (tope de {MAX_TOOL_CALLS}). respond sin un paso que "
                "el mensaje exige vuelve a la torre con un aviso. Lo demás, y cualquier error del modelo, va a responder."},
    {"id": "aduana", "graph": "retrieve", "station": "Aduana", "title": "Valida la solicitud", "code": "validate_request",
     "layers": ["rule"],
     "does": "Revisa cada solicitud antes de ejecutarla: forma, límites, SKU y cantidades que el cliente respaldó.",
     "receives": f"La herramienta y los argumentos que pidió Grok: hasta {MAX_ITEMS} artículos y cantidades enteras "
                 f"de 1 a {MAX_QUANTITY}.",
     "decides": "Si la aprueba, pasa a la bodega con los argumentos validados. Si la rechaza, la herramienta no corre y "
                "Grok recibe el código del rechazo."},
    {"id": "bodega", "graph": "retrieve", "station": "Bodega", "title": "Ejecuta la herramienta", "code": "tools.py",
     "layers": ["data"],
     "does": "Lee el catálogo SQLite en solo lectura, con negocio y sede fijados por el servidor; un pedido solo "
             "aparta unidades.",
     "receives": "Los argumentos aprobados por la aduana.",
     "decides": "Devuelve el sobre {status, data, error}. Si la búsqueda dejó un solo producto que el cliente distinguió "
                "y una cantidad entera, la aduana valida la cotización en el mismo paso. Si la salida ya está completa "
                "(categoría, búsqueda sin resultados, pedido confirmado o cancelado, consulta vacía) y no falta ningún "
                "paso, va directo a responder; si no, vuelve a Grok como observación."},
    {"id": "respond", "graph": "respond", "station": "Balanza", "title": "Verifica y responde", "code": "reply_is_grounded",
     "layers": ["model", "rule", "data"],
     "does": "Arma la respuesta final con los datos de las herramientas y comprueba la redacción que propuso Grok.",
     "receives": "La última decisión, las observaciones de la corrida y el error, si lo hubo.",
     "decides": "La redacción de Grok se usa solo si cada $, SKU y cantidad coincide con lo observado y no promete "
                "reserva, pago ni fechas que nadie anotó. Si no, responde el servidor."},
    {"id": "outcome", "graph": "__end__", "station": "Mostrador", "title": "Estado final", "code": "estado",
     "layers": ["rule"],
     "does": "Toda corrida termina con un estado y su grupo; si algo falla, en uno seguro que no inventa precio ni "
             "existencias.",
     "receives": "El estado, la respuesta y el error de la balanza.",
     "decides": "El evaluador compara el estado y el SKU con los esperados en evaluation/cases.json."},
]

# «internal» marca lo que el mapa separa dentro de un mismo nodo del grafo; no es una arista de LangGraph.
EDGES = [
    {"from": "cliente", "to": "validate", "label": "mensaje", "when": "Cada mensaje entra por la puerta."},
    {"from": "validate", "to": "interpret", "label": "válido", "when": "Mensaje válido, con lo delicado ya quitado."},
    {"from": "validate", "to": "respond", "label": "sin Grok",
     "when": "Inyección (bloqueo y, en una conversación, baneo) o solo temas que no se entregan."},
    {"from": "interpret", "to": "route", "label": "decisión", "when": "Grok devuelve su JSON o falla.",
     "internal": True},
    {"from": "route", "to": "aduana", "label": "call_tool", "when": "Grok pidió una herramienta y quedan llamadas."},
    {"from": "route", "to": "interpret", "label": "aviso",
     "when": "Grok respondió sin un paso que el mensaje exige: vuelve con un aviso del servidor."},
    {"from": "route", "to": "respond", "label": "respond",
     "when": "Grok decidió responder, falló o se alcanzó el tope de herramientas."},
    {"from": "aduana", "to": "bodega", "label": "aprobada", "when": "La solicitud pasó las reglas.", "internal": True},
    {"from": "aduana", "to": "interpret", "label": "rechazo",
     "when": "La solicitud no pasó: la herramienta no corre y Grok recibe el código."},
    {"from": "bodega", "to": "interpret", "label": "observación", "when": "El resultado vuelve a Grok."},
    {"from": "bodega", "to": "aduana", "label": "auto-cotiza", "internal": True,
     "when": "Un solo producto distinguido y una cantidad entera: el servidor cotiza sin pedirle a Grok otro paso."},
    {"from": "bodega", "to": "respond", "label": "sin Grok",
     "when": "La herramienta dejó la respuesta completa y no falta ningún paso: se responde sin otra llamada a Grok."},
    {"from": "respond", "to": "outcome", "label": "estado", "when": "Respuesta y estado final."},
]


def describe_flow() -> dict:
    return {"nodes": NODES, "edges": EDGES}
