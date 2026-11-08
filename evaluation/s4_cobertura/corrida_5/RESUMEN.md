# Semana de carga S4: resumen de la corrida desatendida

Generado desde `bitacora.jsonl` con `python -m asistendero.evaluacion.desatendido resumen`. Inventario real de Ferretería Carluz; consultas de cliente simuladas, todas distintas (`cola.json`).

| Medida | Valor |
|---|---|
| Unidades de trabajo terminadas | 182 |
| Exitosas | 169 (92.9%) |
| Costo total | 1.198407 USD |
| Costo por tarea | 0.006585 USD |
| Horas entre la primera y la última tarea | 0.60 |
| Llamadas a Grok | 1155 |
| Commit | 484b002 |
| Modelo | grok-4.20-0309-non-reasoning |

## Por clase de tarea

| Clase | Tareas | Exitosas |
|---|---|---|
| agendar_recogida | 14 | 13 |
| datos_personales | 14 | 12 |
| dos_clientes_ultima_unidad | 14 | 14 |
| inyeccion_y_baneo | 14 | 14 |
| lista_con_no_manejado | 14 | 12 |
| lista_editable | 14 | 14 |
| mas_de_lo_que_hay | 14 | 13 |
| opciones_y_memoria | 14 | 13 |
| pedido_cambio_cancelacion | 14 | 11 |
| pide_una_persona | 14 | 14 |
| regateo | 14 | 13 |
| tienda_en_medio | 14 | 12 |
| vencimiento | 14 | 14 |

## Errores y motivos de falla

- `INSUFFICIENT_STOCK`: 27
- `CHANGE_BY_REGISTERING`: 12
- `INVALID_ARGUMENT`: 5
- `QUANTITY_NOT_GROUNDED`: 5
- `SKU_NOT_GROUNDED`: 4
- `NOT_FOUND`: 3
- `MODEL_FAILURE`: 1
- `PURCHASE_NOT_STATED`: 1
- turno 2: pedidos []: 6
- turno 1: pedidos []: 5
- turno 2: estado order_issue: 4
- turno 1: estado nearby: 3
- turno 3: pedidos []: 3
- turno 1: estado not_found: 3
- turno 3: estado order_issue: 2
- turno 1: falta CLZ-0856: 2
- turno 2: estado not_found: 2
- turno 4: pedidos []: 2
- turno 5: pedidos []: 2
- turno 1: falta CLZ-1383: 1
- turno 1: muestra el código CLZ-1383: 1
- turno 1: falta CLZ-0283: 1
- turno 3: sin recogida «2026-10-22 15:00»: 1

## Eventos del proceso

- arranque: 1
- fin: 1
