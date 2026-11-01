"""El recorrido de una foto del cliente, para el diagrama del visor: etapas, carriles, datos y salidas.

Cada etapa nombra la función que la hace (``code``, «módulo:nombre») y saca sus límites de las constantes del código;
``tests/test_harness_info.py`` importa cada función y compara los códigos de rechazo con ``photo.py``, para que el
diagrama no describa algo que ya no existe. El visor lo dibuja con ``foto-flujo.js`` y marca, con los eventos de la
traza (``vision``, ``route`` con ``foto``, ``node`` y ``session``), por dónde pasó la última foto.

Carriles: ``cliente`` (el navegador), ``servidor`` (reglas del código) y ``grok`` (lo único que decide el modelo).
Cada etapa dice qué base lee o escribe (``data``); las bases son tres: el manifiesto de fotos, el catálogo SQLite en
solo lectura y la sesión, que guarda solo la referencia corta.
"""

from asistendero.agente.entrada.injection import INJECTION_CODES
from asistendero.agente.flujo.graph import MAX_TOOL_CALLS
from asistendero.agente.respuesta.reply_photos import MAX_REPLY_PHOTOS
from asistendero.agente.vision.look import IMAGE_DETAIL, VISION_MAX_TOKENS
from asistendero.agente.vision.photo import JPEG_QUALITY, MAX_PHOTO_BYTES, MAX_PHOTO_PIXELS, VISION_SIDE
from asistendero.agente.vision.photo_planner import GUESSED
from asistendero.tienda.catalogo.product_photos import SAME_PHOTO_DISTANCE, manifest

# El visor reduce la foto en el navegador antes de mandarla (``app.js``, ``maxDim``); la prueba lo compara.
BROWSER_SIDE = 1024
REJECTIONS = ["PHOTO_TOO_LARGE", "PHOTO_FORMAT", "PHOTO_UNREADABLE"]
# Cómo se nombra en el diagrama cada campo que Grok supone; un campo nuevo en ``GUESSED`` falla aquí hasta nombrarlo.
GUESSED_LABELS = {"material": "material", "presentacion_uso": "uso", "color_acabado": "color"}

STORES = [
    {"id": "fotos", "title": "Fotos del catálogo", "code": "datos/fotos/fotos.json",
     "does": "Una foto libre por familia de producto, con su huella de 64 bits, su licencia y su autor.",
     "mode": "Solo lectura"},
    {"id": "catalogo", "title": "Catálogo SQLite", "code": "mock_catalog_s3.sqlite3 · mode=ro",
     "does": "Productos, precios y existencias del negocio y la sede que fija el servidor.",
     "mode": "Solo lectura, consultas parametrizadas"},
    {"id": "sesion", "title": "Sesión de la conversación", "code": "sessions.sqlite3",
     "does": "El turno con la referencia corta «[Foto: …]»; nunca los bytes ni el base64 de la foto.",
     "mode": "Escritura del turno filtrado"},
]


