// Pedidos del chat: la tarjeta que se atiende en el mostrador y la vista con filtros por estado y búsqueda.
import {$, STATUS, api, art, busy, button, clockText, cop, el, fill, icon, minutesLeft, pill, statusPill, toDate, toast,
  twoTap, units, whenText} from './tendero-core.js';
import {openPayment, paymentPill} from './tendero-payments.js';

const FILTERS = [
  ['activos', 'Por atender'], ['revisar', 'Revisar'], ['pendiente', 'Por confirmar'], ['confirmado', 'Confirmados'],
  ['entregado', 'Entregados'], ['cancelado', 'Cancelados'], ['vencido', 'Vencidos'], ['todos', 'Todos'],
];
const EMPTY = {
  activos: 'No hay pedidos por atender. Los pedidos del chat aparecen aquí solos.',
  revisar: 'Nada que revisar: ningún pago por verificar ni recogida atrasada.',
  todos: 'Todavía no han llegado pedidos por el chat.',
};
const state = {filter:'activos', query:'', orders:[], reviewCount:0};

const lastEvent = (order, status) => [...order.historial].reverse().find(event => event.estado === status);
const sentence = text => text ? text.charAt(0).toUpperCase() + text.slice(1) : '';

// Lo que el tendero necesita saber de un vistazo: cuánto le queda al apartado o cuándo pasan a recoger.
export function orderTiming(order) {
  if (order.estado === 'pendiente') {
    const left = minutesLeft(order.aparta_hasta);
    const until = toDate(order.aparta_hasta);
    const text = left === null ? 'Esperando el «sí» del cliente'
      : left <= 0 ? 'El apartado vence ya' : 'Vence en ' + left + ' min · ' + clockText(until);
    return {icon:'clock', text, urgent:true};
  }
  if (order.estado === 'confirmado') {
    return order.recogida ? {icon:'calendar', text:'Recoge ' + whenText(order.recogida)}
      : {icon:'calendar', text:'Sin hora de recogida · apartado hasta ' + whenText(order.aparta_hasta)};
  }
  const event = lastEvent(order, order.estado);
  const detail = order.estado === 'vencido' ? 'Venció sin confirmar' : sentence(event?.detalle) || STATUS[order.estado]?.label;
  return {icon:STATUS[order.estado]?.icon || 'alert', text:detail + (event ? ' · ' + whenText(event.hora) : '')};
}

// Pedidos activos por urgencia: primero los apartados que vencen antes, luego las recogidas más cercanas.
export function byUrgency(orders) {
  const key = order => order.estado === 'pendiente' ? [0, toDate(order.aparta_hasta)?.getTime() ?? 0]
    : [1, toDate(order.recogida || order.aparta_hasta)?.getTime() ?? Infinity];
  return [...orders].sort((a, b) => {
    const [x, y] = [key(a), key(b)];
    return x[0] - y[0] || x[1] - y[1];
  });
}

export function orderCard(order, refresh, {compact = false} = {}) {
  const card = el('article', 'order');
  card.dataset.status = order.estado;
  const code = el('h3', 'order-code', order.pedido);
  code.id = 'pedido-' + order.pedido;
  card.setAttribute('aria-labelledby', code.id);

  const head = el('header', 'order-head');
  const title = el('div', 'order-title');
  title.append(code, statusPill(order.estado));
  const total = el('div', 'order-total');
  total.append(el('span', '', 'Total'), el('strong', '', cop(order.total_cop)));
  head.append(title, total);

  const timing = orderTiming(order);
  const when = el('p', 'order-when' + (timing.urgent ? ' is-urgent' : ''));
  when.append(icon(timing.icon), el('span', '', timing.text));
  const review = el('div', 'order-review');
  review.setAttribute('role', 'note');
  (order.revisar || []).forEach(reason => {
    const line = el('span');
    line.append(icon('alert'), el('span', '', reason));
    review.append(line);
  });

  const lines = el('ul', 'order-lines');
  order.lineas.forEach(line => {
    const row = el('li');
    const what = el('span', 'line-what');
    const text = el('span');
    text.append(el('b', '', units(line.cantidad, line.unidad)), el('em', '', line.nombre + ' · ' + line.variante),
      el('small', '', line.sku));
    what.append(art(line.sku, 'thumb', 34), text);
    row.append(what, el('span', 'line-sub', cop(line.subtotal_cop)));
    lines.append(row);
  });
  card.append(head, when);
  if (review.children.length) card.append(review);
  card.append(lines);
  if (order.pago && typeof order.pago === 'object') card.append(paymentRow(order, refresh));

  if (order.nota) {
    const note = el('p', 'order-note');
    note.append(icon('chat'), el('span', '', order.nota));
    card.append(note);
  }
  const meta = el('p', 'order-meta');
  const chat = el('a', '', 'Conversación ' + order.conversacion);
  chat.href = '#conversaciones/' + order.conversacion;
  meta.append(pill('Lo registró el asistente', 'info', 'bot'), chat, el('span', '', 'pedido ' + whenText(order.creado)));
  card.append(meta);

  if (!compact && order.historial.length) {
    const history = el('details', 'order-history');
    history.append(el('summary', '', 'Historial (' + order.historial.length + ')'));
    const steps = el('ol', 'timeline compact');
    order.historial.forEach(event => {
      const step = el('li');
      step.append(el('time', '', whenText(event.hora)), el('span', '', sentence(event.detalle)));
      steps.append(step);
    });
    history.append(steps);
    card.append(history);
  }

  if (order.estado === 'pendiente' || order.estado === 'confirmado') {
    const actions = el('div', 'order-actions');
    const deliver = button('primary', 'Entregar', 'check');
    deliver.setAttribute('aria-label', 'Marcar entregado el pedido ' + order.pedido);
    deliver.addEventListener('click', () => busy(deliver, () => act('/api/pedidos/entregar', order,
      'Pedido ' + order.pedido + ' entregado. Ya se descontó de la bodega.', refresh)));
    const cancel = button('danger ghost', 'Cancelar', 'x');
    cancel.setAttribute('aria-label', 'Cancelar el pedido ' + order.pedido);
    twoTap(cancel, 'Toca otra vez para cancelar', () => act('/api/pedidos/cancelar', order,
      'Pedido ' + order.pedido + ' cancelado. Sus productos vuelven a estar disponibles.', refresh));
    actions.append(deliver, cancel);
    card.append(actions);
  }
  return card;
}

