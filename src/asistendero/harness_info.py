"""Descripción del harness para el mapa del visor, armada con las constantes que usa el flujo.

El texto explicativo de cada etapa vive en ``ui/index.html``; aquí solo están los datos que cambian con el
código (prompt, versión, herramientas, límites, códigos y estados) para que el mapa no se desactualice.
"""

from asistendero.graph import MAX_MESSAGE_CHARS, MAX_TOOL_CALLS
from asistendero.grok import AGENT_PROMPT, MAX_ARGUMENT_CHARS, MAX_ITEMS, PROMPT_VERSION, TOOL_NAMES, current_model
from asistendero.orders import HOLD_MINUTES
from asistendero.guardrails import SENSITIVE_TOPICS
from asistendero.injection import INJECTION_CODES
from asistendero.reminders import REMINDER_CODES
from asistendero.validation import MAX_QUANTITY


TOOLS = {
    "buscar_productos": {
        "arguments": '{"items": [{"text": "tubo PVC de 1/2 para agua", "material": "PVC", "measure": "1/2 pulgada"}]}',
        "returns": "Por artículo, coincidencias (matches) u opciones cercanas (nearby, sin precio para Grok).",
    },
    "consultar_disponibilidad": {
        "arguments": '{"sku": "PVC-050"}',
        "returns": "Existencias, unidad y fecha del SKU. No aparta unidades.",
    },
    "calcular_cotizacion_informativa": {
        "arguments": '{"lines": [{"sku": "PVC-050", "quantity": 2}]}',
        "returns": "Precio unitario, subtotales y total en COP con reservation_created=false.",
    },
    "consultar_info_tienda": {
        "arguments": '{"tema": "horario"}',
        "returns": "Información ficticia de la tienda; con horario, si está abierta según el reloj del servidor.",
    },
    "explorar_categoria": {
        "arguments": '{"categoria": "plomería"}',
        "returns": "Sin categoría, la lista de categorías; con ella, sus productos y variantes, sin precios.",
    },
    "registrar_pedido": {
        "arguments": '{"lines": [{"sku": "PVC-050", "quantity": 3}]}',
        "returns": f"Pedido pendiente con código, líneas y total; aparta las unidades {HOLD_MINUTES} minutos. Solo en sesión.",
    },
    "confirmar_pedido": {
        "arguments": '{"pedido": "P-1A2B3C"}',
        "returns": "Pedido confirmado: queda apartado hasta la recogida (o 24 horas). Solo si el cliente confirmó ahora.",
    },
    "agendar_recogida": {
        "arguments": '{"pedido": "P-1A2B3C", "fecha": "2026-10-22", "hora": "16:00", "nota": "lo recoge mi hermano"}',
        "returns": "Pedido con la hora de recogida (dentro del horario y de 7 días) y la nota sin datos personales.",
    },
    "consultar_pedido": {
        "arguments": '{"pedido": "P-1A2B3C"} o {}',
        "returns": "Estado, líneas, total y horas de los pedidos de esta conversación.",
    },
    "cancelar_pedido": {
        "arguments": '{"pedido": "P-1A2B3C"}',
        "returns": "Pedido cancelado y unidades liberadas. Solo si el cliente pidió cancelar.",
    },
}

# Lo que se quita del mensaje antes de Grok y la respuesta fija que recibe el cliente.
GUARDRAILS = {code: reply for code, (_, reply) in SENSITIVE_TOPICS.items()}

# Rechazos del servidor antes de ejecutar: la solicitud nunca llega a la herramienta.
REJECTIONS = {
    "UNKNOWN_TOOL": "Herramienta fuera de la lista permitida.",
    "INVALID_ARGUMENT": "Argumentos con forma, campos o longitud no permitidos.",
    "TOO_MANY_ITEMS": f"Más de {MAX_ITEMS} artículos, o una lista recortada después de ese rechazo.",
    "INVALID_QUANTITY": f"Cantidad que no es un entero de 1 a {MAX_QUANTITY}.",
    "SKU_NOT_GROUNDED": "SKU que no salió de una búsqueda o que el mensaje no distingue.",
    "QUANTITY_NOT_GROUNDED": "Cantidad que el cliente no dijo.",
    "DUPLICATE_CALL": "La misma llamada ya se ejecutó en esta corrida.",
    "SESSION_REQUIRED": "Herramienta de pedidos fuera de una conversación con sesión.",
    "PURCHASE_NOT_STATED": "Registrar un pedido sin que el cliente diga que lo lleva.",
    "CONFIRMATION_NOT_STATED": "Confirmar sin un «sí» del cliente en este mensaje, o en el mismo turno del registro.",
    "TIME_NOT_GROUNDED": "Agendar una hora o un día que el cliente no dijo.",
    "CANCEL_NOT_STATED": "Cancelar sin que el cliente lo pida.",
    "ORDER_UNCHANGED": "Registrar igual el pedido que se acaba de cancelar en el mismo turno.",
}

