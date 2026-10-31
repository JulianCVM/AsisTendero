// Hoy: las cifras del día en una franja y, debajo, la bandeja «Por hacer» que arma el servidor (bandeja.py) con lo
// accionable en orden de urgencia. Al lado, lo que hizo AsisTendero, la mercancía en camino y lo más vendido.
import {$, api, busy, cop, dayText, el, fill, foldList, icon, pill, plural, toast, units, whenText} from './tendero-core.js';
import {orderTiming} from './tendero-orders.js';
import {openPayment} from './tendero-payments.js';

const PRIORITY = {
  urgente: {label:'Urgente', tone:'danger', icon:'alert'},
  revisar: {label:'Revisar', tone:'warning', icon:'search'},
  hoy: {label:'Hoy', tone:'info', icon:'calendar'},
  aviso: {label:'Aviso', tone:'', icon:'truck'},
};
// El aviso de la bodega lleva la caja; el de un proveedor atrasado, el camión.
const NOTICE_ICON = {agotados:'box', proveedor:'truck'};
const INBOX_SHOWN = 6;

function stripFact(label, value, note, href, filter, alert) {
  const link = el('a', 'day-fact');
  link.href = href;
  if (filter) link.dataset.filter = filter;
  if (alert) link.dataset.alert = 'true';
  link.append(el('span', 'day-fact-label', label), el('strong', 'day-fact-value', value), el('span', 'day-fact-note', note));
  return link;
}

function renderStrip(summary) {
  const money = summary.dinero;
  const counts = summary.por_estado;
  const unpaid = money.por_cobrar.total_cop;
  const toCheck = money.por_verificar.pagos;
  const queue = summary.bandeja;
  const stockLine = queue.find(item => item.tipo === 'agotados');
  $('#day-strip').replaceChildren(
    stripFact('Vendido hoy', cop(money.ventas_registradas.total_cop),
      'Cobrado ' + cop(money.ingresos_confirmados.total_cop), '#ventas'),
    stripFact('Por cobrar', cop(unpaid), toCheck ? plural(toCheck, 'comprobante por verificar', 'comprobantes por verificar')
      : plural(money.por_cobrar.pedidos, 'venta sin pago', 'ventas sin pago'), '#ventas', null, unpaid > 0),
    stripFact('Pedidos activos', String(counts.pendiente + counts.confirmado),
      counts.pendiente + ' por confirmar · ' + counts.confirmado + ' por recoger', '#pedidos', 'activos', counts.pendiente > 0),
    stripFact('Bodega', stockLine ? stockLine.titulo : 'Todo surtido', stockLine?.detalle[0] || 'Nada agotado ni por surtir',
      '#inventario', stockLine?.filtro, Boolean(stockLine)));
}

