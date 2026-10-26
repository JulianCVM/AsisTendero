// Chats: lista de conversaciones con su estado de atención, el detalle con los mensajes, los pedidos y el bloqueo, y
// las acciones del tendero (tomar, responder, devolver al asistente, finalizar, bloquear y levantar un bloqueo).
// Las acciones posibles las decide el servidor (handoff.actions); aquí solo se pintan.
import {$, STATUS, api, busy, button, cop, el, fill, icon, pill, plural, showError, toast, twoTap, whenText} from './tendero-core.js';

const ATTENTION = {
  ia: {label:'Atiende el asistente', tone:'info', icon:'bot'},
  requiere_humano: {label:'Pide al tendero', tone:'warning', icon:'user'},
  tendero: {label:'La atiendes tú', tone:'success', icon:'user'},
  finalizada: {label:'Finalizada', tone:'', icon:'check'},
};
const FILTERS = [['', 'Todas'], ['requiere_humano', 'Piden al tendero'], ['tendero', 'Atiendes tú'], ['bloqueadas', 'Bloqueadas'],
  ['ia', 'Asistente'], ['finalizada', 'Finalizadas']];
const ACTIONS = {
  tomar: {label:'Tomar el chat', css:'primary', icon:'user', path:'/api/conversaciones/tomar', done:'Ahora atiendes tú: el asistente no responde.'},
  devolver: {label:'Devolver al asistente', css:'secondary', icon:'bot', path:'/api/conversaciones/devolver', done:'El asistente vuelve a atender.'},
  finalizar: {label:'Finalizar', css:'ghost', icon:'check', path:'/api/conversaciones/finalizar', done:'Conversación finalizada.'},
  desbloquear: {label:'Levantar el bloqueo', css:'secondary', icon:'lock', path:'/api/bloqueos/levantar', done:'Bloqueo levantado.'},
};
// Solo se marcan los turnos que el tendero debería mirar; una respuesta normal no lleva etiqueta.
const TURN_FLAGS = {
  handoff:['Pidió al tendero', 'warning'], staff:['Lo atiendes tú', 'info'], blocked:['Bloqueado', 'danger'],
  refused:['No se entregó', 'warning'], tool_error:['Catálogo no disponible', 'danger'], not_verified:['Sin verificar', 'warning'],
  model_error:['Falla del modelo', 'danger'], model_invalid:['Respuesta no válida', 'danger'],
  limit_reached:['Límite de consultas', 'danger'], quote_error:['Cotización no disponible', 'danger'],
};
const state = {filter:'', query:'', open:'', refresh:null, timer:null};

const attentionPill = key => {
  const info = ATTENTION[key] || {label:key, tone:''};
  return pill(info.label, info.tone, info.icon);
};

function listItem(chat) {
  const item = el('li');
  const link = el('a', 'chat-item');
  link.href = '#conversaciones/' + chat.id;
  if (chat.id === state.open || chat.id_corto === state.open) link.setAttribute('aria-current', 'true');
  const avatar = el('span', 'chat-avatar' + (chat.en_vivo ? ' is-live' : ''));
  avatar.append(icon(chat.bloqueo ? 'shield' : 'chat'));
  if (chat.en_vivo) avatar.setAttribute('aria-label', 'Activa en los últimos 15 minutos');
  const body = el('span', 'chat-item-body');
  const top = el('span', 'chat-top');
  top.append(el('strong', '', 'Cliente ' + chat.id_corto), el('time', 'chat-when', whenText(chat.ultima_actividad)));
  const tags = el('span', 'chat-tags');
  tags.append(chat.bloqueo ? pill(chat.bloqueo.tipo === 'manual' ? 'Bloqueada por ti' : 'Bloqueada', 'danger', 'shield')
    : attentionPill(chat.atencion));
  if (chat.incidencias) tags.append(pill(plural(chat.incidencias, 'incidencia', 'incidencias'), 'warning', 'alert'));
  if (chat.pedidos.length) tags.append(pill(plural(chat.pedidos.length, 'pedido', 'pedidos'), '', 'bag'));
  body.append(top, el('span', 'chat-preview', chat.vista_previa || 'Sin mensajes del cliente'), tags);
  link.append(avatar, body);
  item.append(link);
  return item;
}

