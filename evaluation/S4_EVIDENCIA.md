# Evidencia S4: pedidos, conversaciones largas, varios clientes y varios modelos

**Datos ficticios.** El catálogo, la tienda y los clientes son simulados; nada de esto representa un piloto. Cada
corrida real se lanzó con `python -m asistendero.evaluate --live` y su costo es el informado por la API
(`api_reported`). Los reportes completos quedan en `.local/` (ignorado por git).

## Qué se mide

24 casos nuevos en cuatro suites (ver `docs/HARNESS.md`, «Evaluación»):

| Suite | Casos | Qué prueba |
|---|---|---|
| `ruido` | 12 | Mala ortografía, mayúsculas, emojis, inglés, una sola palabra, peticiones difusas |
| `pedidos` | 8 | Comprar, confirmar, agendar, cambiar la hora, cancelar, dejar vencer el apartado, fiado, agendar sin pedido |
| `sesion_larga` | 2 | Conversaciones de 11 y 9 turnos con varias consultas, dos pedidos y una cancelación |
| `concurrencia` | 2 | Clientes que escriben a la vez a la misma tienda (K-01: dos piden 6 de los 9 bultos) |

Sin Grok, `tests/test_eval_sessions.py` recorre los 24 casos con un Grok guionizado y `tests/test_chaos.py` corre
conversaciones con decisiones aleatorias (500 sin fallos antes de `46f01f2`; 200 sin fallos sobre `e813368`).

## Resultado vigente: `e813368`, `s4-pedidos-v3`

| Corrida | Modelos | Casos | Resultado | Llamadas | USD | Reporte |
|---|---|---|---|---|---|---|
| 4 | `grok-4.20-0309-non-reasoning` | `pedidos`, G-07, M-01 y 3 fallos controlados | **10/10 y 3/3** | 53 | 0.086788 | `eval-20261022T162802410984Z` |
| 5 | `grok-4.20-0309-non-reasoning` | `sesion_larga` y `concurrencia` (7 clientes) | **4/4** | 63 | 0.094676 | `eval-20261022T162914589763Z` |
| 6 | 4 modelos, 3 casos a la vez | `pedidos`, `sesion_larga`, `concurrencia` | **12/12** | 105 | 0.469057 | `eval-20261022T163032844564Z` |
| 7 | 4 modelos, 3 casos a la vez | `ruido` | **12/12** | 28 | 0.119609 | `eval-20261022T163656473947Z` |

En K-01, con dos clientes simultáneos por 6 de los 9 bultos, uno obtuvo el pedido y el otro `INSUFFICIENT_STOCK`;
nunca hubo más apartado que bodega.

### Por modelo (corridas 6 y 7)

Cada caso usa un modelo, en rueda; en los casos con clientes, cada cliente usa el suyo. Los casos no son los mismos
para cada modelo, así que el costo por unidad compara órdenes de magnitud, no modelos en igualdad de condiciones.

| Modelo | Aprobados | Llamadas | USD | USD por unidad |
|---|---|---|---|---|
| `grok-4.20-0309-non-reasoning` | 7/7 | 43 | 0.059649 | 0.0085 |
| `grok-4.5` | 6/6 | 17 | 0.087702 | 0.0146 |
| `grok-4.7` | 7/7 | 24 | 0.211102 | 0.0302 |
| `grok-4.20-0309-reasoning` | 7/7 | 49 | 0.230213 | 0.0329 |

## Cómo se llegó ahí

| Corrida | Commit y prompt | Casos | Resultado | Llamadas | USD |
|---|---|---|---|---|---|
| 1 | `db2b895`, `s4-pedidos-v1` | los 24 S4 | 19/24 | 149 | 0.199452 |
| 2 | `86c4a60`, `s4-pedidos-v2` | los 67; **detenida por falta de memoria del equipo** tras 57 | 53/57 | 172 | 0.191809 |
| 3 | `6df04b7` (mismo código), `s4-pedidos-v2` | `pedidos`, G-07, M-01, R-12 | 8/11 | 65 | 0.100944 |

Cada falla se reprodujo en una prueba con la decisión real de Grok, que falla sin el arreglo:

| Caso | Falla | Causa | Arreglo |
|---|---|---|---|
| P-03 | Preguntó la presentación ya dicha | Grok puso «galón» en `presentation` y no en `text`; el servidor lo descartó | `86c4a60`: con un artículo, el atributo se respalda con todo el mensaje |
| P-02 | No registró de nuevo tras vencer | El aviso no decía qué herramienta faltaba | `86c4a60`: `ORDER_REQUIRED` nombra la herramienta |
| L-01 | «¿Quieres que lo registre?» en vez de registrar | El prompt pedía mostrar el resumen antes | `86c4a60`: `s4-pedidos-v2` registra en el mismo turno |
| L-02 | «¿Cuánto me toca pagar?» sin consultar | Respondió desde el contexto, que no trae precios | `86c4a60`: la pregunta por el pedido pide `consultar_pedido` |
| R-06 | Búsqueda sin resultado ante «algo para arreglar la casa» | Respuesta segura: sin precio y pide otra referencia | El caso acepta `not_found` |
| M-01 | «Dame 3 metros de ese» rechazado | Grok cotizó el SKU recordado sin volver a buscar | `e813368`: la cotización acepta los productos de la sesión, como los pedidos |
| P-02 | Registró sin que el cliente lo pidiera | «¿Todavía lo puedo confirmar?» contaba como confirmación | `e813368`: una pregunta solo confirma si abre con el sí |
| G-07 | Estado `order_issue` sin conversación | El pedido rechazado (`SESSION_REQUIRED`) tapaba la cotización | `e813368`: el estado sigue siendo `quoted`; prompt `s4-pedidos-v3` |

