"""Grok decide, paso a paso, si responder o pedir una de las herramientas del servidor."""

from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import json
import os

# En redes con un proxy que firma con un certificado propio (corporativas, universitarias), Python no confía en los
# certificados del sistema y la llamada a la pasarela falla. truststore es opcional: si no está instalado, se usa el
# almacén de certificados de Python, como antes. Cualquier otro fallo al inyectarlo sí debe verse.
try:
    import truststore
except ImportError:
    truststore = None
if truststore is not None:
    truststore.inject_into_ssl()

import openai
from openai import OpenAI

from asistendero.agente.modelo.prompt import AGENT_PROMPT, PROMPT_VERSION


DEFAULT_MODEL = "grok-4.20-0309-non-reasoning"
DEFAULT_BASE_URL = "https://api.reto.pltk.mx/v1"
# El reglamento del reto permite solo estas familias; otro modelo se rechaza antes de llamar a la pasarela.
ALLOWED_MODEL_FAMILIES = ("grok-4.7", "grok-4.6", "grok-4.5", "grok-4.20")
TEMPERATURE = 0
MAX_OUTPUT_TOKENS = 600
RESPONSE_FORMAT = {"type": "json_object"}
TIMEOUT_SECONDS = 45.0
MAX_ITEMS = 5
MAX_ARGUMENT_CHARS = 1500
MAX_REPLY_CHARS = 1200
# Las herramientas de pedidos solo funcionan dentro de una sesión: el servidor sabe de quién es cada pedido.
ORDER_TOOLS = ("registrar_pedido", "confirmar_pedido", "agendar_recogida", "consultar_pedido", "cancelar_pedido")
TOOL_NAMES = (
    "buscar_productos", "consultar_disponibilidad", "calcular_cotizacion_informativa",
    "consultar_info_tienda", "explorar_categoria", *ORDER_TOOLS,
)
STORE_TOPICS = ("horario", "ubicacion", "medios_pago", "domicilios", "garantias", "contacto", "pedidos", "facturacion")
INTENTS = ("productos", "pedido", "tienda", "saludo", "otro")
# Con varios clientes atendidos en hilos, cada hilo puede usar otro modelo sin tocar GROK_MODEL.
MODEL_OVERRIDE: ContextVar[str | None] = ContextVar("grok_model_override", default=None)

class ModelError(Exception):
    """Fallo de la llamada a Grok con un código estable y un mensaje seguro para mostrar."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Decision:
    action: str
    intent: str
    tool: str | None
    arguments: dict | None
    reply: str
    model: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    valid_json: bool = True
    raw_response: str | None = None
    cached_input_tokens: int | None = None
    reported_cost_usd_ticks: int | None = None


# La caché de xAI va por bloques de 128 tokens y vive en el servidor que atendió la llamada. En las corridas reales
# hasta el 24-10-2026 (3.924 llamadas), una de cada 7 en la corrida v10 cayó en un servidor frío y solo cacheó 128
# tokens del prompt fijo. xAI enruta por esta cabecera (`prompt_cache_key` en su API de Responses). Va tras la bandera
# GROK_CONV_ID porque no se ha comprobado que la pasarela del reto la reenvíe: se enciende para una corrida medida.
CONVERSATION_HEADER = "x-grok-conv-id"


def conversation_key(session_id: str | None) -> str | None:
    """Clave estable de enrutamiento: la de la sesión o, sin sesión, la del prompt; nunca el id en claro."""
    if os.getenv("GROK_CONV_ID", "").strip().casefold() not in {"1", "true", "si", "sí"}:
        return None
    # Sin sesión, todas las consultas sueltas comparten el mismo prefijo (el prompt fijo): conviene el mismo servidor.
    seed = f"sesion:{session_id}" if session_id else f"prompt:{PROMPT_VERSION}"
    return hashlib.sha256(f"asistendero:{seed}".encode("utf-8")).hexdigest()[:32]


def _complete(
    system: str, payload: dict, conversation: str | None = None,
) -> tuple[str, str, int | None, int | None, int | None, int | None]:
    """Envía un prefijo ``system`` 100 % estático (para aciertos de Prompt Caching) y los datos dinámicos en ``user``."""
    if not isinstance(system, str) or not system:
        raise ValueError("El bloque system debe ser un texto estático no vacío.")
    api_key = os.getenv("GROK_API_KEY", "").strip()
    if not api_key:
        raise ModelError("MODEL_NOT_CONFIGURED", "Falta GROK_API_KEY. Configúrala en .env o en el entorno.")
    model = current_model()
    if not model.startswith(ALLOWED_MODEL_FAMILIES):
        raise ModelError("MODEL_NOT_ALLOWED", "El reto solo permite Grok 4.7, 4.6, 4.5 o 4.20.")
    client = OpenAI(
        api_key=api_key,
        base_url=os.getenv("GROK_BASE_URL", DEFAULT_BASE_URL).strip(),
        timeout=TIMEOUT_SECONDS,
        max_retries=1,
    )
    create_kwargs: dict = {
        "model": model,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "response_format": RESPONSE_FORMAT,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
        ],
    }
    if conversation:
        create_kwargs["extra_headers"] = {CONVERSATION_HEADER: conversation}
    # Los mensajes del SDK pueden incluir datos de la solicitud: solo se propaga un código.
    try:
        result = client.chat.completions.create(**create_kwargs)
    except openai.APITimeoutError:
        raise ModelError("MODEL_TIMEOUT", "Grok no respondió a tiempo.") from None
    except openai.RateLimitError:
        raise ModelError("MODEL_QUOTA", "Grok rechazó la llamada por cuota o límite de uso.") from None
    except (openai.AuthenticationError, openai.PermissionDeniedError):
        raise ModelError("MODEL_AUTH", "Grok rechazó la clave configurada.") from None
    except openai.APIStatusError as exc:
        if exc.status_code == 402:
            raise ModelError("MODEL_QUOTA", "La cuenta de Grok no tiene créditos disponibles.") from None
        raise ModelError("MODEL_UNAVAILABLE", f"Grok devolvió un error HTTP {exc.status_code}.") from None
    except openai.APIConnectionError:
        raise ModelError("MODEL_UNAVAILABLE", "No fue posible conectar con Grok.") from None
    usage = result.usage
    prompt_details = getattr(usage, "prompt_tokens_details", None)
    cached_tokens = None
    if prompt_details is not None:
        cached_tokens = getattr(prompt_details, "cached_tokens", None)
        if cached_tokens is None and isinstance(prompt_details, dict):
            cached_tokens = prompt_details.get("cached_tokens")
    if cached_tokens is None:
        cached_tokens = getattr(usage, "cached_tokens", None)
        if cached_tokens is None and isinstance(usage, dict):
            cached_tokens = usage.get("cached_tokens")
    content = result.choices[0].message.content if result.choices else None
    return (
        content or "",
        result.model or model,
        getattr(usage, "prompt_tokens", None) if not isinstance(usage, dict) else usage.get("prompt_tokens"),
        getattr(usage, "completion_tokens", None) if not isinstance(usage, dict) else usage.get("completion_tokens"),
        cached_tokens,
        getattr(usage, "cost_in_usd_ticks", None) if not isinstance(usage, dict) else usage.get("cost_in_usd_ticks"),
    )


def current_model() -> str:
    return MODEL_OVERRIDE.get() or os.getenv("GROK_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def parse_decision(raw: str) -> tuple[str, str, str | None, dict | None, str]:
    """Valida la forma de la decisión; los argumentos de cada herramienta los valida el grafo."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("decisión inválida")
    action = data["action"]
    intent = data["intent"]
    reply = data["reply"]
    tool = data.get("tool")
    arguments = data.get("arguments")
    # En la primera corrida S3, Grok 4.20 escribió 5 de 43 veces la herramienta en "action"
    # ({"action":"calcular_cotizacion_informativa","tool":"calcular_cotizacion_informativa"}). La
    # intención es inequívoca y los argumentos se validan igual, así que se lee como call_tool.
    if action in TOOL_NAMES and tool in (None, action):
        action, tool = "call_tool", action
    # «horario» era la intención de S2; se acepta como «tienda» para no invalidar una decisión correcta.
    intent = "tienda" if intent == "horario" else intent
    if intent not in INTENTS:
        raise ValueError("intención inválida")
    if not isinstance(reply, str) or len(reply) > MAX_REPLY_CHARS:
        raise ValueError("respuesta inválida")
    if action == "call_tool":
        if tool not in TOOL_NAMES:
            raise ValueError("herramienta desconocida")
        if not isinstance(arguments, dict):
            raise ValueError("argumentos inválidos")
        if len(json.dumps(arguments, ensure_ascii=False)) > MAX_ARGUMENT_CHARS:
            raise ValueError("argumentos demasiado largos")
        return action, intent, tool, arguments, ""
    if action == "respond":
        if tool is not None or arguments not in (None, {}):
            raise ValueError("respuesta directa con herramienta")
        return action, intent, None, None, reply.strip()
    raise ValueError("acción inválida")


