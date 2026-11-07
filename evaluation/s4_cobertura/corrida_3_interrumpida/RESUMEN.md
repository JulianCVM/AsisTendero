# Semana de carga S4: resumen de la corrida desatendida

Generado desde `bitacora.jsonl` con `python -m asistendero.evaluacion.desatendido resumen`. Inventario real de Ferretería Carluz; consultas de cliente simuladas, todas distintas (`cola.json`).

| Medida | Valor |
|---|---|
| Unidades de trabajo terminadas | 25 |
| Exitosas | 23 (92.0%) |
| Costo total | 0.184671 USD |
| Costo por tarea | 0.007387 USD |
| Horas entre la primera y la última tarea | 0.09 |
| Llamadas a Grok | 178 |
| Commit | 2f059cb |
| Modelo | grok-4.20-0309-non-reasoning |

## Por clase de tarea

| Clase | Tareas | Exitosas |
|---|---|---|
| agendar_recogida | 3 | 2 |
| datos_personales | 3 | 3 |
| dos_clientes_ultima_unidad | 4 | 4 |
| lista_con_no_manejado | 2 | 2 |
| lista_editable | 2 | 2 |
| mas_de_lo_que_hay | 1 | 1 |
| opciones_y_memoria | 1 | 1 |
| pedido_cambio_cancelacion | 1 | 1 |
| pide_una_persona | 3 | 3 |
| regateo | 1 | 1 |
| tienda_en_medio | 2 | 2 |
| vencimiento | 2 | 1 |

## Errores y motivos de falla

- `INSUFFICIENT_STOCK`: 5
- `INVALID_ARGUMENT`: 2
- `SKU_NOT_GROUNDED`: 1
- `CHANGE_BY_REGISTERING`: 1
- `QUANTITY_NOT_GROUNDED`: 1
- `NOT_FOUND`: 1
- turno 1: pedidos []: 2
- turno 2: pedidos []: 2
- turno 3: pedidos []: 2
- turno 1: estado found: 1
- turno 2: sin aviso «liberé lo apartado»: 1
- turno 4: estado order_issue: 1
- turno 4: pedidos []: 1
- turno 1: estado nearby: 1
- turno 1: falta CLZ-0283: 1
- turno 2: estado order_issue: 1
- turno 3: estado answered: 1
- turno 3: sin recogida «2026-10-22 15:00»: 1

## Eventos del proceso

- arranque: 1
