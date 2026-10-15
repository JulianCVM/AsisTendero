# Harness experimental de AsisTendero

**Estado:** implementación de prueba en `codex/harness-tests`, derivada de `dev/julian`. No representa todavía la arquitectura final acordada con la pareja. Relacionado con [PT-006](https://github.com/JulianCVM/AsisTendero/issues/6), [PT-031](https://github.com/JulianCVM/AsisTendero/issues/31) y [PT-032](https://github.com/JulianCVM/AsisTendero/issues/32); ninguna issue queda cerrada por este experimento.

## Contrato del flujo

```text
entrada textual
  → validar longitud y contenido
  → leer hasta cinco candidatos del SQLite ficticio (solo lectura, sede fija)
  → si hay candidatos: Grok selecciona un SKU o null en JSON
  → verificar que el SKU exista en esos candidatos y que la variante esté especificada
  → componer respuesta con nombre, precio y stock leídos de SQLite
  → salida textual con aviso de datos simulados
```

El modelo **interpreta la consulta**. No recibe SQL, ni precio, ni stock; tampoco escribe en la base. La selección es una propuesta, nunca un hecho: el código la rechaza si inventa un SKU o el cliente no precisó la variante. Precio, stock y mensaje final salen del renderizador determinista y de la fila consultada. Si no hay candidatos, se responde sin llamada al modelo para no gastar cupo ni alucinar un producto.

La base SQLite está en `.local/mock_catalog.sqlite3` y no se publica. `seed.py` crea seis variantes ficticias y no sobrescribe una base existente. `MockCatalog` abre conexiones `mode=ro`, filtra por negocio y sede de demostración definidos en servidor, y solo expone métodos de lectura. Esto es **fuente de verdad de la demo**, no inventario del piloto ni una implementación de permisos multinegocio.

## Reglas iniciales de respuesta

1. Responder solo al producto consultado. La salida `found` contiene variante, SKU, precio y stock simulados con unidad; `clarify` solicita medida o presentación; `not_found` reconoce que la base no contiene el producto.
2. No inferir disponibilidad real, compatibilidad, descuentos, promesas de reserva, pago, entrega o acciones del tendero. Los datos de la demo se etiquetan como simulados en cada respuesta que contiene hechos.
3. Ante variantes del mismo nombre, se exige una señal distintiva en la consulta. Ni siquiera una selección de Grok salta esa comprobación.
4. La salida JSON de Grok se valida. Un valor fuera de los candidatos o inválido no llega al cliente como hecho.
5. Una llamada al modelo como máximo por consulta con candidatos. El número de candidatos, longitud de entrada y tokens de salida están acotados. No hay memoria conversacional ni acciones externas en este corte.

## Método de prueba y comparación

- **Pruebas locales sin costo:** `python -m pytest -q` crea SQLite temporal y sustituye Grok por decisiones controladas. Comprueba fidelidad a datos, ambigüedad, SKU inventado, ausencia de coincidencia, aislamiento de negocio y entrada vacía. Son reglas de seguridad del flujo; no evalúan redacción real del modelo.
- **Evaluación real, explícita y acotada:** `python -m asistendero.evaluate --live --limit 4` ejecuta casos sintéticos de `evaluation/cases.json`. Sin `--live` no llama a Grok. Guarda en `.local/` un reporte ignorado por Git con versión del prompt, modelo, hash de la base, respuestas, estado, latencia y tokens si la pasarela los informa.
- **Revisión humana:** leer cada respuesta por precisión, brevedad y utilidad. La aprobación automática de estados no mide estilo ni confianza del cliente. Registrar falsos positivos, preguntas insuficientes y casos sin respuesta antes de cambiar el prompt o el modelo.
- **Cambios controlados:** no incluir ejemplos de evaluación en el prompt ni modificarlo caso por caso. Para comparar versiones, mantener el mismo corpus y la misma base, cambiar una variable por vez (prompt, modelo o recuperación), conservar el reporte y explicar la diferencia. Una mejora debe conservar todas las reglas locales y no aumentar errores factuales.

`PROMPT_VERSION=catalog-select-v1` identifica las instrucciones de selección. La salida de producción y las pruebas usan el mismo grafo; los dobles de prueba se inyectan solo como dependencia. Los reportes no incluyen la clave. No se atribuyen a Grok hechos que la base o las reglas del programa resolvieron.

## Modelo y costo

La clave del reto lista `grok-4.20-0309-non-reasoning`. Se usa como valor predeterminado para estas consultas de texto: xAI publica tarifas inferiores a las de `grok-4.7` para ese modelo ([ficha 4.20](https://docs.x.ai/developers/models/grok-4.20-0309-non-reasoning), [ficha 4.7](https://docs.x.ai/developers/models/grok-4.7)). **La pasarela del reto puede facturar o limitar de otro modo**; comparar tokens y costo real antes de afirmar ahorro. Mantener `GROK_MODEL` configurable permite repetir el mismo corpus con otro modelo sin cambiar reglas ni datos.

## Próximo límite arquitectónico

El contrato de `MockCatalog` permite sustituir SQLite por herramientas autorizadas de negocio: derivar negocio/sede de sesión verificada, devolver datos fechados y versionados, validar permisos, y mantener lectura separada de futuras mutaciones. El cambio requiere PT-001/PT-002 y las reglas de PT-003/PT-005; no se conecta Supabase ni se implementa una reserva por anticipación.
