# Arquitectura de AsisTendero: descomposición funcional y organización propuesta

Análisis del 31-10-2026, hecho sobre el código de `feat/s4-pedidos-tendero` y el panel en vivo (`/#hoy` en escritorio y
a 390 px). Primero dice **para qué existe** cada parte, después **dónde vive hoy** y qué falla, y al final la
organización a la que se migra. `docs/HARNESS.md` sigue siendo la referencia del flujo del agente; este documento
ordena todo lo demás alrededor de él.

## 1. Finalidad del ecosistema

Una ferretería de barrio recibe preguntas por chat que hoy contesta a mano. AsisTendero:

1. **Atiende al cliente** con precio y existencias leídos del catálogo, sin inventar nada, y deja **pedidos para
   recoger** solo cuando el cliente los pide y confirma.
2. **Le devuelve el control al tendero**: él decide precios, inventario, cobros, entregas y cuándo intervenir en un chat.
3. **Demuestra que es confiable**: cada ejecución deja traza, costo y resultado, y un evaluador mide cientos de casos.

| Actor | Qué necesita | Por dónde entra |
|---|---|---|
| Cliente | Saber si hay, cuánto vale, apartar y que lo atienda una persona si hace falta | Chat (hoy: visor local o terminal) |
| Tendero | Ver qué atender ahora, cobrar y entregar, mantener catálogo e inventario, abastecerse, supervisar chats | Panel (`/`) |
| Grok | Decidir el siguiente paso (responder o pedir una herramienta) | Pasarela del reto |
| Servidor (harness) | Validar cada decisión, ejecutar herramientas, verificar la respuesta, guardar la traza | Código del paquete |
| Quien evalúa o desarrolla | Ver por qué el agente hizo lo que hizo, medir costo y calidad | Visor (`:8765`), evaluador, pruebas |
| Visitante | Entender el producto | Página pública (`/inicio`) |

## 2. Descomposición funcional

Cuatro módulos. Cada submódulo agrupa procesos que se ven desde afuera; las funcionalidades son lo que el código ya hace.

### A. Atención al cliente (el agente y su harness)

| Submódulo | Procesos | Funcionalidades |
|---|---|---|
| A1. Entrada segura | Filtrar el mensaje, detectar manipulación, bloquear | Límite de 2.000 caracteres, temas delicados y datos personales, inyección y baneo, mensaje mal escrito |
| A2. Decisión | Armar el contexto, pedir a Grok el paso, interpretar su salida | Prompt versionado, contrato de salida (`respond` o herramienta), errores `MODEL_*` |
| A3. Reglas antes de ejecutar | Validar cada solicitud con lo que dijo el cliente | SKU respaldado, cantidad dicha, medida ambigua, lista de compras, opciones mostradas, reglas de pedido (sí, hora, cancelar) |
| A4. Herramientas | Ejecutar en el servidor, siempre con negocio y sede fijos | Buscar, cotizar, existencias, surtido, información de la tienda, registrar, confirmar, agendar y cancelar pedido |
| A5. Respuesta verificada | Comprobar cifras, redactar si Grok falla | Respuesta respaldada, texto determinista, avisos del servidor (`INFO_REQUIRED`…), reabastecimiento |
| A6. Conversación | Recordar la sesión, pasar a una persona | Productos y opciones recordados, pedido activo, vencimiento a los 5 minutos, paso al tendero |

### B. Operación de la tienda (lo que administra el tendero)