ERRORS = {
    "tool": {
        "NOT_FOUND": "El SKU no existe en la sede.",
        "INSUFFICIENT_STOCK": "La cantidad supera las existencias.",
        "CATALOG_UNAVAILABLE": "No se pudo leer el catálogo.",
        "TOOL_FAILURE": "La herramienta falló o devolvió un sobre mal formado.",
        "ORDER_NOT_FOUND": "El pedido no existe o es de otra conversación.",
        "ORDER_EXPIRED": f"El pedido venció ({HOLD_MINUTES} minutos sin confirmar o sin recoger a tiempo).",
        "ORDER_CLOSED": "El pedido ya está entregado, cancelado o vencido.",
        "TOO_MANY_ORDERS": "La conversación ya tiene el máximo de pedidos activos.",
        "PICKUP_IN_PAST": "Recogida antes de 10 minutos desde ahora.",
        "PICKUP_TOO_FAR": "Recogida a más de 7 días.",
        "PICKUP_OUTSIDE_HOURS": "Recogida con la tienda cerrada.",
    },
    "model": {
        "MODEL_NOT_CONFIGURED": "Falta la llave de Grok.",
        "MODEL_NOT_ALLOWED": "Modelo fuera de los que permite el reto (Grok 4.7, 4.6, 4.5 o 4.20).",
        "MODEL_AUTH": "La pasarela rechazó la llave.",
        "MODEL_QUOTA": "Sin cuota o créditos.",
        "MODEL_TIMEOUT": "Grok no respondió a tiempo.",
        "MODEL_UNAVAILABLE": "No se pudo conectar con Grok.",
        "MODEL_INVALID_OUTPUT": "La decisión no era JSON válido.",
        "TOOL_CALL_LIMIT": f"Se alcanzó el tope de {MAX_TOOL_CALLS} herramientas.",
    },
}

# Cada estado final y el grupo con el que se juzga si la corrida salió bien.
OUTCOMES = {
    "verified": {
        "label": "Resuelto con datos verificados",
        "states": {
            "quoted": "Cotización informativa", "found": "Productos encontrados",
            "insufficient_stock": "Existencias insuficientes", "nearby": "Opciones cercanas",
            "not_found": "Sin coincidencia", "answered": "Respondido sin herramientas",
            "informed": "Información de la tienda o del catálogo",
            "order_pending": "Pedido registrado, falta confirmar", "order_confirmed": "Pedido confirmado",
            "pickup_scheduled": "Recogida agendada", "order_cancelled": "Pedido cancelado",
            "order_status": "Estado de pedidos",
        },
    },
    "clarify": {
        "label": "Pide un dato al cliente",
        "states": {"clarify": "Falta aclaración", "partial": "Resultado parcial",
                   "order_issue": "Pedido que necesita otro dato o venció"},
    },
    "safe_failure": {
        "label": "Fallo controlado en estado seguro",
        "states": {
            "tool_error": "Catálogo no disponible", "quote_error": "Cotización no disponible",
            "model_error": "Fallo del modelo", "model_invalid": "Respuesta no válida",
            "limit_reached": "Límite de herramientas", "not_verified": "Sin verificar",
            "refused": "Pedido de información que no se entrega",
            "blocked": "Intento de inyección bloqueado; en una conversación, sesión baneada",
        },
    },
}


def describe_harness() -> dict:
    """Datos públicos del flujo; no incluye la llave ni la URL de la pasarela."""
    return {
        "prompt_version": PROMPT_VERSION,
        "model": current_model(),
        "instructions": AGENT_PROMPT,
        "limits": {
            "max_message_chars": MAX_MESSAGE_CHARS,
            "max_tool_calls": MAX_TOOL_CALLS,
            "max_items": MAX_ITEMS,
            "max_argument_chars": MAX_ARGUMENT_CHARS,
            "max_quantity": MAX_QUANTITY,
        },
        "tools": [{"name": name, **TOOLS[name]} for name in TOOL_NAMES],
        "rejections": REJECTIONS,
        "errors": ERRORS,
        "reminders": REMINDER_CODES,
        "guardrails": GUARDRAILS,
        "injections": INJECTION_CODES,
        "outcomes": OUTCOMES,
    }
