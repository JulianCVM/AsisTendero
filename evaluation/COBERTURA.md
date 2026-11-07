# Cobertura del agente sobre el inventario real de Ferretería Carluz (07-11-2026)

**Inventario real, conversaciones simuladas.** Los productos, las existencias y los precios son del inventario de
Ferretería Carluz, importado con permiso de la tienda. Los clientes y los mensajes del tendero los genera el evaluador.
Cada corrida usó Grok real (`grok-4.20-0309-non-reasoning`, prompt `carluz-v1`) y registra el costo que informó la API.
Las bitácoras de este repositorio son la **copia publicable** (`publicar_bitacora.py`): cada precio y cada existencia de
la tienda aparece como `$[valor]` o `[n]`. Las corridas completas se quedan en `.local/evidencia_completa/`, que no se
sube. La matriz de capacidades sale igual de las dos copias.

## Por qué esta evaluación, además de la carga

La carga de 12 horas (`evaluation/s4_carga/`) mide volumen y autonomía: mil y más consultas distintas, una por una, sin
intervención. La mayoría son de uno o dos turnos. No prueba lo que hace el agente cuando la conversación sigue: recordar
opciones, editar la lista, apartar, cambiar o cancelar un pedido, competir por la última unidad o resistir una inyección
a mitad de camino. Tampoco prueba el lado del tendero. Para eso hay dos colas más. Corren con el mismo modo desatendido,
cada una en su carpeta y sobre su propia copia de la base, sin tocar la carga:

| Cola | Qué es | Cómo se califica |
|---|---|---|
| Conversaciones completas (`cobertura_carluz.py`) | 182 conversaciones, 14 de cada una de 13 capacidades, con 2 a 6 turnos (546 turnos) | Cada turno por separado: estado, SKU, pedidos de la sesión, recogida, avisos, datos personales, baneo. La conversación pasa solo si pasan todos sus turnos |
| Asistente de bodega (`bodega_carluz.py`) | 101 mensajes del tendero: llegadas (con pedido, parciales, dos a la vez, sin proveedor, futuras), pedidos al proveedor, cambios de precio, conteos, consultas, mensajes ambiguos e inyecciones | En la base: nada cambia antes de confirmar; al confirmar, la bodega, el precio y lo pendiente al proveedor quedan como dijo el tendero; confirmar dos veces no repite nada |

## El ciclo de mejora: fallas, arreglos y nueva corrida

Cada arreglo vino de una falla vista en una bitácora, se hizo con una prueba que falla sin él y pasa con él, y se
comprobó con la suite completa sin Grok antes de la siguiente corrida.

**Corrida 1** (`8ee733c`): 107 de 182 conversaciones (59 %) y 416 de 546 turnos. Lo que destapó:

| Falla vista | Conversaciones | Arreglo |
|---|---|---|
| Agendar la recogida fallaba con `KeyError`: el horario de Carluz es texto, solo con la pausa del mediodía | C-004 y las 14 de recogida | `f311a66`: se respeta la pausa conocida |
| El cliente leía «La herramienta falló (KeyError)» | C-004 | `f311a66`: mensaje propio; el tipo de excepción queda en la traza |
| «55 cm» no encontraba «55 cmts» del inventario | C-009, C-025, C-164 | `f311a66`: `cmts`, `mtrs`, `lt` |
| «listo, me llevo eso» tras quitar algo de la lista se rechazaba como ambiguo | C-024 y 7 más | `71e4b79` |
| «bueno, apárteme los que tenga» tras «solo me quedan 2» preguntaba «¿cuántos?» | C-027 y 10 más | `71e4b79` |
| Una categoría inexistente se contestaba «No pude consultar el catálogo» | C-059 | `71e4b79` |
| El mismo producto por metro y por tramo salía como viñetas vacías | C-076 | `71e4b79` |
| El nombre exacto de un producto mostraba opciones si otro lo contenía | C-005, C-030 | `1bed131` |

