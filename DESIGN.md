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

1. **Cabecera fija y portada:** AsisTendero en primer plano, «Centro de pruebas» como contexto y tres enlaces a las secciones (Conversar, Cómo funciona, Traza), que a 760 px se ocultan. La etiqueta de entorno recuerda que los datos son simulados. Debajo, una portada en petróleo con el propósito del visor y las tres reglas del agente (Grok decide, el servidor valida, el catálogo manda). Cada sección lleva un encabezado numerado (01, 02, 03).
2. **Conversación:** burbuja del cliente a la derecha y burbuja del agente a la izquierda. El texto se ajusta sin cortar mensajes largos. Al iniciar una prueba, el visor muestra «Estoy revisando tu consulta…» con tres puntos animados (quietos con movimiento reducido) como **estado de interfaz**; no es una respuesta generada por Grok. El hilo tiene su propia caja con desplazamiento (`#chat-scroll`, `overscroll-behavior: contain`): leer mensajes anteriores no mueve la página. Un mensaje nuevo baja al final solo si quien lee ya estaba ahí; si subió, aparece «↓ Ir al último mensaje». El cuadro de mensaje crece con el texto hasta 180 px y el botón Enviar va a su lado. Con teclado, **Enter envía** y **Shift + Enter** hace un salto de línea; Enter no envía mientras se compone una palabra (acentos, teclado predictivo). En pantallas táctiles Enter es salto de línea y se envía con el botón, como en las apps de chat. Al enviar, el cuadro queda vacío para el siguiente mensaje; si el visor no responde, el mensaje vuelve al cuadro para reenviarlo.
3. **Compositor:** campo etiquetado, contador de caracteres, escenarios de ejemplo en píldoras (incluido «Surtido») y botón ámbar. El envío conserva la validación de longitud y las llamadas del flujo existente.
4. **Así lo resolvió:** cuatro pasos con estado visible: recibir, entender, consultar y verificar/responder. La consulta de catálogo puede omitirse cuando Grok responde directamente.
5. **Uso y costo:** monto por ejecución, costo por llamada cuando está disponible, base del cálculo y métricas. Las cifras son informadas por la API o estimadas según el caso; nunca se presentan como débito confirmado de los créditos del reto.
6. **Castillo del harness:** una figura isométrica hecha con el kit de anatomy (MIT, `tools/castillo/vendor`) en la que cada edificio es una pieza del flujo: puerta con rastrillo (`validate`), torre de Grok con linterna (`interpret`), cruce con señal (`next_node`), aduana con talanquera (`validate_request`), bodega con cajas (`tools.py`), balanza (`reply_is_grounded`) y mostrador con bandera de estado. Un cubo ámbar, el mensaje, recorre el camino. Sin prueba en curso repite cuatro recorridos de ejemplo (cotización, inyección, SKU rechazado, aviso del servidor), que también se eligen con botones; durante una prueba repite el recorrido real a partir de los eventos del visor. Una franja de texto narra cada paso y la leyenda numerada marca la estación actual con `aria-current`, de modo que el estado nunca depende solo del color. Se detiene fuera de pantalla y con movimiento reducido no anima: espera a que se elija un recorrido y salta de paso en paso. La figura se regenera con `node tools/castillo/build.mjs`, que escribe el SVG entre los marcadores `castillo:inicio` y `castillo:fin` de `index.html` y el archivo `ui/iso.css`; los tonos de la paleta están en `ui/castillo.css` y el movimiento en `ui/castillo.js`.
7. **Mapa del harness:** debajo del castillo, seis etapas (recibir, Grok lee y decide, ruta, validar y ejecutar, verificar y responder, ¿salió bien?) para explicar el flujo. Cada afirmación lleva una etiqueta de capa: **Instrucción** (borde punteado), **Decide Grok** (petróleo sólido), **Regla** (ámbar) y **Dato** (verde). La capa se lee en el texto de la etiqueta, no solo en el color. Muestra el prompt completo, las herramientas, los rechazos y los estados finales agrupados, que llegan de `/api/harness` (`harness_info.py`), y debajo el recorrido de la última ejecución, paso a paso.
8. **Traza técnica:** eventos plegables y filtros por Grok, catálogo y sistema. Permite copiar la respuesta o descargar manualmente el JSON.

En escritorio, el chat ocupa la columna principal y la explicación queda al lado. En pantallas estrechas, primero aparece la conversación y después los paneles de explicación; las trazas permanecen más abajo. Los controles interactivos tienen foco visible y la acción principal mide al menos 44 px de alto.

## Voz y límites

La respuesta al cliente debe ser breve, natural y útil. Puede usar un saludo cercano como «Hola, veci» cuando suene apropiado, sin repetirlo mecánicamente. Precio, existencia, medida, horario, pago y reserva solo se afirman con datos verificados. Si falta un atributo decisivo, se pide una aclaración concreta.

