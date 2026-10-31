// Mapa del harness: datos de /api/harness, el grafo de decisión (harness-map.js) y el recorrido de la última
// ejecución, armado solo con los eventos de la traza: qué nodos visitó, cuántas veces y por qué conexión.
import {authorOf, el, harnessInfo, onRun, outcomeOf, plural} from './visor-comun.js';
import {createMap} from './harness-map.js';

const statusPill = document.querySelector('#harness-status');
const verdict = document.querySelector('#harness-verdict');
const path = document.querySelector('#harness-path');
let info = null;
let map = null;
let run = null;

function setPill(label, tone) {
  statusPill.textContent = label;
  if (tone) statusPill.dataset.tone = tone;
  else statusPill.removeAttribute('data-tone');
}
function station(id) {
  return info?.flow.nodes.find(node => node.id === id)?.station || id;
}
function fresh() {
  return {visits: {}, walked: {}, notes: {}, final: null, tone: '', at: null, routeTo: null, lastDecision: null};
}
function visit(id) {
  run.visits[id] = (run.visits[id] || 0) + 1;
  run.at = id;
}
function walk(from, to) {
  if (from) run.walked[from + '>' + to] = (run.walked[from + '>' + to] || 0) + 1;
  visit(to);
}
function note(id, text, tone) {
  (run.notes[id] ||= []).push(text);
  const item = el('li', 'path-step');
  item.dataset.tone = tone || 'neutral';
  item.append(el('span', 'path-stage', station(id)), el('span', 'path-text', text));
  path.append(item);
}
function argumentsText(value) {
  const text = JSON.stringify(value ?? {});
  return text.length > 120 ? text.slice(0, 117) + '…' : text;
}
function refresh() {
  map?.update(run);
}

function reset() {
  run = fresh();
  path.replaceChildren();
  verdict.textContent = 'Ejecutando la prueba…';
  setPill('En curso', 'warning');
  refresh();
}

function onRunning(node) {
  if (node === 'validate') walk('cliente', 'validate');
  else if (node === 'interpret') {
    const from = run.at === 'route' ? 'route' : run.at;
    if (from === 'route') note('route', 'Grok respondió sin un paso que el mensaje exige: vuelve a la torre con un aviso.', 'warning');
    walk(from, 'interpret');
  } else if (node === 'retrieve') {
    // Si retrieve vuelve a empezar desde la bodega, no lo pidió Grok: el servidor auto-cotiza el match unívoco.
    if (run.at === 'bodega') {
      note('bodega', 'Un solo producto distinguido y una cantidad entera: el servidor cotiza en el mismo paso.');
      walk('bodega', 'aduana');
      return;
    }
    note('route', 'call_tool con llamadas disponibles: pasa a la aduana.');
    walk('route', 'aduana');
  } else if (node === 'respond') {
    if (run.at === 'route') note('route', 'Pasa a verificar y responder.');
    if (run.at === 'bodega') note('bodega', 'La herramienta dejó la respuesta completa: se responde sin otra llamada a Grok.');
    walk(run.at, 'respond');
  }
}