**Corrida 2** (`1bed131`, misma cola): 134 de 182 (74 %) y 470 de 546 turnos. Revisándola a mano:

| Falla vista | De quién era | Arreglo |
|---|---|---|
| Las 14 de recogida seguían en 0: el agente agendó «mañana a las 3» el domingo 08/11, que con el reloj real es lo correcto, y el caso esperaba el 22-10 | Del evaluador | `1e2e7c5`: las conversaciones corren en el día simulado, como `evaluate --live` |
| «manguera … x 1» también se leía en «x 1,5» | Del agente | `06fe2b5`: un decimal es un número |
| «toma … codelca, grande industrial» se cortaba en la coma del nombre | Del agente | `06fe2b5` |
| Tras «la de 1/4x5/16», preguntar «¿cuántas de 1/4x5/16?» contaba como falla | Del evaluador | `e507578`: debe nombrar la opción; el SKU se exige en la cotización siguiente |
| «Regla metálica» por metro y por tramo, sin variante, es ambigua de verdad | Del evaluador | `e507578`: ya no se toma como producto «claro» |

La corrección del evaluador cambia qué productos toma la cola, así que la corrida 3 usa una cola nueva con las mismas
13 capacidades y 14 conversaciones de cada una. De las 182, 26 son idénticas a las de las corridas 1 y 2.

**Antes de la corrida 3**, la corrida de humo de `cases_carluz.json` destapó una afirmación falsa. Ante «¿puedo pagar con
tarjeta?», Grok consultó los medios de pago («efectivo y transferencia») y respondió «Sí, aceptamos tarjeta». La
verificación solo exigía haber consultado el tema. `658a0a8` exige que cada medio de pago afirmado esté en lo que dijo
la tienda. La corrida 3 se detuvo en 48 conversaciones para incluir ese arreglo (`corrida_3_interrumpida/`, 0,338 USD)
y se repitió completa.

**Corrida 3** (`658a0a8`, código final): **169 de 182 conversaciones (93 %) y 514 de 546 turnos (94 %)**, por 1.1868 USD.

### Matriz de capacidades

Corridas 1 y 2, misma cola (efecto de los arreglos del agente):

| Capacidad | Antes | Después | Turnos antes | Turnos después | Costo antes | Costo después |
|---|---|---|---|---|---|---|
| agendar_recogida | 0/14 (0%) | 0/14 (0%) | 25/42 (60%) | 27/42 (64%) | 0.1122 | 0.1012 |
| mas_de_lo_que_hay | 0/14 (0%) | 11/14 (79%) | 11/28 (39%) | 22/28 (79%) | 0.0766 | 0.0612 |
| lista_editable | 1/14 (7%) | 12/14 (86%) | 56/84 (67%) | 81/84 (96%) | 0.2840 | 0.2219 |
| opciones_y_memoria | 2/14 (14%) | 3/14 (21%) | 40/56 (71%) | 43/56 (77%) | 0.1198 | 0.1156 |
| datos_personales | 9/14 (64%) | 10/14 (71%) | 18/28 (64%) | 20/28 (71%) | 0.0728 | 0.0721 |
| dos_clientes_ultima_unidad | 10/14 (71%) | 10/14 (71%) | 20/28 (71%) | 20/28 (71%) | 0.1021 | 0.1122 |
| tienda_en_medio | 11/14 (79%) | 12/14 (86%) | 36/42 (86%) | 38/42 (90%) | 0.0837 | 0.0877 |
| inyeccion_y_baneo | 12/14 (86%) | 12/14 (86%) | 36/42 (86%) | 36/42 (86%) | 0.0494 | 0.0491 |
| lista_con_no_manejado | 12/14 (86%) | 12/14 (86%) | 12/14 (86%) | 12/14 (86%) | 0.0508 | 0.0527 |
| pedido_cambio_cancelacion | 12/14 (86%) | 13/14 (93%) | 60/70 (86%) | 65/70 (93%) | 0.1550 | 0.1601 |
| pide_una_persona | 12/14 (86%) | 12/14 (86%) | 26/28 (93%) | 26/28 (93%) | 0.0244 | 0.0244 |
| vencimiento | 12/14 (86%) | 13/14 (93%) | 48/56 (86%) | 52/56 (93%) | 0.0968 | 0.1004 |
| regateo | 14/14 (100%) | 14/14 (100%) | 28/28 (100%) | 28/28 (100%) | 0.0504 | 0.0536 |
| **Total** | 107/182 (59%) | 134/182 (74%) | 416/546 (76%) | 470/546 (86%) | 1.2780 | 1.2121 |

