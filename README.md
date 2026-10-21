# AsisTendero

**AsisTendero** es un agente conversacional basado en Grok que busca ayudar a ferreterías y tiendas de barrio colombianas a atender consultas y operar con información confiable. Forma parte de **PulsoTienda**, el nombre de trabajo de una plataforma para conectar conversaciones, catálogo, inventario y decisiones del comercio.

Este repositorio contiene una **versión ejecutable del corte S2**: recibe mensajes escritos y deja que Grok decida cuál de **tres herramientas del servidor** necesita (buscar productos, consultar disponibilidad y calcular una cotización informativa). El servidor valida cada solicitud antes de ejecutarla sobre un catálogo ficticio de ferretería y responde solo con datos comprobados. También incluye una interfaz local para explorar cada ejecución y un mapa del harness que explica el flujo. El piloto con un comercio real y las funciones comerciales más amplias siguen en definición y desarrollo.

## El problema

En muchos comercios pequeños, los productos, precios, existencias y conversaciones se gestionan entre cuadernos, mensajes y la memoria de quienes atienden. Cuando alguien pregunta por un artículo específico, puede ser difícil identificar la variante correcta y responder con un dato actualizado. Esta es la situación que motiva el proyecto; su frecuencia e impacto deberán validarse con el comercio piloto.

La visión de PulsoTienda es que el agente pueda acompañar el recorrido comercial y apoyar al dueño en la operación diaria. La primera etapa se concentra en una pregunta básica: **¿puede entender una solicitud de un cliente, buscar únicamente lo pertinente y contestar sin inventar productos, precios ni disponibilidad?**

El primer piloto previsto es una ferretería de una sede. El establecimiento, su catálogo y sus datos aún no están definidos; por eso esta versión trabaja con seis productos de demostración.

## Qué hace hoy

- Recibe consultas de texto desde la terminal o desde un visor web local.
- Usa Grok para decidir, paso a paso, si responde o pide una de tres herramientas:
  - `buscar_productos`: hasta cinco artículos por llamada, con criterios como tipo de producto, material, medida, uso y presentación.
  - `consultar_disponibilidad`: existencias de un SKU.
  - `calcular_cotizacion_informativa`: precio, subtotales y total en COP con las cantidades que dijo el cliente.
- Valida cada solicitud de Grok **antes** de ejecutarla:
  - herramienta permitida y argumentos dentro de sus límites;
  - SKU que salió de una búsqueda y que el mensaje distingue;
  - cantidad que el cliente expresó;
  - como máximo seis herramientas por ejecución.

  Si la rechaza, la herramienta no corre y Grok recibe el código.
- Si falta una variante, pide precisión; si la medida no existe, muestra opciones cercanas sin tratarlas como equivalentes; si no hay existencias suficientes, dice cuánto hay.
- Responde preguntas generales que no necesitan catálogo. Por ejemplo, si preguntan si la tienda está atendiendo, indica que no hay un horario verificado.
- Usa la redacción de Grok solo si cada precio, SKU y cantidad coincide con lo que devolvieron las herramientas; si no, responde con los datos del catálogo.
- Termina cada fallo (catálogo caído, timeout, cuota, salida inválida, tope de herramientas) en un estado seguro con código, sin inventar precio ni existencias.
- Muestra en el visor la ruta seguida, las llamadas al modelo, las herramientas pedidas y ejecutadas, el costo por ejecución y un mapa del harness con las seis etapas del flujo.

El catálogo, los precios y las existencias de esta versión son **ficticios**. La cotización es **informativa**: no crea pedidos, reservas, pagos ni facturas (`reservation_created=false`).

## Cómo funciona

```text
Mensaje del cliente
       │
       ▼
1. validate ── texto no vacío, máximo 2.000 caracteres
       │
       ▼
2. interpret ── Grok lee su prompt + mensaje + observaciones ◄─────────┐
       │        y devuelve JSON: respond o call_tool                   │
       ▼                                                               │
3. next_node ── call_tool ─► 4. retrieve: el servidor valida la        │
       │                       solicitud y, si la acepta, ejecuta la   │
       │                       herramienta en SQLite (solo lectura) ───┘
       │
       ├── respond sin cotizar con cantidad dicha ─► vuelve a 2 una vez con el aviso QUOTE_REQUIRED
       │
       ▼
5. respond ── verifica la redacción de Grok o arma la respuesta con los datos
       │
       ▼
6. estado ── quoted, found, clarify, nearby, insufficient_stock… o un fallo controlado
```

