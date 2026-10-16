# Primera evaluación sintética

**Fecha:** 15 de octubre de 2026 (Colombia). **Rama:** `codex/harness-tests`. **Modelo:** `grok-4.20-0309-non-reasoning` mediante la pasarela del reto. **Prompt:** `catalog-select-v1`.

Se ejecutó `python -m asistendero.evaluate --live --limit 4` con el SQLite ficticio creado por `seed.py`. El resultado fue **4/4 casos esperados**, con tres llamadas a Grok y una respuesta sin llamada al no encontrar candidatos. La pasarela informó **1.309 tokens de entrada y 29 de salida** entre las tres llamadas. El reporte detallado queda en `.local/`, fuera de Git.

| Caso | Esperado | Observado |
| --- | --- | --- |
| PVC 1/2 explícito | Variante `PVC-050` | SKU correcto; precio y stock salieron del SQLite simulado. |
| PVC sin medida | Aclaración | Preguntó por medida sin elegir variante ni mostrar precio. |
| Tornillo agotado | Variante `TOR-025-2` | SKU correcto; informó agotamiento simulado. |
| Taladro ausente | Sin coincidencia | Reconoció que no está en el catálogo; no llamó a Grok. |

Las pruebas locales adicionales comprobaron que una selección inventada no se convierte en precio o stock y que modificar una fila ficticia cambia la respuesta sin modificar el prompt. **Alcance de esta medición:** cuatro consultas sintéticas; no permite afirmar exactitud general, ahorro real, funcionamiento con datos del piloto ni tarifa efectiva de la pasarela. La próxima comparación deberá mantener corpus y base constantes, variar solo el modelo o prompt y revisar manualmente brevedad, pertinencia y errores.
