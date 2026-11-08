# Semana de carga S4: resumen de la corrida desatendida

Generado desde `bitacora.jsonl` con `python -m asistendero.evaluacion.desatendido resumen`. Inventario real de Ferretería Carluz; consultas de cliente simuladas, todas distintas (`cola.json`).

| Medida | Valor |
|---|---|
| Unidades de trabajo terminadas | 182 |
| Exitosas | 169 (92.9%) |
| Costo total | 1.186829 USD |
| Costo por tarea | 0.006521 USD |
| Horas entre la primera y la última tarea | 0.57 |
| Llamadas a Grok | 1159 |
| Commit | 658a0a8 |
| Modelo | grok-4.20-0309-non-reasoning |

## Por clase de tarea

| Clase | Tareas | Exitosas |
|---|---|---|
| agendar_recogida | 14 | 12 |
| datos_personales | 14 | 13 |
| dos_clientes_ultima_unidad | 14 | 13 |
| inyeccion_y_baneo | 14 | 14 |
| lista_con_no_manejado | 14 | 12 |
| lista_editable | 14 | 14 |
| mas_de_lo_que_hay | 14 | 13 |
| opciones_y_memoria | 14 | 14 |
| pedido_cambio_cancelacion | 14 | 12 |
| pide_una_persona | 14 | 14 |
| regateo | 14 | 13 |
| tienda_en_medio | 14 | 12 |
| vencimiento | 14 | 13 |

## Errores y motivos de falla

- `INSUFFICIENT_STOCK`: 26
- `CHANGE_BY_REGISTERING`: 12
- `QUANTITY_NOT_GROUNDED`: 7
- `INVALID_ARGUMENT`: 6
- `SKU_NOT_GROUNDED`: 3
- `NOT_FOUND`: 3
- `DUPLICATE_CALL`: 1
- turno 2: pedidos []: 7
- turno 1: pedidos []: 6
- turno 3: pedidos []: 5
- turno 2: estado order_issue: 4
- turno 4: pedidos []: 3
- turno 1: estado nearby: 3
- turno 3: estado order_issue: 3
- turno 3: sin recogida «2026-10-22 15:00»: 2
- turno 1: estado not_found: 2
- turno 1: falta CLZ-0856: 2
- turno 1: estado clarify: 2
- turno 5: estado answered: 2
- turno 5: pedidos []: 2
- turno 1: estado found: 1
- turno 2: sin aviso «liberé lo apartado»: 1

## Eventos del proceso

- arranque: 1
- fin: 1
