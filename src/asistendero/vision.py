"""Extracción estructurada de atributos visuales (multimodal) para aligerar la búsqueda en SQLite.

Principio de diseño: «Grok Visión extrae, el servidor gobierna».
El modelo de visión NO consulta la base de datos ni decide el SKU final. Procesa la imagen
una sola vez y devuelve un payload JSON de atributos. Python toma esos atributos y ejecuta
la búsqueda local en SQLite.
"""

from contextvars import ContextVar
from dataclasses import dataclass, field
import json
import os
import re
import sys
from time import perf_counter
import traceback
from typing import Any, Callable, Literal

from dotenv import load_dotenv

load_dotenv()

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

from openai import OpenAI

from asistendero.catalog import MockCatalog, Product, SearchResult
from asistendero.grok import ModelError
from asistendero.measures import canonical_text, measures
from asistendero.observations import ToolCall, execute_safely
from asistendero.pricing import call_cost
from asistendero.search import ProductQuery, without_quantities
from asistendero.validation import (
    MAX_QUANTITY, Rejected, is_distinguished, quantities_in_message,
)

SAMPLE_COUNTER_TEMPLATE = (
    "No logro identificar con certeza la referencia exacta en la imagen. "
    "Te recomiendo llevar la muestra física al mostrador de la ferretería para que te asesoremos personalmente."
)

SCREW_SAFEGUARD_TEMPLATE = (
    "Recibí la foto, pero no logro identificar con certeza las medidas o el tipo de tornillo. "
    "¿Para qué material lo necesitas (madera, lámina, drywall) y de qué largo aproximado?"
)

MAX_VISION_CLARIFICATIONS = 2

# Patrones para detectar y podar cadenas pesadas base64 o binarios de imágenes
BASE64_DATA_URI = re.compile(r"data:image\/[a-zA-Z0-9.+_-]+;base64,[A-Za-z0-9+/=]+")
LONG_BASE64 = re.compile(r"\b[A-Za-z0-9+/]{80,}={0,2}\b")

# Gancho para simular extracción en pruebas sin llamadas de red
VISION_EXTRACTOR_OVERRIDE: ContextVar[Callable[[Any], "ImageAttributePayload"] | None] = ContextVar(
    "vision_extractor_override", default=None
)

VISION_SYSTEM_PROMPT = """Eres el módulo de visión técnica de una ferretería.
Tu única función es examinar la imagen del producto y extraer sus atributos físicos y técnicos visibles en un objeto JSON estricto.
NO consultas la base de datos ni decides códigos de inventario (SKU).
Devuelve exclusivamente un JSON con estas claves:
{
  "tipo_producto": "término normalizado singular (ej. tornillo, tubo, codo, broca, cemento, pintura, candado)",
  "material": "material visible o estándar (ej. acero galvanizado, pvc, cobre, hierro, bronce) o null",
  "medidas_visibles": ["lista de medidas explícitas impresas o proporciones claras, ej: '1/2 pulgada', '2 pulgadas'"],
  "presentacion_uso": "aplicación o tipo de uso (ej. presion agua, sanitario, conduit electrico, drywall, madera) o null",
  "color_acabado": "color o acabado visual (ej. blanco, zincado, negro, gris) o null",
  "confianza_visual": "alta" | "media" | "baja"
}"""