| Submódulo | Procesos | Funcionalidades |
|---|---|---|
| B1. Catálogo | Mantener lo que se vende y lo que ve el asistente | Productos, categorías, imagen dibujada, información de la tienda |
| B2. Inventario | Cambiar precio y existencias con historial | Ajustes, movimientos, alertas de stock bajo, fecha de reabastecimiento |
| B3. Pedidos | Atender lo que dejó el chat | Por confirmar, por recoger, entregar (descuenta bodega), cancelar, vencidos |
| B4. Ventas y cobros | Registrar el pago en el mostrador | Métodos, comprobante por verificar, vendido frente a cobrado, historial |
| B5. Abastecimiento | Pedir al proveedor y recibir | Proveedores, órdenes, llegadas parciales o con productos de más |
| B6. Asistente de bodega | Convertir lo que el tendero cuenta en cambios | Grok interpreta, el servidor arma una propuesta, el tendero confirma |
| B7. Supervisión | Ver y tomar conversaciones | Bandeja de chats, atender, liberar, finalizar, bloquear y desbloquear |

### C. Observabilidad y evaluación

| Submódulo | Funcionalidades |
|---|---|
| C1. Traza | `run_id`, latencia, tokens, costo por llamada, llave omitida |
| C2. Mapa del harness | Nodos y conexiones atados al grafo compilado |
| C3. Evaluación | 334 casos en 20 suites y dos negocios, sesiones con varios clientes, oráculo de precios y códigos, reporte y comparación |

### D. Entregas (cómo se usa)

Terminal (`asistendero`), visor (`:8765`), panel y página pública (`:8766`), comando único (`python -m asistendero`) y
tienda de demostración (`--demo`).

## 3. Cómo estaba (antes de los pasos 2 y 3 de la migración)

**68 módulos en una sola carpeta** (`src/asistendero/`, unas 12.000 líneas) y **51 archivos de interfaz en `ui/`**
(visor, panel y página pública mezclados). Los nombres dicen poco de a qué módulo pertenecen (`choices.py`,
`observations.py`, `stock_apply.py`). Agrupados por el grafo de importaciones:

| Módulo | Archivos de hoy |
|---|---|
| A. Agente | `grok`, `prompt`, `graph`, `reminders`, `guardrails`, `injection`, `spelling`, `validation`, `order_rules`, `measures`, `search`, `product_fit`, `choices`, `shopping_list`, `tools`, `order_tools`, `executor`, `observations`, `answers`, `reply_text`, `store_replies`, `order_replies`, `restock`, `sessions`, `chat`, `handoff` |
| B. Tienda | `catalog`, `catalog_admin`, `stock_thresholds`, `product_art*`, `inventory`, `orders`, `order_watch`, `payments`, `sales`, `sales_history`, `purchasing*`, `stock_arrivals`, `stock_operations`, `stock_apply`, `stock_matching`, `stock_assistant`, `stock_proposal`, `supervision` |
| Datos | `seed`, `catalog_data`, `demo` |
| C. Observabilidad | `tracing`, `pricing`, `harness_info`, `harness_flow`, `evaluate`, `eval_*` |
| D. Entregas | `cli`, `launcher`, `visual`, `tendero`, `tendero_views`, `tendero_actions`, `ui/` |

Problemas de estructura que el grafo deja ver:

1. **La tienda depende del agente.** `inventory` importa `SKU_PATTERN` de `validation` y `valid_plan` de `restock`
   (que a su vez usa `reply_text`); `stock_operations` y `demo` usan `format_cop` de `reply_text`. Un formato de
   moneda o un patrón de SKU son de la tienda, no de la conversación.
2. **El contrato del agente vive en el cliente del modelo.** `TOOL_NAMES`, `ORDER_TOOLS` y los límites están en
   `grok.py`, y de ahí los importan `validation`, `tools` y `order_rules`: cambiar de cliente de modelo arrastra las reglas.
3. **El esquema de la base está repartido**: 30 tablas se crean en 9 módulos distintos, con `upgrade_db` en `seed`.
   No hay un lugar que diga qué tablas existen y quién escribe en cada una.
4. **`ui/` mezcla tres aplicaciones**: el visor, el panel y la página pública comparten carpeta y prefijos de nombre;
   `tendero.py` sirve también los archivos de la página pública.
