// Hoy: indicadores, lo que necesita revisión, la cola del mostrador, la plata del día, la actividad del asistente,
// lo más vendido, la mercancía en camino y lo que está por surtir. Todo sale de /api/resumen y del inventario.
import {$, api, art, cop, dayText, el, fill, icon, plural, units, whenText} from './tendero-core.js';
import {byUrgency, orderCard} from './tendero-orders.js';
import {availabilityPill, openEditor} from './tendero-inventory.js';

const ACTIVITY_ICON = {pedido:'bag', chat:'chat', bloqueo:'shield', ayuda:'user', incidencia:'alert'};

function fact(label, value, note) {
  const box = el('div');
  const amount = el('dd', '', value);
  if (note) amount.append(el('small', '', note));
  box.append(el('dt', '', label), amount);
  return box;
}

function renderKpis(summary, low) {
  const counts = summary.por_estado;
  const sold = summary.dinero.ventas_registradas;
  $('#kpi-total').textContent = cop(sold.total_cop);
  const paid = summary.dinero.ingresos_confirmados.total_cop;
  $('#kpi-sales').textContent = plural(sold.pedidos, 'pedido entregado', 'pedidos entregados') + ' · cobrado ' + cop(paid);

  const queue = byUrgency(summary.por_recoger);
  const firstHold = queue.find(order => order.estado === 'pendiente');
  $('#kpi-pending').textContent = String(counts.pendiente);
  $('#kpi-pending-note').textContent = firstHold ? 'El primero vence ' + whenText(firstHold.aparta_hasta) : 'Nada esperando el «sí»';
  $('#kpi-pending-card').dataset.alert = String(counts.pendiente > 0);
  const nextPickup = queue.find(order => order.estado === 'confirmado' && order.recogida);
  $('#kpi-confirmed').textContent = String(counts.confirmado);
  $('#kpi-confirmed-note').textContent = nextPickup ? 'Próxima: ' + whenText(nextPickup.recogida)
    : counts.confirmado ? 'Sin hora agendada' : 'Nadie por recoger';

  const soldOut = low.filter(product => product.disponible <= 0).length;
  $('#kpi-low').textContent = String(low.length);
  $('#kpi-low-note').textContent = soldOut ? plural(soldOut, 'agotado', 'agotados') : 'Ninguno agotado';
  $('#kpi-low-card').dataset.alert = String(soldOut > 0);
  return queue;
}

function renderAttention(items) {
  $('#attention-card').hidden = !items.length;
  $('#attention-list').replaceChildren(...items.map(item => {
    const row = el('li');
    const link = el('a');
    link.href = item.enlace;
    link.append(icon(ACTIVITY_ICON[item.tipo] || 'alert'), el('span', '', item.texto));
    if (item.dato) link.append(el('b', '', item.dato));
    row.append(link);
    return row;
  }));
}

function renderMoney(money) {
  $('#money-facts').replaceChildren(
    fact('Vendido (entregado)', cop(money.ventas_registradas.total_cop), plural(money.ventas_registradas.pedidos, 'pedido', 'pedidos')),
    fact('Cobrado (confirmado)', cop(money.ingresos_confirmados.total_cop), plural(money.ingresos_confirmados.pagos, 'pago', 'pagos')),
    fact('Por verificar', cop(money.por_verificar.total_cop), plural(money.por_verificar.pagos, 'comprobante', 'comprobantes')),
    fact('Por cobrar', cop(money.por_cobrar.total_cop), plural(money.por_cobrar.pedidos, 'venta sin pago', 'ventas sin pago')));
}

function renderAgent(agent) {
  $('#agent-facts').replaceChildren(
    fact('Conversaciones', String(agent.conversaciones), plural(agent.mensajes, 'mensaje', 'mensajes')),
    fact('Pedidos del chat', String(agent.pedidos), 'registrados hoy'),
    fact('Piden al tendero', String(agent.requieren_humano), agent.atendidas_por_ti ? agent.atendidas_por_ti + ' atendidas por ti' : 'en este momento'),
    fact('Bloqueos', String(agent.bloqueos), plural(agent.incidencias, 'incidencia', 'incidencias')));
  fill($('#activity-list'), $('#activity-empty'), agent.actividad, item => {
    const step = el('li');
    const body = el('div');
    body.append(el('strong', '', item.texto));
    step.append(el('time', '', whenText(item.hora)), body);
    if (item.enlace) {
      const link = el('a', 'link', 'Ver');
      link.href = item.enlace;
      body.append(link);
    }
    return step;
  });
}

function renderTop(best) {
  const top = best[0]?.cantidad || 1;
  fill($('#top-list'), $('#top-empty'), best, line => {
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
    const when = el('span', 'pill', order.fecha_estimada ? 'Llega ' + dayText(order.fecha_estimada) : 'Sin fecha');
    when.dataset.tone = order.atrasada ? 'danger' : 'info';
    if (order.atrasada) when.textContent = 'Atrasado · ' + dayText(order.fecha_estimada);
    link.append(name, when);
    item.append(link);
    return item;
  });
}

function renderRestock(low, refresh) {
  const urgent = [...low].sort((a, b) => a.disponible - b.disponible).slice(0, 6);
  fill($('#restock-list'), $('#restock-empty'), urgent, product => {
    const item = el('li');
    const open = el('button', 'mini-row');
    open.type = 'button';
    open.setAttribute('aria-label', 'Editar ' + product.nombre + ' ' + product.variante + ': ' +
      (product.disponible ? product.disponible + ' para vender' : 'agotado'));
    const name = el('span', 'mini-name');
    const text = el('span');
    text.append(el('strong', '', product.nombre + ' · ' + product.variante),
      el('small', '', product.en_camino ? product.en_camino + ' en camino' : 'Alerta en ' + product.alerta));
    name.append(art(product.sku, 'thumb', 40), text);
    open.append(name, availabilityPill(product));
    open.addEventListener('click', () => openEditor(product, refresh));
    item.append(open);
    return item;
  });
}

export async function loadToday(refresh) {
  const [summary, low] = await Promise.all([api('/api/resumen'), api('/api/inventario?bajo=1')]);
  const queue = renderKpis(summary, low.productos);
  renderAttention(summary.revisar);
  fill($('#queue-list'), $('#queue-empty'), queue, order => orderCard(order, refresh, {compact:true}));
  renderMoney(summary.dinero);
  renderAgent(summary.asistente);
  renderTop(summary.mas_vendidos);
  renderIncoming(summary.en_camino);
  renderRestock(low.productos, refresh);
}
