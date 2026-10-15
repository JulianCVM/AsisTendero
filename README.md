# AsisTendero · primer flujo de Semana 1

AsisTendero es el agente de **PulsoTienda**, una propuesta para ayudar a ferreterías y tiendas de barrio colombianas a atender consultas y coordinar ventas sin perder el control humano de inventario, pagos y decisiones de crédito. El primer piloto previsto es una ferretería de una sede; el comercio y sus datos aún no están definidos.

## Qué hace esta versión

Recibe una consulta escrita de un cliente de ferretería, la pasa por un grafo de LangGraph, llama **realmente** a Grok mediante la pasarela del reto y muestra la respuesta. Por ejemplo: «Necesito un tubo PVC para agua». El agente puede pedir el diámetro y otros datos que falten. No consulta todavía un catálogo ni confirma disponibilidad, precio, reservas o pagos.

```text
consulta por terminal → validar entrada → Grok (xAI) → respuesta por terminal
                         └──────────── LangGraph ────────────┘
```

Esta es una implementación parcial para el corte de Semana 1. No cierra PT-001, PT-006, PT-009 ni PT-031. WhatsApp, Wompi, Supabase, herramientas de negocio y panel siguen pendientes. El flujo no usa datos de un comercio real.

## Ejecutar en Windows (PowerShell)

Se necesita Python 3.11 o superior y la clave `pk_...` entregada por el reto, con acceso al modelo elegido. Desde esta carpeta:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Edita `.env` y coloca tu propia `GROK_API_KEY`. La URL predeterminada es `https://api.reto.pltk.mx/v1`. El modelo por defecto es `grok-4.7`; cambia `GROK_MODEL` si tu clave tiene acceso a otro modelo. La pasarela del reto se presenta como compatible con la API de xAI; la compatibilidad efectiva de esta clave y el modelo aún debe comprobarse con una llamada real. **No subas `.env` ni la clave al repositorio.** Si tienes Python 3.11, 3.12 o 3.13, cambia `-3.14` por tu versión disponible.

Si tu instalación de Python falla al ejecutar `ensurepip` durante la creación del entorno, usa `py -3.14 -m venv --without-pip .venv` y después `py -3.14 -m pip --python .venv install -e ".[dev]"`.

```powershell
.\.venv\Scripts\python.exe -m asistendero "Necesito un tubo PVC para agua"
```

La salida exacta varía porque la genera Grok. Debería responder en español y pedir una aclaración útil, sin inventar stock ni precio. Si falta la clave, el comando falla con una indicación clara. La llamada real consume el cupo o créditos asignados a la clave del reto.

## Ejecutar con Docker

```powershell
docker build -t asistendero-semana1 .
docker run --rm --env-file .env asistendero-semana1 "Necesito un tubo PVC para agua"
```

Docker usa la misma clave local del archivo ignorado por Git. Este contenedor ejecuta solo el flujo de terminal, sin base de datos ni servicios adicionales.

## Verificación y evidencia

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m asistendero "Busco tornillos para madera"
```

La prueba automatizada usa un modelo simulado para comprobar el recorrido del grafo sin gasto. **No demuestra conexión a Grok.** Para acreditar la Semana 1, ejecuta el segundo comando con una clave válida, guarda una captura o transcripción de la entrada y la respuesta (sin mostrar la clave), y publica el código en un repositorio público. Una respuesta real y un `README` público aún deben verificarse por el equipo; este documento no afirma que ya se hayan obtenido.

## Estructura

- `src/asistendero/graph.py`: estados, nodos y transiciones de LangGraph.
- `src/asistendero/grok.py`: instrucciones del agente y llamada a xAI.
- `src/asistendero/cli.py`: entrada y salida por terminal.
- `tests/test_graph.py`: comprobación local del recorrido sin API.

## Fuentes de diseño

- [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [xAI Chat Completions](https://docs.x.ai/developers/model-capabilities/legacy/chat-completions)
- [PT-006: contratos de herramientas](https://github.com/JulianCVM/AsisTendero/issues/6) y [PT-009: base del proyecto](https://github.com/JulianCVM/AsisTendero/issues/9). Sus alcances completos son posteriores a este flujo mínimo.
