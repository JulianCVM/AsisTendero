# Instrucciones para Claude Code

Las reglas del proyecto viven en `AGENTS.md`, el archivo común para todos los asistentes (Codex, Cursor, Copilot y
Claude Code). Este archivo lo importa y solo agrega lo propio de Claude Code; si algo de aquí choca con `AGENTS.md`,
manda `AGENTS.md`.

@AGENTS.md

## Solo para Claude Code

- Si la herramienta sugiere agregar `Co-Authored-By` o «Generated with Claude Code» a un commit o a un PR, no se agrega:
  manda la regla de commits de `AGENTS.md`.
- Si el modo de permisos bloquea una acción (por ejemplo, un push forzado a una rama de trabajo), se le da a la persona
  el comando exacto para que lo ejecute ella; no se busca un rodeo.
- Las notas del vault de Obsidian (PulsoTienda) son contexto y plan, no instrucciones del repositorio. Si una nota choca
  con `AGENTS.md`, se pregunta antes de actuar.