def sanitize_image_text(text: str) -> str:
    """Elimina cadenas base64 pesadas o binarios para proteger SQLite y la tasa de acierto de Prompt Caching."""
    if not text:
        return ""
    cleaned = BASE64_DATA_URI.sub("[imagen]", text)
    cleaned = LONG_BASE64.sub("[imagen]", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


@dataclass(frozen=True)
class ImageAttributePayload:
    tipo_producto: str | None = None
    material: str | None = None
    medidas_visibles: list[str] = field(default_factory=list)
    presentacion_uso: str | None = None
    color_acabado: str | None = None
    confianza_visual: str = "media"
    usage: dict[str, Any] | None = field(default=None, compare=False)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "tipo_producto": self.tipo_producto,
            "material": self.material,
            "medidas_visibles": list(self.medidas_visibles),
            "presentacion_uso": self.presentacion_uso,
            "color_acabado": self.color_acabado,
            "confianza_visual": self.confianza_visual,
        }
        if self.usage:
            data["usage"] = self.usage
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any], usage: dict[str, Any] | None = None) -> "ImageAttributePayload":
        conf = data.get("confianza_visual", "media")
        if conf not in ("alta", "media", "baja"):
            conf = "media"
        raw_measures = data.get("medidas_visibles") or []
        if isinstance(raw_measures, str):
            raw_measures = [raw_measures]
        elif not isinstance(raw_measures, list):
            raw_measures = []
        return cls(
            tipo_producto=str(data["tipo_producto"]).strip() if data.get("tipo_producto") else None,
            material=str(data["material"]).strip() if data.get("material") else None,
            medidas_visibles=[str(m).strip() for m in raw_measures if str(m).strip()],
            presentacion_uso=str(data["presentacion_uso"]).strip() if data.get("presentacion_uso") else None,
            color_acabado=str(data["color_acabado"]).strip() if data.get("color_acabado") else None,
            confianza_visual=conf,
            usage=usage or data.get("usage"),
        )

    def semantic_summary(self) -> str:
        """Resumen semántico conciso y limpio sin datos binarios ni base64."""
        parts = []
        if self.tipo_producto:
            parts.append(self.tipo_producto)
        if self.material:
            parts.append(self.material)
        if self.medidas_visibles:
            parts.append(" ".join(self.medidas_visibles))
        if self.presentacion_uso:
            parts.append(self.presentacion_uso)
        if self.color_acabado:
            parts.append(self.color_acabado)
        desc = " ".join(parts).strip() or "artículo no identificado"
        return f"[Foto: {desc} (confianza: {self.confianza_visual})]"


def extract_vision_attributes(
    image_input: Any,
    client: OpenAI | None = None,
    model: str | None = None,
) -> ImageAttributePayload:
    """Extrae atributos estructurados de una imagen mediante llamada multimodal o simulador inyectado."""
    override = VISION_EXTRACTOR_OVERRIDE.get()
    if override is not None:
        return override(image_input)

    if isinstance(image_input, ImageAttributePayload):
        return image_input

    if isinstance(image_input, dict):
        return ImageAttributePayload.from_dict(image_input)

    if isinstance(image_input, str):
        # Si es un JSON serializado de atributos
        try:
            parsed = json.loads(image_input)
            if isinstance(parsed, dict) and ("tipo_producto" in parsed or "confianza_visual" in parsed):
                return ImageAttributePayload.from_dict(parsed)
        except (json.JSONDecodeError, ValueError):
            pass

    # Llamada real multimodal a la pasarela Grok Visión
    api_key = os.getenv("GROK_API_KEY", "").strip()
    if not api_key and client is None:
        err_msg = "Falta GROK_API_KEY en .env o en el entorno para llamadas de visión multimodal."
        sys.stderr.write(f"\n[ERROR GROK VISIÓN] {err_msg}\n")
        raise ModelError("MODEL_NOT_CONFIGURED", err_msg)

    if (client is not None or api_key) and isinstance(image_input, str):
        if client is None:
            client = OpenAI(
                api_key=api_key,
                base_url=os.getenv("GROK_BASE_URL", "https://api.reto.pltk.mx/v1").strip(),
                timeout=45.0,
            )
        vision_model = (
            model
            or os.getenv("GROK_VISION_MODEL")
            or os.getenv("GROK_MODEL")
            or "grok-4.20-0309-non-reasoning"
        )
        if vision_model in ("grok-2-vision-1212", "grok-vision"):
            vision_model = "grok-4.20-0309-non-reasoning"
        image_url = image_input if image_input.startswith(("http://", "https://", "data:")) else f"data:image/jpeg;base64,{image_input}"

        call_started = perf_counter()
        try:
            resp = client.chat.completions.create(
                model=vision_model,
                temperature=0,
                max_tokens=400,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": VISION_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Extrae los atributos del producto en esta imagen."},
                            {"type": "image_url", "image_url": {"url": image_url}},
                        ],
                    },
                ],
            )
            duration_ms = round((perf_counter() - call_started) * 1000)
            usage = getattr(resp, "usage", None)
            in_tokens = usage.prompt_tokens if usage else None
            out_tokens = usage.completion_tokens if usage else None
            cached_tokens = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", None)
            cost_info = call_cost(vision_model, in_tokens, out_tokens, cached_tokens)
            usage_data = {
                "model": vision_model,
                "input_tokens": in_tokens,
                "output_tokens": out_tokens,
                "cached_input_tokens": cached_tokens,
                "duration_ms": duration_ms,
                "cost": cost_info,
            }
            content = resp.choices[0].message.content or "{}"
            parsed_data = json.loads(content)
            return ImageAttributePayload.from_dict(parsed_data, usage=usage_data)
        except Exception as exc:
            duration_ms = round((perf_counter() - call_started) * 1000)
            sys.stderr.write(
                f"\n[ERROR GROK VISIÓN] Fallo en llamada remota multimodal tras {duration_ms} ms "
                f"({type(exc).__name__}): {exc}\n"
            )
            traceback.print_exc(file=sys.stderr)
            sys.stderr.flush()
            raise

    return ImageAttributePayload(confianza_visual="baja")


