// «Resultado de la prueba»: lo que se observa y se compara de cada ejecución, leído solo de los eventos de la traza.
// Estado final y su grupo, quién redactó, herramientas pedidas, ejecutadas y rechazadas, Grok, tokens, latencia y
// costo; el costo por llamada queda plegado. «Ejecuciones de esta visita» guarda las últimas en memoria.
import {authorOf, el, formatMs, formatUsd, harnessInfo, onRun, outcomeOf, plural} from './visor-comun.js';

const status = document.querySelector('#status');
const outcomeBox = document.querySelector('#result-outcome');
const outcomeMark = document.querySelector('#result-mark');
const groupText = document.querySelector('#result-group');
const stateText = document.querySelector('#result-state');
const author = document.querySelector('#result-author');
const toolsCount = document.querySelector('#result-tools-count');
const toolList = document.querySelector('#result-tools');
const costAmount = document.querySelector('#cost-amount');
const costBasis = document.querySelector('#cost-basis');
const costLines = document.querySelector('#cost-lines');
const copy = document.querySelector('#copy-answer');
const runList = document.querySelector('#run-list');
const runsEmpty = document.querySelector('#runs-empty');
const STEP_NAMES = ['validate', 'interpret', 'retrieve', 'respond'];
const STEP_TEXT = {running: 'En curso', complete: 'Hecho', skipped: 'Omitido', error: 'Error'};
const RUNNING_TEXT = {validate: 'Revisando el mensaje', interpret: 'Grok decide', retrieve: 'Consultando el catálogo',
  respond: 'Verificando la respuesta'};
const MARKS = {success: '✓', warning: '!', error: '×'};
const MAX_RUNS = 8;
let info = null;
let run = null;
let runNumber = 0;

harnessInfo.then(data => { info = data; }).catch(() => { /* sin descripción, los estados se muestran sin grupo */ });

function setStatus(label, tone) {
  status.textContent = label;
  if (tone) status.dataset.tone = tone;
  else status.removeAttribute('data-tone');
}
function setStep(name, state) {
  const step = document.querySelector('#step-' + name);
  if (!step) return;
  step.className = 'step' + (state ? ' ' + state : '');
  step.querySelector('.step-state').textContent = STEP_TEXT[state] || 'Pendiente';
  if (state === 'running') run.runningStep = name;
}
function costLabel(basis) {
  return ({api_reported: 'Informado por la API', xai_public_estimate: 'Estimado con tarifa pública xAI',
    mixed: 'Mezcla de costo informado y estimado'})[basis] || 'Costo no disponible';
}
function renderCost(finalCost, done) {
  const known = run.costs.filter(item => item.cost);
  if (finalCost) {
    costAmount.textContent = formatUsd(finalCost.usd);
    costBasis.textContent = costLabel(finalCost.basis) + ' · ' + plural(finalCost.calls, 'llamada', 'llamadas');
  } else if (!known.length) {
    costAmount.textContent = '—';
    costBasis.textContent = done ? 'No disponible para esta ejecución.' : 'Esperando el uso de Grok…';
  } else {
    costAmount.textContent = formatUsd(known.reduce((sum, item) => sum + Number(item.cost.usd), 0));
    costBasis.textContent = 'Parcial' + (done ? ' · ejecución incompleta' : '') + ' · ' + known.length + ' de ' +
      run.costs.length + ' llamadas con costo';
  }
}
function renderTools() {
  const executed = run.tools.filter(call => call.executed).length;
  const rejected = run.tools.length - executed;
  toolsCount.textContent = run.tools.length ? plural(run.tools.length, 'pedida', 'pedidas') + ' · ' + executed +
    (executed === 1 ? ' ejecutada' : ' ejecutadas') + ' · ' + rejected + (rejected === 1 ? ' rechazada' : ' rechazadas')
    : 'Ninguna';
  toolList.replaceChildren(...run.tools.map(call => {
    const code = call.response?.error?.code;
    const verdict = !call.executed ? 'rechazada' : (call.response?.status === 'ok' ? 'ok' : 'error');
    const item = el('li', 'result-tool');
    item.dataset.verdict = verdict;
    item.append(el('code', '', call.requested_tool || '—'),
      el('span', 'tool-verdict', verdict === 'ok' ? 'Ejecutada · ok' : (verdict === 'rechazada' ? 'Rechazada · ' + code
        : 'Ejecutada · ' + (code || 'error'))));
    return item;
  }));
}
function setOutcome(title, detail, tone) {
  groupText.textContent = title;
  stateText.textContent = detail;
  outcomeMark.textContent = MARKS[tone] || '…';
  if (tone) outcomeBox.dataset.tone = tone;
  else outcomeBox.removeAttribute('data-tone');
}
function remember(final) {
  runNumber += 1;
  const outcome = outcomeOf(final.estado, info);
  const item = el('li', 'run-item');
  item.dataset.tone = outcome.tone;
  const head = el('div', 'run-head');
  head.append(el('span', 'run-number', '#' + runNumber), el('strong', 'run-state', outcome.label),
    el('span', 'run-group', outcome.groupLabel));
  const facts = el('dl', 'run-facts');
  const executed = final.tools_executed?.length ?? 0;
  for (const [term, value] of [
    ['Herramientas', (final.tools_requested?.length ?? 0) + ' pedidas · ' + executed + ' ejecutadas'],
    ['Grok', plural(final.model_calls ?? 0, 'llamada', 'llamadas')],
    ['Latencia', formatMs(final.duration_ms)],
    ['Costo', final.cost ? formatUsd(final.cost.usd) : '—'],
  ]) {
    const pair = el('div');
    pair.append(el('dt', '', term), el('dd', '', value));
    facts.append(pair);
  }
  item.append(head, el('p', 'run-message', '«' + (run.message || '—') + '»'), facts);
  runList.prepend(item);
  while (runList.children.length > MAX_RUNS) runList.lastElementChild.remove();
  runsEmpty.hidden = true;
}

