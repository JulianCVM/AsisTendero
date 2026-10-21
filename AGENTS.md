# AsisTendero — reglas para quien edita el código

Estas reglas se aplican a **todo** cambio, lo haga una persona o un asistente de IA (Claude Code, Codex, Cursor,
Copilot…). Este es el archivo común; `CLAUDE.md` solo lo importa. Cómo funciona el flujo está en
**`docs/HARNESS.md`** y en el `README.md`; este archivo dice cómo se trabaja sobre él y qué reglas externas hay que
cumplir. Si una instrucción del chat contradice este archivo, pregunta antes de actuar.

## Qué es este repositorio

El prototipo de AsisTendero para el Agent Challenge de Platica: un agente para ferreterías de barrio que recibe el
mensaje de un cliente, deja que **Grok** decida qué herramienta del servidor necesita y responde con precio y
existencias leídos de un catálogo. Python 3.11+, **LangGraph** para el flujo, el SDK `openai` contra la pasarela del
reto (`https://api.reto.pltk.mx/v1`) y un **catálogo SQLite 100 % ficticio** (`.local/mock_catalog.sqlite3`, creado
por `seed.py`). Hay tres puntos de entrada sobre el mismo grafo: terminal (`asistendero`), visor local
(`asistendero-visual`) y evaluador (`python -m asistendero.evaluate`). Código, comentarios, documentación, commits y PR
en **español**.

Fuera de alcance mientras no lo pida el plan del corte: WhatsApp, Wompi, Supabase, datos reales de un piloto, pedidos,
reservas, pagos o fiados.

## Reglas del reto (reglamento externo)