`e813368` también quitó el aviso `QUOTE_REQUIRED` tras registrar un pedido: el pedido ya trae precio y total, y el
aviso costaba dos llamadas más.

## Herramientas frente a la definición del reto

Aclaración de la organización (22-10-2026): una herramienta es una función que **el agente decide invocar por sí
mismo** para consultar información o ejecutar una acción real (una base de datos, una API, la propia plataforma),
con manejo de errores; no cuenta una función que solo regresa datos fijos. Se piden tres.

| # | Herramienta | Qué hace de verdad | Errores propios |
|---|---|---|---|
| 1 | `buscar_productos` | Consulta parametrizada a `products` en SQLite; las existencias restan lo apartado por pedidos activos | `INVALID_ARGUMENT`, `CATALOG_UNAVAILABLE` |
| 2 | `consultar_disponibilidad` | Lee existencias de un SKU en ese momento | `NOT_FOUND`, `INVALID_ARGUMENT`, `CATALOG_UNAVAILABLE` |
| 3 | `calcular_cotizacion_informativa` | Lee precio y existencias actuales y calcula subtotales y total | `INSUFFICIENT_STOCK`, `NOT_FOUND`, `INVALID_QUANTITY` |
| 4 | `consultar_info_tienda` | Lee `store_info` de SQLite; con `horario` calcula si la tienda está abierta con el reloj del servidor | `INVALID_ARGUMENT`, `NOT_FOUND` |
| 5 | `explorar_categoria` | Cuenta en SQLite variantes y cuántas tienen existencias | `NOT_FOUND`, `CATALOG_UNAVAILABLE` |
| 6 | `registrar_pedido` | **Escribe** un pedido y aparta existencias 5 minutos (`BEGIN IMMEDIATE`) | `INSUFFICIENT_STOCK`, `TOO_MANY_ORDERS`, `SESSION_REQUIRED` |
| 7 | `confirmar_pedido` | **Cambia** el pedido a confirmado y extiende el apartado | `ORDER_EXPIRED`, `ORDER_CLOSED`, `ORDER_NOT_FOUND` |
| 8 | `agendar_recogida` | **Guarda** fecha, hora y nota de recogida | `PICKUP_IN_PAST`, `PICKUP_OUTSIDE_HOURS`, `PICKUP_TOO_FAR` |
| 9 | `consultar_pedido` | Lee los pedidos de la conversación con su estado y total | `ORDER_NOT_FOUND` |
| 10 | `cancelar_pedido` | **Cancela** el pedido y libera lo apartado | `ORDER_CLOSED`, `ORDER_NOT_FOUND` |

Cómo se comprueba cada parte de la definición:

- **El agente decide.** Grok elige `call_tool` y sus argumentos; el servidor valida y ejecuta, pero nunca llama una
  herramienta por su cuenta. Un aviso (`QUOTE_REQUIRED`, `ORDER_REQUIRED`…) solo le recuerda un paso a Grok. En
  las corridas 4 a 7, Grok pidió por sí mismo 9 de las 10 herramientas: 127 solicitudes, 120 ejecutadas. El
  servidor frenó 7 antes de ejecutarlas (por ejemplo, `CONFIRMATION_NOT_STATED` o `QUANTITY_NOT_GROUNDED`) y hubo 4
  `INSUFFICIENT_STOCK` reales. `consultar_disponibilidad` no se pidió en esas corridas.
- **Acción real sobre la propia plataforma, no datos fijos.**
  - `test_price_and_stock_edits_reach_the_agent_and_leave_an_audit_trail`: el tendero cambia precio y existencias
    en su panel y, sin reiniciar nada, `consultar_disponibilidad` y `calcular_cotizacion_informativa` devuelven los
    valores nuevos (antes, cotizar 15 metros no alcanzaba).
  - `test_new_products_are_searchable_by_the_agent_and_skus_never_repeat`: un producto creado en el panel aparece
    en `buscar_productos`.
  - `test_delivered_orders_become_the_day_sales`: un pedido registrado por el agente llega al panel y, al
    entregarlo, descuenta bodega y cuenta como venta del día.
- **Manejo de errores.**
  - Toda respuesta tiene la forma `{"status", "data", "error", "source", "observed_at"}`, con un código estable.
  - Una base caída da `CATALOG_UNAVAILABLE` sin exponer rutas (`test_execute_tool_reports_catalog_unavailable_without_leaking_paths`).
  - Una excepción o una respuesta mal formada da `TOOL_FAILURE` (`execute_safely`).
  - Los fallos controlados F-01 a F-03 pasaron en la corrida 4.

**Conclusión:** se cumple el criterio de S2, con margen.

- Hay **diez** herramientas que consultan o modifican la base de la propia plataforma, y Grok invocó nueve por sí
  mismo con la llave del reto.
- La más débil es `consultar_info_tienda`. Lee la base y usa el reloj, pero hoy su contenido sale de `seed.py` y el
  panel del tendero aún no lo edita. Si alguien la objetara, quedan nueve.
- La base es local y sus datos son ficticios. Que sean ficticios no la vuelve «datos fijos»: el agente lee y
  escribe la misma base que el tendero administra.

**Consumo S4 medido (corridas 1 a 7):** 635 llamadas, USD 1.262335.
