# AsisTendero

**AsisTendero** es un agente conversacional basado en Grok que busca ayudar a ferreterías y tiendas de barrio colombianas a atender consultas y operar con información confiable. Forma parte de **PulsoTienda**, la plataforma que conecta conversaciones, catálogo, inventario y decisiones del comercio: PulsoTienda es el producto (panel del tendero y página pública) y AsisTendero, el agente que atiende el chat.

Este repositorio contiene la **versión ejecutable del corte S3**: recibe mensajes escritos, sueltos o dentro de una conversación con memoria, y deja que Grok decida cuál de **cinco herramientas del servidor** necesita (buscar productos, consultar disponibilidad, calcular una cotización informativa, consultar la información de la tienda y explorar categorías). El servidor filtra las preguntas trampa antes de Grok, valida cada solicitud antes de ejecutarla sobre un catálogo ficticio de ferretería y responde solo con datos comprobados. También incluye una interfaz local para explorar cada ejecución, un mapa del harness y un evaluador de 43 casos con comparación de modelos y costo por tarea. El piloto con un comercio real y las funciones comerciales más amplias siguen en definición y desarrollo.

## El problema

En muchos comercios pequeños, los productos, precios, existencias y conversaciones se gestionan entre cuadernos, mensajes y la memoria de quienes atienden. Cuando alguien pregunta por un artículo específico, puede ser difícil identificar la variante correcta y responder con un dato actualizado. Esta es la situación que motiva el proyecto; su frecuencia e impacto deberán validarse con el comercio piloto.

La visión de PulsoTienda es que el agente pueda acompañar el recorrido comercial y apoyar al dueño en la operación diaria. La primera etapa se concentra en una pregunta básica: **¿puede entender una solicitud de un cliente, buscar únicamente lo pertinente y contestar sin inventar productos, precios ni disponibilidad?**

El primer piloto previsto es una ferretería de una sede. El establecimiento, su catálogo y sus datos aún no están definidos; por eso esta versión trabaja con un catálogo de demostración de 435 variantes en 12 categorías. Para evaluar al agente fuera de la ferretería, la misma base trae una segunda tienda ficticia, una tienda de barrio de mercado diario con 108 productos (granos, lácteos, huevos, frescos, aseo, bebidas y mecato), que solo usa el evaluador.

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
- Muestra en el visor el resultado de cada prueba para evaluarla (estado, quién redactó, herramientas pedidas, ejecutadas y rechazadas, costo y latencia), un castillo animado del harness (cada edificio es un nodo o una barrera del flujo), un mapa interactivo del flujo de decisión y la traza en paneles legibles con el JSON a un clic.

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
       ├── pide «todo» y la cotización no trae la lista ─► vuelve a 2 una vez con el aviso LIST_QUOTE_REQUIRED
       │
       ▼
5. respond ── verifica la redacción de Grok o arma la respuesta con los datos
       │
       ▼
