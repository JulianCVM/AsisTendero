# Semana de carga S4: resumen de la corrida desatendida

Generado desde `bitacora.jsonl` con `python -m asistendero.evaluacion.desatendido resumen`. Inventario real de Ferretería Carluz; consultas de cliente simuladas, todas distintas (`cola.json`).

| Medida | Valor |
|---|---|
| Unidades de trabajo terminadas | 1300 |
| Exitosas | 1227 (94.4%) |
| Costo total | 2.994178 USD |
| Costo por tarea | 0.002303 USD |
| Horas entre la primera y la última tarea | 12.24 |
| Llamadas a Grok | 3278 |
| Commit | 970dbd5 |
| Modelo | grok-4.20-0309-non-reasoning |

## Por clase de tarea

| Clase | Tareas | Exitosas |
|---|---|---|
| categoria | 39 | 38 |
| conversacion | 98 | 81 |
| cotizacion | 208 | 208 |
| error_ortografia | 39 | 36 |
| familia | 117 | 104 |
| inyeccion | 13 | 10 |
| no_manejado | 65 | 50 |
| precio | 691 | 677 |
| tienda | 30 | 23 |

## Errores y motivos de falla

- `INSUFFICIENT_STOCK`: 127
- `NOT_FOUND`: 41
- `QUANTITY_NOT_GROUNDED`: 33
- `INVALID_ARGUMENT`: 31
- `PURCHASE_NOT_STATED`: 24
- `SKU_NOT_GROUNDED`: 8
- `MODEL_FAILURE`: 6
- estado tool_error: 27
- turno 4: estado order_issue: 8
- estado not_verified: 7
- estado informed: 7
- eligió otro producto: 4
- estado answered: 3
- 1 llamadas a Grok: 3
- estado partial: 3
- turno 1: estado tool_error: 3
- turno 1: estado model_error: 3
- turno 2: estado model_error: 3
- turno 3: estado model_error: 3
- turno 1: estado not_verified: 2
- estado model_invalid: 2
- turno 3: estado order_issue: 1

## Eventos del proceso

- arranque: 1
- fin: 1
- pausa: 2