function paymentRow(order, refresh) {
  const row = el('div', 'order-pay');
  const info = el('span');
  info.append(el('span', '', 'Pago:'), paymentPill(order.pago));
  if (order.pago.metodo_texto) info.append(el('span', '', order.pago.metodo_texto));
  row.append(info);
  if (order.pago.estado !== 'confirmado' && order.estado !== 'cancelado' && order.estado !== 'vencido') {
    const open = button('secondary small', order.pago.estado === 'pendiente' ? 'Registrar pago' : 'Actualizar pago', 'cash');
    open.setAttribute('aria-label', 'Registrar el pago del pedido ' + order.pedido);
    open.addEventListener('click', () => openPayment(order, refresh));
    row.append(open);
  }
  return row;
}

async function act(path, order, done, refresh) {
  try {
    await api(path, {pedido:order.pedido});
    toast(done, 'ok');
  } catch (error) {
    toast(error.message, 'error');
  }
  await refresh();
}

function matches(order, query) {
  if (!query) return true;
  const text = [order.pedido, order.nota || '', ...order.lineas.map(line => line.nombre + ' ' + line.variante + ' ' + line.sku)]
    .join(' ').toLocaleLowerCase('es');
  return query.split(/\s+/).every(word => text.includes(word));
}

function renderFilters(counts, refresh) {
  const group = $('#order-filter');
  const total = Object.values(counts).reduce((sum, value) => sum + value, 0);
  const amount = {activos:counts.pendiente + counts.confirmado, todos:total, revisar:state.reviewCount, ...counts};
  group.replaceChildren(...FILTERS.map(([key, label]) => {
    const chip = el('button');
    chip.type = 'button';
    chip.setAttribute('aria-pressed', String(key === state.filter));
    chip.append(el('span', '', label), el('b', 'count', String(amount[key] ?? 0)));
    chip.addEventListener('click', () => { state.filter = key; refresh(); });
    return chip;
  }));
}

function renderOrders(refresh) {
  const shown = state.orders.filter(order => matches(order, state.query));
  fill($('#order-list'), $('#orders-empty'), shown, order => orderCard(order, refresh));
  $('#orders-empty-title').textContent = state.query ? 'Sin coincidencias' : 'No hay pedidos';
  $('#orders-empty-text').textContent = state.query ? 'Ningún pedido coincide con «' + state.query + '».'
    : EMPTY[state.filter] || 'No hay pedidos en «' + FILTERS.find(([key]) => key === state.filter)[1] + '».';
}

export async function loadOrders(refresh, filter) {
  if (filter) state.filter = filter;
  const summary = api('/api/resumen');
  let orders;
  if (state.filter === 'activos') {
    const [pending, confirmed] = await Promise.all(['pendiente', 'confirmado'].map(status =>
      api('/api/pedidos?estado=' + status)));
    orders = byUrgency([...pending.pedidos, ...confirmed.pedidos]);
  } else if (state.filter === 'revisar') {
    orders = (await api('/api/pedidos?revisar=1')).pedidos;
  } else {
    const query = state.filter === 'todos' ? '' : '?estado=' + encodeURIComponent(state.filter);
    orders = (await api('/api/pedidos' + query)).pedidos;
  }
  state.orders = orders;
  const totals = await summary;
  state.reviewCount = totals.revisar_pedidos;
  renderFilters(totals.por_estado, refresh);
  renderOrders(refresh);
}

export function bindOrderSearch(refresh) {
  $('#order-search').addEventListener('input', event => {
    state.query = event.target.value.trim().toLocaleLowerCase('es');
    renderOrders(refresh);
  });
}
