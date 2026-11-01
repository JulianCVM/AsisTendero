# Costo por tarea y por operación

**Datos ficticios.** El catálogo, las dos tiendas y los clientes son simulados; nada de esto representa un piloto.
Cada costo es el que informó la API de la pasarela del reto en cada llamada (`api_reported`), no una estimación por
tarifa. Las herramientas del agente corren en el servidor sobre SQLite: no tienen costo de API, solo latencia.

Este documento es el reporte de costo por ejecución del entregable S3/S4. Sale de la corrida 48, real, del evaluador con
Grok sobre el commit `bef4913`, en 5 tandas de suites (cada una en su proceso, mismo commit
y modelo): 345 tareas, que es cada caso de `evaluation/cases.json`. Una tarea puede ser un mensaje suelto,
una conversación de varios turnos o varios clientes a la vez. Las tablas se generaron sin llamar a Grok, con

```powershell
.\.venv\Scripts\python.exe -m asistendero.evaluacion.eval_costs .local\eval-20261101T203838787427Z.json .local\eval-20261101T204047172772Z.json .local\eval-20261101T204320123688Z.json .local\eval-20261101T204515745940Z.json .local\eval-20261101T204655840615Z.json --out evaluation\COSTOS_POR_TAREA.md
```

(`eval_costs` las une solo si comparten commit y modelo, sin cambios sin commit y sin casos repetidos)
y la parte escrita a mano es este encabezado y la sección «Cómo leerlo». El reporte JSON completo, con cada evento,
queda en `.local/` (no se sube: trae las trazas). El resultado de la corrida y sus fallos están en
`evaluation/S4_EVIDENCIA.md`.

## Cómo leerlo

- **Tarea:** un caso de evaluación completo. **Mensaje:** cada mensaje del cliente dentro de una tarea.
- **Operación de Grok:** cada llamada al modelo. «Interpretar el mensaje» es la primera decisión del turno. «Leer lo
  observado» es la decisión que viene después de una herramienta: pedir otra o redactar la respuesta. Una llamada de
  más suele venir de un aviso del servidor (por ejemplo, «falta cotizar»).
- **Tokens de entrada (caché):** el prompt fijo va primero y la pasarela lo reutiliza. El número entre paréntesis
  son los tokens que salieron de la caché, más baratos.
- **Tareas sin llamar a Grok:** inyecciones y otros mensajes que el servidor rechaza antes del modelo. Cuestan cero.
- **Proyección a 1.000 tareas:** el costo medio por tarea multiplicado por 1.000, con la misma mezcla de casos. Es
  una cuenta, no una medición.

## Corrida

- Commit `bef4913` (árbol limpio), modelo `grok-4.20-0309-non-reasoning`, prompt `mercado-v1`, `s4-conversacion-v12`, inicio 2026-11-01T20:40:44.749416+00:00.
- 345 tareas (500 mensajes del cliente), 344 aprobadas. Costo informado por la API para 345 de 345 tareas.

## Resumen

| Medida | Valor |
|---|---|
| Costo total | 0.967176 USD |
| Costo medio por tarea | 0.002803 USD |
| Mediana, percentil 90 y máximo por tarea | 0.001699 / 0.006191 / 0.026348 USD |
| Costo medio por mensaje del cliente | 0.001934 USD |
| Costo medio por llamada a Grok | 0.000936 USD |
| Llamadas a Grok por tarea | 2.99 |
| Tokens de entrada desde la caché | 92.6 % |
| Llamadas con el prompt fijo en caché | 99.2 % |
| Tareas sin llamar a Grok (rechazos antes del modelo) | 46 |
| Proyección a 1.000 tareas con esta mezcla | 2.803409 USD |

## Costo por operación de Grok

| Operación | Llamadas | USD total | USD por llamada | Tokens de entrada (caché) | Tokens de salida | ms por llamada |
|---|---|---|---|---|---|---|
| Leer lo observado y redactar la respuesta | 442 | 0.455252 | 0.001030 | 1310172 (1195520) | 29133 | 1735 |
| Interpretar el mensaje y pedir una herramienta | 388 | 0.331809 | 0.000855 | 1082739 (1017600) | 18746 | 1529 |
| Leer lo observado y pedir otra herramienta | 150 | 0.138623 | 0.000924 | 441844 (408704) | 6183 | 1420 |
| Interpretar el mensaje y responder sin herramientas | 45 | 0.038821 | 0.000863 | 124280 (117504) | 2740 | 1710 |
| Mirar la foto del cliente (visión) | 8 | 0.002672 | 0.000334 | 4224 (3584) | 462 | 1611 |

## Herramientas del servidor (sin costo de API)

| Herramienta | Pedidas por Grok | Ejecutadas | Rechazadas por la validación | ms por ejecución |
|---|---|---|---|---|
| `buscar_productos` | 295 | 290 | 5 | 18 |
| `calcular_cotizacion_informativa` | 179 | 162 | 17 | 1 |
| `registrar_pedido` | 62 | 59 | 3 | 6 |
| `consultar_info_tienda` | 33 | 33 | 0 | 1 |
| `confirmar_pedido` | 21 | 18 | 3 | 5 |
| `agendar_recogida` | 13 | 13 | 0 | 4 |
| `cancelar_pedido` | 12 | 8 | 4 | 5 |
| `explorar_categoria` | 7 | 7 | 0 | 7 |
| `consultar_pedido` | 7 | 7 | 0 | 1 |
| `consultar_disponibilidad` | 3 | 3 | 0 | 1 |

## Por suite

| Suite | Tareas | Aprobadas | Llamadas a Grok | USD | USD por tarea |
|---|---|---|---|---|---|
| ampliacion | 20 | 20 | 45 | 0.038465 | 0.001923 |
| catalogo | 12 | 12 | 26 | 0.022311 | 0.001859 |
| concurrencia | 2 | 2 | 14 | 0.012155 | 0.006078 |
| conversacion | 5 | 5 | 21 | 0.016775 | 0.003355 |
| extremos | 24 | 23 | 57 | 0.047895 | 0.001996 |
| fallas | 38 | 38 | 125 | 0.122084 | 0.003213 |
| flujos | 15 | 15 | 104 | 0.108927 | 0.007262 |
| fotos | 11 | 11 | 14 | 0.007694 | 0.000699 |
| inyeccion | 45 | 45 | 26 | 0.021320 | 0.000474 |
| memoria | 6 | 6 | 62 | 0.064801 | 0.010800 |
| mercado | 33 | 33 | 94 | 0.088277 | 0.002675 |
| natural | 14 | 14 | 96 | 0.094277 | 0.006734 |
| parafrasis | 24 | 24 | 56 | 0.047311 | 0.001971 |
| pedidos | 8 | 8 | 38 | 0.037399 | 0.004675 |
| ruido | 12 | 12 | 27 | 0.022849 | 0.001904 |
| s2 | 10 | 10 | 23 | 0.019264 | 0.001926 |
| seguridad | 10 | 10 | 9 | 0.007471 | 0.000747 |
| sesion_larga | 2 | 2 | 36 | 0.048398 | 0.024199 |
| surtido | 10 | 10 | 20 | 0.015502 | 0.001550 |
| tienda | 6 | 6 | 10 | 0.007917 | 0.001320 |
| variados | 38 | 38 | 130 | 0.116083 | 0.003055 |

