# Evidencia del flujo de Semana 1

**Fecha:** 15 de octubre de 2026 (Colombia). **Estado:** flujo textual de extremo a extremo verificado con Grok; alcance limitado al prototipo de terminal.

## Ejecución real

**Entrada:**

```text
Necesito un tubo PVC para agua, ¿me puedes ayudar?
```

**Comando:**

```powershell
.\.venv\Scripts\python.exe -m asistendero 'Necesito un tubo PVC para agua, ¿me puedes ayudar?'
```

**Configuración no secreta:** `GROK_BASE_URL=https://api.reto.pltk.mx/v1`; `GROK_MODEL=grok-4.7`. La clave se leyó de `.env`, archivo ignorado por Git, y no se publica.

**Respuesta observada:**

```text
Claro. Para orientarte con el tubo PVC para agua, ¿qué diámetro y longitud necesitas?
```

**Resultado del proceso:** código de salida `0`. La respuesta se obtuvo mediante el nodo `consultar_grok` del grafo LangGraph y una llamada a la pasarela del reto. La prueba automatizada local terminó con `2 passed`.

Esta prueba demuestra entrada textual → LangGraph → Grok → salida textual. No demuestra aún consulta de catálogo, disponibilidad real, pedido, pago, WhatsApp, persistencia ni funcionamiento del contenedor Docker.