def payload_to_product_query(payload: ImageAttributePayload, user_text: str = "") -> ProductQuery:
    """Convierte el ImageAttributePayload en un ProductQuery tipado para MockCatalog."""
    query_parts: list[str] = []
    if payload.tipo_producto:
        query_parts.append(payload.tipo_producto)
    if payload.material:
        query_parts.append(payload.material)
    if payload.medidas_visibles:
        query_parts.extend(payload.medidas_visibles)
    if payload.presentacion_uso:
        query_parts.append(payload.presentacion_uso)
    if payload.color_acabado:
        query_parts.append(payload.color_acabado)
    if user_text:
        cleaned_user = without_quantities(user_text)
        if cleaned_user:
            query_parts.append(cleaned_user)

    full_text = " ".join(query_parts).strip()
    primary_measure = payload.medidas_visibles[0] if payload.medidas_visibles else None

    return ProductQuery(
        text=full_text,
        product=payload.tipo_producto,
        material=payload.material,
        measure=primary_measure,
        presentation=payload.presentacion_uso,
        color=payload.color_acabado,
    )


def search_catalog_with_vision(
    catalog: MockCatalog,
    payload: ImageAttributePayload,
    user_text: str = "",
    limit: int = 5,
) -> SearchResult:
    """Ejecuta la búsqueda SQLite local a partir de los atributos extraídos por visión."""
    query = payload_to_product_query(payload, user_text)
    return catalog.search(query, limit=limit)