6. estado ── quoted, found, clarify, nearby, insufficient_stock, informed, refused… o un fallo controlado
```

**Grok decide** qué información necesita y **el servidor ejecuta**: el modelo no tiene acceso SQL libre, no elige negocio ni sede y no puede imponer precio ni existencias. Una pregunta general suele necesitar una llamada a Grok; una cotización de un producto, unas cuatro (buscar, consultar, cotizar y responder). El detalle del contrato, las barreras y los códigos está en [docs/HARNESS.md](docs/HARNESS.md), y el visor lo muestra en su sección **Mapa del harness**.

Por ejemplo, ante «Necesito 2 metros de tubo PVC de 1/2 para agua y 1 bulto de cemento gris de 50 kg», el agente busca ambos artículos, consulta `PVC-050` y `CEM-050` y responde «Te quedaría así: • 2 metros de tubo PVC presión para agua de 1/2 pulgada (a $8.500 el metro): $17.000 • 1 bulto de cemento gris de 50 kg: $39.500 · Total: $56.500», con precios de demostración y sin anunciar cuánto queda si el cliente no lo pregunta. En una conversación recuerda lo que el cliente va cotizando: tras «un metro de tubo conduit» y «agrega una manguera de abasto, ¿cuánto sería todo?» cotiza las dos cosas juntas, y tras listar tres tubos entiende «dame del primero 3 metros». Ante «Busco tubo PVC de 1 pulgada», indica que no encontró esa medida exacta y muestra las medidas cercanas sin afirmar que sirven para lo mismo. Ante «20 metros de PVC de 1/2», la cotización detecta que solo hay 12 y lo dice.

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

Necesitas Python 3.11 o superior, Git, conexión a la API y una clave de Grok válida para el endpoint configurado. Clona el repositorio y entra a su carpeta:

```bash
git clone https://github.com/JulianCVM/AsisTendero.git
cd AsisTendero
```

Desde la raíz del repositorio, en **Windows PowerShell**:

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

Si la llamada a la pasarela falla por el certificado (red con un proxy que firma con su propio certificado), `grok.py` usa los certificados del sistema cuando el paquete opcional `truststore` (MIT) está instalado; sin él, usa los de Python.

`GROK_CONV_ID=1` (opcional, apagada) pide a la pasarela atender cada conversación en el mismo servidor para reutilizar la caché del prompt; está apagada hasta medirla con una corrida real ([HARNESS.md](docs/HARNESS.md#caché-del-prompt)).

En macOS o Linux, sustituye `.\.venv\Scripts\python.exe` por `./.venv/bin/python` en los comandos siguientes.

## Uso

### Todo con un solo comando

```powershell
.\.venv\Scripts\python.exe -m asistendero          # chat del cliente con su traza y plataforma del tendero
.\.venv\Scripts\python.exe -m asistendero --demo   # lo mismo, sobre la tienda de demostración
```

Arranca en un solo proceso el [visor](#visor-local) (chat del cliente y traza, [http://127.0.0.1:8765/](http://127.0.0.1:8765/)) y el [panel del tendero](#panel-del-tendero) ([http://127.0.0.1:8766/](http://127.0.0.1:8766/), con la página de presentación en `/inicio`). Los dos usan la misma tienda, los mismos pedidos y las mismas conversaciones: lo que un cliente pide en el chat aparece en el panel, y lo que el tendero responde al tomar una conversación llega al chat. Si el catálogo ficticio no existe, lo crea en `.local/mock_catalog_s3.sqlite3` (435 variantes de ferretería y la tienda de mercado del evaluador); si ya existe, solo le agrega los productos nuevos de la siembra sin tocar los precios ni las existencias que el tendero ya cambió. `Ctrl+C` detiene todo. Abrir las páginas no llama a Grok: cada mensaje del chat y cada **Interpretar** del asistente de bodega sí, y consumen créditos.

El mismo comando, con un mensaje o con `--chat`, responde en la terminal (abajo). Los comandos de cada parte por separado (`asistendero.entregas.visor`, `asistendero.entregas.panel`, `asistendero.datos`) siguen disponibles. Si prefieres crear el catálogo sin arrancar nada, usa `python -m asistendero.datos`, que se detiene si la base ya existe.

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

Lo abre el comando único; para abrirlo solo:

```powershell
.\.venv\Scripts\python.exe -m asistendero.entregas.visor
```

Abre [http://127.0.0.1:8765/](http://127.0.0.1:8765/) en el navegador. El visor solo escucha en `127.0.0.1` y permite observar la conversación, los pasos del agente y la traza de cada ejecución. El **castillo del harness** muestra el flujo como un castillo isométrico que recorre el mensaje: repite recorridos de ejemplo y, durante una prueba, el recorrido real. Debajo, el **Mapa del harness** es un grafo de decisión que se recorre con mouse, toque o teclado: cada nodo dice qué hace, qué recibe, qué decide y a dónde sigue, y tras una prueba marca el camino recorrido. La **inspección técnica** muestra cada evento en paneles (entrada, decisión de Grok, resultado de la herramienta, evidencia, errores) con el JSON original plegado. El selector de apariencia (claro, oscuro o el del sistema) es el mismo del panel y de la página pública y se recuerda en las tres. Con **Conversación con memoria** activado, cada mensaje continúa la misma sesión del servidor hasta pulsar **Nueva conversación**. En el chat, **Enter** envía y **Shift + Enter** hace un salto de línea; el hilo se desplaza dentro de su caja. Los costos se distinguen entre **valor informado por la API** y **estimación con tarifas públicas de referencia**; una estimación no confirma el cobro de la pasarela del reto. Detén el servidor con `Ctrl+C`. Consulta [los detalles del visor](docs/HARNESS.md).

### Panel del tendero

Lo abre el comando único; para abrirlo solo:

```powershell
.\.venv\Scripts\python.exe -m asistendero.entregas.panel
```

Abre [http://127.0.0.1:8766/](http://127.0.0.1:8766/). Secciones: **Hoy** (cuatro cifras del día y la bandeja **Por hacer**, ordenada por urgencia, con Entregar y Registrar pago a la mano; al lado, lo que hizo AsisTendero, la mercancía en camino y lo más vendido), **Pedidos** (filas compactas con su pago y sus motivos para revisar; filtros Por atender, Revisar e Historial), **Ventas y pagos** (vendido no es cobrado; un comprobante no es un pago confirmado), **Inventario** (una tabla de productos con la lectura «Como lo ve AsisTendero», que muestra lo que responde el chat; arriba, la barra del asistente de bodega para contar qué pasó escribiendo o dictando, sin aplicar nada hasta confirmar; abastecimiento con pedidos al proveedor y llegadas parciales, movimientos, categorías y alertas de stock) y **Chats** (supervisión, tomar o devolver una conversación, responder y bloquear). Tema claro u oscuro; en el celular la navegación va abajo y en el computador, a la izquierda. Solo escucha en `127.0.0.1` y no tiene usuarios: es una demostración local. Ver [el panel en HARNESS](docs/HARNESS.md#panel-del-tendero).

```powershell
.\.venv\Scripts\python.exe -m asistendero.entregas.panel --demo   # tienda de demostración con ventas, pagos, proveedores y chats simulados
```

`--demo` rehace `.local/demo/` cada vez y no toca la base del chat ni del evaluador. Con `python -m asistendero --demo`, el chat del visor también usa esa tienda. La página pública de presentación está en [http://127.0.0.1:8766/inicio](http://127.0.0.1:8766/inicio): explica el producto y trae una demo en un celular que se reproduce sola con casos fijos (no llama a Grok), junto a lo que pasa por dentro y lo que ve el tendero. **Interpretar** en el asistente de bodega llama a Grok con la llave del reto (consume créditos); el resto del panel no llama a Grok.

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

### Lo que respalda la página pública

La página `/inicio` habla en lenguaje de negocio y no reproduce detalles técnicos ni comandos. Esto es lo que respalda cada garantía que promete:

| Garantía de la página | Dónde se cumple |
|---|---|
| Una cifra que no coincide con el catálogo no se envía | `reply_is_grounded` (`answers.py`): la redacción de Grok se usa solo si cada `$`, SKU y cantidad sale de las observaciones de esa ejecución; si no, responde la salida determinista del servidor. |
| Con una medida ambigua se pregunta y no se elige por el cliente | `validate_request` (`validation.py`) y las opciones mostradas de `choices.py`; una opción cercana no es equivalente. |
| Un intento de manipulación se bloquea antes de llegar al modelo | `detect_injection` y `blocked_reply` (`injection.py`): no llama a Grok y la conversación queda bloqueada hasta que el tendero la desbloquee. |
| El pedido se confirma con el «sí» del cliente y lo apartado se libera a los 5 minutos | `validate_order_request` (`order_rules.py`) y `HOLD_MINUTES` (`orders.py`). |
| Precio y existencias solo cambian desde el panel; el cobro y la entrega son en el mostrador | `inventory.py`, `payments.py` y [docs/PAGOS.md](docs/PAGOS.md). |
| La clave del servicio de IA no se muestra al cliente | Vive en `.env` (excluido de Git) y la traza la registra como `"api_key": "[omitida]"` (`tracing.py`). |

Cifras del repositorio: **334 casos de evaluación en 20 suites** ([cases.json](evaluation/cases.json)); **45 de ellos en la suite `inyeccion`**, con **34 ataques** que deben bloquearse antes de Grok y frases legítimas parecidas que deben atenderse; **10 herramientas** que Grok puede pedir (`TOOL_NAMES` de `grok.py`), y **más de 850 pruebas automáticas** que nunca llaman a Grok (`pytest -q`). Topes que el código hace cumplir: un mensaje de hasta **2.000 caracteres**, hasta **6 herramientas** por mensaje, lo apartado espera el «sí» **5 minutos**, hasta **3 pedidos activos** por conversación y la recogida se agenda con **hasta 7 días** de anticipación. `tests/test_tendero.py` compara estas cifras con su fuente.

La [evidencia S2](evaluation/S2_EVIDENCIA.md) registra las corridas reales con Grok de los diez casos `S2-01` a `S2-10` y de dos fallos controlados (catálogo inaccesible y modelo inaccesible), con `run_id`, tokens, latencia y costo informado por la API. Con `s2-tools-v1` pasaron 7 de 10 casos y los dos fallos. Los tres que fallaron se corrigieron en `s2-tools-v2`. Con esa versión, los diez casos y los dos fallos pasaron en una sola corrida sobre el commit `ffcdde4`. Desde el 21-10-2026 el evaluador agrega un tercer fallo controlado (salida inválida del modelo, sin red) y guarda en cada reporte el commit evaluado; la corrida vigente da 10/10 casos y 3/3 fallos sobre `a6a190e`. Los casos son evidencia del flujo funcional; no constituyen una medida general de precisión. Las verificaciones de [búsqueda estructurada](evaluation/VERIFICACION_BUSQUEDA_ESTRUCTURADA.md) y de [Semana 1](EVIDENCIA_SEMANA1.md) corresponden a versiones anteriores del agente.

La [evidencia S3](evaluation/S3_EVIDENCIA.md) mide el set propio de **43 casos (48 turnos)** en cinco suites (S2, catálogo, tienda, seguridad y conversación) con costo por tarea. Con `s3-conversacion-v1` pasaron 33/43; corregidos los fallos, `s3-conversacion-v2` dio **42/43 y 3/3 fallos controlados sobre `76f86c4`**, con USD 0.0036 por tarea y 2,95 llamadas a Grok por tarea. El caso restante (C-08) se corrigió en `8a4ac95` y no se ha vuelto a medir. La comparación entre modelos Grok quedó interrumpida y sigue pendiente.

El comando de evaluación usa los [casos](evaluation/cases.json) y **solo llama a Grok si se usa `--live`**:

```powershell
.\.venv\Scripts\python.exe -m asistendero.evaluacion --live --include-failures
.\.venv\Scripts\python.exe -m asistendero.evaluacion --live --suite seguridad conversacion   # solo esas suites
.\.venv\Scripts\python.exe -m asistendero.evaluacion --live --model grok-4.20-0309-reasoning   # otro modelo permitido
.\.venv\Scripts\python.exe -m asistendero.evaluacion --compare .local\eval-A.json .local\eval-B.json   # tabla, sin Grok
.\.venv\Scripts\python.exe -m asistendero.evaluacion.eval_costs .local\eval-A.json --out evaluation\COSTOS_POR_TAREA.md   # costo por operación, sin Grok
# S4: conversaciones largas con pedidos, clientes a la vez y varios modelos, con tope de gasto
.\.venv\Scripts\python.exe -m asistendero.evaluacion --live --suite ruido pedidos sesion_larga concurrencia --budget-usd 1
.\.venv\Scripts\python.exe -m asistendero.evaluacion --live --suite extremos flujos variados --concurrency 3 --budget-usd 1
.\.venv\Scripts\python.exe -m asistendero.evaluacion --live --suite pedidos concurrencia --concurrency 3 `
    --models grok-4.20-0309-non-reasoning grok-4.5 grok-4.7 --budget-usd 2
# 31-10: catálogo ampliado, tienda de mercado (prompt mercado-v1) y paráfrasis
.\.venv\Scripts\python.exe -m asistendero.evaluacion --live --suite ampliacion mercado parafrasis --concurrency 3 --budget-usd 1
```

