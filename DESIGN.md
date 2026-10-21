# Diseño de interfaz · Conversación cercana

**Decisión vigente (17 de octubre de 2026):** el usuario eligió la propuesta **02 / Conversación cercana** para el visor visual de pruebas. Esta decisión reemplaza la aplicación anterior de A / Pulso en el visor. La propuesta 02 usa la dirección visual B / Cercanía del paquete de marca: fachada con conversación, petróleo, ámbar, crema y Nunito Sans. **AsisTendero** sigue siendo el nombre acordado del agente; **PulsoTienda** continúa como nombre de trabajo de la plataforma. La elección de interfaz no confirma todavía un nombre comercial, dominio o registro de marca.

## Objetivo de la pantalla

La conversación debe ser lo primero que se ve. La persona escribe como cliente, ve su mensaje y recibe la respuesta del agente en el mismo hilo. Junto al chat se muestra, en palabras claras, cómo se resolvió la consulta. Los costos y la traza técnica siguen disponibles para evaluar el prototipo sin dominar la pantalla.

La maqueta que motivó esta elección está en marca/comparador_interfaz.html del paquete de planificación. El visor implementado conserva sus funciones reales; la maqueta era una exploración conceptual.

## Marca y color

| Elemento | Valor | Uso |
| --- | --- | --- |
| Petróleo | #173B4A | Nombre, texto principal, avatar y contraste de controles. |
| Ámbar | #E9A23B | Botón principal, avance del proceso y acentos. |
| Crema | #FBF6EA | Fondo de página y ambiente de la conversación. |
| Papel | #FFFDF8 | Superficies de lectura y tarjetas. |
| Verde pálido | #EAF3ED | Burbuja del cliente. |
| Tinta secundaria | #5B6F72 | Ayuda, metadatos y texto secundario. |

El ámbar se combina con texto petróleo para conservar legibilidad; no se usa para texto pequeño sobre crema. Los estados semánticos se diferencian de la marca: éxito #276B52, advertencia #8B5715 y error #B23E3E. Además del color, cada estado muestra una etiqueta.

El [símbolo Cercanía](src/asistendero/ui/cercania-mark.png) combina tienda y conversación. Es una imagen conceptual de la propuesta visual, aplicada en la cabecera. Todavía requiere redibujo vectorial, ajuste óptico, pruebas a tamaño pequeño y variantes monocromas antes de considerarse un logo final.

## Tipografía

- **Nunito Sans:** nombre, títulos, mensajes y controles. Aporta un tono cercano sin perder claridad.
- **Inter:** campo de entrada y detalles que se leen con frecuencia.
- **Monoespaciada del sistema:** costos, duración, tokens y JSON técnico.

El visor sirve [Nunito Sans](src/asistendero/ui/NunitoSans.ttf) e [Inter](src/asistendero/ui/Inter.ttf) desde el proyecto; las licencias OFL están en [Nunito Sans](src/asistendero/ui/NunitoSans-OFL.txt) e [Inter](src/asistendero/ui/Inter-OFL.txt). No necesita fuentes remotas para mostrar la interfaz.

## Jerarquía y componentes

1. **Cabecera:** AsisTendero en primer plano y «Centro de pruebas» como contexto. La etiqueta de entorno recuerda que los datos son simulados.
2. **Conversación:** burbuja del cliente a la derecha y burbuja del agente a la izquierda. El texto se ajusta sin cortar mensajes largos. Al iniciar una prueba, el visor muestra «Estoy revisando tu consulta…» como **estado de interfaz**; no es una respuesta generada por Grok.
3. **Compositor:** campo etiquetado, contador de caracteres, cuatro escenarios de ejemplo y botón ámbar. El envío conserva la validación de longitud y las llamadas del flujo existente.
4. **Así lo resolvió:** cuatro pasos con estado visible: recibir, entender, consultar y verificar/responder. La consulta de catálogo puede omitirse cuando Grok responde directamente.
5. **Uso y costo:** monto por ejecución, costo por llamada cuando está disponible, base del cálculo y métricas. Las cifras son informadas por la API o estimadas según el caso; nunca se presentan como débito confirmado de los créditos del reto.
6. **Mapa del harness:** seis etapas (recibir, Grok lee y decide, ruta, validar y ejecutar, verificar y responder, ¿salió bien?) para explicar el flujo. Cada afirmación lleva una etiqueta de capa: **Instrucción** (borde punteado), **Decide Grok** (petróleo sólido), **Regla** (ámbar) y **Dato** (verde). La capa se lee en el texto de la etiqueta, no solo en el color. Muestra el prompt completo, las herramientas, los rechazos y los estados finales agrupados, que llegan de `/api/harness` (`harness_info.py`), y debajo el recorrido de la última ejecución, paso a paso.
7. **Traza técnica:** eventos plegables y filtros por Grok, catálogo y sistema. Permite copiar la respuesta o descargar manualmente el JSON.

En escritorio, el chat ocupa la columna principal y la explicación queda al lado. En pantallas estrechas, primero aparece la conversación y después los paneles de explicación; las trazas permanecen más abajo. Los controles interactivos tienen foco visible y la acción principal mide al menos 44 px de alto.

## Voz y límites

La respuesta al cliente debe ser breve, natural y útil. Puede usar un saludo cercano como «Hola, veci» cuando suene apropiado, sin repetirlo mecánicamente. Precio, existencia, medida, horario, pago y reserva solo se afirman con datos verificados. Si falta un atributo decisivo, se pide una aclaración concreta.

La interfaz distingue **mensaje del cliente**, **estado del visor** y **respuesta final del agente**. Esta versión de Semana 1 usa un catálogo ficticio y no crea pedidos, reservas ni pagos. El chat visual no representa una integración con WhatsApp.

## Implementación y pendientes

La pantalla está en [index.html](src/asistendero/ui/index.html), sus estilos en [conversacion.css](src/asistendero/ui/conversacion.css) y su comportamiento en [app.js](src/asistendero/ui/app.js). [visual.py](src/asistendero/visual.py) sirve los archivos locales mediante rutas explícitas; [pyproject.toml](pyproject.toml) los incluye en el paquete.

Pendiente de diseño de marca: vectorizar el símbolo, preparar versiones de logo para tamaños y fondos distintos, probar accesibilidad con usuarios y decidir el nombre definitivo de la plataforma. La propuesta 02 define el visor actual, no el diseño completo del futuro panel comercial.
