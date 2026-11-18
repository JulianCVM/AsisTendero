# Semana de carga S4: resumen de la corrida desatendida

Generado desde `bitacora.jsonl` con `python -m asistendero.evaluacion.desatendido resumen`. Inventario real de Ferretería Carluz; consultas de cliente simuladas, todas distintas (`cola.json`).

| Medida | Valor |
|---|---|
| Unidades de trabajo terminadas | 101 |
| Exitosas | 100 (99.0%) |
| Costo total | 0.082761 USD |
| Costo por tarea | 0.000819 USD |
| Horas entre la primera y la última tarea | 0.05 |
| Llamadas a Grok | 101 |
| Commit | e6fa46a |
| Modelo | grok-4.20-0309-non-reasoning |

## Por clase de tarea

| Clase | Tareas | Exitosas |
|---|---|---|
| ambiguo | 6 | 6 |
| cambio_precio | 10 | 10 |
| consulta | 10 | 10 |
| conteo | 10 | 10 |
| dos_llegadas | 10 | 9 |
| inyeccion | 5 | 5 |
| llegada_futura | 10 | 10 |
| llegada_parcial | 10 | 10 |
| llegada_sin_proveedor | 10 | 10 |
| pedido_proveedor | 10 | 10 |
| recepcion | 10 | 10 |

## Errores y motivos de falla

- Ninguno
- sin recepcion de CLZ-1371: 1

## Eventos del proceso

- arranque: 1
- fin: 1
