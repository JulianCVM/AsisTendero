"""Descripción del harness para el mapa del visor, armada con las constantes que usa el flujo.

El texto explicativo de cada etapa vive en ``ui/index.html``; aquí solo están los datos que cambian con el
código (prompt, versión, herramientas, límites, códigos y estados) para que el mapa no se desactualice.
"""

import os

from asistendero.graph import MAX_MESSAGE_CHARS, MAX_TOOL_CALLS
from asistendero.grok import AGENT_PROMPT, DEFAULT_MODEL, MAX_ARGUMENT_CHARS, MAX_ITEMS, PROMPT_VERSION, TOOL_NAMES
from asistendero.reminders import REMINDERS
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
}

# Rechazos del servidor antes de ejecutar: la solicitud nunca llega a la herramienta.
REJECTIONS = {
    "UNKNOWN_TOOL": "Herramienta fuera de la lista permitida.",
    "INVALID_ARGUMENT": "Argumentos con forma, campos o longitud no permitidos.",
    "TOO_MANY_ITEMS": f"Más de {MAX_ITEMS} artículos, o una lista recortada después de ese rechazo.",
    "INVALID_QUANTITY": f"Cantidad que no es un entero de 1 a {MAX_QUANTITY}.",
    "SKU_NOT_GROUNDED": "SKU que no salió de una búsqueda o que el mensaje no distingue.",
    "QUANTITY_NOT_GROUNDED": "Cantidad que el cliente no dijo.",
    "DUPLICATE_CALL": "La misma llamada ya se ejecutó en esta corrida.",
}

ERRORS = {
    "tool": {
        "NOT_FOUND": "El SKU no existe en la sede.",
        "INSUFFICIENT_STOCK": "La cantidad supera las existencias.",
        "CATALOG_UNAVAILABLE": "No se pudo leer el catálogo.",
        "TOOL_FAILURE": "La herramienta falló o devolvió un sobre mal formado.",
    },
    "model": {
        "MODEL_NOT_CONFIGURED": "Falta la llave de Grok.",
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
        },
    },
    "clarify": {
        "label": "Pide un dato al cliente",
        "states": {"clarify": "Falta aclaración", "partial": "Resultado parcial"},
    },
    "safe_failure": {
        "label": "Fallo controlado en estado seguro",
        "states": {
            "tool_error": "Catálogo no disponible", "quote_error": "Cotización no disponible",
            "model_error": "Fallo del modelo", "model_invalid": "Respuesta no válida",
            "limit_reached": "Límite de herramientas", "not_verified": "Sin verificar",
        },
    },
}


def describe_harness() -> dict:
    """Datos públicos del flujo; no incluye la llave ni la URL de la pasarela."""
    return {
        "prompt_version": PROMPT_VERSION,
        "model": os.getenv("GROK_MODEL", DEFAULT_MODEL),
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
        "reminders": [item["error"] for item in REMINDERS.values()],
        "outcomes": OUTCOMES,
    }
