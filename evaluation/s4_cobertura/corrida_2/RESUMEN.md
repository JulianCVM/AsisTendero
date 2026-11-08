# Semana de carga S4: resumen de la corrida desatendida

Generado desde `bitacora.jsonl` con `python -m asistendero.evaluacion.desatendido resumen`. Inventario real de Ferretería Carluz; consultas de cliente simuladas, todas distintas (`cola.json`).

| Medida | Valor |
|---|---|
| Unidades de trabajo terminadas | 182 |
| Exitosas | 134 (73.6%) |
| Costo total | 1.212126 USD |
| Costo por tarea | 0.006660 USD |
| Horas entre la primera y la última tarea | 0.56 |
| Llamadas a Grok | 1164 |
| Commit | 1bed131 |
| Modelo | grok-4.20-0309-non-reasoning |

## Por clase de tarea

| Clase | Tareas | Exitosas |
|---|---|---|
| agendar_recogida | 14 | 0 |
| datos_personales | 14 | 10 |
| dos_clientes_ultima_unidad | 14 | 10 |
| inyeccion_y_baneo | 14 | 12 |
| lista_con_no_manejado | 14 | 12 |
| lista_editable | 14 | 12 |
| mas_de_lo_que_hay | 14 | 11 |
| opciones_y_memoria | 14 | 3 |
| pedido_cambio_cancelacion | 14 | 13 |
| pide_una_persona | 14 | 12 |
| regateo | 14 | 14 |
| tienda_en_medio | 14 | 12 |
| vencimiento | 14 | 13 |

## Errores y motivos de falla

- `INSUFFICIENT_STOCK`: 22
- `CHANGE_BY_REGISTERING`: 13
- `SKU_NOT_GROUNDED`: 10
- `QUANTITY_NOT_GROUNDED`: 9
- `INVALID_ARGUMENT`: 7
- `NOT_FOUND`: 3
- `DUPLICATE_CALL`: 2
- `PURCHASE_NOT_STATED`: 1
- turno 3: sin recogida «2026-10-22 15:00»: 14
- turno 2: pedidos []: 11
- turno 1: estado clarify: 11
- turno 2: estado clarify: 11
- turno 1: pedidos []: 8
- turno 3: pedidos []: 6
- turno 2: estado order_issue: 5
- 0 pedidos activos entre todos: 4
- turno 3: estado order_issue: 3
- turno 1: estado not_found: 3
- turno 1: falta CLZ-1164: 2
- cliente 1: turno 1: estado clarify: 2
- cliente 2: turno 1: estado clarify: 2
- turno 1: falta CLZ-1377: 2
- turno 1: falta CLZ-0856: 2

## Eventos del proceso

- arranque: 1
- fin: 1
