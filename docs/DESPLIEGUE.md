# Despliegue: contenedor y modo desatendido (plan)

**Estado:** el contenedor sigue siendo un plan. El **modo desatendido ya existe** (07-11-2026): `evaluacion/desatendido.py`, con la cola de `carga_carluz.py` y la bitácora de `bitacora_carga.py`; ver «Modo desatendido» abajo. Lo pidió Julian el 07-11-2026
para ir diseñando el despliegue con el inventario real de Ferretería Carluz y para el hito S4 (mil unidades de trabajo,
doce horas desatendido y bitácora completa).

## Lo que se midió antes de decidir

Con el inventario real (2.032 productos), en esta máquina y sin Grok:

| Medida | Antes de optimizar | Después |
|---|---|---|
| Búsqueda, mediana | 56,1 ms | 7,1 ms |
| Búsqueda, p95 | 72,8 ms | 24,2 ms |
| Observación de `explorar_categoria`, Plomería | 30.011 caracteres | 2.626 caracteres |
| Observación de `explorar_categoria`, Pinturas | 18.426 caracteres | 2.628 caracteres |
| Observación de `buscar_productos` | 1.125 caracteres | Igual: no depende del tamaño del catálogo |
| Base SQLite | — | 668 KB |
| Importar el Excel | — | Menos de 1 s |
| Lista completa del panel (`/api/inventario`) | — | 717 KB, 45 ms por HTTP local |

El peso del catálogo real nunca estuvo en SQLite: estaba en la lista de categorías que iba a Grok y en la búsqueda, que
volvía a separar palabras en cada consulta. La lista del panel solo se pide al abrir Inventario o al filtrar; el
refresco de 15 s no la toca (`LIVE` de `tendero.js`).

## Decisión: un solo contenedor, con SQLite en un volumen

**Un contenedor de base de datos aparte no se justifica ahora.** Son unos 2.000 productos, una sede y un solo proceso
que escribe; SQLite lo atiende en milisegundos y ya usa transacciones `BEGIN IMMEDIATE` para que dos clientes no aparten
la última unidad. Una base aparte agregaría red, credenciales y otra cosa que vigilar, sin un problema que resolver.
Se revisa si llegan varias sedes o varios procesos escribiendo a la vez.

```text
┌──────────────── contenedor asistendero ─────────────────┐
│  evaluador o modo desatendido  →  grafo  →  herramientas │──► pasarela del reto (Grok)
│                                              │           │
└──────────────────────────────────────────────┼───────────┘
                                   volumen /app/.local
                         tienda.sqlite3 · sesiones · bitácora
```

### Qué cambia respecto al `Dockerfile` actual

- Hoy corre `python -m asistendero.datos`, que **siembra el catálogo ficticio dentro de la imagen**. Para la tienda real
  no debe haber datos en la imagen: la base entra por el volumen.
- `.dockerignore` ya excluye `.env` y `.local`, y `*.xlsx` queda fuera de git. `*.xlsx` y `*.xls` también quedan
  fuera de la imagen por `.dockerignore`, para que un Excel suelto en la carpeta no termine en ella.
- La llave entra por variable de entorno al arrancar (`--env-file`), nunca en la imagen.
- Usuario sin privilegios, y `mem_limit`: la corrida 44 se cortó a los 207 casos porque la máquina se quedó sin memoria.
  Con un límite y `restart: on-failure`, ese fallo queda acotado y el proceso continúa donde iba.

### Lo que el contenedor no expone todavía

El panel y el visor **solo escuchan en `127.0.0.1` y rechazan otro `Host`** (`AGENTS.md`), y no tienen usuarios ni
permisos. Publicar sus puertos dejaría el inventario y los chats abiertos. Por eso el primer uso del contenedor es el
evaluador y el modo desatendido, **sin puertos publicados**. Abrir el panel al tendero exige antes autenticación y
HTTPS; esa decisión es de Julian y es un cambio aparte.

## Modo desatendido para S4

Antes solo existía el evaluador, cuya ventana continua más larga en los reportes locales fue de 1,26 h (el jurado midió 2,6 h en la pasarela). El comando nuevo:

```powershell
.\.venv\Scripts\python.exe -m asistendero.evaluacion.desatendido preparar --tareas 1300
.\.venv\Scripts\python.exe -m asistendero.evaluacion.desatendido correr --horas 12.25 --budget-usd 25 --supervisar
.\.venv\Scripts\python.exe -m asistendero.evaluacion.desatendido resumen
```

La bitácora queda en `evaluation/s4_carga/`: `bitacora.jsonl` (fuente, una línea por tarea y por evento), `bitacora.csv`, `RESUMEN.md`, `cola.json` y `estado.json`. Cumple con esto:

1. **Reanudable:** lo hecho se lee de la bitácora; si el proceso se cae, `--supervisar` lo relanza y sigue sin repetir
   ni reintentar tareas. El equipo no se suspende mientras corre (`SetThreadExecutionState`).
2. **Bitácora JSONL por unidad**: hora, commit, `PROMPT_VERSION`, modelo, tokens, costo, estado final y error. Sin
   llave ni datos personales (`redact_personal_data`).
3. **Tope de gasto obligatorio**: al llegarle, para y lo deja escrito; igual que `--budget-usd`.
4. **Ritmo fijo**: mil unidades en doce horas son una cada 43 s, muy por debajo del límite de la pasarela. Un fallo del
   modelo espera y se registra; **no se reintenta en bucle**.
5. **Reporte al cerrar**: unidades hechas y fallidas, horas continuas, costo total y por unidad.

### Qué cuenta como unidad de trabajo

La organización la definió el 07-11-2026: una tarea completa resuelta de punta a punta, no una llamada suelta a Grok. Aquí cada unidad es una consulta o una conversación corta de cliente sobre el inventario real, todas distintas (precio, cotización, familia con varias medidas, conversación con pedido para recoger, producto que no se maneja, información de la tienda, categoría, errores de escritura e intentos de inyección).

### Nota previa

El reglamento castiga inflar el consumo, y repetir 345 casos tres veces para llegar a mil puede leerse así. La propuesta
es que cada unidad sea una tarea distinta sobre el inventario real: una consulta de cliente por producto o por familia,
generada del catálogo, con su respuesta verificada por el servidor. **Conviene confirmar con la organización qué acepta
como unidad antes de gastar.**

### Presupuesto

Al costo medido en la corrida 48 (0,002803 USD por tarea), 1.300 unidades cuestan unos 3,6 USD. El 07-11-2026 Julian
destinó a esta corrida el saldo de la llave (60 USD); el tope de `--budget-usd` (25 USD) corta mucho antes de gastarlo
si el costo real sobre el catálogo de Carluz resulta mayor que el medido.

## Orden

1. [Hecho] Permiso del tendero (confirmado por Julian el 07-11-2026) y datos de la tienda.
2. [Hecho] Cola, bitácora, ritmo, reanudación y tope del modo desatendido, con pruebas y sin Grok.
3. Corrida real corta de `cases_carluz.json` y luego la de doce horas, desde el commit de esta rama.
4. Imagen sin datos, con volumen, y una corrida corta dentro del contenedor (pendiente).
