// Piezas comunes del visor: crear nodos con textContent, formatos, nombres de estados y la descripción del harness.
// app.js emite «asistendero:reset» al empezar una prueba y «asistendero:event» por cada evento de la traza; el
// resultado (resultado.js), el mapa (harness.js), la inspección (traza.js) y el castillo los escuchan.

export function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

export function plural(count, one, many) {
  return count + ' ' + (count === 1 ? one : many);
}

export function formatUsd(value) {
  const amount = Number(value);
  return Number.isFinite(amount) ? '$' + amount.toLocaleString('en-US', {minimumFractionDigits: 6, maximumFractionDigits: 8})
    : 'No disponible';
}

export function formatMs(value) {
  return typeof value === 'number' ? value.toLocaleString('es-CO') + ' ms' : '—';
}

export const STATE_LABELS = {
  order_pending: 'Pedido por confirmar', order_confirmed: 'Pedido confirmado', pickup_scheduled: 'Recogida agendada',
  order_cancelled: 'Pedido cancelado', order_status: 'Estado del pedido', order_issue: 'Pedido con novedad',
  informed: 'Información de la tienda', refused: 'Pedido no permitido', blocked: 'Mensaje bloqueado',
  found: 'Productos encontrados', partial: 'Resultado parcial', clarify: 'Falta aclaración', not_found: 'Sin coincidencia',
  answered: 'Respondido', model_invalid: 'Respuesta no válida', quoted: 'Cotización informativa',
  nearby: 'Opciones cercanas', insufficient_stock: 'Existencias insuficientes', quote_error: 'Cotización no disponible',
  tool_error: 'Catálogo no disponible', not_verified: 'Sin verificar', model_error: 'Fallo del modelo',
  limit_reached: 'Límite de herramientas', handoff: 'Avisado al tendero', staff: 'Atiende el tendero',
};

export const NODE_LABELS = {validate: 'Puerta', interpret: 'Torre de Grok', retrieve: 'Aduana y bodega', respond: 'Balanza'};

// Tono de cada grupo de estados (harness_info.OUTCOMES); el texto del grupo siempre acompaña al color.
export const GROUP_TONES = {verified: 'success', clarify: 'warning', human: 'warning', safe_failure: 'error'};

// Una sola lectura de /api/harness para todo el visor; quien la necesite espera esta promesa.
export const harnessInfo = fetch('/api/harness')
  .then(response => response.ok ? response.json() : Promise.reject(new Error('HTTP ' + response.status)));

// Estado y grupo de un estado final, con la clasificación del servidor si ya llegó.
export function outcomeOf(estado, info) {
  for (const [group, data] of Object.entries(info?.outcomes || {})) {
    if (estado in data.states) return {group, groupLabel: data.label, label: data.states[estado], tone: GROUP_TONES[group]};
  }
  return {group: '', groupLabel: 'Estado sin clasificar', label: STATE_LABELS[estado] || estado, tone: 'warning'};
}

// La redacción de Grok se entregó si la respuesta final es exactamente la que propuso en su última decisión.
export function authorOf(final, lastDecision) {
  if (final.inyeccion) return {key: 'blocked', text: 'El servidor: respuesta fija de bloqueo, sin Grok'};
  if (!final.model_called) return {key: 'server', text: 'El servidor, sin llamar a Grok'};
  const proposed = lastDecision?.reply?.trim();
  if (proposed && final.respuesta === proposed) return {key: 'grok', text: 'Grok: su redacción se entregó tal cual'};
  return {key: 'server', text: 'El servidor, con los datos de las herramientas'};
}

export function onRun(handlers) {
  document.addEventListener('asistendero:reset', () => handlers.reset?.());
  document.addEventListener('asistendero:event', ({detail}) => handlers.event?.(detail));
}