Un caso con `"negocio": "mercado"` corre con el catálogo, los pedidos y el prompt (`mercado-v1`) de la tienda de
mercado; cada renglón del reporte guarda su negocio y su versión de prompt. Además de lo que pide cada caso, el
evaluador revisa siempre dos cosas por su cuenta (`eval_oracle.py`): que cada cifra en pesos de la respuesta haya
salido de las herramientas de ese turno y que la respuesta no muestre un SKU. Un caso puede exigir también cómo
llegó Grok a la respuesta: herramientas que no debía ejecutar (`forbidden_tools`), productos que no debía elegir
(`forbidden_skus`) y campos que alguna búsqueda debía llevar (`expected_search`). Los casos con el mismo `grupo`
(suite `parafrasis`) dicen lo mismo con otras palabras, y el resumen dice en cuántos grupos el agente respondió igual.

Las corridas con `--live` consumen cupo. Guardan en `.local/` el reporte con los eventos completos y, caso por caso, una bitácora parcial (`*.partial.jsonl`). `--models` reparte los modelos en rueda (cada caso, o cada cliente de un caso de concurrencia, usa el siguiente) y el reporte separa aprobados, llamadas, tokens y costo por modelo, y la tabla comparativa trae el costo por llamada, el % de tokens que salió de la caché y el % de llamadas que reutilizaron el prompt fijo. `--concurrency` (1 a 6) corre varios casos a la vez y `--budget-usd` deja de empezar casos al llegar al tope; los que ya corrían terminan. La hora de la tienda en la evaluación arranca el miércoles 21-10-2026 a las 9:00 y avanza con el reloj real, para que «mañana a las 10» signifique siempre lo mismo.