5. **Dos marcas** (resuelto el 31-10-2026): PulsoTienda es el producto (panel y página pública) y AsisTendero, el agente (visor, chat y menciones al asistente).

## 4. Diagnóstico del panel (`/#hoy` y las demás vistas)

Medido con el lanzador en marcha, solo navegando (sin acciones):

| Vista | Alto escritorio | Alto 390 px | Lo que pasa |
|---|---|---|---|
| Hoy | 2.523 | 3.965 | Nueve bloques: cifras, avisos, pedidos, «Plata del día» (repite «Vendido hoy»), asistente, más vendidos, mercancía en camino y por surtir (repite la cifra de arriba). No dice qué hacer primero. |
| Pedidos | 900 | 1.450 | Tarjetas anchas iguales a las de Hoy; ocho filtros. |
| Ventas | 2.419 | 3.293 | Cada venta es una tarjeta; para revisar 15 ventas hay que bajar 2.000 px. |
| Inventario | 2.808 | 7.435 | 384 productos en tarjetas de 3 columnas, 48 por página; 55 botones. |
| Catálogo | 3.561 | 6.252 | **Los mismos 384 productos** otra vez, con ilustraciones grandes; solo cambia que es de consulta. |
| Asistente de bodega | 900 | 844 | Entrada aparte para algo que es otra forma de cambiar el inventario. |
| Chats | 1.015 | 1.959 | Lista y detalle; funciona, con siete filtros. |

Conclusiones:

- **Hoy no es una bandeja de trabajo**: mezcla lo urgente (entregar, verificar un comprobante, un cliente que pide
  al tendero) con estadísticas. Lo accionable debería ir primero y en una sola cola ordenada por urgencia.
- **Inventario y Catálogo duplican** la misma lista. Para 384 productos, una tabla densa (nombre, variante, SKU,
  precio, bodega, apartado, para vender, estado) con búsqueda, filtros y orden sirve más que tarjetas; «lo que ve el
  asistente» es una columna o un interruptor, no otra vista.
- **El asistente de bodega es una forma de editar el inventario**: va como barra «Cuéntale qué pasó» dentro de
  Inventario, no como sección propia.
- **Ventas y Pedidos** son listas que se revisan en fila: filas compactas que se abren, con menos filtros
  («Por atender», «Por cobrar o verificar», «Historial»).

## 5. Organización propuesta

No se impone una arquitectura de libro. El patrón que manda es el del **harness**: un núcleo donde Grok decide y el
servidor valida, ejecuta, observa y verifica; alrededor, una **tienda** con sus datos, y por fuera las **entregas**.
Se toma de la arquitectura hexagonal solo lo útil: las dependencias van hacia adentro y cada borde (modelo, base,
HTTP) está en un lugar.

```text
src/asistendero/
  agente/                 A · el harness: Grok decide y el servidor valida, ejecuta y verifica
    modelo/               cliente de Grok y prompt
    flujo/                grafo de LangGraph, avisos del servidor, mapa del flujo
    entrada/              guardrails, inyección, ortografía
    reglas/               validación, reglas de pedido, opciones, turnos breves y especificaciones, lista de compras
    herramientas/         herramientas de catálogo y de pedido, ejecutor, observaciones
    respuesta/            verificación y textos de la respuesta, reabastecimiento
    conversacion/         sesiones, turno de chat, paso al tendero, avisos de vencimiento, supervisión
  tienda/                 B · lo que administra el tendero (SQLite)
    vocabulario.py        SKU, texto normalizado y pesos: el idioma del catálogo, común con el agente
    reloj.py              zona de Bogotá, días y la hora que las pruebas fijan
    catalogo/             lectura, búsqueda, medidas, parecido de productos, categorías, alertas e imágenes
    inventario/  pedidos/  ventas/  abastecimiento/  bodega/
  datos/                  catálogo ficticio, semilla y esquema
  observabilidad/         C · traza, costo, mapa del harness
  evaluacion/             C · evaluador, sesiones y reporte
  entregas/               D · cli, lanzador, visor/ y panel/ (cada uno con su servidor), demo.py, estaticos.py
    web/                  archivos de las pantallas: comun/, visor/, panel/ y pagina/
```

