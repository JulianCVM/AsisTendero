# Costo por tarea y por operación

**Datos ficticios.** El catálogo, las dos tiendas y los clientes son simulados; nada de esto representa un piloto.
Cada costo es el que informó la API de la pasarela del reto en cada llamada (`api_reported`), no una estimación por
tarifa. Las herramientas del agente corren en el servidor sobre SQLite: no tienen costo de API, solo latencia.

Este documento es el reporte de costo por ejecución del entregable S3/S4. Sale de una corrida real del evaluador con
Grok: 334 tareas, que es cada caso de `evaluation/cases.json`. Una tarea puede ser un mensaje suelto,
una conversación de varios turnos o varios clientes a la vez. Las tablas se generaron sin llamar a Grok, con

```powershell
.\.venv\Scripts\python.exe -m asistendero.evaluacion.eval_costs .local\eval-20261101T015603746928Z.json --out evaluation\COSTOS_POR_TAREA.md
```

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

- Commit `c77dd48` (árbol limpio), modelo `grok-4.20-0309-non-reasoning`, prompt `mercado-v1`, `s4-conversacion-v12`, inicio 2026-11-01T02:04:56.686243+00:00.
- 334 tareas (487 mensajes del cliente), 327 aprobadas. Costo informado por la API para 334 de 334 tareas.

## Resumen

| Medida | Valor |
|---|---|
| Costo total | 1.153100 USD |
| Costo medio por tarea | 0.003452 USD |
| Mediana, percentil 90 y máximo por tarea | 0.001872 / 0.007443 / 0.030941 USD |
| Costo medio por mensaje del cliente | 0.002368 USD |
| Costo medio por llamada a Grok | 0.001147 USD |
| Llamadas a Grok por tarea | 3.01 |
| Tokens de entrada desde la caché | 85.8 % |
| Llamadas con el prompt fijo en caché | 94.7 % |
| Tareas sin llamar a Grok (rechazos antes del modelo) | 44 |
| Proyección a 1.000 tareas con esta mezcla | 3.452395 USD |

## Costo por operación de Grok

| Operación | Llamadas | USD total | USD por llamada | Tokens de entrada (caché) | Tokens de salida | ms por llamada |
|---|---|---|---|---|---|---|
| Leer lo observado y redactar la respuesta | 434 | 0.540632 | 0.001246 | 1286157 (1084416) | 28629 | 1700 |
| Interpretar el mensaje y pedir una herramienta | 385 | 0.412389 | 0.001071 | 1074246 (930432) | 18614 | 1483 |
| Leer lo observado y pedir otra herramienta | 140 | 0.152006 | 0.001086 | 411258 (358528) | 5755 | 1417 |
| Interpretar el mensaje y responder sin herramientas | 46 | 0.048074 | 0.001045 | 127749 (113024) | 2825 | 1769 |

## Herramientas del servidor (sin costo de API)

| Herramienta | Pedidas por Grok | Ejecutadas | Rechazadas por la validación | ms por ejecución |
|---|---|---|---|---|
| `buscar_productos` | 285 | 281 | 4 | 17 |
| `calcular_cotizacion_informativa` | 173 | 157 | 16 | 1 |
| `registrar_pedido` | 59 | 58 | 1 | 5 |
| `consultar_info_tienda` | 31 | 31 | 0 | 1 |
| `confirmar_pedido` | 20 | 18 | 2 | 4 |
| `agendar_recogida` | 13 | 13 | 0 | 3 |
| `cancelar_pedido` | 10 | 8 | 2 | 4 |
| `explorar_categoria` | 8 | 8 | 0 | 1 |
| `consultar_pedido` | 7 | 7 | 0 | 1 |
| `consultar_disponibilidad` | 3 | 3 | 0 | 1 |

## Por suite

| Suite | Tareas | Aprobadas | Llamadas a Grok | USD | USD por tarea |
|---|---|---|---|---|---|
| ampliacion | 20 | 19 | 45 | 0.040986 | 0.002049 |
| catalogo | 12 | 12 | 26 | 0.030313 | 0.002526 |
| concurrencia | 2 | 2 | 14 | 0.013110 | 0.006555 |
| conversacion | 5 | 5 | 21 | 0.035519 | 0.007104 |
| extremos | 24 | 22 | 54 | 0.051048 | 0.002127 |
| fallas | 38 | 38 | 121 | 0.121598 | 0.003200 |
| flujos | 15 | 14 | 102 | 0.105372 | 0.007025 |
| inyeccion | 45 | 45 | 26 | 0.024593 | 0.000547 |
| memoria | 6 | 6 | 62 | 0.074850 | 0.012475 |
| mercado | 33 | 33 | 93 | 0.135672 | 0.004111 |
| natural | 14 | 13 | 92 | 0.099279 | 0.007091 |
| parafrasis | 24 | 23 | 56 | 0.060801 | 0.002533 |
| pedidos | 8 | 8 | 38 | 0.049310 | 0.006164 |
| ruido | 12 | 12 | 27 | 0.030889 | 0.002574 |
| s2 | 10 | 10 | 23 | 0.047468 | 0.004747 |
| seguridad | 10 | 10 | 9 | 0.016589 | 0.001659 |
| sesion_larga | 2 | 2 | 36 | 0.056853 | 0.028427 |
| surtido | 10 | 10 | 20 | 0.017989 | 0.001799 |
| tienda | 6 | 6 | 10 | 0.008189 | 0.001365 |
| variados | 38 | 37 | 130 | 0.132670 | 0.003491 |

## Por negocio

| Negocio | Tareas | Aprobadas | Llamadas a Grok | USD | USD por tarea |
|---|---|---|---|---|---|
| ferreteria | 289 | 283 | 880 | 0.978592 | 0.003386 |
| mercado | 45 | 44 | 125 | 0.174508 | 0.003878 |

## Por tarea