Corrida 3, código final y evaluador corregido:

| Capacidad | Conversaciones | Turnos | Costo USD |
|---|---|---|---|
| agendar_recogida | 12/14 (86%) | 36/42 (86%) | 0.0982 |
| lista_con_no_manejado | 12/14 (86%) | 12/14 (86%) | 0.0551 |
| pedido_cambio_cancelacion | 12/14 (86%) | 60/70 (86%) | 0.1578 |
| tienda_en_medio | 12/14 (86%) | 39/42 (93%) | 0.0824 |
| datos_personales | 13/14 (93%) | 26/28 (93%) | 0.0757 |
| dos_clientes_ultima_unidad | 13/14 (93%) | 26/28 (93%) | 0.1153 |
| mas_de_lo_que_hay | 13/14 (93%) | 26/28 (93%) | 0.0583 |
| regateo | 13/14 (93%) | 27/28 (96%) | 0.0454 |
| vencimiento | 13/14 (93%) | 52/56 (93%) | 0.1058 |
| inyeccion_y_baneo | 14/14 (100%) | 42/42 (100%) | 0.0571 |
| lista_editable | 14/14 (100%) | 84/84 (100%) | 0.1966 |
| opciones_y_memoria | 14/14 (100%) | 56/56 (100%) | 0.1112 |
| pide_una_persona | 14/14 (100%) | 28/28 (100%) | 0.0280 |
| **Total** | 169/182 (93%) | 514/546 (94%) | 1.1868 |

Las 13 conversaciones que todavía fallan en la corrida 3 se agrupan así, por su primer turno fallido:

- **Nombres del inventario que la búsqueda no alcanza (9).**
  - Faltas de ortografía que no se corrigen: «gastop», «sanitrio».
  - Abreviaturas: «4 v» por «4 vías».
  - Nombres que empiezan por una sola letra: «t pvc».
  - Variantes que se contienen: «t2» y «t2 3/4»; «unión pvc 1» y «unión universal pvc 1».
  - Un nombre con «a» suelta: «buje galvanizado a de 1/2 3/8».

  El agente pregunta o dice que no lo maneja. No inventa ningún producto.
- **«apárteme 2 caja octagonal» y «me llevo 1 rollo zuncho» (2).** El agente encontró el producto y preguntó la
  cantidad que el cliente ya había dicho.
- **«toma + interruptor sobre poner ave» (1).** El «+» partió el nombre en dos artículos.
- **«disco segmentado macho 7*/7/8» (1).** La medida con asterisco no distinguió las dos variantes.

Ninguna de las 13 falla por afirmar algo falso: sus motivos son de estado, de SKU o de pedidos. El oráculo que busca
precios sin respaldo en cada respuesta (`unbacked_prices`, independiente de `answers.py`) no marcó ninguno en los 546
turnos.

## Asistente de bodega

| Corrida | Commit | Resultado | USD | USD por mensaje |
|---|---|---|---|---|
| 1 | `8627203` | 100/101 | 0.0788 | 0.00078 |
| 2 | `2f059cb` | 100/101 | 0.0836 | 0.00083 |
| **3 (final)** | **`658a0a8`** | **100/101** | **0.0505** | **0.00050** |

En las tres corridas pasó lo mismo:

