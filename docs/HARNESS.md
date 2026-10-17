# Harness experimental de AsisTendero

**Estado:** prototipo local para el primer flujo demostrable. No representa la plataforma comercial completa ni cierra las issues PT-001, PT-006, PT-031 o PT-032. Usa `PROMPT_VERSION=structured-search-v1` y datos ficticios.

## Contrato del flujo

1. `validate` limita la entrada textual a 2.000 caracteres.
2. `interpret` envía **siempre** el mensaje completo a Grok. El modelo devuelve `respond` o `search_products`, con hasta cinco objetos `ProductQuery`: fragmento por artículo, tipo, uso, material, medida, presentación, color, marca y cantidad solo cuando el cliente los expresó.
3. `retrieve` descarta filtros que no están respaldados por el mensaje y ejecuta la herramienta de lectura del servidor por artículo. `MockCatalog` devuelve hasta tres coincidencias exactas o, si no hay ninguna, hasta dos opciones cercanas de la misma categoría. Una opción cercana conserva su diferencia: no es una sustitución validada ni un SKU elegible. Grok no recibe credenciales ni SQL. La identidad de negocio y sede de demostración está fijada en el servidor.
4. `respond` devuelve la respuesta directa para mensajes generales, o llama a Grok de nuevo con los hallazgos. El modelo propone SKU y una respuesta final. El código verifica que el SKU esté entre los candidatos, que la variante sea distinguible y que las cifras de una respuesta generada coincidan con SQLite. Si no puede verificar esa respuesta, compone una salida factual con la base. Para preguntas sobre atención u horario, comprueba además el texto original antes de entregar una respuesta, incluso si Grok clasificó el mensaje como saludo.

Esto permite probar «¿Están atendiendo?» sin forzar una búsqueda de producto y «Busco tubo PVC de 1/2 y cemento gris de 50 kg» con dos búsquedas. No hay horario cargado: no se afirma apertura o cierre. La lista de productos no es un carrito ni una cotización.

## Datos y barreras

La base `.local/mock_catalog.sqlite3` contiene seis variantes ficticias. `seed.py` no sobrescribe una base existente. `MockCatalog` abre SQLite con `mode=ro` y filtra por negocio y sede de demostración. Este filtro prueba la forma del acceso, pero no constituye autenticación o aislamiento multinegocio listo para producción.

El plan del modelo se valida antes de ejecutar herramientas: solo se admite lectura de catálogo, hasta cinco productos, parámetros tipados y ninguna escritura. Precio, stock y SKU finales se comprueban del lado del servidor. Los campos no expresados no se convierten en filtros; la cantidad aún no se usa para reservar ni cotizar. Horarios reales, pedidos, reservas, pagos, fiados y cambios de inventario no están conectados.

## Visor local de pruebas

`python -m asistendero.visual` sirve `http://127.0.0.1:8765/`. Transmite eventos del mismo grafo usado en terminal: interpretación, ruta, hallazgos, segunda llamada si aplica, verificación y respuesta. La clave API se omite de los eventos; las trazas pueden contener mensajes y datos de prueba y solo se guardan al descargarlas manualmente.

El visor muestra el costo **por ejecución** y por llamada, en USD. Primero usa `usage.cost_in_usd_ticks` si la respuesta de la API lo incluye. Si la pasarela no lo informa, calcula una referencia con tokens de entrada, salida y caché (cuando está disponible) y las [tarifas públicas de xAI](https://docs.x.ai/developers/pricing) consultadas el 17 de octubre de 2026. En ese caso se rotula **estimado**. Si falta el uso o el modelo no tiene tarifa conocida, muestra «No disponible»; nunca interpreta un dato ausente como costo cero. La tarifa o el débito de créditos de `api.reto.pltk.mx` puede ser distinto y sigue por verificar.

## Evaluación

`python -m pytest -q --basetemp=.tmp/pytest` usa planificador y resolutor simulados, sin llamadas pagadas. Comprueba el orden Grok → herramienta, respuesta sobre horario no confirmado, listas de productos, ambigüedad, SKU inventado, hechos de SQLite y alcance del negocio de demostración.

`python -m asistendero.evaluate --live --limit 8` usa Grok real y registra versión del prompt, resultados, tokens y latencia en `.local/`. El corpus incluye medida no disponible y descripción parcial. Las mediciones anteriores en `evaluation/RESULTADO_INICIAL.md` corresponden a `catalog-select-v1`; las verificaciones `agent-first-v1` y `agent-first-v2` preceden al prompt actual. Tres llamadas de demostración con `structured-search-v1` comprobaron una lista exacta, una medida ausente y una descripción parcial; no constituyen una tasa de acierto general.

## Límite siguiente

Para producto real, reemplazar `MockCatalog` por herramientas autorizadas de negocio con identidad, sede y permisos verificados; agregar memoria conversacional, carrito, cotización y acciones idempotentes después de cerrar los contratos correspondientes con la pareja. La secuencia de dos llamadas al modelo es una elección de este prototipo, no un requisito oficial del reto.
