# Semana de carga S4: resumen de la corrida desatendida

Generado desde `bitacora.jsonl` con `python -m asistendero.evaluacion.desatendido resumen`. Inventario real de Ferretería Carluz; consultas de cliente simuladas, todas distintas (`cola.json`).

| Medida | Valor |
|---|---|
| Unidades de trabajo terminadas | 182 |
| Exitosas | 107 (58.8%) |
| Costo total | 1.278005 USD |
| Costo por tarea | 0.007022 USD |
| Horas entre la primera y la última tarea | 0.51 |
| Llamadas a Grok | 1236 |
| Commit | 8ee733c |
| Modelo | grok-4.20-0309-non-reasoning |

## Por clase de tarea

| Clase | Tareas | Exitosas |
|---|---|---|
| agendar_recogida | 14 | 0 |
| datos_personales | 14 | 9 |
| dos_clientes_ultima_unidad | 14 | 10 |
| inyeccion_y_baneo | 14 | 12 |
| lista_con_no_manejado | 14 | 12 |
| lista_editable | 14 | 1 |
| mas_de_lo_que_hay | 14 | 0 |
| opciones_y_memoria | 14 | 2 |
| pedido_cambio_cancelacion | 14 | 12 |
| pide_una_persona | 14 | 12 |
| regateo | 14 | 14 |
| tienda_en_medio | 14 | 11 |
| vencimiento | 14 | 12 |

## Errores y motivos de falla

- `INSUFFICIENT_STOCK`: 22
- `INVALID_ARGUMENT`: 20
- `DUPLICATE_CALL`: 19
- `QUANTITY_NOT_GROUNDED`: 19
- `SKU_NOT_GROUNDED`: 16
- `TOOL_FAILURE`: 13
- `CHANGE_BY_REGISTERING`: 12
- `AMBIGUOUS_REFERENCE`: 9
- `NOT_FOUND`: 2
- `PURCHASE_NOT_STATED`: 2
- `MODEL_FAILURE`: 1
- turno 2: pedidos []: 26
- turno 3: estado order_issue: 18
- turno 2: estado order_issue: 18
- turno 1: estado clarify: 16
- turno 3: sin recogida «2026-10-22 15:00»: 14
- turno 1: pedidos []: 12
- turno 2: estado clarify: 12
- turno 5: pedidos []: 11
- turno 3: pedidos []: 10
- turno 5: estado clarify: 9
- turno 6: estado order_issue: 7
- turno 6: pedidos []: 7
- turno 3: estado clarify: 4
- turno 4: pedidos []: 4
- 0 pedidos activos entre todos: 4

## Eventos del proceso

- arranque: 1
- fin: 1
