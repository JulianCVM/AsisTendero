// Recorrido de una foto: carriles (cliente, servidor, Grok), las etapas reales de photo_flow.py y las bases que cada
// una lee o escribe. Tras un turno con foto, cada etapa dice qué pasó con esa foto, leído de la traza: «vision»
// (limpieza, huella, atributos y lo descartado), la «route» con el código que la detuvo, la bodega y la sesión.
// En escritorio es un diagrama de carriles con flechas en SVG; en celular, una lista vertical.
import {el, formatUsd, harnessInfo, onRun, plural} from './visor-comun.js';

const SVG = 'http://www.w3.org/2000/svg';
const MODE_TEXT = {lee: 'Lee', escribe: 'Escribe'};
const STATE_MARK = {idle: '○', done: '✓', skipped: '–', stopped: '■', waiting: '…'};
const wide = matchMedia('(min-width: 761px)');

const diagram = document.querySelector('#photo-flow');
const rows = document.querySelector('#photo-rows');
const links = document.querySelector('#photo-links');
const pill = document.querySelector('#photo-status');
const verdict = document.querySelector('#photo-verdict');
const cards = {};
const chips = [];
let flow = null;
let photoSent = false;
let seen = null;

function kb(bytes) {
  return (bytes / 1000).toLocaleString('es-CO', {maximumFractionDigits: 0}) + ' KB';
}
function setState(id, state, text) {
  const card = cards[id];
  if (!card) return;
  card.dataset.state = state;
  card.querySelector('.pf-mark').textContent = STATE_MARK[state];
  card.querySelector('.pf-state').textContent = text;
}
function touch(store, used) {
  for (const chip of chips) if (chip.dataset.store === store && (!used || chip.dataset.stage === used)) chip.dataset.used = 'true';
}
function setPill(text, tone) {
  pill.textContent = text;
  if (tone) pill.dataset.tone = tone;
  else pill.removeAttribute('data-tone');
}

function build(info) {
  flow = info.photo_flow;
  const lanes = Object.fromEntries(flow.lanes.map((lane, index) => [lane.id, index + 1]));
  const stores = Object.fromEntries(flow.stores.map(store => [store.id, store]));
  const head = el('li', 'pf-head');
  for (const lane of flow.lanes) {
    const title = el('div', 'pf-lane-title');
    title.dataset.lane = lane.id;
    title.style.gridColumn = String(lanes[lane.id]);
    title.append(el('strong', '', lane.title), el('span', '', lane.does));
    head.append(title);
  }
  const dataTitle = el('div', 'pf-lane-title');
  dataTitle.dataset.lane = 'datos';
  dataTitle.style.gridColumn = String(flow.lanes.length + 1);
  dataTitle.append(el('strong', '', 'Datos'), el('span', '', 'Lo que se lee o se guarda'));
  head.append(dataTitle);
  head.setAttribute('aria-hidden', 'true');
  rows.append(head);

  flow.stages.forEach((stage, index) => {
    const row = el('li', 'pf-row');
    const card = el('article', 'pf-card');
    card.dataset.lane = stage.lane;
    card.dataset.state = 'idle';
    card.style.gridColumn = String(lanes[stage.lane]);
    card.style.gridRow = String(index + 2);
    const top = el('div', 'pf-top');
    top.append(el('span', 'pf-step', String(index + 1)), el('span', 'pf-lane', flow.lanes[lanes[stage.lane] - 1].title),
      el('span', 'pf-mark', STATE_MARK.idle));
    top.lastChild.setAttribute('aria-hidden', 'true');
    card.append(top, el('h3', 'pf-title', stage.title), el('code', 'pf-code', stage.code), el('p', 'pf-does', stage.does));
    if (stage.exit) {
      const exit = el('p', 'pf-exit');
      exit.append(el('strong', '', 'Si no pasa: '), document.createTextNode(stage.exit.text + ' '),
        el('code', '', stage.exit.codes.slice(0, 3).join(' · ') + (stage.exit.codes.length > 3 ? ' …' : '')));
      card.append(exit);
    }
    card.append(el('p', 'pf-state', 'Sin ejecutar'));
    cards[stage.id] = card;
    row.append(card);
    for (const access of stage.data) {
      const store = stores[access.store];
      const chip = el('div', 'pf-store');
      chip.dataset.store = store.id;
      chip.dataset.stage = stage.id;
      chip.dataset.mode = access.mode;
      chip.style.gridColumn = String(flow.lanes.length + 1);
      chip.style.gridRow = String(index + 2);
      chip.append(el('span', 'pf-store-mode', MODE_TEXT[access.mode] || access.mode), el('strong', '', store.title),
        el('code', '', store.code), el('span', 'pf-store-note', store.mode));
      chips.push(chip);
      row.append(chip);
    }
    rows.append(row);
  });
  const legend = document.querySelector('#photo-stores');
  for (const store of flow.stores) {
    const item = el('li', '');
    item.append(el('strong', '', store.title), el('code', '', store.code), el('span', '', store.does));
    legend.append(item);
  }
  draw();
  new ResizeObserver(draw).observe(diagram);
  wide.addEventListener('change', draw);
}

