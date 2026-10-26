// Ventas y pagos: filtros por fecha, método y estado; indicadores que separan lo vendido de lo cobrado; el reparto por
// método y la lista de transacciones (cada una es un pedido identificable del chat).
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

function transaction(item) {
  const card = el('article', 'tx');
  const main = el('div', 'tx-main');
  const link = el('a', '', item.pedido);
  link.href = '#conversaciones/' + item.conversacion;
  const title = el('strong');
  title.append(link);
  main.append(title, el('span', '', item.productos.map(line => units(line.cantidad, line.unidad) + ' ' + line.nombre).join(' · ')),
    el('span', '', whenText(item.fecha) + (item.referencia ? ' · Ref. ' + item.referencia : '')));
  const amount = el('div', 'tx-amount');
  amount.append(el('strong', '', cop(item.total_cop)), el('small', '', item.metodo_texto || 'Sin método'));
  const tags = el('div', 'tx-tags');
  const order = pill(STATUS[item.estado_pedido]?.label || item.estado_pedido,
    {entregado:'success', cancelado:'danger', vencido:'danger', pendiente:'warning'}[item.estado_pedido] || '');
  tags.append(order, paymentPill({estado:item.estado_pago}));
  if (item.estado_pedido === 'entregado' && item.estado_pago !== 'confirmado') tags.append(pill('Vendido sin cobrar', 'warning', 'alert'));
  card.append(main, amount, tags);
  return card;
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
}

export function bindSales() {
  $('#sales-filter').addEventListener('change', () => loadSales().catch(error => $('#tx-count').textContent = error.message));
  $('#sales-filter').addEventListener('submit', event => event.preventDefault());
}
