// Asistente de bodega: el tendero escribe o dicta lo que pasó, Grok lo interpreta y el servidor arma una propuesta con
// antes y después. Nada se aplica hasta que el tendero confirma (stock_proposal.py). El dictado usa el reconocimiento
// de voz del navegador cuando existe; si no, se escribe.
import {$, api, busy, cop, el, fill, icon, pill, toast, units, whenText} from './tendero-core.js';

const EXAMPLES = [
  'Llegaron 12 de los 20 bultos de cemento que pedimos',
  'Mañana llegan 30 galones de vinilo blanco',
  'Sube el thinner de galón a 31.500',
  '¿Cuántas brochas de 2 pulgadas quedan?',
];
const STATES = {pendiente:['Por confirmar', 'warning'], aplicada:['Aplicada', 'success'], descartada:['Descartada', ''],
  vencida:['Vencida', 'danger']};
const state = {proposal:null, refresh:null, recognition:null};

function table(headers, rows) {
  const wrap = el('div', 'table-scroll');
  const grid = el('table');
  const head = el('tr');
  headers.forEach(text => head.append(el('th', '', text)));
  const thead = el('thead');
  thead.append(head);
  const body = el('tbody');
  rows.forEach(cells => {
    const row = el('tr');
    cells.forEach(cell => row.append(cell instanceof Node ? (() => { const td = el('td'); td.append(cell); return td; })() : el('td', '', cell)));
    body.append(row);
  });
  grid.append(thead, body);
  wrap.append(grid);
  return wrap;
}

const name = line => line.nombre + ' · ' + line.variante;
const RENDER = {
  recepcion: op => table(['Producto', 'Llegó', 'Bodega', 'Pendiente'], op.lineas.map(line => [name(line),
    '+' + units(line.recibido, line.unidad) + (line.adicional ? ' (' + line.cantidad_adicional + ' adicionales)' : ''),
    line.stock_antes + ' → ' + line.stock_despues, String(line.pendiente)])),
  pedido_proveedor: op => table(['Producto', 'Cantidad'], op.lineas.map(line => [name(line), units(line.cantidad, line.unidad)])),
  programar_entrega: op => table(['Producto', 'Pendiente'], op.lineas.map(line => [name(line), units(line.pendiente, line.unidad)])),
  cambio_precio: op => table(['Producto', 'Antes', 'Ahora'], op.lineas.map(line => [name(line), cop(line.precio_antes), cop(line.precio_nuevo)])),
  correccion_stock: op => table(['Producto', 'Bodega', 'Apartado'], op.lineas.map(line => [name(line),
    line.stock_antes + ' → ' + line.stock_nuevo, String(line.apartado)])),
  consulta: op => table(['Producto', 'Para vender', 'Precio', 'En camino'], op.lineas.map(line => [name(line),
    units(line.disponible, line.unidad), cop(line.precio_cop), line.en_camino ? String(line.en_camino) : '—'])),
};
const SUBTITLE = {
  recepcion: op => (op.oc ? op.oc + ' · ' : '') + (op.proveedor || 'Sin proveedor') + ' · suma a la bodega al confirmar',
  pedido_proveedor: op => (op.proveedor || 'Sin proveedor') + (op.fecha_estimada ? ' · llega ' + op.fecha_estimada : '') + ' · no suma a la bodega',
  programar_entrega: op => (op.oc ? op.oc + ': ' : '') + (op.fecha_antes || 'sin fecha') + ' → ' + op.fecha_nueva + ' · no suma a la bodega',
  cambio_precio: () => 'El asistente cotiza el precio nuevo desde que confirmes',
  correccion_stock: () => 'Conteo físico: reemplaza lo que hay en bodega',
  consulta: () => 'Solo consulta: no cambia nada',
};

function operation(op) {
  const box = el('section', 'op');
  box.dataset.applicable = String(op.aplicable || op.tipo === 'consulta');
  const head = el('header', 'op-head');
  const tag = op.tipo === 'consulta' ? pill('Solo consulta', 'info', 'search')
    : op.aplicable ? pill('Se aplicará', 'success', 'check') : pill('No se aplicará', 'warning', 'alert');
  head.append(el('h3', '', op.titulo), tag);
  box.append(head, el('p', 'hint', (SUBTITLE[op.tipo] || (() => ''))(op)));
  if (op.lineas.length) box.append((RENDER[op.tipo] || RENDER.consulta)(op));
  return box;
}