function bubble(message) {
  const item = el('li', 'bubble');
  if (message.tipo === 'tendero') {
    item.classList.add('from-staff');
    item.append(el('small', '', 'Tú · ' + whenText(message.hora)), el('p', '', message.texto));
    return [item];
  }
  const customer = el('li', 'bubble from-customer');
  customer.append(el('small', '', 'Cliente · ' + whenText(message.hora)), el('p', '', message.cliente || '(mensaje vacío)'));
  const agent = el('li', 'bubble from-agent');
  const label = el('small', '', 'Asistente · turno ' + message.numero);
  const flag = TURN_FLAGS[message.estado];
  if (flag) label.append(' · ', pill(flag[0], flag[1]));
  agent.append(label, el('p', '', message.asistente));
  return [customer, agent];
}

function banBox(ban) {
  const box = el('div', 'callout' + (ban.vigente ? '' : ' is-soft'));
  box.append(icon('shield'));
  const text = el('div');
  text.append(el('strong', '', (ban.vigente ? 'Bloqueada ' : 'Estuvo bloqueada ') + (ban.tipo === 'manual' ? 'por ti' : 'automáticamente') +
    ' · ' + whenText(ban.desde)), el('p', '', ban.regla));
  if (ban.extracto) text.append(el('p', '', 'Evidencia: «' + ban.extracto + '»'));
  if (ban.codigo && ban.tipo !== 'manual') text.append(el('small', '', 'Código ' + ban.codigo + (ban.tecnica ? ' · ' + ban.tecnica : '')));
  if (ban.levantado) text.append(el('small', '', 'Levantado ' + whenText(ban.levantado)));
  box.append(text);
  return box;
}

async function act(path, body, done) {
  try {
    await api(path, body);
    toast(done, 'ok');
  } catch (error) {
    toast(error.message, 'error');
  }
  await state.refresh?.();
}

function banForm(chat) {
  const form = el('form', 'chat-ban');
  const label = el('label', 'field');
  const reason = el('input');
  reason.maxLength = 200;
  reason.required = true;
  reason.placeholder = 'Por qué la bloqueas (lo verás en el historial)';
  label.append(el('span', '', 'Motivo del bloqueo'), reason);
  const error = el('p', 'form-error');
  error.hidden = true;
  const submit = button('danger', 'Bloquear', 'shield');
  submit.type = 'submit';
  form.append(label, error, submit);
  form.addEventListener('submit', event => {
    event.preventDefault();
    if (!reason.value.trim()) return showError(error, 'Escribe el motivo.');
    busy(submit, () => act('/api/conversaciones/bloquear', {sesion:chat.id, motivo:reason.value.trim()},
      'Conversación bloqueada; sus pedidos activos se cancelaron.'));
  });
  return form;
}

function actions(chat) {
  const row = $('#chat-actions');
  row.replaceChildren();
  chat.acciones.filter(name => ACTIONS[name]).forEach(name => {
    const info = ACTIONS[name];
    const node = button(info.css, info.label, info.icon);
    if (name === 'finalizar') {
      twoTap(node, 'Toca otra vez para finalizar', () => act(info.path, {sesion:chat.id}, info.done));
    } else {
      node.addEventListener('click', () => busy(node, () => act(info.path, {sesion:chat.id}, info.done)));
    }
    row.append(node);
  });
  $('#chat-reply').hidden = !chat.acciones.includes('responder');
  if (chat.acciones.includes('bloquear')) {
    const details = el('details', 'chat-ban-box');
    details.append(el('summary', '', 'Bloquear esta conversación'), banForm(chat));
    row.append(details);
  }
}

