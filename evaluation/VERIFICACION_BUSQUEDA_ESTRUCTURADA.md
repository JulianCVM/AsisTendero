# Verificación de búsqueda estructurada

**Fecha:** 17 de octubre de 2026 (Colombia). **Prompt:** `structured-search-v1`. **Entorno:** terminal local, pasarela real de Grok y seis variantes ficticias de SQLite. La clave permanece en `.env` y no se publica.

| Entrada probada | Resultado observado |
| --- | --- |
| `Busco tubo PVC de 1/2 para agua y un bulto de cemento gris de 50 kg` | Respuesta con `PVC-050` a `$8.500 COP` por metro y 12 metros; `CEM-050` a `$39.500 COP` por bulto y 9 bultos. Aclara que son datos simulados. Código de salida `0`. |
| `Busco tubo PVC de 1 pulgada para agua` | No presenta una coincidencia exacta de 1 pulgada. Muestra solo las medidas cercanas de 1/2 y 3/4 pulgada, con sus existencias ficticias y sin asignarles el precio de una coincidencia exacta. Código de salida `0`. |
| `Necesito un tubo para agua, ¿qué tienen?` | Limita la respuesta a los dos tubos para agua del catálogo y pide la medida. No escoge una variante sin confirmación. Código de salida `0`. |
| `Hola, ¿están atendiendo en este momento?` | Indica que no hay horario verificado y ofrece revisar un producto en el catálogo de prueba. No afirma que la tienda esté abierta. Código de salida `0`. |

En la primera ruta Grok interpretó la lista, el código consultó por artículo y Grok respondió con los hallazgos. Las otras rutas comprueban medida ausente, descripción parcial y atención sin horario configurado. La suite local terminó con **19 pruebas correctas y una omitida**; la omitida necesita sockets locales bloqueados por este entorno. Las pruebas incluyen descarte de una medida inventada por el modelo, límite de candidatos, diferencia de material y formato compacto como `50kg`.

Estas corridas muestran funcionamiento de cuatro escenarios, no una tasa de exactitud general. La terminal no registró tokens ni costo de estas ejecuciones; el visor de pruebas puede mostrarlos si la API los informa o si existe una tarifa de referencia para estimarlos. No hubo comercio real, pedido, reserva ni pago.
