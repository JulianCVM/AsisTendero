// Pedidos del chat: la fila que se atiende en el mostrador y la vista con tres filtros y búsqueda.
import {$, STATUS, api, art, busy, button, clockText, cop, el, fill, icon, minutesLeft, pill, statusPill, toDate, toast,
  twoTap, units, whenText} from './tendero-core.js';
import {openPayment, paymentPill} from './tendero-payments.js';

// Tres preguntas del tendero: qué atiendo ahora, qué tengo que revisar y qué pasó antes (con su estado).
const FILTERS = [['activos', 'Por atender'], ['revisar', 'Revisar'], ['historial', 'Historial']];
const HISTORY = [['todos', 'Todos los estados'], ['entregado', 'Entregados'], ['cancelado', 'Cancelados'],
  ['vencido', 'Vencidos'], ['pendiente', 'Por confirmar'], ['confirmado', 'Confirmados']];
const EMPTY = {
  activos: 'No hay pedidos por atender. Los pedidos del chat aparecen aquí solos.',
  revisar: 'Nada que revisar: ningún pago por verificar ni recogida atrasada.',
  historial: 'Todavía no han llegado pedidos por el chat.',
};
const state = {filter:'activos', status:'todos', query:'', orders:[], reviewCount:0};

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

// Un pedido es una fila: código y estado, cuándo, qué lleva, total y pago, con las acciones a la vista. Las líneas,
// la nota y el historial se abren en «Detalle» para que la lista se lea de un vistazo.
export function orderCard(order, refresh) {
  const card = el('article', 'order order-row');
  card.dataset.status = order.estado;
  const code = el('h3', 'order-code', order.pedido);
  code.id = 'pedido-' + order.pedido;
  card.setAttribute('aria-labelledby', code.id);

  const main = el('div', 'order-main');
  const title = el('div', 'order-title');
  title.append(code, statusPill(order.estado));
  const timing = orderTiming(order);
  const when = el('p', 'order-when' + (timing.urgent ? ' is-urgent' : ''));
  when.append(icon(timing.icon), el('span', '', timing.text));
  const items = order.lineas.map(line => units(line.cantidad, line.unidad) + ' ' + line.nombre + ' ' + line.variante);
  main.append(title, when, el('p', 'order-items', items.join(' · ')));

  const side = el('div', 'order-side');
  side.append(el('strong', 'order-amount', cop(order.total_cop)));
  if (order.pago && typeof order.pago === 'object') side.append(paymentPill(order.pago));
  card.append(main, side);

  if ((order.revisar || []).length) {
    const review = el('div', 'order-review');
    review.setAttribute('role', 'note');
    order.revisar.forEach(reason => {
      const line = el('span');
      line.append(icon('alert'), el('span', '', reason));
      review.append(line);
    });
    card.append(review);
  }
  card.append(orderActions(order, refresh), orderDetail(order));
  return card;
}

function orderActions(order, refresh) {
  const actions = el('div', 'order-actions');
  const open = order.estado === 'pendiente' || order.estado === 'confirmado';
  if (open) {
    const deliver = button('primary small', 'Entregar', 'check');
    deliver.setAttribute('aria-label', 'Marcar entregado el pedido ' + order.pedido);
    deliver.addEventListener('click', () => busy(deliver, () => act('/api/pedidos/entregar', order,
      'Pedido ' + order.pedido + ' entregado. Ya se descontó de la bodega.', refresh)));
    actions.append(deliver);
  }
  if (order.pago && typeof order.pago === 'object' && order.pago.estado !== 'confirmado'
      && order.estado !== 'cancelado' && order.estado !== 'vencido') {
    const pay = button('secondary small', order.pago.estado === 'pendiente' ? 'Registrar pago' : 'Actualizar pago', 'cash');
    pay.setAttribute('aria-label', 'Registrar el pago del pedido ' + order.pedido);
    pay.addEventListener('click', () => openPayment(order, refresh));
    actions.append(pay);
  }
  if (open) {
    const cancel = button('danger ghost small', 'Cancelar', 'x');
    cancel.setAttribute('aria-label', 'Cancelar el pedido ' + order.pedido);
    twoTap(cancel, 'Toca otra vez para cancelar', () => act('/api/pedidos/cancelar', order,
      'Pedido ' + order.pedido + ' cancelado. Sus productos vuelven a estar disponibles.', refresh));
    actions.append(cancel);
  }
  return actions;
}