function onComplete(node, details) {
  if (node === 'validate') {
    if (details.inyeccion) {
      note('validate', 'Inyección ' + details.inyeccion.code + ' (' + details.inyeccion.technique + '): no llega a Grok.', 'error');
    } else {
      const guards = details.barreras?.length ? ' Quitó: ' + details.barreras.join(', ') + '.' : '';
      note('validate', 'Mensaje válido de ' + (details.longitud ?? '—') + ' caracteres.' + guards +
        (details.datos_personales_omitidos ? ' Omitió datos personales.' : ''));
    }
  } else if (node === 'interpret') {
    const decision = details.decision;
    if (details.error) note('interpret', 'Grok falló: ' + details.error.code + '.', 'error');
    else if (decision && !decision.valid_json) note('interpret', 'Grok devolvió una decisión con formato inválido.', 'error');
    else if (decision?.action === 'call_tool') note('interpret', 'Grok pide ' + decision.tool + ' ' + argumentsText(decision.arguments) + '.');
    else note('interpret', 'Grok decide responder' + (decision?.reply ? ': «' + decision.reply.slice(0, 90) + '»' : '') + '.');
    run.lastDecision = decision || run.lastDecision;
    walk('interpret', 'route');
  } else if (node === 'retrieve') {
    const call = details.tool_call || {};
    const code = call.response?.error?.code;
    if (!call.executed) {
      note('aduana', 'Rechaza ' + call.requested_tool + ' (' + code + '): la herramienta no corre.', 'warning');
      return;
    }
    note('aduana', 'Aprueba ' + call.requested_tool + ' ' + argumentsText(call.arguments) + '.', 'success');
    walk('aduana', 'bodega');
    note('bodega', call.requested_tool + ' · ' + (call.response?.status === 'ok' ? 'ok' : 'error ' + code) + ' · ' +
      (call.duration_ms ?? 0) + ' ms.', call.response?.status === 'ok' ? 'success' : 'warning');
  }
}

function onModelRequest(details) {
  // El código del aviso viaja en las observaciones de la siguiente llamada a Grok.
  const codes = new Set((info?.reminders || []).map(item => item.code));
  const sent = (details.observaciones || []).map(item => item?.error?.code).filter(code => codes.has(code));
  const known = run.notes.route || [];
  sent.forEach(code => {
    const text = 'Aviso del servidor: ' + code + '.';
    if (!known.includes(text)) note('route', text, 'warning');
  });
}

function onFinal(details) {
  const outcome = outcomeOf(details.estado, info);
  const who = authorOf(details, run.lastDecision).text;
  note('respond', 'Responde ' + who.charAt(0).toLowerCase() + who.slice(1) + '.');
  walk('respond', 'outcome');
  run.final = 'outcome';
  run.tone = outcome.tone;
  note('outcome', details.estado + ' · ' + outcome.label + ' (' + outcome.groupLabel + ')' +
    (details.error ? ' · ' + details.error.code : '') + '.', outcome.tone);
  const executed = details.tools_executed?.length ?? 0;
  const rejected = (details.tools_requested?.length ?? 0) - executed;
  verdict.textContent = outcome.groupLabel + ': ' + outcome.label + '. ' + plural(details.model_calls ?? 0, 'llamada', 'llamadas') +
    ' a Grok, ' + executed + (executed === 1 ? ' herramienta ejecutada' : ' herramientas ejecutadas') + ' y ' + rejected +
    (rejected === 1 ? ' rechazada.' : ' rechazadas.');
  setPill(outcome.groupLabel, outcome.tone);
}

function onEvent(event) {
  if (!run) reset();
  const details = event.details || {};
  if (event.type === 'input') visit('cliente');
  else if (event.type === 'node' && event.status === 'running') onRunning(event.node);
  else if (event.type === 'node') onComplete(event.node, details);
  else if (event.type === 'model_request') onModelRequest(details);
  else if (event.type === 'final') onFinal(details);
  else if (event.type === 'error') {
    if (run.at) note(run.at, 'La prueba se detuvo aquí: ' + (event.message || 'error de ejecución') + '.', 'error');
    run.final = run.at;
    run.tone = 'error';
    verdict.textContent = 'La prueba se detuvo: ' + (event.message || 'error de ejecución') + '.';
    setPill('Error de ejecución', 'error');
  }
  refresh();
}

function fill(data) {
  info = data;
  document.querySelectorAll('[data-harness]').forEach(node => {
    const key = node.dataset.harness;
    const value = key in data ? data[key] : data.limits?.[key];
    if (value !== undefined) node.textContent = typeof value === 'number' ? value.toLocaleString('es-CO') : String(value);
  });
  map = createMap(data);
  if (run) refresh();
}

harnessInfo.then(fill).catch(() => {
  document.querySelector('#flow-nodes').replaceChildren(
    el('li', 'flow-error', 'No se pudo cargar la descripción del harness desde el visor local.'));
});
onRun({reset, event: onEvent});