**Grok decide** qué información necesita y **el servidor ejecuta**: el modelo no tiene acceso SQL libre, no elige negocio ni sede y no puede imponer precio ni existencias. Una pregunta general suele necesitar una llamada a Grok; una cotización de un producto, unas cuatro (buscar, consultar, cotizar y responder). El detalle del contrato, las barreras y los códigos está en [docs/HARNESS.md](docs/HARNESS.md), y el visor lo muestra en su sección **Mapa del harness**.

Por ejemplo, ante «Necesito 2 metros de tubo PVC de 1/2 para agua y 1 bulto de cemento gris de 50 kg», el agente busca ambos artículos, consulta `PVC-050` y `CEM-050` y entrega un total informativo de $56.500 COP con datos de demostración. Ante «Busco tubo PVC de 1 pulgada», indica que no encontró esa medida exacta y muestra las medidas cercanas sin afirmar que sirven para lo mismo. Ante «20 metros de PVC de 1/2», la cotización detecta que solo hay 12 y lo dice.

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

Abre [http://127.0.0.1:8765/](http://127.0.0.1:8765/) en el navegador. El visor solo escucha en `127.0.0.1` y permite observar la conversación, los pasos del agente y la traza de cada ejecución. El **Mapa del harness** explica en qué etapa Grok recibe sus instrucciones, qué decide, qué reglas aplica el servidor y cómo se clasifica el resultado, y marca el recorrido de la última prueba. Los costos se distinguen entre **valor informado por la API** y **estimación con tarifas públicas de referencia**; una estimación no confirma el cobro de la pasarela del reto. Detén el servidor con `Ctrl+C`. Consulta [los detalles del visor](docs/HARNESS.md).

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

La [evidencia S2](evaluation/S2_EVIDENCIA.md) registra las corridas reales con Grok de los diez casos `S2-01` a `S2-10` y de dos fallos controlados (catálogo inaccesible y modelo inaccesible), con `run_id`, tokens, latencia y costo informado por la API. Con `s2-tools-v1` pasaron 7 de 10 casos y los dos fallos. Los tres que fallaron se corrigieron en `s2-tools-v2` y pasaron 3 de 3 al volver a ejecutarlos. La corrida de los diez casos sobre un mismo commit con `s2-tools-v2` está pendiente. Los casos son evidencia del flujo funcional; no constituyen una medida general de precisión. Las verificaciones de [búsqueda estructurada](evaluation/VERIFICACION_BUSQUEDA_ESTRUCTURADA.md) y de [Semana 1](EVIDENCIA_SEMANA1.md) corresponden a versiones anteriores del agente.

El comando de evaluación usa los [casos](evaluation/cases.json) y **solo llama a Grok si se usa `--live`**:

```powershell
.\.venv\Scripts\python.exe -m asistendero.evaluate --live --include-failures
.\.venv\Scripts\python.exe -m asistendero.evaluate --live --skip S2-02 S2-03   # omite casos ya verificados
```

Ese comando consume cupo y guarda el reporte, con los eventos completos de cada caso, en `.local/`.

## Estructura del repositorio

| Ruta | Contenido |
| --- | --- |
| `src/asistendero/graph.py` | Flujo LangGraph: Grok decide, el servidor ejecuta y se responde. |
| `src/asistendero/validation.py` | Reglas que una solicitud de Grok cumple antes de ejecutarse. |
| `src/asistendero/observations.py` y `executor.py` | Lectura de las respuestas de herramientas y conexión con el ejecutor real. |
| `src/asistendero/answers.py` | Respuesta final verificada contra lo que devolvieron las herramientas. |
| `src/asistendero/grok.py` | Instrucciones del agente e integración con Grok. |
| `src/asistendero/tools.py` | Las tres herramientas del servidor (`execute_tool`) sobre el catálogo. |
| `src/asistendero/search.py` y `catalog.py` | Contrato de búsqueda y lectura del catálogo SQLite. |
| `src/asistendero/evaluate.py` | Evaluador de casos y fallos controlados. |
| `src/asistendero/harness_info.py` | Datos del mapa del harness que muestra el visor. |
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

AsisTendero nació como proyecto del Agent Challenge. El corte S1 demostró el recorrido **mensaje → Grok → procesamiento → respuesta**. El corte S2 agrega tres herramientas reales del servidor, el manejo de errores y las corridas registradas en la evidencia, con una clave de API real y un catálogo de prueba. El [repositorio público](https://github.com/JulianCVM/AsisTendero) y la documentación permiten seguir su evolución; las funciones descritas como próximas no se presentan como parte del flujo ya implementado.

## Licencia

Código bajo [licencia MIT](LICENSE). Según las reglas del reto, Platica recibe una licencia no exclusiva y la titularidad del código sigue siendo de sus autores. Los datos del catálogo de demostración son ficticios.