La interfaz distingue **mensaje del cliente**, **estado del visor**, **respuesta final del agente** y **aviso automático** (borde punteado, ícono «!» y la etiqueta «aviso automático», no solo color). El catálogo es ficticio; desde S4 el chat registra pedidos para recoger, pero no pagos. El chat visual no representa una integración con WhatsApp.

## Implementación y pendientes

La pantalla está en [index.html](src/asistendero/ui/index.html), sus estilos en [conversacion.css](src/asistendero/ui/conversacion.css) y su comportamiento en [app.js](src/asistendero/ui/app.js), [harness.js](src/asistendero/ui/harness.js) y [castillo.js](src/asistendero/ui/castillo.js). [visual.py](src/asistendero/visual.py) sirve los archivos locales mediante rutas explícitas; [pyproject.toml](pyproject.toml) los incluye en el paquete.

El **panel del tendero** ([tendero.html](src/asistendero/ui/tendero.html), [tendero.css](src/asistendero/ui/tendero.css) con los tokens, la base y los componentes, [tendero-views.css](src/asistendero/ui/tendero-views.css) con cada sección, y un módulo JS por sección: `tendero.js` enruta, `tendero-core.js` tiene las piezas comunes y `tendero-theme.js` aplica el tema antes de pintar) usa la misma paleta y tipografía. Se rediseñó el 24-10-2026 y se amplió el 26-10-2026 con los mismos principios: simplicidad operativa, claridad de la información y eficiencia en las tareas de todos los días.

- **Navegación:** Hoy, Pedidos, Ventas, Inventario, Catálogo, Asistente de bodega y Chats, con ícono, texto y un contador cuando algo espera (pedidos por atender, pagos por verificar, agotados, chats que piden al tendero o bloqueados). En el celular es una barra inferior con cinco destinos (Hoy, Pedidos, Inventario, Chats y «Más», que abre Ventas, Catálogo y el asistente); desde 1024 px, una columna petróleo a la izquierda agrupada en «El día», «La bodega» y «Clientes», con la marca y la etiqueta «Datos simulados». La sección actual lleva `aria-current`, una barra ámbar y el texto en blanco, no solo color.
- **Tema oscuro:** los colores son tokens en `:root`; el tema oscuro los redefine con `prefers-color-scheme` y con `data-theme="dark"`. El botón de la barra superior rota entre «igual al equipo», claro y oscuro, y se guarda en el navegador. El petróleo de la marca se aclara en oscuro para conservar contraste; el ámbar sigue llevando texto petróleo.
- **Hoy primero:** indicadores que llevan a su lista filtrada; **Revisa esto** junta lo que necesita al tendero con su enlace; la cola **Atiende ahora** pone las acciones del mostrador en la primera pantalla; **La plata de hoy** separa vendido, cobrado, por verificar y por cobrar.
- **Tarjeta de pedido:** código y estado (ícono + texto), total, la franja de lo urgente, motivos para revisar (ícono «!» y texto), líneas con miniatura, el pago con su método y estado (píldora con texto) y los botones Entregar, Registrar pago y Cancelar (segundo toque).
- **Inventario en tarjetas:** imagen generada, nombre, variante y SKU, precio por unidad, disponibilidad (Agotado, Pocas · 3, o el número) y una franja con la bodega, lo apartado y lo que viene en camino. Funciona igual en el celular y en el computador: no hay tabla que desplazar. El editor es una hoja (`<dialog>`, abajo en el celular y centrada desde 640 px).
- **Propuestas antes de cambios:** una llegada de mercancía y el asistente de bodega muestran primero lo que va a cambiar (antes → después, pendientes, adicionales) y solo escriben al confirmar. Lo que no se aplicará se marca con borde punteado y la etiqueta «No se aplicará», no solo con color.
- **Chats:** lista y detalle lado a lado desde 900 px; en el celular el detalle reemplaza la lista y tiene botón para volver. Burbujas distintas para el cliente, el asistente y el tendero, cada una con su etiqueta escrita.
- **Imágenes de producto:** pictogramas generados por familia (`product_art.py`) con el fondo del color de su categoría; no son fotos ni llevan marcas, y no se anuncian al lector de pantalla (`alt=""`): el nombre está al lado.
- **Página pública** (`/inicio`, [inicio.html](src/asistendero/ui/inicio.html) e [inicio.css](src/asistendero/ui/inicio.css)): qué hace AsisTendero, cómo funciona y lo que todavía no hace, con un ejemplo de conversación marcado como ilustrativo.
- **Avisos:** cada acción responde con un aviso flotante (`role="status"`); los errores duran más y usan otro ícono además del color. No hay `alert()`, `confirm()` ni `prompt()`.
- **Movimiento:** transiciones cortas al cambiar de sección y al abrir una hoja; con movimiento reducido no hay animaciones.

Pendiente de diseño de marca: vectorizar el símbolo, preparar versiones de logo para tamaños y fondos distintos, probar accesibilidad con usuarios y decidir el nombre definitivo de la plataforma. La propuesta 02 define el visor actual, no el diseño completo del futuro panel comercial.
