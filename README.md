# AsisTendero

**AsisTendero** es un agente conversacional basado en Grok que busca ayudar a ferreterías y tiendas de barrio colombianas a atender consultas y operar con información confiable. Forma parte de **PulsoTienda**, el nombre de trabajo de una plataforma para conectar conversaciones, catálogo, inventario y decisiones del comercio.

Este repositorio contiene la **versión ejecutable del corte S3**: recibe mensajes escritos, sueltos o dentro de una conversación con memoria, y deja que Grok decida cuál de **cinco herramientas del servidor** necesita (buscar productos, consultar disponibilidad, calcular una cotización informativa, consultar la información de la tienda y explorar categorías). El servidor filtra las preguntas trampa antes de Grok, valida cada solicitud antes de ejecutarla sobre un catálogo ficticio de ferretería y responde solo con datos comprobados. También incluye una interfaz local para explorar cada ejecución, un mapa del harness y un evaluador de 43 casos con comparación de modelos y costo por tarea. El piloto con un comercio real y las funciones comerciales más amplias siguen en definición y desarrollo.

## El problema

En muchos comercios pequeños, los productos, precios, existencias y conversaciones se gestionan entre cuadernos, mensajes y la memoria de quienes atienden. Cuando alguien pregunta por un artículo específico, puede ser difícil identificar la variante correcta y responder con un dato actualizado. Esta es la situación que motiva el proyecto; su frecuencia e impacto deberán validarse con el comercio piloto.

La visión de PulsoTienda es que el agente pueda acompañar el recorrido comercial y apoyar al dueño en la operación diaria. La primera etapa se concentra en una pregunta básica: **¿puede entender una solicitud de un cliente, buscar únicamente lo pertinente y contestar sin inventar productos, precios ni disponibilidad?**

El primer piloto previsto es una ferretería de una sede. El establecimiento, su catálogo y sus datos aún no están definidos; por eso esta versión trabaja con un catálogo de demostración de 384 variantes en 12 categorías.

## Qué hace hoy

- Recibe consultas de texto desde la terminal o desde un visor web local, sueltas o en una **conversación con memoria acotada**: Grok ve los últimos cuatro turnos sin precios y los productos ya identificados, y entiende «dame 3 metros de ese» o «¿y el de 3/4?».
- Usa Grok para decidir, paso a paso, si responde o pide una de cinco herramientas de consulta:
  - `buscar_productos`: hasta cinco artículos por llamada, con criterios como tipo de producto, material, medida, uso, presentación y color.
  - `consultar_disponibilidad`: existencias de un SKU.
  - `calcular_cotizacion_informativa`: precio, subtotales y total en COP con las cantidades que dijo el cliente.
  - `consultar_info_tienda`: horario (y si está abierta según el reloj del servidor), ubicación, medios de pago, domicilios, garantías y contacto.
  - `explorar_categoria`: las categorías del catálogo o los productos de una, sin precios.
- En una conversación, registra **pedidos para recoger**: el cliente dice que se lo lleva, Grok lo registra con el precio vigente y lo aparta 5 minutos; con su «sí» queda confirmado y apartado hasta la recogida que el cliente agenda («paso mañana a las 4», «lo recoge mi hermano»). Si nadie confirma, vence solo y el cliente recibe un aviso. El pago es en el mostrador: el chat no cobra ni fía.
- Entiende mensajes mal escritos («nesesito 3 metros de tuvo pbc de 1/2 pa l agua») sin aceptar medidas ni cantidades que el cliente no escribió.
- Filtra en código, antes de Grok, las preguntas trampa (instrucciones internas, llaves, datos técnicos, datos de otros clientes o del personal, costos y ventas del negocio) y tapa los datos personales. Si no queda nada que atender, responde sin llamar a Grok.
- Valida cada solicitud de Grok **antes** de ejecutarla:
  - herramienta permitida y argumentos dentro de sus límites;
  - SKU que salió de una búsqueda y que el mensaje distingue;
  - cantidad que el cliente expresó;
  - como máximo seis herramientas por ejecución.

  Si la rechaza, la herramienta no corre y Grok recibe el código.
- Si falta una variante, pide precisión; si la medida no existe, muestra opciones cercanas sin tratarlas como equivalentes; si no hay existencias suficientes, dice cuánto hay.
- Responde preguntas generales que no necesitan catálogo. Horario, pagos, domicilios o garantías solo se afirman si se consultaron con `consultar_info_tienda` en esa ejecución.
- Usa la redacción de Grok solo si cada precio, SKU, cantidad, hora y política coincide con lo que devolvieron las herramientas y no trae fragmentos del prompt ni datos internos; si no, responde con los datos del catálogo. Un pedido de apartar, reservar o fiar recibe siempre la aclaración de que no es pedido ni reserva.
- Termina cada fallo (catálogo caído, timeout, cuota, salida inválida, tope de herramientas) en un estado seguro con código, sin inventar precio ni existencias.
- Muestra en el visor la ruta seguida, las llamadas al modelo, las herramientas pedidas y ejecutadas, el costo por ejecución y un mapa del harness con las seis etapas del flujo.