function path(d, className) {
  const node = document.createElementNS(SVG, 'path');
  node.setAttribute('d', d);
  node.setAttribute('class', className);
  return node;
}
function draw() {
  links.replaceChildren();
  if (!flow || !wide.matches) return;
  const box = diagram.getBoundingClientRect();
  links.setAttribute('viewBox', `0 0 ${box.width} ${box.height}`);
  const defs = document.createElementNS(SVG, 'defs');
  const marker = document.createElementNS(SVG, 'marker');
  for (const [name, value] of Object.entries({id: 'pf-arrow', viewBox: '0 0 10 10', refX: '9', refY: '5', markerWidth: '7', markerHeight: '7', orient: 'auto-start-reverse'})) marker.setAttribute(name, value);
  marker.append(path('M0 0L10 5L0 10z', 'pf-arrow'));
  defs.append(marker);
  links.append(defs);
  const at = node => {
    const rect = node.getBoundingClientRect();
    return {left: rect.left - box.left, right: rect.right - box.left, top: rect.top - box.top, bottom: rect.bottom - box.top,
      x: rect.left - box.left + rect.width / 2, y: rect.top - box.top + rect.height / 2};
  };
  for (const edge of flow.edges) {
    const from = at(cards[edge.from]);
    const to = at(cards[edge.to]);
    const middle = (from.bottom + to.top) / 2;
    const d = Math.abs(from.x - to.x) < 2
      ? `M${from.x} ${from.bottom}V${to.top - 2}`
      : `M${from.x} ${from.bottom}C${from.x} ${middle} ${to.x} ${middle} ${to.x} ${to.top - 2}`;
    const group = document.createElementNS(SVG, 'g');
    group.setAttribute('class', 'pf-link');
    group.dataset.from = edge.from;
    group.dataset.to = edge.to;
    if (cards[edge.from].dataset.state === 'done' && ['done', 'stopped'].includes(cards[edge.to].dataset.state)) group.dataset.walked = 'true';
    const line = path(d, '');
    line.setAttribute('marker-end', 'url(#pf-arrow)');
    const label = document.createElementNS(SVG, 'text');
    label.setAttribute('x', String((from.x + to.x) / 2 + (Math.abs(from.x - to.x) < 2 ? 8 : 0)));
    label.setAttribute('y', String(Math.abs(from.x - to.x) < 2 && to.top - from.bottom > 80 ? (from.bottom + to.top) / 2 : middle + 4));
    label.setAttribute('text-anchor', Math.abs(from.x - to.x) < 2 ? 'start' : 'middle');
    label.textContent = edge.label;
    group.append(line, label);
    links.append(group);
  }
  for (const chip of chips) {
    const from = at(cards[chip.dataset.stage]);
    const to = at(chip);
    const line = path(`M${from.right} ${to.y}H${to.left - 2}`, 'pf-data-link');
    if (chip.dataset.used) line.dataset.used = 'true';
    if (chip.dataset.mode === 'escribe') line.setAttribute('marker-end', 'url(#pf-arrow)');
    else line.setAttribute('marker-start', 'url(#pf-arrow)');
    links.append(line);
  }
}

function idle(text) {
  for (const id of Object.keys(cards)) setState(id, 'idle', text);
  for (const chip of chips) delete chip.dataset.used;
}
function skipRest(from, text) {
  const ids = flow.stages.map(stage => stage.id);
  for (const id of ids.slice(ids.indexOf(from) + 1)) if (cards[id].dataset.state !== 'done') setState(id, 'skipped', text);
}

function reset(detail) {
  photoSent = Boolean(detail?.foto);
  seen = {tools: [], vision: null};
  if (!flow) return;
  if (!photoSent) {
    idle('Este turno no traía foto');
    setPill('Sin foto', '');
    verdict.textContent = 'La última prueba fue solo texto. Adjunta una foto en la conversación para ver su recorrido.';
  } else {
    idle('Pendiente');
    for (const id of Object.keys(cards)) setState(id, 'waiting', 'Esperando…');
    setState('envio', 'done', 'La foto salió reducida desde el navegador');
    setPill('En curso', 'warning');
    verdict.textContent = 'Siguiendo la foto por el servidor…';
  }
  draw();
}