def prepare_step(
    message: str,
    observations: list[dict],
    remaining_calls: int,
    context: dict | None = None,
) -> tuple[dict, str | None]:
    """Arma el mensaje ``user``: lo que cambia menos va primero, para que la caché de prefijo lo reutilice.

    Orden: la conversación compactada (fija durante el turno; su reloj, al final de ella), el mensaje (fijo en el
    turno), las observaciones (crecen agregando al final) y las llamadas disponibles (cambian en cada paso). Así el
    segundo paso de un turno reutiliza todo hasta la última observación del primero. El ``session_id`` no va en el
    payload: solo sirve para la clave de enrutamiento. Devuelve ``(payload, session_id)``.
    """
    from asistendero.agente.conversacion.sessions import compact_context

    session_id: str | None = None
    clean_context: dict | None = None
    if context:
        session_id = context.get("session_id")
        compacted = compact_context(context)
        if compacted:
            clean_context = compacted

    payload: dict = {}
    if clean_context:
        payload["conversacion"] = clean_context
    payload["mensaje"] = message
    payload["observaciones"] = observations
    payload["llamadas_disponibles"] = remaining_calls
    return payload, session_id


def decide_with_grok(
    message: str, observations: list[dict], remaining_calls: int, context: dict | None = None,
) -> Decision:
    payload, session_id = prepare_step(message, observations, remaining_calls, context)
    # Una sola llamada por paso: nunca se repite, ni ante un error inesperado (sería consumo sin tarea real).
    raw, model, in_tokens, out_tokens, cached_tokens, cost_ticks = _complete(
        AGENT_PROMPT, payload, conversation=conversation_key(session_id),
    )
    return decision_from_raw(
        raw, model=model, input_tokens=in_tokens, output_tokens=out_tokens,
        cached_input_tokens=cached_tokens, reported_cost_usd_ticks=cost_ticks,
    )


def decision_from_raw(raw: str, **usage: object) -> Decision:
    """Convierte el texto de Grok en una decisión; un texto inválido da ``valid_json=False``."""
    usage = {**usage, "raw_response": raw}
    try:
        action, intent, tool, arguments, reply = parse_decision(raw)
    except (ValueError, KeyError, TypeError):
        return Decision("respond", "otro", None, None, "", valid_json=False, **usage)
    return Decision(action, intent, tool, arguments, reply, **usage)
