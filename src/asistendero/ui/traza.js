// Inspección técnica: cada evento de la traza como un panel legible (traza-lectura.js), con la relación entre etapas
// («causado por» y «provocó») y el JSON original plegado. Conserva los filtros y la descarga de la traza completa.
import {el, NODE_LABELS, onRun} from './visor-comun.js';
import {readable} from './traza-lectura.js';

const list = document.querySelector('#event-list');
const empty = document.querySelector('#empty-events');
const counter = document.querySelector('#counter');
const download = document.querySelector('#download');
const expand = document.querySelector('#expand-events');
const filterButtons = [...document.querySelectorAll('[data-filter]')];
const TYPE_TITLES = {input: 'Mensaje recibido', route: 'Ruta decidida', final: 'Resultado final', error: 'Error de ejecución',
  session: 'Memoria de la sesión', ban: 'Conversación bloqueada'};
let events = [];
let rows = [];
let activeFilter = 'all';

function kindOf(event) {
  if (event.type === 'model_request' || event.type === 'model_response') return 'model';
  if (event.type === 'node' && event.node === 'retrieve') return 'tool';
  return 'system';
}
function titleOf(event) {
  const phase = event.details?.phase === 'resolve' ? 'resolver' : 'interpretar';
  if (event.type === 'node') return NODE_LABELS[event.node] + ' · ' + (event.status === 'running' ? 'empieza' : 'termina');
  if (event.type === 'model_request') return 'Solicitud a Grok · ' + phase;
  if (event.type === 'model_response') return 'Respuesta de Grok · ' + phase;
  return TYPE_TITLES[event.type] || event.type;
}
function subtitleOf(event) {
  const details = event.details || {};
  if (event.type === 'node' && event.node === 'retrieve' && event.status === 'complete') {
    const call = details.tool_call || {};
    return (call.requested_tool || 'Herramienta') + ' · ' + (call.executed ? call.response?.status || '—' : 'rechazada');
  }
  if (event.type === 'node' && event.node === 'interpret' && event.status === 'complete') {
    const decision = details.decision;
    return details.error ? details.error.code : decision?.action === 'call_tool' ? 'pide ' + decision.tool : 'responde';
  }
  if (event.type === 'final') return details.estado;
  if (event.type === 'error') return event.code || 'sin código';
  return ({model: 'Grok', tool: 'Catálogo', system: 'Sistema'})[kindOf(event)];
}

// Qué evento anterior produjo este: así se lee «respuesta de Grok → ruta → herramienta» sin adivinar por el orden.
function causeOf(event) {
  const last = test => {
    for (let index = events.length - 1; index >= 0; index -= 1) if (test(events[index])) return index;
    return -1;
  };
  const isNode = (item, node, status) => item.type === 'node' && item.node === node && item.status === status;
  if (event.type === 'input') return -1;
  if (event.type === 'model_request') return last(item => isNode(item, 'interpret', 'running'));
  if (event.type === 'model_response') return last(item => item.type === 'model_request');
  if (event.type === 'route') return last(item => item.type === 'node' && item.status === 'complete');
  if (event.type === 'final') return last(item => isNode(item, 'respond', 'complete'));
  if (event.type === 'node' && event.status === 'running') {
    return last(item => item.type === 'route' || item.type === 'input' || (item.type === 'node' && item.status === 'complete'));
  }
  if (event.type === 'node' && event.node === 'interpret') {
    const response = last(item => item.type === 'model_response');
    return response > last(item => isNode(item, 'interpret', 'running')) ? response : last(item => isNode(item, 'interpret', 'running'));
  }
  if (event.type === 'node') return last(item => isNode(item, event.node, 'running'));
  return events.length - 1;
}
function jumpTo(index) {
  const row = rows[index];
  if (row.hidden) setFilter('all');
  row.querySelector('details').open = true;
  row.scrollIntoView({block: 'nearest', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
  row.querySelector('summary').focus();
}
function linkTo(index, prefix) {
  const button = el('button', 'event-link', prefix + ' #' + String(index + 1).padStart(2, '0') + ' ' + titleOf(events[index]));
  button.type = 'button';
  button.addEventListener('click', () => jumpTo(index));
  return button;
}

function setFilter(filter) {
  activeFilter = filter;
  filterButtons.forEach(item => item.setAttribute('aria-pressed', String(item.dataset.filter === filter)));
  render();
}
function render() {
  let visible = 0;
  rows.forEach(row => {
    row.hidden = activeFilter !== 'all' && row.dataset.kind !== activeFilter;
    if (!row.hidden) visible += 1;
  });
  empty.hidden = events.length > 0 && visible > 0;
  if (!empty.hidden && events.length) empty.textContent = 'No hay eventos de esta categoría en la ejecución.';
  counter.textContent = events.length + (events.length === 1 ? ' evento' : ' eventos') +
    (activeFilter === 'all' ? '' : ' · ' + visible + ' visibles') + (events.length ? ' · abre uno para leerlo.' : '.');
}

function add(event) {
  const cause = causeOf(event);
  events.push(event);
  const index = events.length - 1;
  const row = el('li', 'event');
  row.dataset.kind = kindOf(event);
  row.dataset.type = event.type;
  if (event.type === 'node') row.dataset.status = event.status;
  const box = el('details');
  if (event.type === 'final' || event.type === 'error') box.open = true;
  const summary = el('summary');
  const main = el('span', 'event-main');
  main.append(el('span', 'event-title', titleOf(event)), el('span', 'event-kind', subtitleOf(event)));
  summary.append(el('span', 'event-index', String(events.length).padStart(2, '0')), main,
    el('span', 'event-time', (event.elapsed_ms ?? 0) + ' ms'));
  const body = el('div', 'event-body');
  const relations = el('div', 'event-relations');
  if (cause >= 0) relations.append(linkTo(cause, '← Causado por'));
  const effects = el('div', 'event-effects');
  relations.append(effects);
  const raw = el('details', 'raw-json');
  raw.append(el('summary', '', 'JSON original del evento'), el('pre', '', JSON.stringify(event, null, 2)));
  body.append(...readable(event), relations, raw);
  box.append(summary, body);
  row.append(box);
  rows.push(row);
  list.append(row);
  if (cause >= 0) rows[cause].querySelector('.event-effects').append(linkTo(index, '→ Provocó'));
  render();
  download.disabled = false;
  expand.disabled = false;
}

function reset() {
  events = [];
  rows = [];
  list.replaceChildren();
  empty.hidden = false;
  empty.textContent = 'Esperando los eventos de la ejecución…';
  download.disabled = true;
  expand.disabled = true;
  expand.textContent = 'Abrir visibles';
  render();
}

filterButtons.forEach(button => button.addEventListener('click', () => setFilter(button.dataset.filter)));
expand.addEventListener('click', () => {
  const visible = rows.filter(row => !row.hidden).map(row => row.querySelector('details'));
  const open = visible.some(box => !box.open);
  visible.forEach(box => { box.open = open; });
  expand.textContent = open ? 'Cerrar visibles' : 'Abrir visibles';
});
download.addEventListener('click', () => {
  const blob = new Blob([JSON.stringify(events, null, 2)], {type: 'application/json'});
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'asistendero-traza-' + Date.now() + '.json';
  link.click();
  URL.revokeObjectURL(url);
});
onRun({reset, event: add});