function showProposal(proposal) {
  state.proposal = proposal;
  $('#proposal-card').hidden = false;
  $('#proposal-heard').textContent = '«' + proposal.texto + '»';
  $('#proposal-status').replaceChildren(pill(...(STATES.pendiente)));
  $('#proposal-ops').replaceChildren(...proposal.operaciones.map(operation));
  $('#proposal-warnings').replaceChildren(...[...proposal.advertencias, ...proposal.dudas].map(text => {
    const item = el('li');
    item.append(icon('alert'), el('span', '', text));
    return item;
  }));
  const applicable = proposal.operaciones.some(op => op.aplicable && op.tipo !== 'consulta');
  $('#proposal-apply').hidden = !applicable;
  $('#proposal-apply').disabled = !applicable;
  $('#proposal-card').scrollIntoView({behavior:'smooth', block:'start'});
}

function closeProposal(status) {
  state.proposal = null;
  $('#proposal-status').replaceChildren(pill(...(STATES[status] || STATES.descartada)));
  $('#proposal-apply').hidden = true;
  setTimeout(() => { if (!state.proposal) $('#proposal-card').hidden = true; }, 2500);
}

export async function loadAssistant() {
  const data = await api('/api/asistente/historial');
  fill($('#assist-log'), $('#assist-log-empty'), data.historial, entry => {
    const step = el('li');
    const body = el('div');
    const [label, tone] = STATES[entry.estado] || [entry.estado, ''];
    body.append(el('strong', '', entry.resumen || entry.texto), el('span', '', '«' + entry.texto + '»'), pill(label, tone));
    step.append(el('time', '', whenText(entry.hora)), body);
    return step;
  });
}

function setupVoice() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const mic = $('#assist-mic');
  if (!Recognition) {
    mic.hidden = true;
    $('#assist-mic-hint').textContent = 'Este navegador no permite dictar; escribe el mensaje.';
    return;
  }
  const recognition = state.recognition = new Recognition();
  recognition.lang = 'es-CO';
  recognition.interimResults = true;
  recognition.continuous = false;
  let base = '';
  recognition.addEventListener('result', event => {
    const heard = [...event.results].map(result => result[0].transcript).join(' ');
    $('#assist-text').value = (base + ' ' + heard).trim().slice(0, 1000);
    $('#assist-count').textContent = $('#assist-text').value.length + '/1000';
  });
  recognition.addEventListener('end', () => {
    mic.setAttribute('aria-pressed', 'false');
    mic.setAttribute('aria-label', 'Dictar por voz');
    $('#assist-mic-hint').textContent = 'Revisa el texto antes de interpretar.';
  });
  recognition.addEventListener('error', event => {
    $('#assist-mic-hint').textContent = event.error === 'not-allowed' ? 'Sin permiso para el micrófono.' : 'No se pudo dictar; escribe el mensaje.';
  });
  mic.addEventListener('click', () => {
    if (mic.getAttribute('aria-pressed') === 'true') return recognition.stop();
    base = $('#assist-text').value;
    mic.setAttribute('aria-pressed', 'true');
    mic.setAttribute('aria-label', 'Detener el dictado');
    // El navegador puede enviar el audio a su servicio de voz: se avisa antes de escuchar.
    $('#assist-mic-hint').textContent = 'Escuchando… El dictado lo procesa el navegador.';
    recognition.start();
  });
}

export function bindAssistant(refresh) {
  state.refresh = refresh;
  $('#assist-examples').replaceChildren(...EXAMPLES.map(text => {
    const node = el('button', 'chip', text);
    node.type = 'button';
    node.addEventListener('click', () => {
      $('#assist-text').value = text;
      $('#assist-count').textContent = text.length + '/1000';
      $('#assist-text').focus();
    });
    return node;
  }));
  $('#assist-text').addEventListener('input', () => { $('#assist-count').textContent = $('#assist-text').value.length + '/1000'; });
  $('#assist-form').addEventListener('submit', event => {
    event.preventDefault();
    const text = $('#assist-text').value.trim();
    if (!text) return;
    busy($('#assist-send'), async () => {
      try {
        showProposal((await api('/api/asistente/interpretar', {texto:text})).propuesta);
      } catch (error) {
        toast(error.message, 'error');
      }
    });
  });
  $('#proposal-apply').addEventListener('click', event => busy(event.currentTarget, async () => {
    try {
      const result = await api('/api/asistente/aplicar', {id:state.proposal.id});
      result.resultados.forEach(line => toast(line, 'ok'));
      closeProposal('aplicada');
      $('#assist-text').value = '';
      await state.refresh?.();
    } catch (error) {
      toast(error.message, 'error');
    }
  }));
  $('#proposal-cancel').addEventListener('click', event => busy(event.currentTarget, async () => {
    if (state.proposal) await api('/api/asistente/descartar', {id:state.proposal.id}).catch(() => null);
    closeProposal('descartada');
    await loadAssistant().catch(() => null);
  }));
  $('#proposal-fix').addEventListener('click', () => {
    $('#assist-text').focus();
    $('#assist-text').select();
  });
  setupVoice();
}
