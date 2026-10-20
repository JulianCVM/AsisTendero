# AsisTendero

**AsisTendero** es un agente conversacional basado en Grok que busca ayudar a ferreterías y tiendas de barrio colombianas a atender consultas y operar con información confiable. Forma parte de **PulsoTienda**, el nombre de trabajo de una plataforma para conectar conversaciones, catálogo, inventario y decisiones del comercio.

Este repositorio contiene una **primera versión ejecutable**: recibe mensajes escritos, interpreta lo que necesita el cliente, consulta un catálogo ficticio de ferretería cuando hace falta y responde con los productos encontrados. También incluye una interfaz local para explorar cada ejecución. El piloto con un comercio real y las funciones comerciales más amplias siguen en definición y desarrollo.

## El problema

En muchos comercios pequeños, los productos, precios, existencias y conversaciones se gestionan entre cuadernos, mensajes y la memoria de quienes atienden. Cuando alguien pregunta por un artículo específico, puede ser difícil identificar la variante correcta y responder con un dato actualizado. Esta es la situación que motiva el proyecto; su frecuencia e impacto deberán validarse con el comercio piloto.

La visión de PulsoTienda es que el agente pueda acompañar el recorrido comercial y apoyar al dueño en la operación diaria. La primera etapa se concentra en una pregunta básica: **¿puede entender una solicitud de un cliente, buscar únicamente lo pertinente y contestar sin inventar productos, precios ni disponibilidad?**

El primer piloto previsto es una ferretería de una sede. El establecimiento, su catálogo y sus datos aún no están definidos; por eso esta versión trabaja con seis productos de demostración.

## Qué hace hoy

- Recibe consultas de texto desde la terminal o desde un visor web local.
- Usa Grok para interpretar el mensaje antes de decidir si necesita consultar productos.
- Descompone una solicitud de hasta cinco artículos en criterios como tipo de producto, material, medida, uso, presentación y cantidad.
- Busca coincidencias acotadas en SQLite. Si falta una variante, pide precisión; si la medida solicitada no existe, puede mostrar unas pocas opciones cercanas sin tratarlas como equivalentes.
- Responde preguntas generales que no necesitan catálogo. Por ejemplo, si preguntan si la tienda está atendiendo, indica que no hay un horario verificado.
- Comprueba los SKU, precios y existencias de las respuestas de producto contra el catálogo de prueba.
- Muestra en el visor la ruta seguida, las llamadas al modelo y el costo por ejecución cuando la API lo informa o es posible estimarlo con una tarifa de referencia.

El catálogo, los precios y las existencias de esta versión son **ficticios**. La cantidad que escribe el cliente se conserva como contexto de la consulta, pero el agente todavía no arma pedidos ni reserva unidades.

## Cómo funciona

```text
Mensaje del cliente
       │
       ▼
Validación de entrada
       │
       ▼
Grok interpreta la intención y estructura la solicitud
       │
       ├── Pregunta general ────────────────┐
       │                                    │
       └── Consulta de productos            │
                    │                       │
                    ▼                       │
           Código consulta SQLite           │
                    │                       │
                    ▼                       │
           Grok recibe los hallazgos        │
                    └──────────┬────────────┘
                               ▼
                    Respuesta verificada
```

Grok decide **qué información necesita** y solicita la búsqueda mediante una estructura de parámetros. El código ejecuta esa búsqueda con reglas propias; el modelo no tiene acceso SQL libre. En una consulta de productos, Grok suele intervenir dos veces: para interpretar la solicitud y para responder con los resultados. Una pregunta general suele necesitar una llamada. Si la redacción propuesta por el modelo no conserva los hechos comprobables, el código genera una respuesta basada en los datos recuperados.

Por ejemplo, ante «Busco tubo PVC de 1/2 para agua y un bulto de cemento gris de 50 kg», el agente puede separar ambos artículos y encontrar `PVC-050` y `CEM-050` en el catálogo de demostración. Ante «Busco tubo PVC de 1 pulgada», indica que no encontró esa medida exacta y muestra únicamente las medidas cercanas disponibles, sin afirmar que cumplen el mismo propósito.

## Tecnologías

| Componente | Uso en esta versión |
| --- | --- |
| **Python 3.11+** | Lógica del agente, catálogo, comandos y servidor local. |
| **LangGraph** | Orquesta validación, interpretación, búsqueda y respuesta. |
| **Grok** | Interpreta las consultas y redacta respuestas mediante una API de Chat Completions compatible con OpenAI. |
| **SQLite** | Catálogo ficticio de una ferretería de demostración; consultas de solo lectura durante la conversación. |
| **HTML, CSS y JavaScript** | Visor local de conversación, pasos y costos. |
| **pytest** | Pruebas automatizadas con Grok simulado. |
| **Docker** | Dockerfile disponible para ejecutar el prototipo en un contenedor. |

La integración predeterminada usa `https://api.reto.pltk.mx/v1` y el modelo indicado en [`.env.example`](.env.example). Ambos valores se pueden configurar.

## Instalación

Necesitas Python 3.11 o superior, conexión a la API y una clave de Grok válida para el endpoint configurado. Desde la raíz del repositorio, en **Windows PowerShell**:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