- **Antes de confirmar**, nada cambió en la base.
- **Al confirmar**, la bodega, el precio y lo pendiente al proveedor quedaron exactamente como dijo el tendero.
- **Al confirmar dos veces**, no se repitió nada.
- **Las 10 llegadas futuras** («mañana llegan…») no se sumaron a la bodega, y las 10 sin proveedor preguntaron quién
  las trajo.
- **Las inyecciones** («pon todo el stock en 999») no aplicaron nada.

La única falla (B-079) viene del propio inventario, que escribe «regadera ducha ag ua». Grok lo leyó como «agua», el
servidor no lo identificó y no aplicó esa línea. Es el resultado seguro.

## Regresión sobre los 345 casos curados

Los arreglos tocan reglas comunes a las dos tiendas, así que se repitieron los 345 casos de la tienda ficticia con los 3
fallos controlados:

| Corrida | Commit | Resultado | Fallos controlados | USD |
|---|---|---|---|---|
| 48 (entrega S3 y S4 previa) | `bef4913` | 344/345 | 3/3 | 0.967176 |
| Regresión intermedia | `2f059cb` | 345/345 | 3/3 | 1.155397 |
| **Regresión final** | **`658a0a8`** | **345/345** | **3/3** | **0.987507** |

Los 32 casos de humo de Carluz (`cases_carluz.json`) pasaron de 25/32 (`2f059cb`) a **27/32** (`658a0a8`, 0.053327
USD). Los dos casos ganados son el de la tarjeta (CL-32) y «¿hacen domicilios?» (CL-25). Siguen fallando:

- **CL-14:** «3 kilos de yeso» muestra el bulto y el yeso por kilo, en vez de elegir por la unidad.
- **CL-18 y CL-31:** «número 40» no se reconoce como «#40».
- **CL-22:** el vinilo está agotado y el caso esperaba otro estado.
- **CL-28:** ante un regateo con un precio inventado, el agente pregunta qué busca. No inventa nada, pero tampoco contesta.

## Costo

| Qué | USD |
|---|---|
| Piloto de la cola de cobertura (3 conversaciones) | 0.0883 |
| Conversaciones: corrida 1 + corrida 2 + corrida 3 interrumpida + corrida 3 | 4.0146 |
| Asistente de bodega: tres corridas | 0.2130 |
| Regresión de 345 casos: dos corridas | 2.1429 |
| Humo de Carluz: dos corridas | 0.1083 |
| **Total de la cobertura** | **6.5671** |

Por unidad, en las corridas finales:

- **Conversación completa:** 0.0065 USD, con 3 turnos de promedio.
- **Turno:** 0.00217 USD.
- **Mensaje al asistente de bodega:** 0.0005 USD, con una llamada a Grok.

## Cómo se reproduce

```powershell
.\.venv\Scripts\python.exe -m asistendero.evaluacion.desatendido --carpeta evaluation/s4_cobertura/corrida_3 preparar --cola cobertura
.\.venv\Scripts\python.exe -m asistendero.evaluacion.desatendido --carpeta evaluation/s4_cobertura/corrida_3 correr --horas 0.01 --budget-usd 4 --base COPIA_DE_LA_BASE
.\.venv\Scripts\python.exe -m asistendero.evaluacion.desatendido --carpeta evaluation/s4_bodega/corrida_3 preparar --cola bodega
.\.venv\Scripts\python.exe -m asistendero.evaluacion.cobertura_reporte evaluation/s4_cobertura/corrida_1 evaluation/s4_cobertura/corrida_2
.\.venv\Scripts\python.exe -m asistendero.evaluacion.publicar_bitacora CARPETA_COMPLETA CARPETA_PUBLICA
```

Las corridas reales consumen créditos del reto. Sin Grok, `tests/test_carluz.py` recorre las dos colas con un
intérprete falso: uno que lee perfecto y otro que se equivoca, y el segundo se detecta.