El catálogo, los precios y las existencias de esta versión son **ficticios**. La cotización es **informativa** (`reservation_created=false`); un pedido solo existe si el cliente lo pidió y Grok lo registró, y nunca implica un pago. El tendero ve esos pedidos y administra el inventario en un panel local.

## Cómo funciona

```text
Mensaje del cliente
       │
       ▼
1. validate ── texto no vacío, máximo 2.000 caracteres; quita frases delicadas
       │        y tapa datos personales (si no queda nada: refused, sin Grok)
       │
       ▼
2. interpret ── Grok lee su prompt + mensaje + observaciones ◄─────────┐
       │        y devuelve JSON: respond o call_tool                   │
       ▼                                                               │
3. next_node ── call_tool ─► 4. retrieve: el servidor valida la        │
       │                       solicitud y, si la acepta, ejecuta la   │
       │                       herramienta en SQLite (solo lectura) ───┘
       │
       ├── respond sin buscar cuando pide productos ─► vuelve a 2 una vez con el aviso SEARCH_REQUIRED
       ├── respond sin cotizar con cantidad dicha ─► vuelve a 2 una vez con el aviso QUOTE_REQUIRED
       ├── respond sobre la tienda sin consultarla ─► vuelve a 2 una vez con el aviso INFO_REQUIRED
       │
       ▼
5. respond ── verifica la redacción de Grok o arma la respuesta con los datos
       │
       ▼
6. estado ── quoted, found, clarify, nearby, insufficient_stock, informed, refused… o un fallo controlado
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

En macOS o Linux, sustituye `.\.venv\Scripts\python.exe` por `./.venv/bin/python` en los comandos siguientes. La base se crea en `.local/mock_catalog_s3.sqlite3`, con 384 variantes ficticias; el comando de carga se detiene si ya existe para no sobrescribirla.

## Uso

### Terminal

```powershell
.\.venv\Scripts\python.exe -m asistendero "Busco tubo PVC de 1/2 para agua y un bulto de cemento gris de 50 kg"
```

También puedes probar una pregunta sin búsqueda de productos:

```powershell
.\.venv\Scripts\python.exe -m asistendero "Hola, ¿están atendiendo en este momento?"
```

La redacción puede variar entre llamadas. Desde S3 el horario es un dato ficticio de la tienda que el agente consulta con `consultar_info_tienda`; el servidor decide si está abierta según su reloj.

Para una conversación de varios turnos con memoria de sesión (por ejemplo, «Busco tubo PVC de 1/2 para agua» y luego «dame 3 metros de ese»):

```powershell
.\.venv\Scripts\python.exe -m asistendero --chat
```

`--model grok-4.20-0309-reasoning` (u otro modelo de las familias 4.7, 4.6, 4.5 o 4.20) reemplaza `GROK_MODEL` para esa ejecución; un modelo fuera del reglamento se rechaza antes de llamar a la pasarela.

### Visor local

```powershell
.\.venv\Scripts\python.exe -m asistendero.visual
```

Abre [http://127.0.0.1:8765/](http://127.0.0.1:8765/) en el navegador. El visor solo escucha en `127.0.0.1` y permite observar la conversación, los pasos del agente y la traza de cada ejecución. El **Mapa del harness** explica en qué etapa Grok recibe sus instrucciones, qué decide, qué reglas aplica el servidor y cómo se clasifica el resultado, y marca el recorrido de la última prueba. Con **Conversación con memoria** activado, cada mensaje continúa la misma sesión del servidor hasta pulsar **Nueva conversación**. Los costos se distinguen entre **valor informado por la API** y **estimación con tarifas públicas de referencia**; una estimación no confirma el cobro de la pasarela del reto. Detén el servidor con `Ctrl+C`. Consulta [los detalles del visor](docs/HARNESS.md).

### Panel del tendero

```powershell
.\.venv\Scripts\python.exe -m asistendero.tendero
```

Abre [http://127.0.0.1:8766/](http://127.0.0.1:8766/). Muestra las ventas del día, los pedidos que llegaron por el chat (para marcarlos entregados o cancelarlos) el inventario, con edición de precio y existencias e historial de cambios, y las conversaciones bloqueadas por intentar inyectar instrucciones, con un botón para desbloquearlas. Solo escucha en `127.0.0.1` y no tiene usuarios: es una demostración local. Ver [el panel en HARNESS](docs/HARNESS.md#panel-del-tendero).

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

La [evidencia S2](evaluation/S2_EVIDENCIA.md) registra las corridas reales con Grok de los diez casos `S2-01` a `S2-10` y de dos fallos controlados (catálogo inaccesible y modelo inaccesible), con `run_id`, tokens, latencia y costo informado por la API. Con `s2-tools-v1` pasaron 7 de 10 casos y los dos fallos. Los tres que fallaron se corrigieron en `s2-tools-v2`. Con esa versión, los diez casos y los dos fallos pasaron en una sola corrida sobre el commit `ffcdde4`. Desde el 21-10-2026 el evaluador agrega un tercer fallo controlado (salida inválida del modelo, sin red) y guarda en cada reporte el commit evaluado; la corrida vigente da 10/10 casos y 3/3 fallos sobre `a6a190e`. Los casos son evidencia del flujo funcional; no constituyen una medida general de precisión. Las verificaciones de [búsqueda estructurada](evaluation/VERIFICACION_BUSQUEDA_ESTRUCTURADA.md) y de [Semana 1](EVIDENCIA_SEMANA1.md) corresponden a versiones anteriores del agente.

La [evidencia S3](evaluation/S3_EVIDENCIA.md) mide el set propio de **43 casos (48 turnos)** en cinco suites (S2, catálogo, tienda, seguridad y conversación) con costo por tarea. Con `s3-conversacion-v1` pasaron 33/43; corregidos los fallos, `s3-conversacion-v2` dio **42/43 y 3/3 fallos controlados sobre `76f86c4`**, con USD 0.0036 por tarea y 2,95 llamadas a Grok por tarea. El caso restante (C-08) se corrigió en `8a4ac95` y no se ha vuelto a medir. La comparación entre modelos Grok quedó interrumpida y sigue pendiente.

El comando de evaluación usa los [casos](evaluation/cases.json) y **solo llama a Grok si se usa `--live`**:

```powershell
.\.venv\Scripts\python.exe -m asistendero.evaluate --live --include-failures
.\.venv\Scripts\python.exe -m asistendero.evaluate --live --suite seguridad conversacion   # solo esas suites
.\.venv\Scripts\python.exe -m asistendero.evaluate --live --model grok-4.20-0309-reasoning   # otro modelo permitido
.\.venv\Scripts\python.exe -m asistendero.evaluate --compare .local\eval-A.json .local\eval-B.json   # tabla, sin Grok
# S4: conversaciones largas con pedidos, clientes a la vez y varios modelos, con tope de gasto
.\.venv\Scripts\python.exe -m asistendero.evaluate --live --suite ruido pedidos sesion_larga concurrencia --budget-usd 1
.\.venv\Scripts\python.exe -m asistendero.evaluate --live --suite extremos flujos variados --concurrency 3 --budget-usd 1
.\.venv\Scripts\python.exe -m asistendero.evaluate --live --suite pedidos concurrencia --concurrency 3 `
    --models grok-4.20-0309-non-reasoning grok-4.5 grok-4.7 --budget-usd 2
```