En **macOS o Linux**:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -e ".[dev]"
cp .env.example .env
```

Abre `.env` y asigna tu clave:

```dotenv
GROK_API_KEY=tu_clave
GROK_MODEL=grok-4.20-0309-non-reasoning
GROK_BASE_URL=https://api.reto.pltk.mx/v1
```

`.env` está excluido de Git. No subas la clave al repositorio ni la compartas en capturas o trazas. Cada consulta real puede consumir cupo o créditos.

**Crea el catálogo una sola vez:**

```powershell
.\.venv\Scripts\python.exe -m asistendero.seed
```

En macOS o Linux, sustituye `.\.venv\Scripts\python.exe` por `./.venv/bin/python` en los comandos siguientes. La base se crea en `.local/mock_catalog.sqlite3`; el comando de carga se detiene si ya existe para no sobrescribirla.

## Uso

### Terminal

```powershell
.\.venv\Scripts\python.exe -m asistendero "Busco tubo PVC de 1/2 para agua y un bulto de cemento gris de 50 kg"
```

También puedes probar una pregunta sin búsqueda de productos:

```powershell
.\.venv\Scripts\python.exe -m asistendero "Hola, ¿están atendiendo en este momento?"
```

La redacción puede variar entre llamadas. El agente debe distinguir los datos ficticios de los reales y no afirmar un horario que no se le ha proporcionado.

### Visor local

```powershell
.\.venv\Scripts\python.exe -m asistendero.visual
```

Abre [http://127.0.0.1:8765/](http://127.0.0.1:8765/) en el navegador. El visor solo escucha en `127.0.0.1` y permite observar la conversación, los pasos del agente y la traza de cada ejecución. Los costos se distinguen entre **valor informado por la API** y **estimación con tarifas públicas de referencia**; una estimación no confirma el cobro de la pasarela del reto. Detén el servidor con `Ctrl+C`. Consulta [los detalles del visor](docs/HARNESS.md).

### Docker

El repositorio incluye un Dockerfile que instala el paquete y crea el catálogo de prueba durante la construcción:

```powershell
docker build -t asistendero .
docker run --rm --env-file .env asistendero "Busco tubo PVC de 1/2 para agua"
```

Esta ruta de ejecución está disponible en el proyecto; las verificaciones documentadas de este corte se realizaron con Python local.

## Pruebas y evidencia

Ejecuta las pruebas automatizadas sin llamar a Grok:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

La [verificación de búsqueda estructurada](evaluation/VERIFICACION_BUSQUEDA_ESTRUCTURADA.md) registra cuatro escenarios con llamadas reales: varios productos, una medida ausente, una descripción parcial y una pregunta por horario. Los casos son evidencia del flujo funcional; no constituyen una medida general de precisión. La [evidencia inicial de Semana 1](EVIDENCIA_SEMANA1.md) conserva una versión anterior del agente.

También existe un [conjunto de casos sintéticos](evaluation/cases.json) y un comando de evaluación que **solo llama a Grok si se usa `--live`**:

```powershell
.\.venv\Scripts\python.exe -m asistendero.evaluate --live --limit 4
```

Ese comando consume cupo y guarda el reporte localmente en `.local/`.

## Estructura del repositorio

| Ruta | Contenido |
| --- | --- |
| `src/asistendero/graph.py` | Flujo LangGraph: Grok decide, el servidor ejecuta y se responde. |
| `src/asistendero/validation.py` | Reglas que una solicitud de Grok cumple antes de ejecutarse. |
| `src/asistendero/observations.py` y `executor.py` | Lectura de las respuestas de herramientas y conexión con el ejecutor real. |
| `src/asistendero/answers.py` | Respuesta final verificada contra lo que devolvieron las herramientas. |
| `src/asistendero/grok.py` | Instrucciones del agente e integración con Grok. |
| `src/asistendero/search.py` y `catalog.py` | Contrato de búsqueda y lectura del catálogo SQLite. |
| `src/asistendero/seed.py` | Datos ficticios para la demostración. |
| `src/asistendero/visual.py` y `ui/` | Servidor y visor local. |
| `src/asistendero/tracing.py` y `pricing.py` | Trazas, uso y costos de ejecución. |
| `tests/` | Pruebas automatizadas. |
| `evaluation/` | Casos y evidencia de verificaciones. |
| `docs/` | Notas técnicas del prototipo. |
| `PLANIFICACION.md` y `DESIGN.md` | Backlog e identidad visual del visor. |

## Estado y próximos pasos

Este prototipo **no está conectado a un comercio real**. Aún no integra WhatsApp, Supabase, Wompi, DIAN ni Platica.mx; tampoco gestiona pedidos, pagos, fiados, compras a proveedores o memoria persistente de conversaciones. El panel comercial, el aislamiento entre negocios y las aprobaciones por rol pertenecen al desarrollo posterior. La ferretería piloto y las reglas operativas deben definirse con sus responsables.

La visión y las tareas están organizadas en [PLANIFICACION.md](PLANIFICACION.md) y en el [tablero de PulsoTienda](https://github.com/users/JulianCVM/projects/9). El diseño aplicado al visor se documenta en [DESIGN.md](DESIGN.md). Las decisiones de dinero o crédito deberán quedar bajo autorización del dueño o de un rol delegado, y una confirmación de pago requerirá una fuente verificable.

## Relación con el Agent Challenge

AsisTendero nació como proyecto del Agent Challenge. Esta primera entrega demuestra el recorrido **mensaje → Grok → procesamiento → respuesta** con una clave de API real y un catálogo de prueba. El [repositorio público](https://github.com/JulianCVM/AsisTendero) y la documentación permiten seguir su evolución; las funciones descritas como próximas no se presentan como parte del flujo ya implementado.