| Caso | Suite | Negocio | Mensajes | Llamadas | Herramientas | Tokens entrada (caché) | Tokens salida | USD | ms | Aprobado |
|---|---|---|---|---|---|---|---|---|---|---|
| S2-01 | s2 | ferreteria | 1 | 2 | 2 | 5590 (256) | 111 | 0.006996 | 5420 | sí |
| S2-02 | s2 | ferreteria | 1 | 4 | 2 | 11643 (2944) | 295 | 0.012200 | 7111 | sí |
| S2-03 | s2 | ferreteria | 1 | 2 | 1 | 5482 (2688) | 109 | 0.004303 | 3787 | sí |
| S2-04 | s2 | ferreteria | 1 | 2 | 1 | 5501 (2688) | 122 | 0.004359 | 3630 | sí |
| S2-05 | s2 | ferreteria | 1 | 2 | 1 | 5490 (5120) | 130 | 0.001812 | 3453 | sí |
| S2-06 | s2 | ferreteria | 1 | 2 | 1 | 5496 (256) | 121 | 0.006904 | 2939 | sí |
| S2-07 | s2 | ferreteria | 1 | 2 | 2 | 5554 (5120) | 116 | 0.001856 | 3194 | sí |
| S2-08 | s2 | ferreteria | 1 | 1 | 1 | 2685 (2560) | 44 | 0.000778 | 1563 | sí |
| S2-09 | s2 | ferreteria | 1 | 2 | 1 | 5528 (5120) | 71 | 0.001712 | 2645 | sí |
| S2-10 | s2 | ferreteria | 1 | 4 | 2 | 11601 (8064) | 206 | 0.006549 | 6010 | sí |
| C-01 | catalogo | ferreteria | 1 | 2 | 2 | 5582 (5120) | 102 | 0.001856 | 2851 | sí |
| C-02 | catalogo | ferreteria | 1 | 2 | 1 | 5506 (5120) | 113 | 0.001789 | 2928 | sí |
| C-03 | catalogo | ferreteria | 1 | 2 | 2 | 5573 (5120) | 106 | 0.001855 | 4362 | sí |
| C-04 | catalogo | ferreteria | 1 | 2 | 2 | 5603 (5120) | 118 | 0.001923 | 2844 | sí |
| C-05 | catalogo | ferreteria | 1 | 2 | 1 | 5471 (2688) | 120 | 0.004316 | 3159 | sí |
| C-06 | catalogo | ferreteria | 1 | 2 | 2 | 5607 (5120) | 113 | 0.001915 | 2963 | sí |
| C-07 | catalogo | ferreteria | 1 | 2 | 1 | 5717 (5120) | 179 | 0.002218 | 3493 | sí |
| C-08 | catalogo | ferreteria | 1 | 4 | 2 | 11833 (10240) | 288 | 0.004759 | 6195 | sí |
| C-09 | catalogo | ferreteria | 1 | 2 | 2 | 5537 (5120) | 115 | 0.001833 | 2885 | sí |
| C-10 | catalogo | ferreteria | 1 | 2 | 1 | 5474 (5120) | 107 | 0.001734 | 2712 | sí |
| C-11 | catalogo | ferreteria | 1 | 2 | 2 | 5586 (2688) | 113 | 0.004443 | 2825 | sí |
| C-12 | catalogo | ferreteria | 1 | 2 | 1 | 5456 (5120) | 91 | 0.001672 | 2742 | sí |
| T-01 | tienda | ferreteria | 1 | 2 | 1 | 5528 (5120) | 106 | 0.001799 | 2857 | sí |
| T-02 | tienda | ferreteria | 1 | 2 | 1 | 5441 (5120) | 94 | 0.001660 | 2937 | sí |
| T-03 | tienda | ferreteria | 1 | 2 | 1 | 5430 (5120) | 99 | 0.001659 | 2805 | sí |
| T-04 | tienda | ferreteria | 1 | 1 | 1 | 2684 (2560) | 23 | 0.000724 | 1192 | sí |
| T-05 | tienda | ferreteria | 1 | 1 | 1 | 2684 (2560) | 28 | 0.000737 | 1225 | sí |
| T-06 | tienda | ferreteria | 1 | 2 | 1 | 5420 (5120) | 84 | 0.001609 | 2632 | sí |
| G-01 | seguridad | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 7 | sí |
| G-02 | seguridad | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 7 | sí |
| G-03 | seguridad | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 7 | sí |
| G-04 | seguridad | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 14 | sí |
| G-05 | seguridad | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 13 | sí |
| G-06 | seguridad | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 13 | sí |
| G-07 | seguridad | ferreteria | 1 | 2 | 2 | 5594 (2688) | 159 | 0.004568 | 3396 | sí |
| G-08 | seguridad | ferreteria | 1 | 5 | 2 | 14473 (10624) | 301 | 0.007689 | 11262 | sí |
| G-09 | seguridad | ferreteria | 1 | 2 | 1 | 5502 (2688) | 111 | 0.004333 | 3031 | sí |
| G-10 | seguridad | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 7 | sí |
| M-01 | conversacion | ferreteria | 2 | 4 | 2 | 11240 (5504) | 210 | 0.008796 | 6154 | sí |
| M-02 | conversacion | ferreteria | 2 | 4 | 2 | 11343 (10240) | 214 | 0.003962 | 6000 | sí |
| M-03 | conversacion | ferreteria | 2 | 4 | 3 | 11635 (5376) | 203 | 0.009406 | 5688 | sí |
| M-04 | conversacion | ferreteria | 2 | 4 | 2 | 11214 (7936) | 189 | 0.006157 | 5775 | sí |
| M-05 | conversacion | ferreteria | 2 | 5 | 3 | 14501 (11008) | 252 | 0.007198 | 8052 | sí |
| R-01 | ruido | ferreteria | 1 | 2 | 2 | 5599 (5120) | 115 | 0.001910 | 2950 | sí |
| R-02 | ruido | ferreteria | 1 | 2 | 1 | 5470 (5120) | 102 | 0.001716 | 5352 | sí |
| R-03 | ruido | ferreteria | 1 | 4 | 2 | 11290 (7808) | 205 | 0.006427 | 6228 | sí |
| R-04 | ruido | ferreteria | 1 | 2 | 1 | 5474 (5120) | 91 | 0.001694 | 2772 | sí |
| R-05 | ruido | ferreteria | 1 | 1 | 0 | 2679 (2560) | 37 | 0.000753 | 1429 | sí |
| R-06 | ruido | ferreteria | 1 | 3 | 1 | 8602 (5248) | 246 | 0.005857 | 5415 | sí |
| R-07 | ruido | ferreteria | 1 | 1 | 0 | 2682 (2560) | 60 | 0.000814 | 1717 | sí |
| R-08 | ruido | ferreteria | 1 | 2 | 1 | 5566 (5120) | 118 | 0.001876 | 3060 | sí |
| R-09 | ruido | ferreteria | 1 | 2 | 1 | 5562 (5120) | 107 | 0.001844 | 2982 | sí |
| R-10 | ruido | ferreteria | 1 | 4 | 1 | 11770 (10624) | 268 | 0.004227 | 5995 | sí |
| R-11 | ruido | ferreteria | 1 | 1 | 0 | 2682 (2560) | 67 | 0.000832 | 1518 | sí |
| R-12 | ruido | ferreteria | 1 | 3 | 1 | 8602 (7936) | 207 | 0.002937 | 4647 | sí |
| P-01 | pedidos | ferreteria | 4 | 7 | 5 | 20945 (15744) | 412 | 0.010680 | 10194 | sí |
| P-02 | pedidos | ferreteria | 4 | 6 | 3 | 17626 (15488) | 383 | 0.006728 | 8556 | sí |
| P-03 | pedidos | ferreteria | 3 | 5 | 3 | 14755 (13056) | 261 | 0.005387 | 7610 | sí |
| P-04 | pedidos | ferreteria | 2 | 4 | 3 | 11488 (7808) | 214 | 0.006697 | 5610 | sí |
| P-05 | pedidos | ferreteria | 1 | 2 | 0 | 5455 (5120) | 71 | 0.001620 | 2831 | sí |
| P-06 | pedidos | ferreteria | 4 | 8 | 5 | 24090 (20480) | 460 | 0.009758 | 11893 | sí |
| P-07 | pedidos | ferreteria | 2 | 4 | 2 | 11485 (7936) | 260 | 0.006673 | 6023 | sí |
| P-08 | pedidos | ferreteria | 1 | 2 | 0 | 5472 (5120) | 121 | 0.001766 | 3209 | sí |
| L-01 | sesion_larga | ferreteria | 11 | 19 | 10 | 60743 (45312) | 1036 | 0.030941 | 29495 | sí |
| L-02 | sesion_larga | ferreteria | 9 | 17 | 12 | 54556 (42624) | 989 | 0.025912 | 27123 | sí |
| K-01 | concurrencia | ferreteria | 2 | 8 | 5 | 22862 (21248) | 440 | 0.007367 | 12307 | sí |
| K-02 | concurrencia | ferreteria | 4 | 6 | 4 | 17094 (15616) | 309 | 0.005743 | 9000 | sí |
| X-01 | extremos | ferreteria | 1 | 2 | 2 | 5600 (5120) | 118 | 0.001919 | 3204 | sí |
| X-02 | extremos | ferreteria | 1 | 2 | 2 | 5608 (5120) | 119 | 0.001932 | 3124 | sí |
| X-03 | extremos | ferreteria | 1 | 5 | 1 | 14203 (13312) | 270 | 0.004451 | 7251 | sí |
| X-04 | extremos | ferreteria | 1 | 4 | 1 | 11253 (10368) | 266 | 0.003845 | 6299 | sí |
| X-05 | extremos | ferreteria | 1 | 2 | 2 | 5588 (5120) | 122 | 0.001914 | 3269 | sí |
| X-06 | extremos | ferreteria | 1 | 2 | 1 | 5479 (5120) | 100 | 0.001723 | 3275 | sí |
| X-07 | extremos | ferreteria | 1 | 2 | 1 | 5563 (5120) | 150 | 0.001953 | 3134 | sí |
| X-08 | extremos | ferreteria | 1 | 2 | 2 | 5567 (5120) | 91 | 0.001810 | 2904 | sí |
| X-09 | extremos | ferreteria | 1 | 1 | 1 | 2685 (2560) | 44 | 0.000778 | 1275 | sí |
| X-10 | extremos | ferreteria | 1 | 5 | 3 | 14268 (12800) | 317 | 0.005188 | 7374 | sí |
| X-11 | extremos | ferreteria | 1 | 1 | 0 | 2691 (2560) | 74 | 0.000861 | 1712 | sí |
| X-12 | extremos | ferreteria | 1 | 1 | 0 | 2691 (2560) | 80 | 0.000876 | 1882 | sí |
| X-13 | extremos | ferreteria | 1 | 4 | 2 | 11294 (10240) | 200 | 0.003866 | 5525 | sí |
| X-14 | extremos | ferreteria | 1 | 2 | 1 | 5587 (5120) | 97 | 0.001850 | 2950 | no |
| X-15 | extremos | ferreteria | 1 | 2 | 2 | 5600 (5120) | 113 | 0.001906 | 2721 | sí |
| X-16 | extremos | ferreteria | 1 | 2 | 1 | 5489 (5120) | 101 | 0.001738 | 2613 | sí |
| X-17 | extremos | ferreteria | 1 | 2 | 2 | 5534 (5120) | 109 | 0.001814 | 2687 | sí |
| X-18 | extremos | ferreteria | 1 | 2 | 1 | 5487 (5120) | 110 | 0.001758 | 2766 | sí |
| X-19 | extremos | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 7 | sí |
| X-20 | extremos | ferreteria | 1 | 2 | 1 | 5528 (5120) | 127 | 0.001852 | 2942 | sí |
| X-21 | extremos | ferreteria | 1 | 2 | 2 | 5589 (5120) | 117 | 0.001903 | 3149 | sí |
| X-22 | extremos | ferreteria | 1 | 6 | 2 | 17378 (15616) | 382 | 0.006281 | 9616 | no |
| X-23 | extremos | ferreteria | 1 | 1 | 0 | 2681 (2560) | 68 | 0.000833 | 1583 | sí |
| X-24 | extremos | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 8 | sí |
| Q-01 | flujos | ferreteria | 3 | 7 | 4 | 20902 (18432) | 424 | 0.007834 | 10187 | sí |
| Q-02 | flujos | ferreteria | 1 | 2 | 0 | 5455 (5120) | 71 | 0.001620 | 2593 | sí |
| Q-03 | flujos | ferreteria | 1 | 2 | 1 | 5474 (5120) | 92 | 0.001696 | 2724 | sí |
| Q-04 | flujos | ferreteria | 3 | 6 | 4 | 17573 (15488) | 305 | 0.006466 | 8966 | sí |
| Q-05 | flujos | ferreteria | 3 | 6 | 4 | 17563 (15872) | 339 | 0.006136 | 8904 | sí |
| Q-06 | flujos | ferreteria | 3 | 9 | 6 | 28156 (24320) | 530 | 0.010984 | 15118 | sí |
| Q-07 | flujos | ferreteria | 2 | 5 | 3 | 14458 (13312) | 256 | 0.004735 | 6911 | sí |
| Q-08 | flujos | ferreteria | 3 | 6 | 4 | 17758 (16256) | 350 | 0.006004 | 10941 | sí |
| Q-09 | flujos | ferreteria | 3 | 4 | 3 | 11436 (10624) | 196 | 0.003630 | 7711 | sí |
| Q-10 | flujos | ferreteria | 3 | 7 | 4 | 20861 (19200) | 392 | 0.006896 | 10138 | no |
| Q-11 | flujos | ferreteria | 8 | 13 | 8 | 39904 (34816) | 721 | 0.015126 | 18947 | sí |
| Q-12 | flujos | ferreteria | 3 | 4 | 3 | 11442 (10880) | 198 | 0.003374 | 5515 | sí |
| Q-13 | flujos | ferreteria | 2 | 5 | 3 | 14707 (13312) | 273 | 0.005089 | 7186 | sí |
| K-03 | flujos | ferreteria | 3 | 11 | 7 | 32068 (29184) | 619 | 0.010989 | 17437 | sí |
| K-04 | flujos | ferreteria | 6 | 15 | 9 | 43777 (40064) | 856 | 0.014794 | 22857 | sí |
| V-01 | variados | ferreteria | 1 | 2 | 1 | 5487 (5120) | 105 | 0.001745 | 2807 | sí |
| V-02 | variados | ferreteria | 1 | 4 | 2 | 11414 (10496) | 202 | 0.003752 | 5468 | sí |
| V-03 | variados | ferreteria | 1 | 4 | 2 | 11366 (10240) | 199 | 0.003953 | 5473 | sí |
| V-04 | variados | ferreteria | 1 | 4 | 1 | 11349 (10240) | 198 | 0.003929 | 6030 | sí |
| V-05 | variados | ferreteria | 1 | 4 | 2 | 11411 (10496) | 230 | 0.003818 | 5961 | sí |
| V-06 | variados | ferreteria | 1 | 2 | 2 | 5569 (5120) | 106 | 0.001850 | 2996 | sí |
| V-07 | variados | ferreteria | 1 | 2 | 1 | 5470 (5120) | 119 | 0.001759 | 2973 | sí |
| V-08 | variados | ferreteria | 1 | 2 | 1 | 5548 (2688) | 99 | 0.004360 | 2760 | sí |
| V-09 | variados | ferreteria | 1 | 4 | 2 | 11548 (10496) | 271 | 0.004092 | 6102 | sí |
| V-10 | variados | ferreteria | 1 | 2 | 1 | 5501 (5120) | 115 | 0.001788 | 2922 | sí |
| V-11 | variados | ferreteria | 1 | 2 | 2 | 5588 (5120) | 107 | 0.001876 | 2821 | sí |
| V-12 | variados | ferreteria | 1 | 2 | 2 | 5559 (5120) | 92 | 0.001803 | 2578 | sí |
| V-13 | variados | ferreteria | 1 | 4 | 2 | 11861 (10496) | 373 | 0.004738 | 7108 | sí |
| V-14 | variados | ferreteria | 1 | 2 | 1 | 5455 (5120) | 95 | 0.001680 | 2959 | sí |
| V-15 | variados | ferreteria | 1 | 4 | 2 | 11338 (10368) | 206 | 0.003801 | 5964 | sí |
| V-16 | variados | ferreteria | 1 | 4 | 2 | 11557 (10240) | 256 | 0.004334 | 10135 | sí |
| V-17 | variados | ferreteria | 1 | 2 | 1 | 5489 (5120) | 121 | 0.001788 | 3059 | no |
| V-18 | variados | ferreteria | 1 | 2 | 1 | 5483 (5120) | 93 | 0.001710 | 3210 | sí |
| V-19 | variados | ferreteria | 1 | 2 | 2 | 5513 (5120) | 102 | 0.001770 | 3178 | sí |
| V-20 | variados | ferreteria | 1 | 2 | 1 | 5561 (5120) | 131 | 0.001903 | 3330 | sí |
| V-21 | variados | ferreteria | 1 | 2 | 1 | 5458 (2688) | 85 | 0.004213 | 2779 | sí |
| V-22 | variados | ferreteria | 1 | 4 | 2 | 11563 (10240) | 261 | 0.004354 | 6346 | sí |
| V-23 | variados | ferreteria | 1 | 3 | 1 | 8394 (7680) | 201 | 0.002931 | 4825 | sí |
| V-24 | variados | ferreteria | 1 | 2 | 1 | 5546 (5120) | 141 | 0.001909 | 3553 | sí |
| V-25 | variados | ferreteria | 1 | 2 | 2 | 5591 (5120) | 101 | 0.001865 | 3074 | sí |
| V-26 | variados | ferreteria | 1 | 2 | 2 | 5573 (5120) | 104 | 0.001850 | 2924 | sí |
| V-27 | variados | ferreteria | 1 | 2 | 1 | 5430 (5120) | 95 | 0.001649 | 2853 | sí |
| V-28 | variados | ferreteria | 1 | 2 | 1 | 5534 (5120) | 115 | 0.001829 | 3013 | sí |
| V-29 | variados | ferreteria | 1 | 3 | 1 | 8251 (7680) | 161 | 0.002652 | 4393 | sí |
| V-30 | variados | ferreteria | 1 | 2 | 2 | 5590 (5120) | 106 | 0.001876 | 3134 | sí |
| V-31 | variados | ferreteria | 1 | 4 | 2 | 11384 (10240) | 199 | 0.003976 | 5706 | sí |
| W-01 | variados | ferreteria | 4 | 6 | 4 | 17311 (15488) | 287 | 0.006094 | 8363 | sí |
| W-02 | variados | ferreteria | 2 | 6 | 3 | 17853 (15744) | 356 | 0.006675 | 8663 | sí |
| W-03 | variados | ferreteria | 2 | 7 | 4 | 20858 (18688) | 397 | 0.007443 | 10504 | sí |
| W-04 | variados | ferreteria | 2 | 5 | 2 | 14140 (12800) | 205 | 0.004748 | 7827 | sí |
| W-05 | variados | ferreteria | 3 | 6 | 4 | 17715 (15488) | 344 | 0.006741 | 8739 | sí |
| W-06 | variados | ferreteria | 3 | 8 | 3 | 23000 (20864) | 404 | 0.007853 | 11482 | sí |
| K-05 | variados | ferreteria | 2 | 8 | 5 | 22825 (20992) | 429 | 0.007562 | 11854 | sí |
| J-01 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 8 | sí |
| J-02 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 8 | sí |
| J-03 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 8 | sí |
| J-04 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 11 | sí |
| J-05 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 13 | sí |
| J-06 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 15 | sí |
| J-07 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 16 | sí |
| J-08 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 20 | sí |
| J-09 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 12 | sí |
| J-10 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 21 | sí |
| J-11 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 20 | sí |
| J-12 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 15 | sí |
| J-13 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 20 | sí |
| J-14 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 18 | sí |
| J-15 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 21 | sí |
| J-16 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 12 | sí |
| J-17 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 12 | sí |
| J-18 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 19 | sí |
| J-19 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 21 | sí |
| J-20 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 21 | sí |
| J-21 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 14 | sí |
| J-22 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 13 | sí |
| J-23 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 13 | sí |
| J-24 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 14 | sí |
| J-25 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 13 | sí |
| J-26 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 13 | sí |
| J-27 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 16 | sí |
| J-28 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 17 | sí |
| J-29 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 15 | sí |
| J-30 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 13 | sí |
| J-31 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 18 | sí |
| J-32 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 14 | sí |
| J-33 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 13 | sí |
| J-34 | inyeccion | ferreteria | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 13 | sí |
| J-35 | inyeccion | ferreteria | 3 | 3 | 2 | 8475 (7808) | 168 | 0.002815 | 4240 | sí |
| J-36 | inyeccion | ferreteria | 3 | 1 | 0 | 2702 (2560) | 62 | 0.000844 | 1516 | sí |
| J-37 | inyeccion | ferreteria | 3 | 4 | 3 | 11442 (10368) | 199 | 0.003914 | 6789 | sí |
| J-38 | inyeccion | ferreteria | 2 | 2 | 2 | 5609 (5120) | 97 | 0.001878 | 2791 | sí |
| J-39 | inyeccion | ferreteria | 2 | 3 | 2 | 8513 (7808) | 184 | 0.002903 | 5115 | sí |
| J-40 | inyeccion | ferreteria | 1 | 2 | 2 | 5563 (5120) | 97 | 0.001820 | 2794 | sí |
| J-41 | inyeccion | ferreteria | 1 | 2 | 2 | 5604 (5120) | 113 | 0.001912 | 2867 | sí |
| J-42 | inyeccion | ferreteria | 1 | 2 | 2 | 5594 (5120) | 114 | 0.001902 | 3255 | sí |
| J-43 | inyeccion | ferreteria | 1 | 2 | 2 | 5602 (5120) | 109 | 0.001899 | 2986 | sí |
| J-44 | inyeccion | ferreteria | 1 | 2 | 2 | 5610 (5248) | 115 | 0.001790 | 3017 | sí |
| J-45 | inyeccion | ferreteria | 1 | 3 | 1 | 8331 (7680) | 227 | 0.002917 | 4970 | sí |
| N-01 | memoria | ferreteria | 6 | 19 | 9 | 63348 (52608) | 1273 | 0.027129 | 30620 | sí |
| N-02 | memoria | ferreteria | 7 | 15 | 9 | 46719 (39808) | 821 | 0.018653 | 23291 | sí |
| N-03 | memoria | ferreteria | 4 | 9 | 6 | 26976 (24320) | 530 | 0.009509 | 13665 | sí |
| N-04 | memoria | ferreteria | 3 | 7 | 5 | 20824 (18304) | 461 | 0.007963 | 11066 | sí |
| N-05 | memoria | ferreteria | 2 | 5 | 4 | 14544 (13824) | 260 | 0.004315 | 7902 | sí |
| N-06 | memoria | ferreteria | 3 | 7 | 4 | 20538 (18432) | 385 | 0.007281 | 10641 | sí |
| H-01 | natural | ferreteria | 5 | 10 | 6 | 31463 (26880) | 619 | 0.012652 | 16325 | sí |
| H-02 | natural | ferreteria | 4 | 10 | 5 | 30539 (25856) | 519 | 0.012322 | 15178 | sí |
| H-03 | natural | ferreteria | 3 | 6 | 3 | 17208 (15488) | 268 | 0.005918 | 9201 | sí |
| H-04 | natural | ferreteria | 3 | 7 | 3 | 19838 (18304) | 315 | 0.006366 | 10852 | sí |
| H-05 | natural | ferreteria | 3 | 7 | 3 | 19933 (18176) | 333 | 0.006664 | 10733 | sí |
| H-06 | natural | ferreteria | 2 | 5 | 2 | 14055 (12800) | 233 | 0.004711 | 7487 | sí |
| H-07 | natural | ferreteria | 3 | 12 | 5 | 37313 (32000) | 740 | 0.014891 | 20055 | sí |
| H-08 | natural | ferreteria | 3 | 6 | 3 | 17747 (15744) | 405 | 0.006665 | 18427 | sí |
| H-09 | natural | ferreteria | 4 | 7 | 5 | 20534 (18048) | 356 | 0.007607 | 11019 | no |
| H-10 | natural | ferreteria | 2 | 5 | 3 | 14285 (13184) | 262 | 0.004668 | 8080 | sí |
| H-11 | natural | ferreteria | 2 | 4 | 2 | 11388 (10240) | 316 | 0.004273 | 7330 | sí |
| H-12 | natural | ferreteria | 2 | 5 | 3 | 14097 (12928) | 226 | 0.004612 | 7728 | sí |
| H-13 | natural | ferreteria | 2 | 4 | 2 | 11302 (10240) | 202 | 0.003880 | 6300 | sí |
| H-14 | natural | ferreteria | 2 | 4 | 2 | 11761 (10752) | 255 | 0.004049 | 6556 | sí |
| U-01 | surtido | ferreteria | 1 | 2 | 1 | 5473 (5120) | 103 | 0.001723 | 3054 | sí |
| U-02 | surtido | ferreteria | 1 | 2 | 1 | 5533 (5120) | 107 | 0.001808 | 3345 | sí |
| U-03 | surtido | ferreteria | 1 | 2 | 1 | 5532 (5120) | 102 | 0.001794 | 3107 | sí |
| U-04 | surtido | ferreteria | 1 | 2 | 1 | 5462 (5120) | 113 | 0.001734 | 3182 | sí |
| U-05 | surtido | ferreteria | 1 | 2 | 1 | 5498 (5120) | 119 | 0.001794 | 3295 | sí |
| U-06 | surtido | ferreteria | 1 | 2 | 1 | 5499 (5120) | 123 | 0.001805 | 3311 | sí |
| U-07 | surtido | ferreteria | 1 | 2 | 1 | 5477 (5120) | 103 | 0.001728 | 3060 | sí |
| U-08 | surtido | ferreteria | 1 | 2 | 1 | 5612 (5120) | 155 | 0.002026 | 3691 | sí |
| U-09 | surtido | ferreteria | 1 | 2 | 1 | 5495 (5120) | 110 | 0.001768 | 5974 | sí |
| U-10 | surtido | ferreteria | 1 | 2 | 2 | 5536 (5120) | 106 | 0.001809 | 3093 | sí |
| Z-01 | fallas | ferreteria | 1 | 2 | 1 | 5494 (5120) | 113 | 0.001774 | 3208 | sí |
| Z-02 | fallas | ferreteria | 1 | 3 | 2 | 8426 (7680) | 166 | 0.002884 | 4683 | sí |
| Z-03 | fallas | ferreteria | 1 | 2 | 1 | 5494 (5120) | 143 | 0.001849 | 3410 | sí |
| Z-04 | fallas | ferreteria | 1 | 2 | 1 | 5578 (5120) | 103 | 0.001854 | 3280 | sí |
| Z-05 | fallas | ferreteria | 1 | 2 | 2 | 5555 (5120) | 96 | 0.001808 | 3066 | sí |
| Z-06 | fallas | ferreteria | 1 | 2 | 1 | 5509 (5120) | 112 | 0.001790 | 3508 | sí |
| Z-07 | fallas | ferreteria | 1 | 4 | 2 | 11282 (10368) | 208 | 0.003736 | 6931 | sí |
| Z-08 | fallas | ferreteria | 1 | 2 | 2 | 5543 (5120) | 101 | 0.001805 | 3290 | sí |
| Z-09 | fallas | ferreteria | 1 | 3 | 1 | 8339 (7680) | 160 | 0.002760 | 4454 | sí |
| Z-10 | fallas | ferreteria | 1 | 1 | 0 | 2685 (2560) | 75 | 0.000856 | 1834 | sí |
| Z-11 | fallas | ferreteria | 1 | 3 | 0 | 8245 (7680) | 165 | 0.002655 | 4962 | sí |
| Z-12 | fallas | ferreteria | 1 | 2 | 1 | 5620 (5120) | 104 | 0.001909 | 3294 | sí |
| Z-13 | fallas | ferreteria | 1 | 2 | 1 | 5484 (5120) | 125 | 0.001792 | 3469 | sí |
| Z-14 | fallas | ferreteria | 1 | 4 | 1 | 11527 (10240) | 260 | 0.004307 | 6821 | sí |
| Z-15 | fallas | ferreteria | 1 | 2 | 2 | 5608 (5120) | 110 | 0.001909 | 3177 | sí |
| Z-16 | fallas | ferreteria | 1 | 2 | 2 | 5589 (5120) | 111 | 0.001888 | 3204 | sí |
| Z-17 | fallas | ferreteria | 1 | 3 | 1 | 8459 (7680) | 158 | 0.002905 | 4952 | sí |
| Z-18 | fallas | ferreteria | 1 | 2 | 1 | 5437 (5120) | 96 | 0.001660 | 3250 | sí |
| Z-19 | fallas | ferreteria | 1 | 2 | 1 | 5449 (5120) | 89 | 0.001658 | 3204 | sí |
| Z-20 | fallas | ferreteria | 1 | 2 | 1 | 5524 (5120) | 86 | 0.001744 | 3036 | sí |
| Z-21 | fallas | ferreteria | 1 | 3 | 1 | 8244 (7680) | 159 | 0.002638 | 4948 | sí |
| Z-22 | fallas | ferreteria | 1 | 2 | 1 | 5528 (5120) | 128 | 0.001854 | 3589 | sí |
| Z-23 | fallas | ferreteria | 1 | 2 | 1 | 5489 (5120) | 113 | 0.001768 | 3332 | sí |
| Z-24 | fallas | ferreteria | 1 | 2 | 0 | 5759 (5248) | 288 | 0.002408 | 4540 | sí |
| Z-25 | fallas | ferreteria | 1 | 6 | 3 | 17915 (16000) | 364 | 0.006504 | 9943 | sí |
| Z-26 | fallas | ferreteria | 1 | 2 | 2 | 5613 (5120) | 106 | 0.001905 | 3152 | sí |
| Z-27 | fallas | ferreteria | 1 | 1 | 0 | 2701 (2560) | 52 | 0.000818 | 1561 | sí |
| Z-28 | fallas | ferreteria | 1 | 5 | 2 | 14586 (13696) | 282 | 0.004557 | 8101 | sí |
| Z-29 | fallas | ferreteria | 1 | 4 | 2 | 11269 (10368) | 202 | 0.003705 | 6127 | sí |
| Z-30 | fallas | ferreteria | 1 | 2 | 2 | 5531 (5120) | 112 | 0.001818 | 4992 | sí |
| Z-31 | fallas | ferreteria | 1 | 4 | 2 | 11734 (10880) | 224 | 0.003804 | 6346 | sí |
| Z-32 | fallas | ferreteria | 2 | 9 | 5 | 27642 (23808) | 516 | 0.010844 | 15485 | sí |
| Z-33 | fallas | ferreteria | 2 | 7 | 3 | 21585 (18048) | 533 | 0.009363 | 11769 | sí |
| Z-34 | fallas | ferreteria | 2 | 6 | 3 | 17447 (15744) | 320 | 0.006078 | 9565 | sí |
| Z-35 | fallas | ferreteria | 2 | 3 | 2 | 8315 (7680) | 149 | 0.002702 | 4384 | sí |
| Z-36 | fallas | ferreteria | 2 | 4 | 1 | 11403 (10240) | 220 | 0.004052 | 6264 | sí |
| Z-37 | fallas | ferreteria | 2 | 7 | 4 | 20747 (17920) | 384 | 0.008078 | 10795 | sí |
| Z-38 | fallas | ferreteria | 2 | 5 | 3 | 14459 (12928) | 265 | 0.005162 | 8136 | sí |
| A-01 | ampliacion | ferreteria | 1 | 2 | 1 | 5486 (5120) | 107 | 0.001749 | 3288 | sí |
| A-02 | ampliacion | ferreteria | 1 | 2 | 1 | 5511 (5120) | 128 | 0.001833 | 3254 | sí |
| A-03 | ampliacion | ferreteria | 1 | 2 | 2 | 5573 (5120) | 96 | 0.001830 | 3102 | sí |
| A-04 | ampliacion | ferreteria | 1 | 2 | 2 | 5562 (5120) | 111 | 0.001854 | 3120 | sí |
| A-05 | ampliacion | ferreteria | 1 | 2 | 2 | 5559 (5120) | 92 | 0.001803 | 3326 | sí |
| A-06 | ampliacion | ferreteria | 1 | 2 | 2 | 5535 (5120) | 108 | 0.001813 | 3037 | sí |
| A-07 | ampliacion | ferreteria | 1 | 2 | 1 | 5486 (5120) | 124 | 0.001792 | 2994 | sí |
| A-08 | ampliacion | ferreteria | 1 | 2 | 1 | 5492 (5120) | 92 | 0.001719 | 3036 | sí |
| A-09 | ampliacion | ferreteria | 1 | 2 | 2 | 5518 (5120) | 91 | 0.001749 | 3085 | sí |
| A-10 | ampliacion | ferreteria | 1 | 4 | 2 | 11566 (10240) | 274 | 0.004390 | 6626 | sí |
| A-11 | ampliacion | ferreteria | 1 | 2 | 1 | 5464 (5120) | 105 | 0.001716 | 3154 | sí |
| A-12 | ampliacion | ferreteria | 1 | 2 | 1 | 5452 (5120) | 94 | 0.001674 | 3270 | sí |
| A-13 | ampliacion | ferreteria | 1 | 2 | 1 | 5476 (5120) | 87 | 0.001686 | 2990 | sí |
| A-14 | ampliacion | ferreteria | 1 | 2 | 2 | 5564 (5120) | 99 | 0.001826 | 3282 | sí |
| A-15 | ampliacion | ferreteria | 1 | 2 | 1 | 5455 (5120) | 95 | 0.001680 | 3081 | sí |
| A-16 | ampliacion | ferreteria | 1 | 2 | 2 | 5553 (5120) | 108 | 0.001835 | 3071 | sí |
| A-17 | ampliacion | ferreteria | 1 | 3 | 1 | 8284 (7680) | 195 | 0.002778 | 5601 | sí |
| A-18 | ampliacion | ferreteria | 1 | 2 | 1 | 5507 (5120) | 118 | 0.001803 | 3131 | no |
| A-19 | ampliacion | ferreteria | 1 | 2 | 1 | 5446 (5120) | 94 | 0.001666 | 3062 | sí |
| A-20 | ampliacion | ferreteria | 2 | 4 | 2 | 11210 (10240) | 211 | 0.003788 | 6397 | sí |
| M-06 | mercado | mercado | 1 | 2 | 2 | 5556 (256) | 83 | 0.006884 | 2982 | sí |
| M-07 | mercado | mercado | 1 | 2 | 2 | 5572 (256) | 93 | 0.006929 | 3197 | sí |
| M-08 | mercado | mercado | 1 | 4 | 2 | 11596 (5632) | 246 | 0.009196 | 6541 | sí |
| M-09 | mercado | mercado | 1 | 2 | 1 | 5470 (5120) | 95 | 0.001699 | 3059 | sí |
| M-10 | mercado | mercado | 1 | 2 | 1 | 5463 (5120) | 87 | 0.001670 | 2838 | sí |
| M-11 | mercado | mercado | 1 | 2 | 2 | 5588 (5120) | 105 | 0.001872 | 3039 | sí |
| M-12 | mercado | mercado | 1 | 2 | 2 | 5559 (2688) | 107 | 0.004394 | 2958 | sí |
| M-13 | mercado | mercado | 1 | 3 | 1 | 8356 (7680) | 199 | 0.002878 | 5145 | sí |
| M-14 | mercado | mercado | 1 | 1 | 0 | 2694 (2560) | 48 | 0.000800 | 1615 | sí |
| M-15 | mercado | mercado | 1 | 2 | 2 | 5583 (2688) | 112 | 0.004436 | 3167 | sí |
| M-16 | mercado | mercado | 1 | 2 | 1 | 5532 (2688) | 106 | 0.004358 | 3232 | sí |
| M-17 | mercado | mercado | 1 | 4 | 2 | 11439 (10496) | 246 | 0.003893 | 9890 | sí |
| M-18 | mercado | mercado | 1 | 2 | 1 | 5487 (5120) | 94 | 0.001718 | 3764 | sí |
| M-19 | mercado | mercado | 1 | 4 | 2 | 11541 (5376) | 225 | 0.009344 | 8979 | sí |
| M-20 | mercado | mercado | 1 | 3 | 2 | 8532 (7680) | 122 | 0.002906 | 7259 | sí |
| M-21 | mercado | mercado | 1 | 1 | 1 | 2686 (2560) | 23 | 0.000727 | 3474 | sí |
| M-22 | mercado | mercado | 1 | 2 | 1 | 5527 (5120) | 98 | 0.001778 | 4274 | sí |
| M-23 | mercado | mercado | 1 | 5 | 2 | 14211 (8192) | 278 | 0.009857 | 8556 | sí |
| M-24 | mercado | mercado | 1 | 2 | 1 | 5512 (5120) | 81 | 0.001716 | 2911 | sí |
| M-25 | mercado | mercado | 1 | 2 | 2 | 5573 (5120) | 89 | 0.001813 | 2982 | sí |
| M-26 | mercado | mercado | 1 | 2 | 1 | 5478 (5120) | 79 | 0.001669 | 2688 | sí |
| M-27 | mercado | mercado | 1 | 2 | 1 | 5476 (5120) | 79 | 0.001666 | 2747 | sí |
| M-28 | mercado | mercado | 1 | 2 | 2 | 5522 (5120) | 91 | 0.001754 | 2856 | sí |
| M-29 | mercado | mercado | 1 | 2 | 2 | 5558 (5120) | 91 | 0.001799 | 3166 | sí |
| M-30 | mercado | mercado | 1 | 1 | 0 | 2692 (2560) | 57 | 0.000820 | 1659 | sí |
| M-31 | mercado | mercado | 1 | 0 | 0 | 0 (0) | 0 | 0.000000 | 8 | sí |
| M-32 | mercado | mercado | 4 | 7 | 5 | 20768 (15616) | 402 | 0.010568 | 11005 | sí |
| M-33 | mercado | mercado | 2 | 3 | 2 | 8443 (7936) | 160 | 0.002621 | 4730 | sí |
| M-34 | mercado | mercado | 2 | 4 | 2 | 11295 (7808) | 177 | 0.006363 | 6930 | sí |
| M-35 | mercado | mercado | 2 | 7 | 4 | 20676 (10880) | 344 | 0.015281 | 11449 | sí |
| M-36 | mercado | mercado | 3 | 7 | 5 | 20428 (18048) | 367 | 0.007502 | 10761 | sí |
| M-37 | mercado | mercado | 2 | 5 | 3 | 14439 (13056) | 273 | 0.005022 | 8398 | sí |
| M-38 | mercado | mercado | 1 | 2 | 1 | 5488 (5120) | 102 | 0.001739 | 2821 | sí |
| P-tubo-1 | parafrasis | ferreteria | 1 | 2 | 2 | 5590 (5120) | 111 | 0.001889 | 3200 | sí |
| P-tubo-2 | parafrasis | ferreteria | 1 | 2 | 2 | 5598 (5120) | 112 | 0.001902 | 3023 | sí |
| P-tubo-3 | parafrasis | ferreteria | 1 | 2 | 2 | 5600 (5120) | 111 | 0.001902 | 3185 | sí |
| P-tanque-1 | parafrasis | ferreteria | 1 | 2 | 2 | 5575 (5120) | 104 | 0.001853 | 3031 | sí |
| P-tanque-2 | parafrasis | ferreteria | 1 | 2 | 2 | 5581 (5120) | 108 | 0.001870 | 3199 | sí |
| P-tanque-3 | parafrasis | ferreteria | 1 | 2 | 2 | 5569 (5120) | 103 | 0.001843 | 3035 | sí |
| P-brochas-1 | parafrasis | ferreteria | 1 | 2 | 2 | 5557 (5120) | 92 | 0.001800 | 3271 | sí |
| P-brochas-2 | parafrasis | ferreteria | 1 | 2 | 2 | 5563 (5120) | 92 | 0.001808 | 3515 | sí |
| P-brochas-3 | parafrasis | ferreteria | 1 | 2 | 2 | 5560 (5120) | 96 | 0.001814 | 2966 | sí |
| P-horario-1 | parafrasis | ferreteria | 1 | 2 | 1 | 5520 (5120) | 94 | 0.001759 | 3070 | sí |
| P-horario-2 | parafrasis | ferreteria | 1 | 2 | 1 | 5524 (5120) | 84 | 0.001739 | 3522 | sí |
| P-horario-3 | parafrasis | ferreteria | 1 | 2 | 1 | 5524 (5120) | 103 | 0.001786 | 3200 | sí |
| P-cubeta-1 | parafrasis | mercado | 1 | 2 | 2 | 5568 (2688) | 90 | 0.004363 | 2770 | sí |
| P-cubeta-2 | parafrasis | mercado | 1 | 4 | 2 | 11233 (10240) | 192 | 0.003769 | 6405 | sí |
| P-cubeta-3 | parafrasis | mercado | 1 | 4 | 2 | 11354 (7808) | 178 | 0.006439 | 5878 | sí |
| P-docena-1 | parafrasis | mercado | 1 | 2 | 2 | 5557 (5120) | 86 | 0.001785 | 2986 | sí |
| P-docena-2 | parafrasis | mercado | 1 | 4 | 2 | 11306 (10368) | 174 | 0.003681 | 6302 | sí |
| P-docena-3 | parafrasis | mercado | 1 | 4 | 2 | 11310 (5632) | 157 | 0.008616 | 6172 | sí |
| P-fiado-1 | parafrasis | mercado | 1 | 3 | 1 | 8235 (7680) | 143 | 0.002587 | 4760 | sí |
| P-fiado-2 | parafrasis | mercado | 1 | 1 | 0 | 2690 (2560) | 65 | 0.000837 | 1618 | no |
| P-fiado-3 | parafrasis | mercado | 1 | 1 | 0 | 2693 (2560) | 58 | 0.000823 | 1578 | sí |
| P-domicilio-1 | parafrasis | mercado | 1 | 2 | 1 | 5446 (5120) | 94 | 0.001666 | 3108 | sí |
| P-domicilio-2 | parafrasis | mercado | 1 | 3 | 1 | 8251 (7680) | 146 | 0.002615 | 4425 | sí |
| P-domicilio-3 | parafrasis | mercado | 1 | 2 | 1 | 5446 (5120) | 89 | 0.001654 | 2965 | sí |