Las corridas con `--live` consumen cupo. Guardan en `.local/` el reporte con los eventos completos y, caso por caso, una bitácora parcial (`*.partial.jsonl`). `--models` reparte los modelos en rueda (cada caso, o cada cliente de un caso de concurrencia, usa el siguiente) y el reporte separa aprobados, llamadas, tokens y costo por modelo. `--concurrency` (1 a 6) corre varios casos a la vez y `--budget-usd` deja de empezar casos al llegar al tope; los que ya corrían terminan. La hora de la tienda en la evaluación arranca el miércoles 21-10-2026 a las 9:00 y avanza con el reloj real, para que «mañana a las 10» signifique siempre lo mismo.

## Estructura del repositorio

| Ruta | Contenido |
| --- | --- |
| `src/asistendero/graph.py` | Flujo LangGraph: Grok decide, el servidor ejecuta y se responde. |
| `src/asistendero/injection.py` | Detecta inyecciones de instrucciones (también disfrazadas) antes de Grok; la sesión queda baneada. |
| `src/asistendero/guardrails.py` | Barreras ante preguntas trampa, datos personales y fugas del prompt. |
| `src/asistendero/sessions.py` y `chat.py` | Sesiones de chat con memoria acotada en SQLite local. |
| `src/asistendero/store_replies.py` | Respuestas y comprobaciones de la información de la tienda. |
| `src/asistendero/reminders.py` | Avisos del servidor cuando Grok responde sin buscar o sin cotizar. |
| `src/asistendero/validation.py` | Reglas que una solicitud de Grok cumple antes de ejecutarse. |
| `src/asistendero/product_fit.py` | Cuál de varios productos distintos describe el cliente con sus palabras. |
| `src/asistendero/observations.py` y `executor.py` | Lectura de las respuestas de herramientas y conexión con el ejecutor real. |
| `src/asistendero/answers.py` | Respuesta final verificada contra lo que devolvieron las herramientas. |
| `src/asistendero/grok.py` | Instrucciones del agente e integración con Grok. |
| `src/asistendero/tools.py` | Las cinco herramientas del servidor (`execute_tool`) sobre el catálogo. |
| `src/asistendero/search.py` y `catalog.py` | Contrato de búsqueda y lectura del catálogo SQLite. |
| `src/asistendero/evaluate.py`, `eval_checks.py`, `eval_sessions.py` y `eval_report.py` | Evaluador de casos de uno o varios turnos, conversaciones con pedidos, clientes a la vez, fallos controlados, costo por tarea y por modelo. |
| `src/asistendero/orders.py`, `order_rules.py`, `order_tools.py`, `order_replies.py` y `order_watch.py` | Pedidos para recoger: apartado, reglas, herramientas, respuestas y avisos de vencimiento. |
| `src/asistendero/inventory.py`, `sales.py`, `tendero.py` y `ui/tendero.*` | Panel local del tendero: inventario, pedidos y ventas. |
| `src/asistendero/spelling.py` | Lectura de mensajes mal escritos para respaldar lo que Grok extrajo. |
| `src/asistendero/harness_info.py` | Datos del mapa del harness que muestra el visor. |
| `src/asistendero/seed.py`, `catalog_data.py` y `measures.py` | Datos ficticios para la demostración y lectura de medidas. |
| `src/asistendero/visual.py` y `ui/` | Servidor y visor local. |
| `src/asistendero/tracing.py` y `pricing.py` | Trazas, uso y costos de ejecución. |
| `tests/` | Pruebas automatizadas. |
| `evaluation/` | Casos y evidencia de verificaciones. |
| `docs/` | Notas técnicas del prototipo. |
| `PLANIFICACION.md` y `DESIGN.md` | Backlog e identidad visual del visor. |

