# Evidencia S4: pedidos, conversaciones largas y varios clientes

**Datos ficticios.** El catálogo, la tienda y los clientes son simulados; nada de esto representa un piloto. Cada
corrida real se lanzó con `python -m asistendero.evaluate --live` y su costo es el informado por la API
(`api_reported`).

## Qué se mide

24 casos nuevos en cuatro suites (ver `docs/HARNESS.md`, «Evaluación»):

| Suite | Casos | Qué prueba |
|---|---|---|
| `ruido` | 12 | Mala ortografía, mayúsculas, emojis, inglés, una sola palabra, peticiones difusas |
| `pedidos` | 8 | Comprar, confirmar, agendar, cambiar la hora, cancelar, dejar vencer el apartado, fiado, agendar sin pedido |
| `sesion_larga` | 2 | Conversaciones de 11 y 9 turnos con varias consultas, dos pedidos y una cancelación |
| `concurrencia` | 2 | Clientes que escriben a la vez a la misma tienda (K-01: dos piden 6 de los 9 bultos) |

Sin Grok, `tests/test_eval_sessions.py` recorre los 24 casos con un Grok guionizado y `tests/test_chaos.py` corre
conversaciones con decisiones aleatorias (500 sin fallos antes de `46f01f2`).

## Corrida 1: casos S4 con `s4-pedidos-v1`

- Commit `db2b895`, `grok-4.20-0309-non-reasoning`, un caso a la vez, tope USD 1.
- **19/24**, 149 llamadas a Grok, 325.132 tokens, **USD 0.199452** (USD 0.0083 por caso).
- Reporte local: `.local/eval-20261022T081512604906Z.json`.

| Caso | Falla | Causa | Arreglo (`86c4a60`) |
|---|---|---|---|
| P-03 | Preguntó la presentación ya dicha | Grok puso «galón» en `presentation` y no en `text`; el servidor lo descartó | Con un solo artículo, el atributo se respalda con todo el mensaje |
| P-02 | No registró de nuevo tras vencer | Grok intentó confirmar el pedido vencido; el aviso no decía qué herramienta faltaba | El aviso `ORDER_REQUIRED` nombra la herramienta |
| L-01 | Preguntó «¿quieres que lo registre?» y no registró | El prompt pedía «mostrar el resumen» antes | `s4-pedidos-v2`: registrar en el mismo turno |
| L-02 | «¿cuánto me toca pagar?» sin consultar | Respondió desde el contexto, que no trae precios | Una pregunta por el pedido pide `consultar_pedido` |
| R-06 | Búsqueda sin resultado ante «algo para arreglar la casa» | Respuesta segura (sin precio, pide otra referencia) | El caso acepta `not_found` |

K-01 pasó: con dos clientes simultáneos, uno obtuvo el pedido y el otro `INSUFFICIENT_STOCK`; nunca hubo más
apartado que bodega.

## Corrida 2: todos los casos con `s4-pedidos-v2` (interrumpida)

- Commit `86c4a60`, `grok-4.20-0309-non-reasoning`, tope USD 1.5, con fallos controlados.
- **Claude Code la detuvo por falta de memoria del equipo** tras 57 de 67 casos; no quedó reporte final, solo la
  bitácora parcial `.local/eval-20261022T083115279738Z.partial.jsonl`.
- Medido en esos 57: **53/57**, 172 llamadas, **USD 0.1918093500**. Fallaron G-07, M-01, R-12 y P-02; el detalle de
  cada falla no quedó guardado.
- No corrieron P-03 a P-08, L-01, L-02, K-01, K-02 ni los tres fallos controlados.

## Pendiente

- Repetir los casos que no corrieron y revisar las cuatro fallas de la corrida 2.
- La corrida con varios modelos (`--models … --concurrency 3`) no se ha hecho.

**Consumo S4 medido:** 321 llamadas, USD 0.3912613500.