## Estructura del repositorio

El paquete se organiza por lo que hace cada parte del sistema; el detalle y el porqué están en
[docs/ARQUITECTURA.md](docs/ARQUITECTURA.md).

| Ruta | Contenido |
| --- | --- |
| `src/asistendero/agente/` | **AsisTendero**, el agente que atiende a los clientes, y su harness. |
| `agente/modelo/` | `grok.py` (cliente de Grok, decisión y contrato de herramientas) y `prompt.py` (instrucciones del agente; la versión de la tienda de mercado sale de la misma con otros ejemplos). |
| `agente/flujo/` | `graph.py` (flujo LangGraph: Grok decide, el servidor valida, ejecuta y responde) y `reminders.py` (avisos cuando Grok responde sin un paso que el mensaje exige). |
| `agente/entrada/` | Lo que se revisa antes de pensar: `injection.py` (inyecciones, con baneo), `guardrails.py` (temas delicados, datos personales, fugas del prompt) y `spelling.py` (mensajes mal escritos). |
| `agente/reglas/` | Reglas antes de ejecutar: `validation.py`, `order_rules.py`, `choices.py` (opciones mostradas y paginadas), `context_resolution.py` (turnos breves que se apoyan en el anterior y lo que el cliente ya dijo de cada producto) y `shopping_list.py` (lo cotizado en la conversación). |
| `agente/herramientas/` | `tools.py` y `order_tools.py` (herramientas del servidor, `execute_tool`), `executor.py` (ejecutor real) y `observations.py` (lectura de sus respuestas). |
| `agente/respuesta/` | `answers.py` (respuesta verificada contra las observaciones), `reply_text.py`, `store_replies.py`, `order_replies.py` y `restock.py` (qué puede afirmar Grok del surtido). |
| `agente/conversacion/` | `sessions.py` (memoria acotada en SQLite), `chat.py` (un turno), `handoff.py` (paso al tendero), `order_watch.py` (vence pedidos y deja el aviso en la conversación) y `supervision.py` (bandeja de conversaciones del panel). |
| `src/asistendero/tienda/` | Lo que administra el tendero sobre la misma base; `vocabulario.py` (SKU, texto normalizado y pesos) y `reloj.py` (hora de la tienda) son comunes a la tienda y al agente. |
| `tienda/catalogo/` | `catalog.py` (lectura en solo lectura), `search.py` (contrato de búsqueda), `measures.py` (medidas como átomos), `product_fit.py` (qué producto describe el texto), `catalog_admin.py` y `stock_thresholds.py` (categorías y alertas) y `product_art*.py` (pictogramas de producto). |
| `tienda/inventario/` | `inventory.py` (precio y existencias con historial) y `surtido.py` (cuándo vuelve a llegar un producto). |
| `tienda/pedidos/` | `orders.py`: pedidos para recoger, apartado y vencimiento a los 5 minutos. |
| `tienda/ventas/` | `payments.py` (registro manual del cobro, ver [PAGOS.md](docs/PAGOS.md)), `sales.py` y `sales_history.py`. |
| `tienda/abastecimiento/` | `purchasing*.py` (proveedores y pedidos al proveedor) y `stock_*.py` (llegadas y cambios de bodega). |
| `tienda/bodega/` | `stock_assistant.py` y `stock_proposal.py`: Grok interpreta lo que cuenta el tendero y el servidor arma una propuesta que se aplica solo al confirmarla. |
| `src/asistendero/datos/` | `catalog_data.py` y `catalog_ampliacion.py` (ferretería), `catalog_mercado.py` (tienda de mercado del evaluador) y `seed.py`: catálogos ficticios y base. |
| `src/asistendero/observabilidad/` | `tracing.py` y `pricing.py` (trazas, tokens y costo) y `harness_info.py` y `harness_flow.py` (mapa del harness atado al grafo real). |
| `src/asistendero/evaluacion/` | `evaluate.py`, `eval_checks.py`, `eval_costs.py` (costo por tarea, por mensaje, por llamada a Grok y por herramienta), `eval_oracle.py` (precios y códigos sin respaldo, análisis de Grok y paráfrasis), `eval_sessions.py` y `eval_report.py`: casos de uno o varios turnos y de los dos negocios, pedidos, clientes a la vez, fallos controlados y costo por tarea. |
| `src/asistendero/entregas/` | Puntos de entrada: `cli.py` y `launcher.py` (comando único), `visor/` (puerto 8765), `panel/` (panel y `/inicio`, puerto 8766; `bandeja.py` ordena lo que hay que hacer hoy), `demo.py` (tienda de demostración, `--demo`) y `estaticos.py`. |
| `entregas/web/` | Archivos de las pantallas: `comun/` (tema, fuentes y logo), `visor/`, `panel/` y `pagina/` (la página pública). |
| `tools/castillo/` | Generador del castillo del harness (`node tools/castillo/build.mjs`, Node 18 o más); incluye el kit isométrico de anatomy con su licencia MIT. |
| `tools/mostrador/` | Generador de la tienda isométrica de «Cómo funciona» en `/inicio` (`node tools/mostrador/build.mjs`); usa el mismo kit de anatomy. |
| `tests/` | Pruebas automatizadas. |
| `evaluation/` | Casos y evidencia de verificaciones. |
| `docs/` | Notas técnicas del prototipo. |
| `PLANIFICACION.md` y `DESIGN.md` | Backlog e identidad visual. |