Reglas de dependencia, comprobadas por `tests/test_arquitectura.py`. Cada paquete importa solo los de abajo:
`entregas → evaluacion → observabilidad → agente → tienda → datos`. Los cruces que aún existen están anotados con su
motivo en `KNOWN_CROSSINGS`; la lista solo puede achicarse (la prueba falla con un cruce nuevo y con uno anotado que
ya desapareció).

1. `entregas` usa todo y nadie importa `entregas`.
2. `agente` usa `tienda` solo para leer el catálogo y registrar pedidos, por medio de `herramientas`.
3. `tienda` no importa `agente`: formatos de moneda, patrones de SKU y fechas de reabastecimiento bajan a `tienda`.
4. La base de `datos` (`seed.py`, `catalog_data.py`) no importa a nadie del paquete y concentra el esquema; la demo
   se arma con los módulos reales de la tienda.
5. `observabilidad` y `evaluacion` leen el agente y la tienda; no les escriben reglas.

## 6. Migración por pasos

Cada paso deja la suite en verde y se puede revisar solo:

1. **Fijar lo pendiente**: dejar en commits ordenados el trabajo actual de la rama antes de mover archivos, para que
   la reorganización sea un diff de solo renombres.
2. **Mover sin cambiar comportamiento** (hecho el 31-10-2026): `git mv` a los paquetes, importaciones absolutas reescritas por un script,
   puntos de entrada de `pyproject.toml` y rutas de `ui/` actualizados; `AGENTS.md`, `HARNESS.md` y el README en el
   mismo cambio. Prueba nueva de reglas de dependencia. Los nombres de archivo no cambiaron; los comandos cortos son
   `python -m asistendero.evaluacion`, `asistendero.datos`, `asistendero.entregas.visor` y `asistendero.entregas.panel`.
3. **Cortar los cruces de capa** (hecho el 31-10-2026): de 30 cruces quedan 4, anotados con su motivo.
   - `tienda/vocabulario.py` (SKU, `normalize_text`, `format_cop`) y `tienda/reloj.py` (zona, días y `local_now`,
     antes repetidos en tres módulos y fijados por las pruebas a través de `tools`).
   - `tienda/inventario/surtido.py`: la forma del surtido; `restock.py` conserva lo que el agente puede decir.
   - `search.py`, `measures.py` y `product_fit.py` (con `is_distinguished`) pasan a `tienda/catalogo`: son la
     búsqueda del catálogo, que también usa el asistente de bodega.
   - `order_watch.py` y `supervision.py` pasan a `agente/conversacion`: avisan y leen conversaciones.
   - `demo.py` pasa a `entregas`: arma la tienda completa con todos los módulos.
   Quedan para después, porque no cruzan capas: sacar el contrato de herramientas de `grok.py` a un
   `contrato.py` y reunir en `datos` las tablas que hoy crea cada módulo.
4. **Rehacer el panel** (hecho el 31-10-2026): bandeja «Por hacer» en Hoy (`bandeja.py`), una sola
   tabla de productos (Inventario + Catálogo + asistente de bodega, con alias para `#catalogo` y `#asistente`),
   Pedidos en filas con tres filtros y la marca PulsoTienda/AsisTendero. Medido en la tienda de demostración, sin
   acciones: Hoy pasa a 1.424 px en escritorio y 3.007 a 390 px (seis pendientes a la vista); Pedidos, a 1.118 y
   1.724; Inventario, a 3.745 y 5.407 con 50 filas, y Catálogo y Asistente dejan de ser vistas. Ventas usa la
   misma tabla (1.655 y 2.888 px con 15 transacciones; antes, 2.330 y 3.047).
