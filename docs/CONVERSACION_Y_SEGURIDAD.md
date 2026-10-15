# Conversación, varios productos y resistencia a instrucciones indebidas

**Estado:** propuesta para las siguientes iteraciones de `codex/harness-tests`; no es funcionalidad implementada. Debe revisarse con la pareja y con PT-001, PT-003, PT-006, PT-023 y PT-024 antes de tratarla como contrato del producto. El harness actual recibe una consulta independiente sobre un producto, no guarda carrito ni historial y no crea pedidos.

## Lo que ya protege el harness

- LangGraph impone el recorrido `validar → recuperar → decidir → responder`. La base SQLite de demostración se lee con código de servidor; Grok no recibe SQL ni credenciales.
- Grok propone un SKU entre candidatos acotados. El backend rechaza SKU inexistentes y variantes sin medida o presentación distintiva. Un SKU escrito en un mensaje no autoriza por sí solo a cambiar de variante.
- Precio y existencias salen del registro SQLite, no del texto del cliente ni de la salida del modelo. No existen herramientas de escritura ni acciones externas.
- El prompt ordena tratar instrucciones dentro de la consulta como datos y devolver `null` si intentan alterar la tarea. Esta instrucción **no es una garantía**: la comprobación decisiva debe permanecer en el código y ampliarse cuando existan operaciones con efectos.

## Flujo propuesto para varios productos

1. Resolver la identidad de negocio, sede y conversación desde el canal autenticado. No tomar esos identificadores del mensaje ni del modelo.
2. Interpretar la intención en una estructura limitada: `consultar`, `agregar`, `quitar`, `cambiar_cantidad` o `confirmar`, más una lista de menciones de producto con cantidad y medida cuando existan. Un texto como «dos tubos de 1/2 y tres tornillos de 2 pulgadas» produce dos menciones separadas. La extracción asistida por Grok requiere esquema validado y límites de líneas; todavía no está implementada.
3. Buscar candidatos **por cada mención** mediante la herramienta de catálogo del servidor. El modelo puede ayudar a desambiguar, pero cada SKU y cantidad se valida contra el catálogo y las reglas del negocio. Una línea incierta queda pendiente y se pregunta por ella sin inventar precio ni sumar un total definitivo.
4. Mantener un carrito estructurado por conversación y sede: `sku`, variante, cantidad, unidad y estado de resolución. «Agrega otro tubo de 1/2» modifica la línea identificada; «agrega uno más» solo se resuelve si hay un único referente claro. Si hay dos posibles, se pregunta cuál. Ningún mensaje ambiguo modifica una orden confirmada.
5. Antes de cotizar o confirmar, consultar precio y disponibilidad vigentes para **todas** las líneas, generar una versión de cotización y mostrar el detalle. Cada cambio de líneas genera nueva versión; la confirmación explícita del cliente se refiere a esa versión. La futura herramienta de reserva revalidará precio, stock y permisos en la misma operación, con idempotencia. Pedido, reserva y pago tienen estados separados.

Ejemplo previsto: «Quiero dos tubos PVC de 1/2 y un bulto de cemento» → dos líneas verificadas → detalle y total de una cotización. Si después dice «agrega un tubo más», se incrementa solo esa línea y se vuelve a cotizar; todavía no se reserva ni se cobra por ese mensaje. **Hoy este recorrido no funciona**: la versión actual busca candidatos para la frase completa y responde sobre un solo producto.

## Ventana de contexto propuesta

- Persistir fuera del prompt el estado operativo: carrito, versión de cotización, pedido y aprobaciones. Un checkpoint de LangGraph guarda el punto de ejecución; la base de negocio conserva los hechos transaccionales. El resumen conversacional nunca sustituye el dato actual de precio, stock o pago.
- Para cada turno, construir contexto con instrucciones versionadas, identidad de negocio/sede derivada del servidor, mensaje nuevo, carrito estructurado, preguntas pendientes y un resumen corto de hechos confirmados de esa sede. Recuperar solo los turnos recientes necesarios, con un presupuesto de tokens medido. No reenviar todo el historial.
- Al resumir, conservar referencias y procedencia de decisiones confirmadas, sin convertir sugerencias o mensajes del cliente en reglas del sistema. No guardar como memoria una orden de «ignora las instrucciones» ni un precio declarado por el cliente. La política de retención y consentimiento está pendiente con PT-001/PT-023.
- Si el referente de «ese», «otro» o «uno más» desapareció del contexto o admite varias interpretaciones, pedir precisión. No reconstruir un carrito por intuición del modelo.

## Pruebas para avanzar sin degradar calidad

- Mantener fijo un corpus versionado y la misma base al comparar prompt, modelo o recuperación. Agregar casos con varios productos, referencias ambiguas, cambios de cantidad, contexto largo y datos desactualizados, además de instrucciones indebidas en mensajes y nombres de productos.
- Separar pruebas sin API de la evaluación real acotada. Verificar hechos, estados y llamadas a herramientas; revisar manualmente brevedad y utilidad de las respuestas. Registrar tokens, latencia, versión del prompt, modelo y hash de datos.
- Para futuras herramientas de escritura, probar que un mensaje no cambie sede, permisos, precio, estado de pago o límite de crédito; que una repetición no duplique un pedido; y que una cotización vieja obligue a revalidar. Limitar pasos del grafo, cantidad de líneas y llamadas al modelo por turno.

**Riesgo pendiente:** la búsqueda actual compara palabras sobre seis filas y la comprobación de variantes no es un detector general de prompt injection. No se debe conectar este grafo a mutaciones, WhatsApp ni datos reales sin contratos de herramientas, autorización y pruebas adicionales.