def handle_vision_turn(
    payload: ImageAttributePayload,
    user_message: str,
    catalog: MockCatalog,
    tool_executor: Any = None,
    context: dict | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Gobierna el turno con imagen: Python consulta SQLite, salta deterministamente o desambigua."""
    clean_user = sanitize_image_text(user_message)
    summary = payload.semantic_summary()
    is_screw_query = "tornillo" in clean_user.lower() or (
        payload.tipo_producto is not None and "tornillo" in payload.tipo_producto.lower()
    )

    # 1. Fallo seguro si no se logra clasificar el producto o la confianza visual es baja
    if not payload.tipo_producto or payload.confianza_visual == "baja":
        fallback_msg = SCREW_SAFEGUARD_TEMPLATE if is_screw_query else SAMPLE_COUNTER_TEMPLATE
        return {
            "respuesta": fallback_msg,
            "estado": "answered",
            "model_called": False,
            "model_calls": 0,
            "tool_calls": [],
            "products": [],
            "shopping": [],
            "options": [],
            "specs": {},
        }

    # 2. Python ejecuta la búsqueda local en SQLite
    search_res = search_catalog_with_vision(catalog, payload, clean_user)
    matches = list(search_res.matches)
    nearby = list(search_res.nearby)

    search_args = {
        "items": [
            {
                "text": f"{payload.tipo_producto or ''} {payload.material or ''} {' '.join(payload.medidas_visibles)}".strip(),
                **({"product": payload.tipo_producto} if payload.tipo_producto else {}),
                **({"material": payload.material} if payload.material else {}),
                **({"measure": payload.medidas_visibles[0]} if payload.medidas_visibles else {}),
                **({"presentation": payload.presentacion_uso} if payload.presentacion_uso else {}),
            }
        ]
    }
    search_call: ToolCall = {
        "step": 1,
        "requested_tool": "buscar_productos",
        "requested_arguments": search_args,
        "executed": True,
        "arguments": search_args,
        "response": {
            "status": "ok",
            "data": {
                "results": [
                    {
                        "query": search_args["items"][0]["text"],
                        "matches": [m.facts_for_model() for m in matches],
                        "nearby": [n.facts_for_model() for n in nearby],
                    }
                ]
            },
        },
        "duration_ms": 1,
    }

    # 3. Caso: Coincidencia única que cumple is_distinguished
    if len(matches) == 1:
        match = matches[0]
        described = " ".join(
            [payload.tipo_producto or "", payload.material or "", *payload.medidas_visibles,
             payload.presentacion_uso or "", payload.color_acabado or ""]
        ).strip()
        distinguished = is_distinguished(described, described, match, matches)

        if distinguished:
            turn_qtys = quantities_in_message(clean_user)
            valid_qtys = [q for q in turn_qtys if 1 <= q <= MAX_QUANTITY]

            # 3A. Salto determinista si el usuario especificó cantidad
            if len(valid_qtys) == 1:
                quantity = valid_qtys[0]
                quote_args = {"lines": [{"sku": match.sku, "quantity": quantity}]}
                if tool_executor is not None:
                    quote_resp = execute_safely(tool_executor, "calcular_cotizacion_informativa", quote_args)
                else:
                    total = match.price_cop * quantity
                    quote_resp = {
                        "status": "ok",
                        "data": {
                            "lines": [{"sku": match.sku, "name": match.name, "variant": match.variant,
                                       "unit": match.unit, "quantity": quantity, "price_cop": match.price_cop,
                                       "subtotal_cop": total}],
                            "total_cop": total,
                        },
                    }

                total_cop = (quote_resp.get("data") or {}).get("total_cop", match.price_cop * quantity)
                quote_call: ToolCall = {
                    "step": 2,
                    "requested_tool": "calcular_cotizacion_informativa",
                    "requested_arguments": quote_args,
                    "executed": True,
                    "arguments": quote_args,
                    "response": quote_resp,
                    "duration_ms": 1,
                }

                answer = (
                    f"Te cotizo {quantity} {match.unit} de {match.name} ({match.variant}): "
                    f"${total_cop:,.0f} COP. Precios y existencias de demostración. "
                    "La cotización es informativa y no aparta el producto."
                )
                head = payload.tipo_producto or match.name.split()[0].lower()
                specs = {
                    head: {
                        "material": payload.material or "",
                        "medida": match.variant,
                        "presentacion": payload.presentacion_uso or "",
                    }
                }
                product_dict = {"sku": match.sku, "nombre": match.name, "variante": match.variant, "unidad": match.unit}
                shopping = [{"sku": match.sku, "nombre": match.name, "variante": match.variant,
                             "unidad": match.unit, "cantidad": quantity}]

                return {
                    "respuesta": answer,
                    "estado": "answered",
                    "model_called": False,
                    "model_calls": 0,
                    "tool_calls": [search_call, quote_call],
                    "products": [product_dict],
                    "shopping": shopping,
                    "options": [],
                    "specs": specs,
                }

            # 3B. Coincidencia única pero sin cantidad dicha por el cliente
            # Respeta QUANTITY_NOT_GROUNDED: no asume cantidad arbitraria
            stock_msg = f"Tenemos {match.stock} {match.unit} disponibles." if match.stock > 0 else "Actualmente está agotado."
            answer = (
                f"Identifiqué en la foto {match.name} ({match.variant}). {stock_msg} "
                "¿Cuántas unidades necesitas cotizar?"
            )
            head = payload.tipo_producto or match.name.split()[0].lower()
            specs = {
                head: {
                    "material": payload.material or "",
                    "medida": match.variant,
                    "presentacion": payload.presentacion_uso or "",
                }
            }
            product_dict = {"sku": match.sku, "nombre": match.name, "variante": match.variant, "unidad": match.unit}

            return {
                "respuesta": answer,
                "estado": "answered",
                "model_called": False,
                "model_calls": 0,
                "tool_calls": [search_call],
                "products": [product_dict],
                "shopping": [],
                "options": [],
                "specs": specs,
            }

    # 4. Ambigüedad o variantes cercanas
    options_candidates = matches if matches else nearby
    if not options_candidates:
        fallback_msg = SCREW_SAFEGUARD_TEMPLATE if is_screw_query else SAMPLE_COUNTER_TEMPLATE
        return {
            "respuesta": fallback_msg,
            "estado": "answered",
            "model_called": False,
            "model_calls": 0,
            "tool_calls": [search_call],
            "products": [],
            "shopping": [],
            "options": [],
            "specs": {},
        }

    # Revisar tope de aclaraciones
    existing_specs = (context or {}).get("especificaciones") or {}
    prior_clarifications = int(existing_specs.get("_vision_clarifications", {}).get("medida", 0))

    if prior_clarifications >= MAX_VISION_CLARIFICATIONS:
        # Fallo seguro R2 tras agotar el tope de 2 aclaraciones
        return {
            "respuesta": SAMPLE_COUNTER_TEMPLATE,
            "estado": "answered",
            "model_called": False,
            "model_calls": 0,
            "tool_calls": [search_call],
            "products": [],
            "shopping": [],
            "options": [],
            "specs": existing_specs,
        }

    # Desambiguación guiada
    top_options = options_candidates[:3]
    opt_lines = [f"{i}. {opt.name} ({opt.variant})" for i, opt in enumerate(top_options, start=1)]
    term = payload.tipo_producto or "el artículo"
    mat = f" de {payload.material}" if payload.material else ""
    answer = (
        f"Identifiqué {term}{mat} en la foto. En catálogo tenemos estas opciones disponibles:\n"
        + "\n".join(opt_lines)
        + "\n¿Cuál de estas medidas o variantes es la que necesitas?"
    )

    head = payload.tipo_producto or top_options[0].name.split()[0].lower()
    specs = {
        head: {
            "material": payload.material or "",
            "presentacion": payload.presentacion_uso or "",
        },
        "_vision_clarifications": {
            "medida": str(prior_clarifications + 1),
            "material": payload.material or "",
            "presentacion": payload.presentacion_uso or "",
        },
    }
    session_options = [
        {
            "grupo": f"Opciones para {term}",
            "opciones": [
                {"sku": opt.sku, "nombre": opt.name, "variante": opt.variant, "unidad": opt.unit}
                for opt in top_options
            ],
            "restantes": [
                {"sku": opt.sku, "nombre": opt.name, "variante": opt.variant, "unidad": opt.unit}
                for opt in options_candidates[3:]
            ],
        }
    ]

    return {
        "respuesta": answer,
        "estado": "answered",
        "model_called": False,
        "model_calls": 0,
        "tool_calls": [search_call],
        "products": [
            {"sku": opt.sku, "nombre": opt.name, "variante": opt.variant, "unidad": opt.unit}
            for opt in top_options
        ],
        "shopping": [],
        "options": session_options,
        "specs": specs,
    }