function reset() {
  run = {tools: [], costs: [], tokens: 0, tokensKnown: false, prompt: 0, cached: 0, lastDecision: null, message: '',
    runningStep: null};
  STEP_NAMES.forEach(name => setStep(name, ''));
  setStatus('Ejecutando', 'warning');
  setOutcome('En curso…', 'El estado final aparece cuando termine la ejecución.', '');
  author.textContent = '—';
  toolsCount.textContent = '—';
  toolList.replaceChildren();
  costLines.replaceChildren();
  renderCost(null, false);
  for (const id of ['#metric-calls', '#metric-tokens', '#metric-cache', '#metric-duration']) {
    document.querySelector(id).textContent = '—';
  }
  copy.disabled = true;
}

function onEvent(event) {
  if (!run) reset();
  const details = event.details || {};
  if (event.type === 'input') run.message = String(details.consulta || '').slice(0, 90);
  if (event.type === 'node') {
    setStep(event.node, event.status);
    if (event.status === 'running') setStatus(RUNNING_TEXT[event.node] || event.node, 'warning');
    if (event.node === 'interpret' && event.status === 'complete') run.lastDecision = details.decision || run.lastDecision;
    if (event.node === 'retrieve' && event.status === 'complete' && details.tool_call) {
      run.tools.push(details.tool_call);
      renderTools();
    }
  }
  if (event.type === 'route' && !run.tools.length) setStep('retrieve', 'skipped');
  if (event.type === 'model_response') {
    run.costs.push({phase: details.phase, cost: details.cost});
    const line = el('div', 'cost-line');
    line.append(el('span', '', 'Llamada ' + run.costs.length + ' · ' + (details.phase === 'resolve' ? 'resolver' : 'interpretar')),
      el('span', '', details.cost ? formatUsd(details.cost.usd) : 'No disponible'));
    costLines.append(line);
    for (const value of [details.input_tokens, details.output_tokens]) {
      if (typeof value === 'number') { run.tokens += value; run.tokensKnown = true; }
    }
    document.querySelector('#metric-tokens').textContent = run.tokensKnown ? run.tokens.toLocaleString('es-CO') : 's/d';
    if (typeof details.input_tokens === 'number') {
      run.prompt += details.input_tokens;
      run.cached += typeof details.cached_input_tokens === 'number' ? details.cached_input_tokens : 0;
    }
    renderCache();
    renderCost(null, false);
  }
  if (event.type === 'final') onFinal(details, event);
  if (event.type === 'error') {
    if (run.runningStep) setStep(run.runningStep, 'error');
    setStatus('Error de ejecución', 'error');
    setOutcome('La prueba se detuvo', (event.code ? event.code + ' · ' : '') + (event.message || 'Error de ejecución.'), 'error');
    renderCost(null, true);
  }
}

// Parte de la entrada que la pasarela sirvió desde la caché: dice si el prefijo estable del prompt se reutilizó.
function renderCache() {
  const target = document.querySelector('#metric-cache');
  target.textContent = run.prompt > 0 ? Math.round((run.cached / run.prompt) * 100) + ' %' : '—';
}

function onFinal(final, event) {
  const outcome = outcomeOf(final.estado, info);
  // Lo que nunca empezó (bloqueo antes de Grok, rechazo de todo el mensaje) queda como omitido, no pendiente.
  STEP_NAMES.forEach(name => {
    if (!document.querySelector('#step-' + name).className.match(/complete|error/)) setStep(name, 'skipped');
  });
  setStatus(outcome.groupLabel, outcome.tone);
  setOutcome(outcome.groupLabel, outcome.label + ' · ' + final.estado + (final.error ? ' · ' + final.error.code : ''), outcome.tone);
  author.textContent = authorOf(final, run.lastDecision).text;
  if (!run.tools.length) renderTools();
  document.querySelector('#metric-calls').textContent = String(final.model_calls ?? '—');
  document.querySelector('#metric-duration').textContent = formatMs(final.duration_ms ?? event.elapsed_ms);
  if (!run.tokensKnown) document.querySelector('#metric-tokens').textContent = final.model_calls ? 's/d' : '0';
  if (typeof final.input_tokens === 'number' && typeof final.cached_input_tokens === 'number') {
    run.prompt = final.input_tokens;
    run.cached = final.cached_input_tokens;
    renderCache();
  }
  renderCost(final.cost, true);
  copy.disabled = !final.respuesta;
  copy.dataset.answer = final.respuesta || '';
  remember(final);
}

copy.addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(copy.dataset.answer || '');
    copy.textContent = 'Copiado';
  } catch {
    copy.textContent = 'No se pudo copiar';
  }
  setTimeout(() => { copy.textContent = 'Copiar respuesta'; }, 1800);
});

onRun({reset, event: onEvent});
