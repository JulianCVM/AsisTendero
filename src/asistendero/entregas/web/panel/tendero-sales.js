// Ventas y pagos: filtros por fecha, método y estado; indicadores que separan lo vendido de lo cobrado; el reparto por
// método y la tabla de transacciones (cada una es un pedido identificable del chat).
import {$, STATUS, api, cop, el, fill, pill, plural, todayKey, units, whenText} from './tendero-core.js';
import {PAY_STATES, paymentPill} from './tendero-payments.js';

const state = {bound:false, options:false};

function kpi(label, value, note, tone) {
  const card = el('div', 'kpi');
  if (tone === 'brand') card.classList.add('is-brand');
  if (tone === 'alert') card.dataset.alert = 'true';
  card.append(el('span', 'kpi-label', label), el('strong', 'kpi-value', value), el('span', 'kpi-note', note));
  return card;
}

function fillOptions(data) {
  if (state.options) return;
  state.options = true;
  Object.entries(data.metodos).forEach(([key, label]) => $('#sales-method').append(new Option(label, key)));
  data.estados_pago.forEach(key => $('#sales-pay').append(new Option(PAY_STATES[key]?.label || key, key)));
  data.estados_pedido.forEach(key => $('#sales-order').append(new Option(STATUS[key]?.label || key, key)));
}

function cell(className, ...content) {
  const node = el('td', className);
  node.setAttribute('role', 'cell');
  node.append(...content);
  return node;
}

// Una transacción es una fila de la misma tabla que el inventario (en el celular, un bloque de dos renglones). Toda la
// celda del pedido lleva a su conversación, para que el enlace tenga tamaño de dedo y no solo el código.
function transaction(item) {
  const row = el('tr');
  row.setAttribute('role', 'row');
  const open = el('a', 'row-open');
  open.href = '#conversaciones/' + item.conversacion;
  open.setAttribute('aria-label', 'Pedido ' + item.pedido + ': abrir su conversación');
  const text = el('span');
  const what = item.productos.map(line => units(line.cantidad, line.unidad) + ' ' + line.nombre).join(' · ');
  text.append(el('strong', '', item.pedido), el('small', '', whenText(item.fecha) + ' · ' + what +
    (item.referencia ? ' · Ref. ' + item.referencia : '')));
  open.append(text);
  const total = el('span', 'tx-total');
  total.append(el('strong', '', cop(item.total_cop)), el('small', '', item.metodo_texto || 'Sin método'));
  const tags = el('span', 'tx-tags');
  const order = pill(STATUS[item.estado_pedido]?.label || item.estado_pedido,
    {entregado:'success', cancelado:'danger', vencido:'danger', pendiente:'warning'}[item.estado_pedido] || '');
  tags.append(order, paymentPill({estado:item.estado_pago}));
  if (item.estado_pedido === 'entregado' && item.estado_pago !== 'confirmado') tags.append(pill('Vendido sin cobrar', 'warning', 'alert'));
  row.append(cell('name', open), cell('num', total), cell('state', tags));
  return row;
}

export async function loadSales() {
  const query = new URLSearchParams();
  [['desde', '#sales-from'], ['hasta', '#sales-to'], ['metodo', '#sales-method'], ['estado_pago', '#sales-pay'],
    ['estado_pedido', '#sales-order']].forEach(([key, selector]) => { if ($(selector).value) query.set(key, $(selector).value); });
  const data = await api('/api/ventas?' + query);
  fillOptions(data);
  const summary = data.resumen;
  const range = summary.desde === summary.hasta ? (summary.desde === todayKey() ? 'hoy' : summary.desde)
    : summary.desde + ' a ' + summary.hasta;
  const narrowed = ['#sales-method', '#sales-pay', '#sales-order'].filter(selector => $(selector).value).length;
  // El resumen del pliegue dice qué se está viendo sin abrirlo: el rango y cuántos filtros hay puestos.
  $('#sales-filter-note').textContent = (range === 'hoy' ? 'Hoy' : range) +
    (narrowed ? ' · ' + plural(narrowed, 'filtro', 'filtros') : ' · todo');
  $('#sales-kpis').replaceChildren(
    kpi('Vendido ' + range, cop(summary.ventas_registradas.total_cop),
      plural(summary.ventas_registradas.pedidos, 'pedido entregado', 'pedidos entregados'), 'brand'),
    kpi('Cobrado', cop(summary.ingresos_confirmados.total_cop), plural(summary.ingresos_confirmados.pagos, 'pago confirmado', 'pagos confirmados')),
    kpi('Por verificar', cop(summary.por_verificar.total_cop), plural(summary.por_verificar.pagos, 'comprobante', 'comprobantes'),
      summary.por_verificar.pagos ? 'alert' : ''),
    kpi('Por cobrar', cop(summary.por_cobrar.total_cop), plural(summary.por_cobrar.pedidos, 'venta sin pago', 'ventas sin pago'),
      summary.por_cobrar.pedidos ? 'alert' : ''));

  const methods = Object.values(summary.por_metodo).filter(item => item.confirmados || item.por_verificar);
  const top = Math.max(1, ...methods.map(item => item.confirmado_cop + item.por_verificar_cop));
  fill($('#method-list'), $('#method-empty'), methods, item => {
    const row = el('li');
    const bar = el('span', 'rank-bar');
    bar.style.setProperty('--share', String((item.confirmado_cop + item.por_verificar_cop) / top));
    row.append(el('span', 'rank-name', item.etiqueta), el('span', 'rank-amount', cop(item.confirmado_cop) +
      (item.por_verificar ? ' + ' + cop(item.por_verificar_cop) + ' por verificar' : '')), bar);
    return row;
  });
  $('#tx-count').textContent = plural(data.transacciones.length, 'transacción', 'transacciones');
  fill($('#tx-list'), $('#tx-empty'), data.transacciones, transaction);
  $('#tx-table').hidden = !data.transacciones.length;
}

export function bindSales() {
  // En pantallas anchas hay espacio: los filtros empiezan abiertos; en el celular, plegados.
  $('#sales-filter-fold').open = matchMedia('(min-width: 1024px)').matches;
  $('#sales-filter').addEventListener('change', () => loadSales().catch(error => $('#tx-count').textContent = error.message));
  $('#sales-filter').addEventListener('submit', event => event.preventDefault());
}