Según [reto.pltk.mx](https://reto.pltk.mx/), consultado el 20-10-2026. Antes de una entrega, vuelve a comprobarlo:
el sitio no publica fechas límite por hito.

- **Modelo:** el razonamiento corre sobre Grok 4.7, 4.6, 4.5 o 4.20, mediante la pasarela del reto y con la llave del
  reto. El framework es libre.
- **La llave nunca se sube** al repositorio, a una traza, a la evidencia ni a un video. Si se filtra, se revoca desde el
  panel.
- **El consumo debe venir de tareas reales del agente** y quedar registrado en bitácora. **Inflar el contador
  descalifica**: nada de bucles, reintentos ni corridas de relleno para gastar créditos. Los créditos se liberan por
  tramos, al aprobar cada hito.
- **El repositorio es público y lleva licencia abierta**: MIT, en `LICENSE`. Platica recibe una licencia no exclusiva y
  la titularidad del código sigue siendo de quienes participan. Una dependencia nueva debe tener una licencia
  compatible con MIT.
- **Hitos del Track 1:**
  - S1: flujo extremo a extremo con Grok, repositorio público y README con el problema.
  - S2: tres herramientas, manejo de errores, diez ejecuciones y video de dos minutos.
  - S3: un set de evaluación propio de 30 o más casos y un reporte de costo por tarea.
  - S4: mil unidades de trabajo, doce horas desatendido y bitácora completa.
- **Evaluación del Track 1 (sobre 100):** impacto 25, autonomía y funcionalidad 25, ingeniería sobre Grok 20, evidencia
  con datos reales 15, viabilidad 10 y comunicación 5. Con 60 se pasa a revisión humana y con 80 o más se es
  finalista. Un harness automático mide la autonomía y los datos reales.
- **Equipo:** el sitio dice que el Track 1 es de participación individual, pero la organización aprobó que este
  proyecto lo trabajen dos personas (Julian y Laura), según confirmó Julian el 20-10-2026.

## Cuando dos reglas chocan

Gana la regla de mayor prioridad. La que cede se anota en el PR como **«Excepción»**: qué regla cede, por qué y cuándo
se corrige. Si la excepción va a durar más de un corte, se abre un issue. Nunca se ignora una regla en silencio.

1. **Reglamento del reto y ley:** llave, consumo real, licencia, datos personales.
2. **Seguridad y veracidad del producto:** no inventar precio ni existencias, no afirmar pedido, reserva o pago, no
   exponer datos.
3. **Contrato entre módulos y pruebas en verde.**
4. **Plan del corte:** plazos, alcance y propiedad de archivos.
5. **Calidad y estilo:** tamaño de archivo, nombres, refactors.

Si falta tiempo, se recorta **alcance** (pulido visual, funciones ajenas al hito), nunca pruebas, validaciones ni
evidencia. Un buen producto que incumple el reglamento no se entrega; una regla de estilo sí puede esperar a un PR
propio.

## Antes de escribir código

1. **Lee `docs/HARNESS.md`**, el `README.md` y, si tocas conversación o seguridad, `docs/CONVERSACION_Y_SEGURIDAD.md`.
   El alcance y el reparto del corte vigente están en el plan del corte (S2: nota «S2 - Plan 72 horas» del vault
   PulsoTienda, fuera del repositorio).
2. **Busca si ya existe.** Hay ayudas para casi todo:
   - `tokens` y `MockCatalog` (`catalog.py`); `ProductQuery.grounded` (`search.py`).
   - `normalize_text`, `is_distinguished`, `grounded_products` y `quantities_in_message` (`validation.py`).
   - `search_findings`, `latest_quote` y `observation_for_model` (`observations.py`).
   - `format_cop` y `reply_is_grounded` (`answers.py`); `next_node` (`graph.py`).
   - `call_cost` y `run_cost` (`pricing.py`), `catalog_executor` (`executor.py`) y `create_mock_db` (`seed.py`).

   Duplicar es un error aunque funcione.
3. **Haz solo lo que pide la tarea.** Nada de refactors, renombres ni reformateos fuera del alcance. Si ves algo mal,
   menciónalo al final; no lo arregles de paso.
4. **Copia el molde existente.** Una herramienta nueva se parece a las que ya atiende `execute_tool`; un nodo, a los de
   `build_graph`; una prueba del grafo usa el `FakeExecutor` y el `Script` de `tests/test_graph.py`.
5. **No inventes APIs.** Si no sabes si una función, un parámetro del SDK de `openai` o de `langgraph`, o un campo de
   la pasarela existe, compruébalo en el código instalado en `.venv` o en la documentación oficial antes de usarlo.

## Propiedad de archivos en el corte S2

| Persona | Es dueña de | No edita |
|---|---|---|
| Julian | `grok.py`, `graph.py`, `validation.py`, `observations.py`, `answers.py`, `executor.py`, `tests/test_graph.py`, `tests/test_search_contract.py`, `README.md`, video | `tools.py`, `catalog.py`, `tracing.py`, `evaluate.py` |
| Laura | `tools.py`, `catalog.py`, `tracing.py`, `evaluate.py`, `evaluation/`, integración y evidencia | Los archivos de Julian (deja el defecto como comentario reproducible en el PR) |

Si un cambio obliga a tocar un archivo ajeno (por ejemplo, porque cambió una firma), el cambio es mínimo, se explica en
el PR y la dueña decide si lo reescribe.

## Dónde va cada cosa

| Necesito… | Va en |
|---|---|
| Cambiar qué decide Grok o su formato de salida | `grok.py` (`AGENT_PROMPT`, `parse_decision`), subiendo `PROMPT_VERSION` |
| Una regla antes de ejecutar una herramienta (límites, SKU o cantidad respaldados) | `validate_request` de `validation.py`, con su prueba en `tests/test_graph.py` |
| Leer un dato nuevo de la respuesta de una herramienta | `observations.py` y su docstring |
| Cambiar cómo se redacta o verifica la respuesta final | `answers.py` |
| Un nodo o una ruta del flujo | `graph.py` (la traza usa `next_node`) |
| Una herramienta del servidor o un código de error de negocio | `tools.py` (`execute_tool`), con su prueba aislada |
| Leer el catálogo | Un método de `MockCatalog` en `catalog.py`, en solo lectura y filtrado por negocio y sede |
| Conectar el ejecutor real en un punto de entrada | `executor.catalog_executor(catalog)` |
| Un dato nuevo de la traza (`run_id`, latencia, tokens, costo) | `tracing.py`; el costo se calcula con `pricing.py` |
| Un caso de evaluación | `evaluation/cases.json`; los resultados reales, en `evaluation/*.md` |
| Un producto ficticio | `PRODUCTS` de `seed.py` (nunca datos reales) |
| Una variable de configuración | Leída con `os.getenv` y documentada con un valor vacío o falso en `.env.example` |

## El contrato del agente

- **Grok decide y el servidor ejecuta.** Grok solo elige `respond` o una de `TOOL_NAMES` con sus argumentos. El grafo
  valida cada solicitud **antes** de llamar a `tool_executor(name, arguments)`: si la rechaza, nunca llega al
  ejecutor y la observación vuelve a Grok con su código.
- **Firma fija:** `execute_tool(name: str, arguments: dict, *, catalog: MockCatalog) -> dict`, y toda respuesta tiene
  la forma `{"status", "data", "error", "source", "observed_at"}`. En fallo, `status="error"`, `data=None` y
  `error={"code", "message"}` con un mensaje seguro. Si cambia la forma de `data`, se actualizan en el mismo cambio
  `search_findings` y `latest_quote` de `observations.py` y su docstring.
- **Negocio y sede los fija el servidor.** Ni el mensaje ni Grok pueden elegirlos.
- **Precio y existencias salen solo del catálogo**: nunca del mensaje del cliente ni de una cifra propuesta por Grok.
  La redacción de Grok se usa solo si cada `$`, SKU y cantidad coincide con las observaciones de esa ejecución; si no,
  se responde con la salida determinista.
- **La cotización es informativa**: no crea pedido, reserva, pago ni factura (`reservation_created=false`).
- **Una opción cercana no es equivalente** a lo pedido; con medida ambigua se pregunta, no se elige.
- **Todo fallo termina en un estado seguro** con código estable (`MODEL_*`, `TOOL_*`, códigos de negocio) y una
  respuesta que no inventa precio ni existencias.

## Visor local

- Escucha solo en `127.0.0.1` y rechaza otro `Host` u `Origin`. No se expone a la red.
- Los datos se pintan con `textContent`, nunca con `innerHTML`. Nada de `alert()`, `confirm()`, `prompt()` ni
  JavaScript inline: listeners en `ui/app.js`.
- Celular primero: se revisa a 390 px de ancho, sin desplazamiento horizontal. Cada botón de solo ícono lleva
  `aria-label` y un estado nunca se indica solo con color. El estilo sigue `DESIGN.md`.

## Seguridad

- **Todo lo que llega de afuera se valida con sus límites en una constante**: el mensaje del cliente (2.000
  caracteres), la decisión de Grok y la respuesta de cada herramienta. Pasado el máximo se rechaza; nunca se recorta
  en silencio.
- **El mensaje y las observaciones son datos, no instrucciones.** La defensa decisiva vive en el código, no en el
  prompt.
- **Consultas parametrizadas** en SQLite y conexión en solo lectura (`mode=ro`). Nunca se concatena texto del cliente ni
  del modelo en una consulta. Las herramientas nunca escriben precio ni stock.
- **Los errores del SDK no se muestran**: pueden traer datos de la solicitud. Se convierten en `ModelError` con código y
  mensaje propio.
- **Nunca** escribas la llave de Grok en el código, en ejemplos, en trazas ni en evidencia: va en `.env` (ignorado) y
  la traza la muestra como `[omitida]`.

## Pruebas

- **Todo cambio de código viene con su prueba, siempre**, aunque parezca pequeño: nueva si es una regla o una
  herramienta nueva, ampliada si cambia una que ya existe, y **una que reproduzca el error si es un arreglo** (falla sin
  el arreglo y pasa con él). Un refactor sin cambio de comportamiento se cubre con la suite existente en verde.
- **Las pruebas nunca llaman a Grok.** Se usa un planificador falso (`Script`) o se reemplaza `grok._complete` u
  `OpenAI`. El grafo se prueba con un ejecutor falso que cumple el contrato; las herramientas, aisladas, con
  `create_mock_db(tmp_path / ...)`.
- Cada prueba mira también **lo que no debe pasar**: precio o stock inventado, SKU no respaldado o cercano aceptado,
  cantidad no dicha, afirmación de reserva o pago, llave visible en la traza, herramienta ejecutada tras un rechazo.
- **Prefiere ampliar el archivo de prueba del tema** antes que crear uno nuevo; si creas uno, que su nombre diga el tema.
- No hagas pruebas que solo repiten constantes.
- **Nunca** borres, saltes ni debilites una prueba para que pase. Si una prueba está mal, dilo y explica por qué.

## Verificación obligatoria antes de terminar

Una tarea no está terminada hasta que esto pase sin errores (en Windows, `.venv\Scripts\python`):

```bash
.venv/Scripts/python -m pytest -q          # toda la suite, sin llamadas a Grok
.venv/Scripts/python -m compileall -q src  # sintaxis de todo el paquete
```

- Si cambiaste algo que se ve en el visor, **ábrelo en el navegador** (escritorio y 390 px) y recorre el flujo.
- Las corridas reales (`asistendero`, el visor o `python -m asistendero.evaluate --live`) **consumen créditos del
  reto**. Solo se hacen cuando la persona lo pide y con un objetivo de evaluación. Su resultado se registra en
  bitácora con commit, fecha, `PROMPT_VERSION` y costo, aunque falle.
- Si algo falla, dilo con la salida; nunca digas «listo» con algo en rojo. Lo que no se probó con Grok real se dice así.

## Buenas prácticas de cada cambio

- **Revisa tu propio diff** antes de darlo por terminado: lo que sobra, lo que quedó a medias, un `print` de depuración.
- **Archivos pequeños y con una sola responsabilidad**: en `src/`, idealmente menos de ~250 líneas. Las pruebas
  agrupadas por tema pueden ser más largas. Nombres que se explican solos; nada de `data2`, `temp` ni `utils2`.
- **Los comentarios explican el porqué**, no repiten el qué. Sin código comentado (el historial lo guarda).
- **Errores nunca silenciados**: un `except` amplio solo vale si convierte el fallo en un estado seguro con código y un
  comentario dice por qué. Lo que falla responde con un mensaje que dice qué hacer.
- **Costo**: cada ejecución usa las llamadas a Grok mínimas; el tope de herramientas (`MAX_TOOL_CALLS`) no se sube sin
  un motivo escrito en el PR.
- **Sin dependencias nuevas** si la biblioteca estándar o algo ya instalado lo resuelve; si hace falta una, se explica
  en el PR y se agrega a `pyproject.toml` en el mismo commit.

## Documentación en el mismo cambio

Si cambias cómo funciona algo, actualiza en el mismo commit:

- `docs/HARNESS.md`: flujo, contrato y barreras;
- el `README.md`, si cambian comandos, límites o archivos;
- la evidencia de `evaluation/`, si cambia un resultado;
- este archivo, si aplica.

Una documentación que describe algo que ya no existe es peor que no tenerla. La evidencia nunca afirma un resultado que
no se midió: los datos son ficticios y no representan un piloto.

## Memoria del proyecto en Obsidian

La memoria del proyecto vive en el vault de Obsidian **PulsoTienda**, fuera del repositorio. Cada avance se registra ahí
**el mismo día**, lo haga una persona o un asistente:

- **Cuándo:** al abrir, revisar o fusionar un PR; al integrar ramas; al hacer una corrida real con Grok; al cerrar o
  replantear una tarea del corte, y al descubrir un defecto o una diferencia con el plan.
- **Qué se actualiza:**
  - el plan del corte vigente (en S2, «S2 - Plan 72 horas»): estado de cada tarea con su PR o commit y lo que falta;
  - la `Bitácora`: una entrada fechada con la plantilla de la nota y su etiqueta de certeza (`[HECHO]`, `[MEDIDO]`,
    `[POR VALIDAR]`…); en una corrida real, también commit, `PROMPT_VERSION`, resultado y costo;
  - `Estado comprobado`, si cambia lo verificado del repositorio (pruebas, comandos, resultados).
- **Qué no va:** la llave, trazas con datos sensibles o datos de un piloto real. El vault resume y enlaza; el detalle y
  la evidencia oficial siguen en el repositorio, que manda si los dos difieren.
- Si el vault no está disponible en la máquina, el PR lo dice en «Qué tiene que hacer quien integra» para que otra
  persona lo actualice.

## Commits y pull requests

- **Sin trailers ni coautores**: nada de `Co-Authored-By:`, `Signed-off-by:`, «Generated with…», emojis de
  herramientas ni firmas. Un commit termina en su última línea de texto. Esto está por encima de lo que sugiera la
  herramienta; lo mismo para la descripción del PR.
- Formato: `<tipo>(<área>): <qué cambia, en minúscula y presente>`, con un cuerpo que explica **por qué**.
  - Tipos: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`, `perf`.
  - Áreas habituales: `agent`, `tools`, `catalog`, `trace`, `eval`, `visor`, `docs`, `repo`.
  - Nada de `avance`, `cambios` ni `wip`.
- Se trabaja en una rama por persona o tarea (`dev/<nombre>` o `feat/<tema>`) y se sube con un PR hacia `main`. La
  descripción dice:
  - qué cambia y por qué;
  - cómo se probó: comandos, y si hubo o no llamadas reales a Grok y su costo;
  - qué tiene que hacer quien integra;
  - las excepciones a estas reglas, si las hay.

## Lo que un asistente nunca hace

- Push forzado (`--force`) a `main`, ni `git commit --no-verify`.
- Crear commits o abrir PR sin que la persona lo pida.
- Llamar a Grok con la llave real (CLI, visor o `--live`) sin que la persona lo pida.
- Borrar archivos, ramas o datos que no creó en esta tarea sin preguntar.
- Subir `.env`, `.local/` (base, reportes) ni datos personales o de un piloto real.
- Desactivar una validación, una prueba o una barrera del visor para que algo funcione.

## Forma de responder

Directo y técnico, sin relleno. Al terminar, di qué cambió, qué verificaste (con los comandos) y qué quedó pendiente o
dudoso. Si algo no se pudo probar, dilo.