function renderDetail(chat) {
  state.open = chat.id;
  $('#chat-layout').dataset.open = 'true';
  $('#chat-detail').hidden = false;
  $('#chat-title').textContent = 'Cliente ' + chat.id_corto;
  $('#chat-meta').textContent = 'Desde ' + whenText(chat.creada) + ' · ' + plural(chat.turnos_total, 'mensaje', 'mensajes') +
    (chat.en_vivo ? ' · activa ahora' : '');
  $('#chat-state').replaceChildren(attentionPill(chat.atencion.estado));
  const alerts = [];
  if (chat.bloqueo) alerts.push(banBox(chat.bloqueo));
  if (chat.atencion.estado === 'requiere_humano') {
    const last = chat.atencion.historial.at(-1);
    const box = el('div', 'callout is-soft');
    box.append(icon('user'), el('p', '', 'Pide hablar con el tendero' + (last?.motivo ? ': ' + last.motivo : '') + '. Tómalo para responderle.'));
    alerts.push(box);
  }
  $('#chat-alerts').replaceChildren(...alerts);
  const transcript = $('#chat-transcript');
  const atBottom = transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight < 40;
  transcript.replaceChildren(...chat.mensajes.flatMap(bubble));
  if (atBottom) transcript.scrollTop = transcript.scrollHeight;
  $('#chat-orders').replaceChildren(...chat.pedidos.map(order => {
    const row = el('a', 'mini-row');
    row.href = '#pedidos';
    const name = el('span', 'mini-name');
    name.append(icon('bag'), el('span', '', order.pedido + ' · ' + cop(order.total_cop)));
    row.append(name, pill(STATUS[order.estado]?.label || order.estado));
    return row;
  }));
  actions(chat);
}

function closeDetail() {
  state.open = '';
  delete $('#chat-layout').dataset.open;
  $('#chat-detail').hidden = true;
}

export async function loadChats(sub, refresh) {
  state.refresh = refresh;
  const query = new URLSearchParams({q:state.query});
  if (state.filter && state.filter !== 'bloqueadas') query.set('estado', state.filter);
  const data = await api('/api/conversaciones?' + query);
  const counts = data.conteo;
  $('#chat-filter').replaceChildren(...FILTERS.map(([key, label]) => {
    const chip = el('button');
    chip.type = 'button';
    chip.setAttribute('aria-pressed', String(key === state.filter));
    chip.append(el('span', '', label));
    const amount = key === '' ? counts.total : counts[key] || 0;
    if (amount) chip.append(el('b', 'count', String(amount)));
    chip.addEventListener('click', () => { state.filter = key; refresh(); });
    return chip;
  }));
  const shown = state.filter === 'bloqueadas' ? data.conversaciones.filter(chat => chat.bloqueo) : data.conversaciones;
  fill($('#chat-list'), $('#chats-empty'), shown, listItem);
  $('#chats-empty-title').textContent = state.query ? 'Sin coincidencias' : 'Sin conversaciones';
  $('#chats-empty-text').textContent = state.query ? 'Prueba con otro código o palabra.'
    : 'Cuando un cliente escriba por el chat, la verás aquí.';
  if (!sub) return closeDetail();
  try {
    renderDetail((await api('/api/conversacion?id=' + encodeURIComponent(sub))).conversacion);
  } catch (error) {
    closeDetail();
    toast(error.message, 'error');
  }
}

export function bindChats(refresh) {
  $('#chat-search').addEventListener('input', () => {
    clearTimeout(state.timer);
    state.timer = setTimeout(() => { state.query = $('#chat-search').value.trim(); refresh(); }, 300);
  });
  $('#chat-back').addEventListener('click', () => { location.hash = '#conversaciones'; });
  $('#chat-reply').addEventListener('submit', event => {
    event.preventDefault();
    const text = $('#chat-reply-text').value.trim();
    if (!text) return;
    busy(event.submitter, async () => {
      try {
        await api('/api/conversaciones/responder', {sesion:state.open, texto:text});
        $('#chat-reply-text').value = '';
        toast('Mensaje enviado: el cliente lo ve en su siguiente consulta.', 'ok');
      } catch (error) {
        toast(error.message, 'error');
      }
      await refresh();
    });
  });
}
