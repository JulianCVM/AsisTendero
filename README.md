# AsisTendero · harness experimental con LangGraph y Grok

AsisTendero es el agente de **PulsoTienda**, una propuesta para ayudar a ferreterías y tiendas de barrio colombianas a atender consultas y coordinar ventas sin perder el control humano de inventario, pagos y decisiones de crédito. El primer piloto previsto es una ferretería de una sede; el comercio y sus datos aún no están definidos.

## Qué hace esta versión

Recibe una consulta escrita de ferretería, recupera candidatos de una **base SQLite ficticia de solo lectura**, usa Grok para identificar una variante y compone una respuesta con los datos exactos de esa base. Si falta la medida, pregunta antes de mostrar un precio; si no hay coincidencias, lo indica. Las respuestas etiquetan los datos como simulados.

```text
consulta → validar → buscar en SQLite → Grok elige SKU o null → verificar → responder
                         └──────────── LangGraph ────────────┘
```

Esta rama es un experimento de harness derivado de `dev/julian`; [el diseño y método de evaluación](docs/HARNESS.md) explican sus límites. La [evidencia del primer flujo de Semana 1](EVIDENCIA_SEMANA1.md) queda preservada. No cierra PT-001, PT-006, PT-009, PT-031 ni PT-032. WhatsApp, Wompi, Supabase, herramientas de negocio y panel siguen pendientes. No se usan datos de un comercio real.

## Ejecutar en Windows (PowerShell)

Se necesita Python 3.11 o superior y la clave `pk_...` entregada por el reto, con acceso al modelo elegido. Desde esta carpeta:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m asistendero.seed
```

Edita `.env` y coloca tu propia `GROK_API_KEY`. La URL predeterminada es `https://api.reto.pltk.mx/v1`. El modelo inicial para este harness es `grok-4.20-0309-non-reasoning`, disponible para la clave del reto consultada el 15 de octubre; `GROK_MODEL` permite comparar otro modelo. **No subas `.env` ni la clave al repositorio.** Si tienes Python 3.11, 3.12 o 3.13, cambia `-3.14` por tu versión disponible.

Si tu instalación de Python falla al ejecutar `ensurepip` durante la creación del entorno, usa `py -3.14 -m venv --without-pip .venv` y después `py -3.14 -m pip --python .venv install -e ".[dev]"`.

```powershell
.\.venv\Scripts\python.exe -m asistendero "Busco tubo PVC de 1/2 para agua"
```

La salida mostrará el precio y stock **simulados** del SKU `PVC-050`. Grok decide qué variante corresponde; el código toma precio y stock de SQLite y rechaza un SKU inventado. Si falta la clave o la base mock, el comando falla con una indicación clara. La llamada real consume cupo o créditos del reto.

## Ejecutar con Docker

```powershell
docker build -t asistendero-semana1 .
docker run --rm --env-file .env asistendero-semana1 "Necesito un tubo PVC para agua"
```

Docker crea la base ficticia durante la construcción y usa la clave local del archivo ignorado por Git. Este contenedor ejecuta solo el flujo de terminal; no conecta servicios reales.

## Verificación y evidencia

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m asistendero.evaluate --live --limit 4
```

`pytest` comprueba las reglas con un modelo simulado sin gasto. El evaluador con `--live` usa cuatro casos ficticios y genera un reporte local en `.local/`; sin esa opción no llama al modelo. En este Windows restringido, si `pytest` no puede crear su temporal del sistema, usa `--basetemp=.tmp/pytest`. El repositorio público es [JulianCVM/AsisTendero](https://github.com/JulianCVM/AsisTendero).

## Estructura

- `src/asistendero/graph.py`: estados, rutas y barreras de LangGraph.
- `src/asistendero/catalog.py` y `seed.py`: lectura de SQLite y datos ficticios.
- `src/asistendero/grok.py`: instrucciones versionadas y decisión estructurada.
- `src/asistendero/cli.py`: entrada y salida por terminal.
- `evaluation/` y `tests/`: evaluación real explícita y pruebas locales sin API.

## Fuentes de diseño

- [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [xAI Chat Completions](https://docs.x.ai/developers/model-capabilities/legacy/chat-completions)
- [PT-006: contratos de herramientas](https://github.com/JulianCVM/AsisTendero/issues/6) y [PT-009: base del proyecto](https://github.com/JulianCVM/AsisTendero/issues/9). Sus alcances completos son posteriores a este flujo mínimo.