## Por negocio

| Negocio | Tareas | Aprobadas | Llamadas a Grok | USD | USD por tarea |
|---|---|---|---|---|---|
| ferreteria | 298 | 297 | 905 | 0.850521 | 0.002854 |
| mercado | 47 | 47 | 128 | 0.116655 | 0.002482 |

## Por tarea

| Caso | Suite | Negocio | Mensajes | Llamadas | Herramientas | Tokens entrada (caché) | Tokens salida | USD | ms | Aprobado |
|---|---|---|---|---|---|---|---|---|---|---|
| S2-01 | s2 | ferreteria | 1 | 2 | 2 | 5590 (5376) | 111 | 0.001620 | 5882 | sí |
| S2-02 | s2 | ferreteria | 1 | 4 | 2 | 11643 (10624) | 295 | 0.004136 | 7189 | sí |
| S2-03 | s2 | ferreteria | 1 | 2 | 1 | 5480 (5120) | 109 | 0.001746 | 3679 | sí |
| S2-04 | s2 | ferreteria | 1 | 2 | 1 | 5501 (5376) | 118 | 0.001526 | 3063 | sí |
| S2-05 | s2 | ferreteria | 1 | 2 | 1 | 5490 (5248) | 124 | 0.001662 | 3332 | sí |
| S2-06 | s2 | ferreteria | 1 | 2 | 1 | 5496 (5376) | 124 | 0.001535 | 3595 | sí |
| S2-07 | s2 | ferreteria | 1 | 2 | 2 | 5554 (5504) | 120 | 0.001463 | 3246 | sí |
| S2-08 | s2 | ferreteria | 1 | 1 | 1 | 2685 (2560) | 44 | 0.000778 | 1406 | sí |
| S2-09 | s2 | ferreteria | 1 | 2 | 1 | 5528 (5120) | 83 | 0.001742 | 3433 | sí |
| S2-10 | s2 | ferreteria | 1 | 4 | 2 | 11601 (11392) | 206 | 0.003055 | 6705 | sí |
| C-01 | catalogo | ferreteria | 1 | 2 | 2 | 5582 (5376) | 102 | 0.001588 | 3316 | sí |
| C-02 | catalogo | ferreteria | 1 | 2 | 1 | 5506 (5120) | 113 | 0.001789 | 6144 | sí |
| C-03 | catalogo | ferreteria | 1 | 2 | 2 | 5573 (5120) | 108 | 0.001860 | 3153 | sí |
| C-04 | catalogo | ferreteria | 1 | 2 | 2 | 5603 (5248) | 120 | 0.001793 | 3334 | sí |
| C-05 | catalogo | ferreteria | 1 | 2 | 1 | 5471 (5248) | 134 | 0.001663 | 3492 | sí |
| C-06 | catalogo | ferreteria | 1 | 2 | 2 | 5607 (5376) | 116 | 0.001654 | 3383 | sí |
| C-07 | catalogo | ferreteria | 1 | 2 | 1 | 5723 (5504) | 179 | 0.001822 | 3495 | sí |
| C-08 | catalogo | ferreteria | 1 | 4 | 2 | 11833 (11264) | 282 | 0.003669 | 6587 | sí |
| C-09 | catalogo | ferreteria | 1 | 2 | 2 | 5537 (5376) | 115 | 0.001564 | 3289 | sí |
| C-10 | catalogo | ferreteria | 1 | 2 | 1 | 5474 (5248) | 107 | 0.001600 | 3278 | sí |
| C-11 | catalogo | ferreteria | 1 | 2 | 2 | 5586 (5248) | 117 | 0.001765 | 3333 | sí |
| C-12 | catalogo | ferreteria | 1 | 2 | 1 | 5456 (5248) | 94 | 0.001545 | 3531 | sí |
| T-01 | tienda | ferreteria | 1 | 2 | 1 | 5528 (5120) | 106 | 0.001799 | 3036 | sí |
| T-02 | tienda | ferreteria | 1 | 2 | 1 | 5441 (5248) | 94 | 0.001526 | 3142 | sí |
| T-03 | tienda | ferreteria | 1 | 2 | 1 | 5430 (5248) | 99 | 0.001525 | 3125 | sí |
| T-04 | tienda | ferreteria | 1 | 1 | 1 | 2684 (2560) | 22 | 0.000722 | 1369 | sí |
| T-05 | tienda | ferreteria | 1 | 1 | 1 | 2684 (2560) | 28 | 0.000737 | 1373 | sí |
| T-06 | tienda | ferreteria | 1 | 2 | 1 | 5420 (5120) | 84 | 0.001609 | 3272 | sí |
| G-01 | seguridad | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 7 | sí |
| G-02 | seguridad | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 8 | sí |
| G-03 | seguridad | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 7 | sí |
| G-04 | seguridad | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 10 | sí |
| G-05 | seguridad | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 17 | sí |
| G-06 | seguridad | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 13 | sí |
| G-07 | seguridad | ferreteria | 1 | 2 | 2 | 5594 (5248) | 124 | 0.001792 | 3507 | sí |
| G-08 | seguridad | ferreteria | 1 | 5 | 2 | 14473 (14080) | 291 | 0.004035 | 8499 | sí |
| G-09 | seguridad | ferreteria | 1 | 2 | 1 | 5502 (5248) | 111 | 0.001645 | 3355 | sí |
| G-10 | seguridad | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 7 | sí |
| M-01 | conversacion | ferreteria | 2 | 4 | 2 | 11236 (10752) | 202 | 0.003260 | 8760 | sí |
| M-02 | conversacion | ferreteria | 2 | 4 | 2 | 11339 (11136) | 212 | 0.003011 | 7361 | sí |
| M-03 | conversacion | ferreteria | 2 | 4 | 3 | 11629 (11136) | 199 | 0.003341 | 6886 | sí |
| M-04 | conversacion | ferreteria | 2 | 4 | 2 | 11214 (10624) | 183 | 0.003320 | 6746 | sí |
| M-05 | conversacion | ferreteria | 2 | 5 | 3 | 14501 (14208) | 254 | 0.003843 | 8823 | sí |
| R-01 | ruido | ferreteria | 1 | 2 | 2 | 5599 (5504) | 115 | 0.001507 | 3604 | sí |
| R-02 | ruido | ferreteria | 1 | 2 | 1 | 5470 (5248) | 106 | 0.001592 | 3231 | sí |
| R-03 | ruido | ferreteria | 1 | 4 | 2 | 11287 (10880) | 205 | 0.003197 | 6481 | sí |
| R-04 | ruido | ferreteria | 1 | 2 | 1 | 5474 (5376) | 91 | 0.001425 | 2981 | sí |
| R-05 | ruido | ferreteria | 1 | 1 | 0 | 2679 (2560) | 35 | 0.000748 | 1584 | sí |
| R-06 | ruido | ferreteria | 1 | 3 | 1 | 8602 (8320) | 256 | 0.002656 | 5545 | sí |
| R-07 | ruido | ferreteria | 1 | 1 | 0 | 2682 (2560) | 59 | 0.000812 | 1615 | sí |
| R-08 | ruido | ferreteria | 1 | 2 | 1 | 5566 (5120) | 118 | 0.001876 | 3290 | sí |
| R-09 | ruido | ferreteria | 1 | 2 | 1 | 5562 (5376) | 107 | 0.001575 | 3014 | sí |
| R-10 | ruido | ferreteria | 1 | 4 | 1 | 11776 (11008) | 267 | 0.003829 | 7060 | sí |
| R-11 | ruido | ferreteria | 1 | 1 | 0 | 2682 (2560) | 67 | 0.000832 | 1748 | sí |
| R-12 | ruido | ferreteria | 1 | 3 | 1 | 8602 (8064) | 205 | 0.002798 | 5662 | sí |
| P-01 | pedidos | ferreteria | 4 | 7 | 5 | 20922 (19072) | 425 | 0.007189 | 11449 | sí |
| P-02 | pedidos | ferreteria | 4 | 6 | 3 | 17605 (16256) | 398 | 0.005932 | 10400 | sí |
| P-03 | pedidos | ferreteria | 3 | 5 | 3 | 14752 (13440) | 263 | 0.004986 | 8343 | sí |
| P-04 | pedidos | ferreteria | 2 | 4 | 3 | 11485 (10496) | 215 | 0.003873 | 6536 | sí |
| P-05 | pedidos | ferreteria | 1 | 2 | 0 | 5455 (5248) | 71 | 0.001486 | 2817 | sí |
| P-06 | pedidos | ferreteria | 4 | 8 | 5 | 24039 (21760) | 455 | 0.008338 | 12687 | sí |
| P-07 | pedidos | ferreteria | 2 | 4 | 2 | 11469 (10496) | 252 | 0.003945 | 6287 | sí |
| P-08 | pedidos | ferreteria | 1 | 2 | 0 | 5472 (5248) | 128 | 0.001650 | 3537 | sí |
| L-01 | sesion_larga | ferreteria | 11 | 19 | 10 | 60555 (49408) | 1013 | 0.026348 | 31258 | sí |
| L-02 | sesion_larga | ferreteria | 9 | 17 | 12 | 54264 (45824) | 934 | 0.022050 | 27212 | sí |
| K-01 | concurrencia | ferreteria | 2 | 8 | 5 | 22864 (21632) | 435 | 0.006954 | 13359 | sí |
| K-02 | concurrencia | ferreteria | 4 | 6 | 4 | 17094 (16256) | 361 | 0.005201 | 9873 | sí |
| X-01 | extremos | ferreteria | 1 | 2 | 2 | 5600 (5376) | 122 | 0.001660 | 3801 | sí |
| X-02 | extremos | ferreteria | 1 | 2 | 2 | 5610 (5120) | 120 | 0.001936 | 4003 | sí |
| X-03 | extremos | ferreteria | 1 | 5 | 1 | 14203 (13440) | 284 | 0.004352 | 8622 | sí |
| X-04 | extremos | ferreteria | 1 | 4 | 1 | 11253 (10240) | 251 | 0.003942 | 10122 | sí |
| X-05 | extremos | ferreteria | 1 | 2 | 2 | 5588 (5504) | 110 | 0.001481 | 3076 | sí |
| X-06 | extremos | ferreteria | 1 | 2 | 1 | 5479 (5248) | 100 | 0.001588 | 3308 | sí |
| X-07 | extremos | ferreteria | 1 | 2 | 1 | 5563 (5248) | 150 | 0.001818 | 3804 | sí |
| X-08 | extremos | ferreteria | 1 | 2 | 2 | 5567 (5248) | 106 | 0.001713 | 3245 | sí |
| X-09 | extremos | ferreteria | 1 | 1 | 1 | 2685 (2560) | 44 | 0.000778 | 1413 | sí |
| X-10 | extremos | ferreteria | 1 | 5 | 3 | 14268 (13952) | 331 | 0.004013 | 7943 | sí |
| X-11 | extremos | ferreteria | 1 | 3 | 1 | 8248 (7936) | 172 | 0.002407 | 8404 | sí |
| X-12 | extremos | ferreteria | 1 | 1 | 0 | 2691 (2688) | 93 | 0.000774 | 1993 | sí |
| X-13 | extremos | ferreteria | 1 | 4 | 2 | 11294 (11008) | 201 | 0.003062 | 5897 | sí |
| X-14 | extremos | ferreteria | 1 | 4 | 2 | 11238 (10624) | 195 | 0.003380 | 6349 | sí |
| X-15 | extremos | ferreteria | 1 | 2 | 2 | 5600 (5376) | 113 | 0.001638 | 3327 | sí |
| X-16 | extremos | ferreteria | 1 | 2 | 1 | 5489 (5248) | 108 | 0.001621 | 3046 | sí |
| X-17 | extremos | ferreteria | 1 | 2 | 2 | 5534 (5376) | 109 | 0.001545 | 3215 | sí |
| X-18 | extremos | ferreteria | 1 | 2 | 1 | 5487 (5376) | 110 | 0.001489 | 3111 | sí |
| X-19 | extremos | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 7 | sí |
| X-20 | extremos | ferreteria | 1 | 2 | 1 | 5528 (5504) | 133 | 0.001463 | 3536 | sí |
| X-21 | extremos | ferreteria | 1 | 2 | 2 | 5589 (5376) | 110 | 0.001616 | 3305 | sí |
| X-22 | extremos | ferreteria | 1 | 5 | 2 | 14356 (13184) | 272 | 0.004782 | 8041 | no |
| X-23 | extremos | ferreteria | 1 | 1 | 0 | 2681 (2560) | 69 | 0.000836 | 2035 | sí |
| X-24 | extremos | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 7 | sí |
| Q-01 | flujos | ferreteria | 3 | 7 | 4 | 20891 (18944) | 396 | 0.007213 | 10911 | sí |
| Q-02 | flujos | ferreteria | 1 | 2 | 0 | 5455 (5248) | 71 | 0.001486 | 2921 | sí |
| Q-03 | flujos | ferreteria | 1 | 2 | 1 | 5474 (5376) | 96 | 0.001438 | 3357 | sí |
| Q-04 | flujos | ferreteria | 3 | 6 | 4 | 17555 (15744) | 334 | 0.006248 | 9605 | sí |
| Q-05 | flujos | ferreteria | 3 | 6 | 4 | 17575 (15872) | 355 | 0.006191 | 9739 | sí |
| Q-06 | flujos | ferreteria | 3 | 9 | 6 | 27992 (22144) | 525 | 0.013051 | 14063 | sí |
| Q-07 | flujos | ferreteria | 2 | 5 | 3 | 14446 (13184) | 259 | 0.004862 | 7534 | sí |
| Q-08 | flujos | ferreteria | 3 | 6 | 4 | 17729 (16256) | 328 | 0.005912 | 9879 | sí |
| Q-09 | flujos | ferreteria | 3 | 4 | 3 | 11433 (10880) | 197 | 0.003360 | 6011 | sí |
| Q-10 | flujos | ferreteria | 3 | 9 | 5 | 27662 (25216) | 593 | 0.009583 | 16095 | sí |
| Q-11 | flujos | ferreteria | 8 | 13 | 8 | 39778 (32512) | 671 | 0.017262 | 19523 | sí |
| Q-12 | flujos | ferreteria | 3 | 4 | 3 | 11442 (10880) | 202 | 0.003384 | 6467 | sí |
| Q-13 | flujos | ferreteria | 2 | 5 | 3 | 14693 (13568) | 269 | 0.004792 | 7674 | sí |
| K-03 | flujos | ferreteria | 3 | 11 | 7 | 32069 (30848) | 636 | 0.009286 | 18132 | sí |
| K-04 | flujos | ferreteria | 6 | 15 | 9 | 43732 (39936) | 851 | 0.014860 | 23790 | sí |
| V-01 | variados | ferreteria | 1 | 2 | 1 | 5487 (5248) | 97 | 0.001591 | 3075 | sí |
| V-02 | variados | ferreteria | 1 | 4 | 2 | 11414 (11264) | 202 | 0.002945 | 6028 | sí |
| V-03 | variados | ferreteria | 1 | 4 | 2 | 11366 (10624) | 199 | 0.003550 | 5927 | sí |
| V-04 | variados | ferreteria | 1 | 4 | 2 | 11381 (10368) | 192 | 0.003820 | 6491 | sí |
| V-05 | variados | ferreteria | 1 | 4 | 2 | 11411 (10368) | 229 | 0.003950 | 6126 | sí |
| V-06 | variados | ferreteria | 1 | 2 | 2 | 5569 (5120) | 107 | 0.001853 | 3076 | sí |
| V-07 | variados | ferreteria | 1 | 2 | 1 | 5470 (5120) | 123 | 0.001769 | 3114 | sí |
| V-08 | variados | ferreteria | 1 | 2 | 1 | 5548 (5120) | 101 | 0.001812 | 2858 | sí |
| V-09 | variados | ferreteria | 1 | 4 | 2 | 11548 (10880) | 268 | 0.003681 | 6299 | sí |
| V-10 | variados | ferreteria | 1 | 2 | 1 | 5501 (5248) | 114 | 0.001651 | 3214 | sí |
| V-11 | variados | ferreteria | 1 | 2 | 2 | 5588 (5504) | 106 | 0.001471 | 3050 | sí |
| V-12 | variados | ferreteria | 1 | 2 | 2 | 5559 (5376) | 95 | 0.001541 | 3192 | sí |
| V-13 | variados | ferreteria | 1 | 4 | 2 | 11861 (11008) | 393 | 0.004250 | 7023 | sí |
| V-14 | variados | ferreteria | 1 | 2 | 1 | 5460 (5120) | 100 | 0.001699 | 3142 | sí |
| V-15 | variados | ferreteria | 1 | 4 | 2 | 11335 (10368) | 194 | 0.003767 | 5716 | sí |
| V-16 | variados | ferreteria | 1 | 4 | 2 | 11557 (11264) | 241 | 0.003222 | 6238 | sí |
| V-17 | variados | ferreteria | 1 | 2 | 2 | 5576 (5248) | 103 | 0.001717 | 3024 | sí |
| V-18 | variados | ferreteria | 1 | 2 | 1 | 5483 (5248) | 103 | 0.001601 | 3248 | sí |
| V-19 | variados | ferreteria | 1 | 2 | 2 | 5513 (5376) | 102 | 0.001501 | 3040 | sí |
| V-20 | variados | ferreteria | 1 | 2 | 1 | 5561 (5376) | 132 | 0.001636 | 3236 | sí |
| V-21 | variados | ferreteria | 1 | 2 | 1 | 5458 (5248) | 85 | 0.001525 | 3000 | sí |
| V-22 | variados | ferreteria | 1 | 4 | 2 | 11563 (11392) | 263 | 0.003150 | 6273 | sí |
| V-23 | variados | ferreteria | 1 | 3 | 1 | 8394 (7680) | 230 | 0.003004 | 5591 | sí |
| V-24 | variados | ferreteria | 1 | 2 | 1 | 5546 (5376) | 128 | 0.001608 | 3102 | sí |
| V-25 | variados | ferreteria | 1 | 2 | 2 | 5591 (5504) | 101 | 0.001462 | 2938 | sí |
| V-26 | variados | ferreteria | 1 | 2 | 2 | 5573 (5120) | 104 | 0.001850 | 2999 | sí |
| V-27 | variados | ferreteria | 1 | 2 | 1 | 5430 (5120) | 100 | 0.001662 | 3054 | sí |
| V-28 | variados | ferreteria | 1 | 2 | 1 | 5534 (5376) | 114 | 0.001558 | 3088 | sí |
| V-29 | variados | ferreteria | 1 | 3 | 1 | 8251 (7808) | 160 | 0.002515 | 4721 | sí |
| V-30 | variados | ferreteria | 1 | 2 | 2 | 5590 (5504) | 107 | 0.001476 | 5183 | sí |
| V-31 | variados | ferreteria | 1 | 4 | 2 | 11414 (10240) | 203 | 0.004023 | 6414 | sí |
| W-01 | variados | ferreteria | 4 | 6 | 4 | 17299 (15872) | 280 | 0.005658 | 9700 | sí |
| W-02 | variados | ferreteria | 2 | 6 | 3 | 17837 (16256) | 332 | 0.006057 | 8666 | sí |
| W-03 | variados | ferreteria | 2 | 8 | 4 | 23997 (21760) | 424 | 0.008208 | 11521 | sí |
| W-04 | variados | ferreteria | 2 | 5 | 2 | 14140 (13312) | 206 | 0.004212 | 6876 | sí |
| W-05 | variados | ferreteria | 3 | 6 | 4 | 17664 (15872) | 324 | 0.006224 | 9262 | sí |
| W-06 | variados | ferreteria | 3 | 7 | 4 | 19998 (18688) | 351 | 0.006253 | 11521 | sí |
| K-05 | variados | ferreteria | 2 | 8 | 5 | 22823 (21888) | 426 | 0.006611 | 12703 | sí |
| J-01 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 25 | sí |
| J-02 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 19 | sí |
| J-03 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 13 | sí |
| J-04 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 7 | sí |
| J-05 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 14 | sí |
| J-06 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 7 | sí |
| J-07 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 7 | sí |
| J-08 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 8 | sí |
| J-09 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 21 | sí |
| J-10 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 24 | sí |
| J-11 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 8 | sí |
| J-12 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 16 | sí |
| J-13 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 7 | sí |
| J-14 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 8 | sí |
| J-15 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 8 | sí |
| J-16 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 7 | sí |
| J-17 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 9 | sí |
| J-18 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 7 | sí |
| J-19 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 8 | sí |
| J-20 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 8 | sí |
| J-21 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 9 | sí |
| J-22 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 8 | sí |
| J-23 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 8 | sí |
| J-24 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 9 | sí |
| J-25 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 7 | sí |
| J-26 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 8 | sí |
| J-27 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 7 | sí |
| J-28 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 7 | sí |
| J-29 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 7 | sí |
| J-30 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 8 | sí |
| J-31 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 8 | sí |
| J-32 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 8 | sí |
| J-33 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 7 | sí |
| J-34 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 8 | sí |
| J-35 | inyeccion | ferreteria | 3 | 3 | 2 | 8476 (8192) | 169 | 0.002416 | 5106 | sí |
| J-36 | inyeccion | ferreteria | 3 | 1 | 0 | 2702 (2560) | 53 | 0.000822 | 1899 | sí |
| J-37 | inyeccion | ferreteria | 3 | 4 | 3 | 11433 (10752) | 198 | 0.003497 | 6674 | sí |
| J-38 | inyeccion | ferreteria | 2 | 2 | 2 | 5609 (5248) | 96 | 0.001741 | 3002 | sí |
| J-39 | inyeccion | ferreteria | 2 | 3 | 2 | 8511 (8064) | 182 | 0.002627 | 5226 | sí |
| J-40 | inyeccion | ferreteria | 1 | 2 | 2 | 5563 (5376) | 97 | 0.001551 | 5758 | sí |
| J-41 | inyeccion | ferreteria | 1 | 2 | 2 | 5602 (5504) | 111 | 0.001501 | 3120 | sí |
| J-42 | inyeccion | ferreteria | 1 | 2 | 2 | 5594 (5504) | 115 | 0.001501 | 2883 | sí |
| J-43 | inyeccion | ferreteria | 1 | 2 | 2 | 5602 (5376) | 109 | 0.001630 | 3081 | sí |
| J-44 | inyeccion | ferreteria | 1 | 2 | 2 | 5610 (5504) | 115 | 0.001521 | 3057 | sí |
| J-45 | inyeccion | ferreteria | 1 | 3 | 1 | 8331 (8064) | 227 | 0.002514 | 5815 | sí |
| N-01 | memoria | ferreteria | 6 | 19 | 9 | 63141 (55808) | 1232 | 0.023408 | 30859 | sí |
| N-02 | memoria | ferreteria | 7 | 15 | 9 | 46740 (43136) | 817 | 0.015175 | 24202 | sí |
| N-03 | memoria | ferreteria | 4 | 9 | 6 | 26952 (25472) | 508 | 0.008214 | 14458 | sí |
| N-04 | memoria | ferreteria | 3 | 7 | 5 | 20816 (19328) | 439 | 0.006823 | 12294 | sí |
| N-05 | memoria | ferreteria | 2 | 5 | 4 | 14544 (13952) | 262 | 0.004185 | 7464 | sí |
| N-06 | memoria | ferreteria | 3 | 7 | 4 | 20528 (18688) | 383 | 0.006995 | 10698 | sí |
| H-01 | natural | ferreteria | 5 | 14 | 6 | 45352 (40064) | 907 | 0.016890 | 26246 | sí |
| H-02 | natural | ferreteria | 4 | 10 | 5 | 30553 (26752) | 530 | 0.011427 | 15637 | sí |
| H-03 | natural | ferreteria | 3 | 6 | 3 | 17192 (15872) | 265 | 0.005487 | 9071 | sí |
| H-04 | natural | ferreteria | 3 | 7 | 3 | 19838 (18688) | 312 | 0.005955 | 10126 | sí |
| H-05 | natural | ferreteria | 3 | 7 | 3 | 19907 (18816) | 331 | 0.005954 | 12114 | sí |
| H-06 | natural | ferreteria | 2 | 5 | 2 | 14055 (13568) | 244 | 0.003932 | 7827 | sí |
| H-07 | natural | ferreteria | 3 | 12 | 5 | 37286 (33536) | 738 | 0.013240 | 19300 | sí |
| H-08 | natural | ferreteria | 3 | 6 | 3 | 17717 (16256) | 428 | 0.006147 | 11469 | sí |
| H-09 | natural | ferreteria | 4 | 7 | 5 | 20774 (19072) | 389 | 0.006914 | 11009 | sí |
| H-10 | natural | ferreteria | 2 | 5 | 3 | 14286 (13696) | 237 | 0.004069 | 7154 | sí |
| H-11 | natural | ferreteria | 2 | 4 | 2 | 11382 (10880) | 324 | 0.003614 | 6569 | sí |
| H-12 | natural | ferreteria | 2 | 5 | 3 | 14093 (13184) | 226 | 0.004338 | 7400 | sí |
| H-13 | natural | ferreteria | 2 | 4 | 2 | 11298 (10880) | 196 | 0.003188 | 5948 | sí |
| H-14 | natural | ferreteria | 2 | 4 | 2 | 11747 (11648) | 267 | 0.003121 | 6483 | sí |
| U-01 | surtido | ferreteria | 1 | 2 | 1 | 5473 (5376) | 99 | 0.001444 | 3071 | sí |
| U-02 | surtido | ferreteria | 1 | 2 | 1 | 5533 (5504) | 107 | 0.001405 | 3325 | sí |
| U-03 | surtido | ferreteria | 1 | 2 | 1 | 5532 (5376) | 102 | 0.001525 | 2900 | sí |
| U-04 | surtido | ferreteria | 1 | 2 | 1 | 5462 (5248) | 110 | 0.001592 | 3095 | sí |
| U-05 | surtido | ferreteria | 1 | 2 | 1 | 5498 (5248) | 119 | 0.001660 | 3506 | sí |
| U-06 | surtido | ferreteria | 1 | 2 | 1 | 5499 (5120) | 115 | 0.001785 | 3482 | sí |
| U-07 | surtido | ferreteria | 1 | 2 | 1 | 5477 (5376) | 103 | 0.001459 | 2884 | sí |
| U-08 | surtido | ferreteria | 1 | 2 | 1 | 5612 (5504) | 156 | 0.001626 | 3408 | sí |
| U-09 | surtido | ferreteria | 1 | 2 | 1 | 5495 (5248) | 97 | 0.001601 | 3191 | sí |
| U-10 | surtido | ferreteria | 1 | 2 | 2 | 5536 (5504) | 106 | 0.001406 | 3060 | sí |
| Z-01 | fallas | ferreteria | 1 | 2 | 1 | 5494 (5376) | 113 | 0.001505 | 3441 | sí |
| Z-02 | fallas | ferreteria | 1 | 5 | 2 | 14409 (13312) | 275 | 0.004721 | 8003 | sí |
| Z-03 | fallas | ferreteria | 1 | 2 | 1 | 5494 (2688) | 136 | 0.004385 | 4735 | sí |
| Z-04 | fallas | ferreteria | 1 | 2 | 1 | 5578 (5376) | 103 | 0.001585 | 3271 | sí |
| Z-05 | fallas | ferreteria | 1 | 2 | 2 | 5555 (5376) | 92 | 0.001529 | 3029 | sí |
| Z-06 | fallas | ferreteria | 1 | 2 | 1 | 5509 (5376) | 108 | 0.001511 | 6349 | sí |
| Z-07 | fallas | ferreteria | 1 | 4 | 2 | 11282 (10496) | 206 | 0.003597 | 8660 | sí |
| Z-08 | fallas | ferreteria | 1 | 2 | 2 | 5543 (5120) | 101 | 0.001805 | 4883 | sí |
| Z-09 | fallas | ferreteria | 1 | 4 | 1 | 11239 (10752) | 217 | 0.003302 | 6201 | sí |
| Z-10 | fallas | ferreteria | 1 | 1 | 0 | 2685 (2560) | 63 | 0.000826 | 2172 | sí |
| Z-11 | fallas | ferreteria | 1 | 3 | 0 | 8245 (7936) | 159 | 0.002371 | 4502 | sí |
| Z-12 | fallas | ferreteria | 1 | 2 | 1 | 5620 (5376) | 104 | 0.001640 | 3104 | sí |
| Z-13 | fallas | ferreteria | 1 | 2 | 1 | 5484 (5248) | 126 | 0.001660 | 3286 | sí |
| Z-14 | fallas | ferreteria | 1 | 4 | 1 | 11527 (7936) | 266 | 0.006741 | 6498 | sí |
| Z-15 | fallas | ferreteria | 1 | 2 | 2 | 5608 (5504) | 110 | 0.001506 | 3066 | sí |
| Z-16 | fallas | ferreteria | 1 | 2 | 2 | 5589 (5120) | 107 | 0.001878 | 6729 | sí |
| Z-17 | fallas | ferreteria | 1 | 3 | 1 | 8459 (8192) | 160 | 0.002372 | 4771 | sí |
| Z-18 | fallas | ferreteria | 1 | 2 | 1 | 5437 (5248) | 82 | 0.001491 | 2870 | sí |
| Z-19 | fallas | ferreteria | 1 | 2 | 1 | 5449 (5248) | 97 | 0.001543 | 3136 | sí |
| Z-20 | fallas | ferreteria | 1 | 2 | 1 | 5524 (5376) | 86 | 0.001475 | 2805 | sí |
| Z-21 | fallas | ferreteria | 1 | 3 | 1 | 8244 (7936) | 155 | 0.002360 | 4803 | sí |
| Z-22 | fallas | ferreteria | 1 | 2 | 1 | 5490 (5248) | 148 | 0.001722 | 3727 | sí |
| Z-23 | fallas | ferreteria | 1 | 2 | 1 | 5489 (5248) | 113 | 0.001633 | 3176 | sí |
| Z-24 | fallas | ferreteria | 1 | 2 | 0 | 5759 (5120) | 304 | 0.002583 | 4677 | sí |
| Z-25 | fallas | ferreteria | 1 | 8 | 4 | 24673 (22144) | 466 | 0.008755 | 12311 | sí |
| Z-26 | fallas | ferreteria | 1 | 2 | 2 | 5613 (5248) | 106 | 0.001771 | 3009 | sí |
| Z-27 | fallas | ferreteria | 1 | 1 | 0 | 2701 (2560) | 51 | 0.000816 | 1528 | sí |
| Z-28 | fallas | ferreteria | 1 | 5 | 2 | 14586 (13824) | 266 | 0.004382 | 7892 | sí |
| Z-29 | fallas | ferreteria | 1 | 4 | 2 | 11269 (10368) | 204 | 0.003710 | 5902 | sí |
| Z-30 | fallas | ferreteria | 1 | 2 | 2 | 5531 (5376) | 110 | 0.001544 | 3097 | sí |
| Z-31 | fallas | ferreteria | 1 | 4 | 2 | 11788 (10880) | 237 | 0.003904 | 6441 | sí |
| Z-32 | fallas | ferreteria | 2 | 6 | 3 | 17628 (15744) | 322 | 0.006309 | 9130 | sí |
| Z-33 | fallas | ferreteria | 2 | 7 | 3 | 21539 (18944) | 531 | 0.008360 | 11583 | sí |
| Z-34 | fallas | ferreteria | 2 | 7 | 3 | 20510 (18304) | 346 | 0.007283 | 10310 | sí |
| Z-35 | fallas | ferreteria | 2 | 4 | 2 | 11169 (10368) | 195 | 0.003562 | 5738 | sí |
| Z-36 | fallas | ferreteria | 2 | 4 | 1 | 11399 (10496) | 224 | 0.003788 | 6225 | sí |
| Z-37 | fallas | ferreteria | 2 | 7 | 4 | 20737 (18304) | 391 | 0.007680 | 10764 | sí |
| Z-38 | fallas | ferreteria | 2 | 5 | 3 | 14459 (13568) | 261 | 0.004480 | 7438 | sí |
| A-01 | ampliacion | ferreteria | 1 | 2 | 1 | 5486 (5248) | 108 | 0.001617 | 3254 | sí |
| A-02 | ampliacion | ferreteria | 1 | 2 | 1 | 5511 (5376) | 137 | 0.001586 | 3216 | sí |
| A-03 | ampliacion | ferreteria | 1 | 2 | 2 | 5573 (5504) | 96 | 0.001427 | 2795 | sí |
| A-04 | ampliacion | ferreteria | 1 | 2 | 2 | 5562 (5376) | 109 | 0.001580 | 2963 | sí |
| A-05 | ampliacion | ferreteria | 1 | 2 | 2 | 5559 (5120) | 104 | 0.001833 | 5594 | sí |
| A-06 | ampliacion | ferreteria | 1 | 2 | 2 | 5535 (5120) | 109 | 0.001815 | 2849 | sí |
| A-07 | ampliacion | ferreteria | 1 | 2 | 1 | 5486 (5248) | 116 | 0.001637 | 3016 | sí |
| A-08 | ampliacion | ferreteria | 1 | 2 | 1 | 5497 (5120) | 90 | 0.001720 | 2913 | sí |
| A-09 | ampliacion | ferreteria | 1 | 2 | 2 | 5518 (5120) | 92 | 0.001752 | 2719 | sí |
| A-10 | ampliacion | ferreteria | 1 | 4 | 2 | 11572 (10368) | 285 | 0.004291 | 6346 | sí |
| A-11 | ampliacion | ferreteria | 1 | 2 | 1 | 5464 (5120) | 105 | 0.001716 | 2852 | sí |
| A-12 | ampliacion | ferreteria | 1 | 2 | 1 | 5452 (5248) | 94 | 0.001540 | 2768 | sí |
| A-13 | ampliacion | ferreteria | 1 | 2 | 1 | 5476 (5120) | 87 | 0.001686 | 2775 | sí |
| A-14 | ampliacion | ferreteria | 1 | 2 | 2 | 5564 (5120) | 99 | 0.001826 | 3785 | sí |
| A-15 | ampliacion | ferreteria | 1 | 2 | 1 | 5455 (5120) | 95 | 0.001680 | 3050 | sí |
| A-16 | ampliacion | ferreteria | 1 | 2 | 2 | 5553 (5120) | 106 | 0.001830 | 3102 | sí |
| A-17 | ampliacion | ferreteria | 1 | 3 | 1 | 8284 (8192) | 195 | 0.002241 | 4981 | sí |
| A-18 | ampliacion | ferreteria | 1 | 2 | 1 | 5486 (5248) | 112 | 0.001627 | 3035 | sí |
| A-19 | ampliacion | ferreteria | 1 | 2 | 1 | 5446 (5248) | 94 | 0.001532 | 3101 | sí |
| A-20 | ampliacion | ferreteria | 2 | 4 | 2 | 11206 (10496) | 216 | 0.003527 | 6002 | sí |
| M-06 | mercado | mercado | 1 | 2 | 2 | 5556 (5120) | 83 | 0.001776 | 3300 | sí |
| M-07 | mercado | mercado | 1 | 2 | 2 | 5569 (5504) | 93 | 0.001415 | 3142 | sí |
| M-08 | mercado | mercado | 1 | 4 | 2 | 11608 (10752) | 255 | 0.003858 | 6104 | sí |
| M-09 | mercado | mercado | 1 | 2 | 1 | 5470 (5248) | 95 | 0.001565 | 2872 | sí |
| M-10 | mercado | mercado | 1 | 2 | 1 | 5463 (5376) | 87 | 0.001401 | 2959 | sí |
| M-11 | mercado | mercado | 1 | 2 | 2 | 5588 (5120) | 101 | 0.001862 | 2743 | sí |
| M-12 | mercado | mercado | 1 | 2 | 2 | 5559 (5120) | 111 | 0.001850 | 2764 | sí |
| M-13 | mercado | mercado | 1 | 3 | 1 | 8356 (8064) | 199 | 0.002475 | 4820 | sí |
| M-14 | mercado | mercado | 1 | 1 | 0 | 2694 (2560) | 49 | 0.000802 | 1394 | sí |
| M-15 | mercado | mercado | 1 | 2 | 2 | 5583 (5248) | 112 | 0.001748 | 3203 | sí |
| M-16 | mercado | mercado | 1 | 2 | 1 | 5527 (5120) | 106 | 0.001798 | 3000 | sí |
| M-17 | mercado | mercado | 1 | 4 | 2 | 11439 (11264) | 239 | 0.003069 | 5853 | sí |
| M-18 | mercado | mercado | 1 | 2 | 1 | 5487 (5248) | 80 | 0.001548 | 2979 | sí |
| M-19 | mercado | mercado | 1 | 4 | 2 | 11541 (10880) | 228 | 0.003572 | 5850 | sí |
| M-20 | mercado | mercado | 1 | 2 | 1 | 5442 (5248) | 94 | 0.001527 | 2779 | sí |
| M-21 | mercado | mercado | 1 | 1 | 1 | 2686 (2560) | 23 | 0.000727 | 1168 | sí |
| M-22 | mercado | mercado | 1 | 2 | 1 | 5527 (2688) | 100 | 0.004336 | 2915 | sí |
| M-23 | mercado | mercado | 1 | 5 | 2 | 14211 (13568) | 273 | 0.004200 | 8276 | sí |
| M-24 | mercado | mercado | 1 | 2 | 1 | 5512 (5504) | 103 | 0.001368 | 3045 | sí |
| M-25 | mercado | mercado | 1 | 2 | 2 | 5573 (5120) | 91 | 0.001818 | 3046 | sí |
| M-26 | mercado | mercado | 1 | 2 | 1 | 5478 (5120) | 79 | 0.001669 | 2944 | sí |
| M-27 | mercado | mercado | 1 | 2 | 1 | 5476 (2816) | 79 | 0.004086 | 3190 | sí |
| M-28 | mercado | mercado | 1 | 2 | 2 | 5522 (5376) | 91 | 0.001485 | 3462 | sí |
| M-29 | mercado | mercado | 1 | 2 | 2 | 5558 (5376) | 91 | 0.001530 | 3169 | sí |
| M-30 | mercado | mercado | 1 | 3 | 1 | 8330 (8064) | 167 | 0.002363 | 4961 | sí |
| M-31 | mercado | mercado | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 7 | sí |
| M-32 | mercado | mercado | 4 | 7 | 5 | 20742 (18560) | 393 | 0.007422 | 11197 | sí |
| M-33 | mercado | mercado | 2 | 3 | 2 | 8443 (7936) | 165 | 0.002633 | 4602 | sí |
| M-34 | mercado | mercado | 2 | 4 | 2 | 11291 (10624) | 179 | 0.003406 | 6947 | sí |
| M-35 | mercado | mercado | 2 | 7 | 4 | 20670 (19200) | 343 | 0.006535 | 10044 | sí |
| M-36 | mercado | mercado | 3 | 7 | 5 | 20428 (19840) | 366 | 0.005618 | 10207 | sí |
| M-37 | mercado | mercado | 2 | 5 | 3 | 14440 (10880) | 287 | 0.007344 | 7552 | sí |
| M-38 | mercado | mercado | 1 | 2 | 1 | 5488 (5376) | 102 | 0.001470 | 2820 | sí |
| P-tubo-1 | parafrasis | ferreteria | 1 | 2 | 2 | 5590 (5504) | 111 | 0.001486 | 2914 | sí |
| P-tubo-2 | parafrasis | ferreteria | 1 | 2 | 2 | 5596 (5504) | 116 | 0.001506 | 2876 | sí |
| P-tubo-3 | parafrasis | ferreteria | 1 | 2 | 2 | 5600 (5248) | 111 | 0.001767 | 3039 | sí |
| P-tanque-1 | parafrasis | ferreteria | 1 | 2 | 2 | 5575 (5376) | 105 | 0.001586 | 2830 | sí |
| P-tanque-2 | parafrasis | ferreteria | 1 | 2 | 2 | 5581 (5376) | 105 | 0.001594 | 2982 | sí |
| P-tanque-3 | parafrasis | ferreteria | 1 | 2 | 2 | 5569 (5376) | 106 | 0.001581 | 2801 | sí |
| P-brochas-1 | parafrasis | ferreteria | 1 | 2 | 2 | 5557 (5376) | 95 | 0.001539 | 2760 | sí |
| P-brochas-2 | parafrasis | ferreteria | 1 | 2 | 2 | 5563 (5120) | 92 | 0.001808 | 2814 | sí |
| P-brochas-3 | parafrasis | ferreteria | 1 | 2 | 2 | 5560 (5376) | 96 | 0.001545 | 2928 | sí |
| P-horario-1 | parafrasis | ferreteria | 1 | 2 | 1 | 5520 (5376) | 94 | 0.001490 | 2808 | sí |
| P-horario-2 | parafrasis | ferreteria | 1 | 2 | 1 | 5524 (5120) | 84 | 0.001739 | 3007 | sí |
| P-horario-3 | parafrasis | ferreteria | 1 | 2 | 1 | 5524 (5120) | 119 | 0.001826 | 2977 | sí |
| P-cubeta-1 | parafrasis | mercado | 1 | 2 | 2 | 5568 (5376) | 90 | 0.001540 | 3041 | sí |
| P-cubeta-2 | parafrasis | mercado | 1 | 4 | 2 | 11233 (10624) | 189 | 0.003359 | 5645 | sí |
| P-cubeta-3 | parafrasis | mercado | 1 | 4 | 2 | 11354 (11008) | 178 | 0.003079 | 5444 | sí |
| P-docena-1 | parafrasis | mercado | 1 | 2 | 2 | 5557 (5376) | 86 | 0.001516 | 2793 | sí |
| P-docena-2 | parafrasis | mercado | 1 | 4 | 2 | 11306 (10752) | 174 | 0.003278 | 5760 | sí |
| P-docena-3 | parafrasis | mercado | 1 | 4 | 2 | 11310 (8192) | 165 | 0.005948 | 5358 | sí |
| P-fiado-1 | parafrasis | mercado | 1 | 3 | 1 | 8235 (7936) | 134 | 0.002296 | 4253 | sí |
| P-fiado-2 | parafrasis | mercado | 1 | 1 | 0 | 2690 (2560) | 59 | 0.000822 | 1851 | sí |
| P-fiado-3 | parafrasis | mercado | 1 | 1 | 0 | 2693 (2688) | 59 | 0.000691 | 1637 | sí |
| P-domicilio-1 | parafrasis | mercado | 1 | 2 | 1 | 5446 (5248) | 94 | 0.001532 | 2781 | sí |
| P-domicilio-2 | parafrasis | mercado | 1 | 3 | 1 | 8251 (8064) | 163 | 0.002254 | 4671 | sí |
| P-domicilio-3 | parafrasis | mercado | 1 | 2 | 1 | 5446 (5248) | 92 | 0.001527 | 2762 | sí |
| F-01 | fotos | ferreteria | 2 | 4 | 2 | 11774 (11520) | 179 | 0.003069 | 5658 | sí |
| F-02 | fotos | ferreteria | 1 | 1 | 1 | 518 (384) | 56 | 0.000384 | 77 | sí |
| F-03 | fotos | ferreteria | 1 | 1 | 2 | 526 (384) | 58 | 0.000399 | 66 | sí |
| F-04 | fotos | ferreteria | 1 | 1 | 1 | 510 (384) | 59 | 0.000382 | 114 | sí |
| F-05 | fotos | ferreteria | 1 | 1 | 0 | 558 (384) | 51 | 0.000422 | 10 | sí |
| F-06 | fotos | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 5 | sí |
| F-07 | fotos | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 21 | sí |
| F-08 | fotos | mercado | 1 | 1 | 1 | 534 (512) | 60 | 0.000280 | 32 | sí |
| F-09 | fotos | mercado | 1 | 1 | 1 | 518 (512) | 58 | 0.000255 | 16 | sí |
| F-10 | fotos | ferreteria | 2 | 3 | 2 | 6414 (5888) | 155 | 0.002223 | 2773 | sí |
| F-11 | fotos | ferreteria | 1 | 1 | 1 | 534 (512) | 60 | 0.000280 | 52 | sí |