function orderDetail(order) {
  const detail = el('details', 'order-detail');
  detail.append(el('summary', '', 'Detalle'));
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
  detail.append(lines);
  if (order.pago && typeof order.pago === 'object' && order.pago.metodo_texto) {
    detail.append(el('p', 'order-meta', 'Pago: ' + order.pago.metodo_texto));
  }
  if (order.nota) {
    const note = el('p', 'order-note');
    note.append(icon('chat'), el('span', '', order.nota));
    detail.append(note);
  }
  const meta = el('p', 'order-meta');
  const chat = el('a', '', 'Conversación ' + order.conversacion);
  chat.href = '#conversaciones/' + order.conversacion;
  meta.append(pill('Lo registró AsisTendero', 'info', 'bot'), chat, el('span', '', 'pedido ' + whenText(order.creado)));
  detail.append(meta);
  if (order.historial.length) {
    const steps = el('ol', 'timeline compact');
    order.historial.forEach(event => {
      const step = el('li');
      step.append(el('time', '', whenText(event.hora)), el('span', '', sentence(event.detalle)));
      steps.append(step);
    });
    detail.append(steps);
  }
  return detail;
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
  const total = Object.values(counts).reduce((sum, value) => sum + value, 0);
  const amount = {activos:counts.pendiente + counts.confirmado, revisar:state.reviewCount, historial:total};
  $('#order-filter').replaceChildren(...FILTERS.map(([key, label]) => {
    const chip = el('button');
    chip.type = 'button';
    chip.setAttribute('aria-pressed', String(key === state.filter));
    chip.append(el('span', '', label), el('b', 'count', String(amount[key] ?? 0)));
    chip.addEventListener('click', () => { state.filter = key; refresh(); });
    return chip;
  }));
  $('#order-status-box').hidden = state.filter !== 'historial';
  const select = $('#order-status');
  if (!select.options.length) {
    HISTORY.forEach(([key, label]) => select.append(new Option(label, key)));
    select.addEventListener('change', () => { state.status = select.value; refresh(); });
  }
  select.value = state.status;
}

function renderOrders(refresh) {
  const shown = state.orders.filter(order => matches(order, state.query));
  fill($('#order-list'), $('#orders-empty'), shown, order => orderCard(order, refresh));
  $('#orders-empty-title').textContent = state.query ? 'Sin coincidencias' : 'No hay pedidos';
  $('#orders-empty-text').textContent = state.query ? 'Ningún pedido coincide con «' + state.query + '».'
    : state.filter === 'historial' && state.status !== 'todos'
      ? 'No hay pedidos en «' + HISTORY.find(([key]) => key === state.status)[1] + '».' : EMPTY[state.filter];
}

export async function loadOrders(refresh, filter) {
  // Desde Hoy llega «activos», «revisar» o un estado («pendiente»): un estado abre el historial ya filtrado.
  if (filter && FILTERS.some(([key]) => key === filter)) state.filter = filter;
  else if (filter && HISTORY.some(([key]) => key === filter)) [state.filter, state.status] = ['historial', filter];
  const summary = api('/api/resumen');
  let orders;
  if (state.filter === 'activos') {
    const [pending, confirmed] = await Promise.all(['pendiente', 'confirmado'].map(status =>
      api('/api/pedidos?estado=' + status)));
    orders = byUrgency([...pending.pedidos, ...confirmed.pedidos]);
  } else if (state.filter === 'revisar') {
    orders = (await api('/api/pedidos?revisar=1')).pedidos;
  } else {
    const query = state.status === 'todos' ? '' : '?estado=' + encodeURIComponent(state.status);
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