## Estado y próximos pasos

Este prototipo **no está conectado a un comercio real**. Aún no integra WhatsApp, Supabase, Wompi, DIAN ni Platica.mx; gestiona pedidos para recoger sobre datos ficticios, pero no pagos, fiados, domicilios ni compras a proveedores. La memoria de conversación es local, dura 12 horas y no guarda datos personales; ver [docs/CONVERSACION_Y_SEGURIDAD.md](docs/CONVERSACION_Y_SEGURIDAD.md). El panel comercial, el aislamiento entre negocios y las aprobaciones por rol pertenecen al desarrollo posterior. La ferretería piloto y las reglas operativas deben definirse con sus responsables.

La visión y las tareas están organizadas en [PLANIFICACION.md](PLANIFICACION.md) y en el [tablero de PulsoTienda](https://github.com/users/JulianCVM/projects/9). El diseño aplicado al visor se documenta en [DESIGN.md](DESIGN.md). Las decisiones de dinero o crédito deberán quedar bajo autorización del dueño o de un rol delegado, y una confirmación de pago requerirá una fuente verificable.

## Relación con el Agent Challenge

AsisTendero nació como proyecto del Agent Challenge. El corte S1 demostró el recorrido **mensaje → Grok → procesamiento → respuesta**. El corte S2 agrega tres herramientas reales del servidor, el manejo de errores y las corridas registradas en la evidencia, con una clave de API real y un catálogo de prueba. El corte S3 agrega un set propio de 43 casos, el reporte de costo por tarea, la comparación entre los modelos Grok permitidos, sesiones de chat, dos herramientas de tienda y las barreras ante preguntas trampa. El corte S4 agrega pedidos para recoger con avisos de vencimiento, el panel del tendero, la lectura de mensajes mal escritos, pruebas de caos y la evaluación de conversaciones largas con varios clientes y modelos a la vez. El [repositorio público](https://github.com/JulianCVM/AsisTendero) y la documentación permiten seguir su evolución; las funciones descritas como próximas no se presentan como parte del flujo ya implementado.

## Licencia

Código bajo [licencia MIT](LICENSE). Según las reglas del reto, Platica recibe una licencia no exclusiva y la titularidad del código sigue siendo de sus autores. Los datos del catálogo de demostración son ficticios.