function onVision(details) {
  seen.vision = details;
  setState('texto', 'done', 'Sin inyección: la foto se puede mirar');
  const cleaning = details.limpieza;
  setState('limpieza', 'done', cleaning
    ? `Llegó de ${cleaning.entrada.ancho}×${cleaning.entrada.alto} px (${kb(cleaning.entrada.bytes)}); quedó de ${cleaning.limpia.ancho}×${cleaning.limpia.alto} px (${kb(cleaning.limpia.bytes)}), sin metadatos`
    : 'Atributos ya armados (prueba): no hubo foto que limpiar');
  const report = details.cotejo;
  touch('fotos', 'huella');
  if (report?.familia) {
    setState('huella', 'done', `La reconoce: familia ${report.familia}, a ${plural(report.mas_cercana, 'bit', 'bits')} de ${report.fotos} fotos (umbral ${report.umbral})`);
    setState('vision', 'skipped', 'No hizo falta: bastó la huella, 0 llamadas a Grok');
  } else {
    setState('huella', 'done', report
      ? `No la reconoce: la más cercana de ${report.fotos} fotos está a ${plural(report.mas_cercana, 'bit', 'bits')} (umbral ${report.umbral})`
      : 'Sin huella: atributos de prueba');
    setState('vision', details.llamada ? 'done' : 'skipped', details.llamada
      ? `Vio: ${details.tipo_producto || 'artículo no identificado'} · confianza ${details.confianza || 'media'}`
      : 'Sin llamada: atributos ya armados');
  }
  const dropped = details.descartados || [];
  touch('catalogo', 'respaldo');
  setState('respaldo', 'done', dropped.length
    ? 'Descartó lo que el catálogo no respalda: ' + dropped.join(', ') + '. Queda: ' + details.resumen
    : 'Todo lo visto tiene respaldo. Queda: ' + details.resumen);
  setState('grafo', 'waiting', 'Buscando en el catálogo…');
}

function onStop(code) {
  setState('texto', 'done', 'Sin inyección');
  if (code.startsWith('PHOTO_')) {
    setState('limpieza', 'stopped', 'Rechazada (' + code + '): respuesta fija, sin Grok');
    skipRest('limpieza', 'No se llegó: la foto se rechazó');
  } else {
    setState('limpieza', 'done', 'Foto válida');
    setState('huella', 'done', 'No la reconoce');
    setState('vision', 'stopped', 'Grok no pudo revisarla (' + code + '): se pide la muestra');
    skipRest('vision', 'No se llegó: Grok no pudo revisar la foto');
  }
  setPill('Detenida', 'error');
  verdict.textContent = 'La foto no siguió: el cliente recibió un mensaje fijo que dice qué hacer, sin precio ni existencias.';
}

function event(item) {
  if (!flow || !photoSent) return;
  const details = item.details || {};
  if (item.type === 'vision') onVision(details);
  else if (item.type === 'model_response' && details.phase === 'vision' && cards.vision.dataset.state === 'done') {
    const tokens = (details.input_tokens || 0) + (details.output_tokens || 0);
    cards.vision.querySelector('.pf-state').textContent += ` · ${tokens} tokens · ${formatUsd(details.cost?.usd)} USD`;
  } else if (item.type === 'route' && details.foto) onStop(details.foto);
  else if (item.type === 'node' && item.node === 'validate' && item.status === 'complete' && details.inyeccion && !seen.vision) {
    setState('texto', 'stopped', 'Inyección (' + details.inyeccion.code + '): la foto no se miró');
    skipRest('texto', 'No se llegó: el texto intentaba una inyección');
    setPill('Bloqueada', 'error');
    verdict.textContent = 'El texto que acompañaba la foto intentaba cambiar las reglas: se bloqueó sin gastar en la foto.';
  } else if (item.type === 'node' && item.node === 'retrieve' && item.status === 'complete' && details.tool_call) {
    const call = details.tool_call;
    seen.tools.push(call.requested_tool + (call.executed ? '' : ' (rechazada: ' + (call.response?.error?.code || 'regla') + ')'));
    touch('catalogo', 'grafo');
    setState('grafo', 'waiting', 'Herramientas: ' + seen.tools.join(', '));
  } else if (item.type === 'final' && seen.vision) {
    setState('grafo', 'done', (seen.tools.length ? 'Herramientas: ' + seen.tools.join(', ') + '. ' : 'Sin herramientas. ')
      + 'Estado final: ' + details.estado);
  } else if (item.type === 'session' && seen.vision) {
    touch('sesion', 'memoria');
    setState('memoria', 'done', `Turno ${item.turno} guardado con ${seen.vision.resumen}; sin los bytes de la foto`);
    const photos = Array.isArray(item.imagenes) ? item.imagenes.length : 0;
    if (photos) touch('fotos', 'respuesta');
    setState('respuesta', photos ? 'done' : 'skipped', photos
      ? `${photos} ${photos === 1 ? 'foto' : 'fotos'} de referencia con su crédito`
      : 'Sin fotos de referencia: ningún producto de la respuesta tiene foto');
    setPill('Recorrida', 'success');
    verdict.textContent = 'Así viajó la última foto: cada etapa dice qué hizo con ella y qué base tocó.';
  }
  draw();
}

harnessInfo.then(build).catch(() => {
  verdict.textContent = 'No se pudo cargar el recorrido de la foto. Recarga la página.';
});
onRun({reset, event});