def _stages() -> list[dict]:
    photos = len(manifest())
    megabytes = f"{MAX_PHOTO_BYTES / 1_000_000:g}".replace(".", ",")
    labels = [GUESSED_LABELS[field] for field in GUESSED]
    guessed = ", ".join(labels[:-1]) + " y " + labels[-1]
    return [
        {"id": "envio", "lane": "cliente", "title": "El visor reduce y envía", "code": "entregas/web/visor/app.js",
         "does": f"El navegador reduce la foto a {BROWSER_SIDE} px de lado mayor y la manda como JPEG en base64 junto "
                 "al texto del cliente.",
         "data": [], "exit": None},
        {"id": "texto", "lane": "servidor", "title": "Revisa el texto que acompaña",
         "code": "asistendero.agente.entrada.injection:detect_injection",
         "does": "Antes de abrir la foto: el base64 que venga pegado se quita del mensaje y el texto se revisa contra "
                 f"las {len(INJECTION_CODES)} familias de inyección.",
         "data": [], "exit": {"codes": sorted(INJECTION_CODES),
                              "text": "La foto no se mira: el grafo bloquea y banea sin llamar a Grok."}},
        {"id": "limpieza", "lane": "servidor", "title": "Valida y limpia la foto",
         "code": "asistendero.agente.vision.photo:read_photo",
         "does": f"Solo JPEG, PNG o WebP adjuntos (nunca un enlace), hasta {megabytes} MB y "
                 f"{MAX_PHOTO_PIXELS // 1_000_000} MP. Se vuelve a guardar como JPEG {JPEG_QUALITY} sin EXIF ni "
                 f"ubicación y se reduce a {VISION_SIDE} px.",
         "data": [], "exit": {"codes": REJECTIONS, "text": "Respuesta fija sin Grok que dice qué hacer."}},
        {"id": "huella", "lane": "servidor", "title": "Compara la huella",
         "code": "asistendero.tienda.catalogo.product_photos:closest_family",
         "does": f"dHash de 64 bits contra las {photos} fotos del catálogo. A {SAME_PHOTO_DISTANCE} bits o menos, y "
                 "con una sola familia al alcance, se sabe qué es sin llamar a Grok.",
         "data": [{"store": "fotos", "mode": "lee"}], "exit": None},
        {"id": "vision", "lane": "grok", "title": "Grok mira la foto", "code": "asistendero.agente.vision.look:look_at",
         "does": f"Una sola llamada, con la foto en detalle «{IMAGE_DETAIL}» y hasta {VISION_MAX_TOKENS} tokens de "
                 "salida: un JSON con tipo, material, medidas visibles, uso, color y confianza. Grok no elige SKU, "
                 "precio ni existencias.",
         "data": [], "exit": {"codes": ["MODEL_*"], "text": "Pide la muestra en el mostrador; no inventa."}},
        {"id": "respaldo", "lane": "servidor", "title": "Deja solo lo que el catálogo respalda",
         "code": "asistendero.agente.vision.photo_planner:backed_payload",
         "does": f"Lo que Grok supone ({guessed}) se queda solo si con eso sigue habiendo un producto exacto; si no, "
                 "se descarta para no convertir el producto pedido en uno cercano.",
         "data": [{"store": "catalogo", "mode": "lee"}], "exit": None},
        {"id": "grafo", "lane": "servidor", "title": "El harness busca y verifica",
         "code": "asistendero.agente.vision.photo_planner:PhotoPlanner",
         "does": "La consulta sigue como texto (mensaje más «[Foto: …]») por el mismo grafo: Puerta, un planificador "
                 "del servidor en lugar de Grok, la aduana valida "
                 f"la búsqueda, la bodega la ejecuta (máximo {MAX_TOOL_CALLS} herramientas) y la balanza comprueba "
                 "cada $, SKU y cantidad.",
         "data": [{"store": "catalogo", "mode": "lee"}], "exit": None},
        {"id": "memoria", "lane": "servidor", "title": "Guarda la referencia, no la foto",
         "code": "asistendero.agente.conversacion.sessions:SessionStore",
         "does": "La sesión guarda el turno con «[Foto: …]» en lugar de la foto: el turno siguiente lo lee como "
                 "cualquier otro texto y la caché del prompt no se rompe.",
         "data": [{"store": "sesion", "mode": "escribe"}], "exit": None},
        {"id": "respuesta", "lane": "cliente", "title": "Responde con fotos de referencia",
         "code": "asistendero.agente.respuesta.reply_photos:reply_photos",
         "does": f"Hasta {MAX_REPLY_PHOTOS} fotos de los productos que salieron de las herramientas, con su crédito; "
                 "el visor solo sirve archivos del manifiesto.",
         "data": [{"store": "fotos", "mode": "lee"}], "exit": None},
    ]


EDGES = [
    ("envio", "texto", "foto + texto"),
    ("texto", "limpieza", "sin inyección"),
    ("limpieza", "huella", "JPEG limpio"),
    ("huella", "respaldo", "la reconoce: 0 llamadas"),
    ("huella", "vision", "no la reconoce"),
    ("vision", "respaldo", "atributos"),
    ("respaldo", "grafo", "consulta + [Foto: …]"),
    ("grafo", "memoria", "turno filtrado"),
    ("memoria", "respuesta", "respuesta verificada"),
]


LANES = [
    {"id": "cliente", "title": "Cliente", "does": "Lo que pasa en el navegador"},
    {"id": "servidor", "title": "Servidor", "does": "Reglas del código, sin modelo"},
    {"id": "grok", "title": "Grok", "does": "Lo único que decide el modelo"},
]


def describe_photo_flow() -> dict:
    """Etapas, conexiones y bases del recorrido de una foto; sin rutas del disco ni datos del cliente."""
    return {"lanes": LANES, "stages": _stages(), "stores": STORES,
            "edges": [{"from": start, "to": end, "label": label} for start, end, label in EDGES],
            "limits": {"browser_side": BROWSER_SIDE, "max_bytes": MAX_PHOTO_BYTES, "vision_side": VISION_SIDE,
                       "fingerprint_distance": SAME_PHOTO_DISTANCE, "vision_max_tokens": VISION_MAX_TOKENS,
                       "photos": len(manifest()), "reply_photos": MAX_REPLY_PHOTOS}}