function orderSummary(order) {
  const lines = order.lineas.map(line => units(line.cantidad, line.unidad) + ' ' + line.nombre);
  return lines.slice(0, 2).join(' · ') + (lines.length > 2 ? ' y ' + (lines.length - 2) + ' más' : '') + ' · ' + cop(order.total_cop);
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

// Lo que se puede hacer sin salir de Hoy: entregar lo confirmado, registrar un pago o abrir el chat que espera.
function itemActions(item, refresh) {
  const actions = el('div', 'inbox-actions');
  const order = item.pedido;
  if (order && order.estado === 'confirmado') {
    const deliver = el('button', 'primary small');
    deliver.type = 'button';
    deliver.append(icon('check'), el('span', '', 'Entregar'));
    deliver.setAttribute('aria-label', 'Marcar entregado el pedido ' + order.pedido);
    deliver.addEventListener('click', () => busy(deliver, () => act('/api/pedidos/entregar', order,
      'Pedido ' + order.pedido + ' entregado. Ya se descontó de la bodega.', refresh)));
    actions.append(deliver);
  }
  if (order && order.pago && order.pago.estado !== 'confirmado' && order.estado !== 'pendiente') {
    const pay = el('button', 'secondary small');
    pay.type = 'button';
    pay.append(icon('cash'), el('span', '', order.pago.estado === 'pendiente' ? 'Registrar pago' : 'Revisar pago'));
    pay.setAttribute('aria-label', 'Registrar el pago del pedido ' + order.pedido);
    pay.addEventListener('click', () => openPayment(order, refresh));
    actions.append(pay);
  }
  const open = el('a', 'link', order ? 'Ver pedido' : item.tipo === 'chat' ? 'Abrir chat' : 'Ver');
  open.href = order ? '#pedidos' : item.enlace;
  if (item.filtro) open.dataset.filter = item.filtro;
  if (order) open.dataset.filter = order.estado === 'entregado' ? 'revisar' : 'activos';
  open.append(icon('arrow'));
  actions.append(open);
  return actions;
}

function inboxItem(item, refresh) {
  const row = el('li', 'inbox-item');
  row.dataset.priority = item.prioridad;
  const info = PRIORITY[item.prioridad];
  const body = el('div', 'inbox-body');
  body.append(el('strong', 'inbox-title', item.titulo));
  const details = [...item.detalle];
  if (item.pedido) {
    const timing = orderTiming(item.pedido);
    // El primer motivo ya es el título de un pedido por revisar: no se repite debajo.
    if (item.prioridad === 'revisar') details.shift();
    details.unshift(timing.text);
    body.append(el('span', 'inbox-detail', orderSummary(item.pedido)));
  }
  details.forEach(text => body.append(el('span', 'inbox-detail', text)));
  row.append(pill(info.label, info.tone, NOTICE_ICON[item.tipo] || info.icon), body, itemActions(item, refresh));
  return row;
}

function fact(label, value, note) {
  const box = el('div');
  const amount = el('dd', '', value);
  if (note) amount.append(el('small', '', note));
  box.append(el('dt', '', label), amount);
  return box;
}

function renderAgent(agent) {
  $('#agent-facts').replaceChildren(
    fact('Conversaciones', String(agent.conversaciones), plural(agent.mensajes, 'mensaje', 'mensajes')),
    fact('Pedidos del chat', String(agent.pedidos), 'registrados hoy'),
    fact('Piden al tendero', String(agent.requieren_humano), agent.atendidas_por_ti ? agent.atendidas_por_ti + ' atendidas por ti' : 'en este momento'),
    fact('Bloqueos', String(agent.bloqueos), plural(agent.incidencias, 'incidencia', 'incidencias')));
  fill($('#activity-list'), $('#activity-empty'), agent.actividad, item => {
    const step = el('li');
    // Con enlace, toda la fila se toca (no un «Ver» chiquito debajo del texto).
    const body = el(item.enlace ? 'a' : 'div', item.enlace ? 'activity-link' : '');
    if (item.enlace) body.href = item.enlace;
    body.append(el('strong', '', item.texto));
    if (item.enlace) body.append(icon('arrow'));
    step.append(el('time', '', whenText(item.hora)), body);
    return step;
  });
  foldList($('#activity-list'), $('#activity-more'), 3, 'movimientos');
}

function renderTop(best) {
  const top = best[0]?.cantidad || 1;
  fill($('#top-list'), $('#top-empty'), best.slice(0, 5), line => {
    const item = el('li');
    const bar = el('span', 'rank-bar');
    // El ancho sale de los datos; se fija con CSSOM porque la CSP no permite atributos style.
    bar.style.setProperty('--share', String(line.cantidad / top));
    item.append(el('span', 'rank-name', line.nombre + ' · ' + line.variante),
      el('span', 'rank-amount', units(line.cantidad, line.unidad)), bar);
    return item;
  });
}

function renderIncoming(orders) {
  fill($('#incoming-list'), $('#incoming-empty'), orders, order => {
    const item = el('li');
    const link = el('a', 'mini-row');
    link.href = '#inventario/abastecimiento';
    const name = el('span', 'mini-name');
    const text = el('span');
    text.append(el('strong', '', order.proveedor + ' · ' + order.oc),
      el('small', '', plural(order.pendiente, 'unidad pendiente', 'unidades pendientes') + ' de ' +
        plural(order.productos, 'producto', 'productos')));
    name.append(icon('truck'), text);
    const when = pill(order.atrasada ? 'Atrasado · ' + dayText(order.fecha_estimada)
      : order.fecha_estimada ? 'Llega ' + dayText(order.fecha_estimada) : 'Sin fecha', order.atrasada ? 'danger' : 'info');
    link.append(name, when);
    item.append(link);
    return item;
  });
}

export async function loadToday(refresh) {
  const summary = await api('/api/resumen');
  renderStrip(summary);
  const queue = summary.bandeja;
  fill($('#inbox-list'), $('#inbox-empty'), queue, item => inboxItem(item, refresh));
  // Lo más urgente queda a la vista; el resto se pliega para que el celular no sea una lista sin fin.
  foldList($('#inbox-list'), $('#inbox-more'), INBOX_SHOWN, 'pendientes');
  const urgent = queue.filter(item => item.prioridad === 'urgente').length;
  $('#inbox-count').textContent = queue.length ? plural(queue.length, 'pendiente', 'pendientes') +
    (urgent ? ' · ' + plural(urgent, 'urgente', 'urgentes') : '') : '';
  renderAgent(summary.asistente);
  renderTop(summary.mas_vendidos);
  renderIncoming(summary.en_camino);
}
