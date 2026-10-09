# AsisTendero

Plataforma para tiendas de barrio, ferreterías, papelerías y otros comercios pequeños. Une inventario, pedidos, ventas, conversaciones y proveedores con un agente Grok que consulta datos reales, propone acciones y pide aprobación cuando corresponde.

**Tablero de desarrollo:** [PulsoTienda](https://github.com/users/JulianCVM/projects/9). Las 53 tareas están en la columna `Todo` y se pueden asignar y mover a `In Progress` o `Done` durante el desarrollo.

## Plan de desarrollo

El [backlog de 53 tareas](https://github.com/JulianCVM/AsisTendero/issues) está organizado por ocho hitos de trabajo. Cada issue tiene identificador PT, prioridad, área, etapa, hito previsto, dependencias y criterio de aceptación.

| Hito | Enfoque | Tareas |
| --- | --- | --- |
| M0 | Alcance, reglas, recorridos y contratos | [Ver tareas](https://github.com/JulianCVM/AsisTendero/issues?q=is%3Aissue+is%3Aopen+label%3Amilestone%3AM0) |
| M1 | Base de la plataforma, cuentas y permisos | [Ver tareas](https://github.com/JulianCVM/AsisTendero/issues?q=is%3Aissue+is%3Aopen+label%3Amilestone%3AM1) |
| M2 | Catálogo, precios e inventario | [Ver tareas](https://github.com/JulianCVM/AsisTendero/issues?q=is%3Aissue+is%3Aopen+label%3Amilestone%3AM2) |
| M3 | Pedidos, ventas, chat y panel operativo | [Ver tareas](https://github.com/JulianCVM/AsisTendero/issues?q=is%3Aissue+is%3Aopen+label%3Amilestone%3AM3) |
| M4 | Agente Grok, herramientas, memoria y aprobaciones | [Ver tareas](https://github.com/JulianCVM/AsisTendero/issues?q=is%3Aissue+is%3Aopen+label%3Amilestone%3AM4) |
| M5 | Proveedores, reposición y fiados | [Ver tareas](https://github.com/JulianCVM/AsisTendero/issues?q=is%3Aissue+is%3Aopen+label%3Amilestone%3AM5) |
| M6 | WhatsApp, Wompi y modalidad fiscal | [Ver tareas](https://github.com/JulianCVM/AsisTendero/issues?q=is%3Aissue+is%3Aopen+label%3Amilestone%3AM6) |
| M7 | Aislamiento, evaluación y piloto | [Ver tareas](https://github.com/JulianCVM/AsisTendero/issues?q=is%3Aissue+is%3Aopen+label%3Amilestone%3AM7) |

Las etiquetas `priority:p0`, `priority:p1` y `priority:p2` marcan la prioridad. Las etiquetas `area:*` y `stage:*` facilitan vistas por dominio y fase. `type:*` distingue decisiones, funciones, integraciones y tareas de calidad.

## Regla de implementación

Las decisiones sobre negocio, pagos, inventario y proveedores deben quedar en operaciones verificables, con historial y permisos. El agente puede leer, explicar y proponer; las acciones sensibles pasan por las herramientas y aprobaciones definidas en los issues.

## Inicio recomendado

1. Completar las decisiones de M0 con el comercio piloto.
2. Montar el núcleo multi negocio de M1 y el inventario de M2.
3. Demostrar un pedido completo en un chat de prueba antes de activar WhatsApp y Wompi.
4. Evaluar el agente con los casos del M7 y registrar evidencia.
