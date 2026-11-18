# Semana de carga S4: resumen de la corrida desatendida

Generado desde `bitacora.jsonl` con `python -m asistendero.evaluacion.desatendido resumen`. Inventario real de Ferretería Carluz; consultas de cliente simuladas, todas distintas (`cola.json`).

| Medida | Valor |
|---|---|
| Unidades de trabajo terminadas | 73 |
| Exitosas | 49 (67.1%) |
| Costo total | 0.340443 USD |
| Costo por tarea | 0.004664 USD |
| Horas entre la primera y la última tarea | 0.22 |
| Llamadas a Grok | 301 |
| Commit | 422b593 |
| Modelo | grok-4.20-0309-non-reasoning |

## Por clase de tarea

| Clase | Tareas | Exitosas |
|---|---|---|
| categoria | 1 | 0 |
| conversacion | 17 | 8 |
| error_ortografia | 3 | 1 |
| familia | 13 | 11 |
| inyeccion | 3 | 2 |
| no_manejado | 15 | 15 |
| precio | 14 | 6 |
| tienda | 7 | 6 |

## Errores y motivos de falla

- `NOT_FOUND`: 33
- `INVALID_ARGUMENT`: 10
- `INSUFFICIENT_STOCK`: 7
- `MODEL_FAILURE`: 5
- `QUANTITY_NOT_GROUNDED`: 3
- `PURCHASE_NOT_STATED`: 1
- `SKU_NOT_GROUNDED`: 1
- turno 4: estado order_issue: 5
- eligió otro producto: 4
- estado model_error: 3
- estado partial: 2
- estado not_verified: 1
- turno 4: estado model_error: 1
- estado answered: 1
- 1 llamadas a Grok: 1
- estado informed: 1
- estado model_invalid: 1
- estado not_found: 1
- estado nearby: 1
- turno 1: estado not_verified: 1
- turno 3: estado not_verified: 1
- turno 2: muestra el código CLZ-1909: 1

## Eventos del proceso

- arranque: 1
- fin: 1
- pausa: 2
