# Verificación en vivo del entregable 1

**Fecha:** 17 de octubre de 2026 (Colombia). **Prompt:** `agent-first-v2`. **Alcance:** dos mensajes ejecutados desde la terminal con una clave local de la pasarela del reto y el catálogo SQLite ficticio. Ninguna clave ni traza privada se publica.

## 1. Consulta sobre atención

**Entrada:** `Hola, ¿están atendiendo en este momento?`

**Resultado observado:** `No tengo un horario verificado de esta ferretería de demostración. Confírmalo directamente con el local.`

**Código de salida:** `0`. La solicitud pasó por Grok y se respondió sin consultar el catálogo. Durante la verificación se detectó que Grok podía clasificar esa frase como saludo y proponer una respuesta que insinuaba atención abierta. Se añadió una comprobación del mensaje original en la salida final y una prueba de regresión. La comprobación no sustituye la primera llamada a Grok.

## 2. Lista de dos productos

**Entrada:** `Busco tubo PVC de 1/2 para agua y un bulto de cemento gris de 50 kg`

**Resultado observado:** el programa respondió con `PVC-050`, `$8.500 COP` por metro y `12 metros` ficticios; y con `CEM-050`, `$39.500 COP` por bulto y `9 bultos` ficticios. Indicó que eran datos simulados.

**Código de salida:** `0`. Esta ruta del grafo hace una llamada de interpretación, ejecuta búsquedas del catálogo para los dos artículos y hace una segunda llamada al modelo con los hallazgos. El código verifica la respuesta contra SQLite antes de entregarla.

## Comprobaciones adicionales y límites

La suite local terminó con **14 pruebas correctas y una omitida** después de la corrección. La prueba omitida pertenece al visor local y depende de la disponibilidad de sockets en el entorno de pruebas.

Estas dos corridas prueban conexión real y las rutas principales del prototipo actual. No miden exactitud general, costo real, estabilidad del servicio, funcionamiento de WhatsApp, datos de un comercio piloto, pedidos, pagos ni reservas. La salida de terminal no registró uso de tokens ni costo de esas corridas; el visor puede mostrar el costo informado o estimado para ejecuciones realizadas allí.