## Estado y próximos pasos

Este prototipo **no está conectado a un comercio real**. Aún no integra WhatsApp, Supabase, Wompi, DIAN ni Platica.mx; gestiona pedidos para recoger sobre datos ficticios, pero no pagos, fiados, domicilios ni compras a proveedores. La memoria de conversación es local, dura 12 horas y no guarda datos personales; ver [docs/CONVERSACION_Y_SEGURIDAD.md](docs/CONVERSACION_Y_SEGURIDAD.md). El panel comercial, el aislamiento entre negocios y las aprobaciones por rol pertenecen al desarrollo posterior. La ferretería piloto y las reglas operativas deben definirse con sus responsables.

La visión y las tareas están organizadas en [PLANIFICACION.md](PLANIFICACION.md) y en el [tablero de PulsoTienda](https://github.com/users/JulianCVM/projects/9). El diseño aplicado al visor se documenta en [DESIGN.md](DESIGN.md). Las decisiones de dinero o crédito deberán quedar bajo autorización del dueño o de un rol delegado, y una confirmación de pago requerirá una fuente verificable.

## Relación con el Agent Challenge

AsisTendero nació como proyecto del Agent Challenge. El corte S1 demostró el recorrido **mensaje → Grok → procesamiento → respuesta**. El corte S2 agrega tres herramientas reales del servidor, el manejo de errores y las corridas registradas en la evidencia, con una clave de API real y un catálogo de prueba. El corte S3 agrega un set propio de 43 casos, el reporte de costo por tarea, la comparación entre los modelos Grok permitidos, sesiones de chat, dos herramientas de tienda y las barreras ante preguntas trampa. El corte S4 agrega pedidos para recoger con avisos de vencimiento, el panel del tendero, la lectura de mensajes mal escritos, pruebas de caos y la evaluación de conversaciones largas con varios clientes y modelos a la vez. El [repositorio público](https://github.com/JulianCVM/AsisTendero) y la documentación permiten seguir su evolución; las funciones descritas como próximas no se presentan como parte del flujo ya implementado.

## Licencia

Código bajo [licencia MIT](LICENSE). Según las reglas del reto, Platica recibe una licencia no exclusiva y la titularidad del código sigue siendo de sus autores. Los datos del catálogo de demostración son ficticios. El castillo del visor usa el kit isométrico de anatomy (MIT, © 2026 Ryan), copiado con su licencia en `tools/castillo/vendor/`.
