// Abastecimiento flexible: pedidos al proveedor (mercancía pendiente, no suma a la bodega), fechas que se reprograman y
// llegadas completas, parciales o con productos de más. Una llegada se revisa antes de confirmarla: solo al confirmar
// sube el stock, y cada movimiento queda asociado al proveedor y a la llegada (purchasing.py).
import {$, api, art, busy, button, closeOnDismiss, cop, dayText, el, fill, icon, pill, plural, showError, toast, twoTap,
  units, whenText} from './tendero-core.js';

const PO_STATES = {pedido:['Pedido', 'info'], parcial:['Llegó una parte', 'warning'], recibida:['Recibido', 'success'],
  cancelada:['Cancelado', 'danger']};
const PO_FILTERS = [['abiertos', 'Por llegar'], ['recibida', 'Recibidos'], ['cancelada', 'Cancelados'], ['todos', 'Todos']];
const state = {filter:'abiertos', data:null, mode:'llegada', refresh:null, products:new Map(), checked:false};
const dialog = $('#supply-dialog');

function poCard(order) {
  const card = el('article', 'order');
  card.dataset.status = {pedido:'confirmado', parcial:'pendiente', recibida:'entregado', cancelada:'cancelado'}[order.estado];
  const head = el('header', 'order-head');
  const title = el('div', 'order-title');
  const [label, tone] = PO_STATES[order.estado] || [order.estado, ''];
  title.append(el('h3', 'order-code', order.oc), pill(label, tone));
  const who = el('div', 'order-total');
  who.append(el('span', '', 'Proveedor'), el('strong', '', order.proveedor));
  head.append(title, who);
  card.append(head);
  if (order.estado === 'pedido' || order.estado === 'parcial') {
    const when = el('p', 'order-when' + (order.atrasada ? ' is-urgent' : ''));
    when.append(icon('calendar'), el('span', '', order.fecha_estimada
      ? (order.atrasada ? 'Atrasado: debía llegar ' : 'Llega ') + dayText(order.fecha_estimada) : 'Sin fecha acordada'));
    card.append(when);
  }
  const lines = el('ul', 'po-lines');
  order.lineas.forEach(line => {
    const row = el('li');
    const bar = el('span', 'po-progress');
    bar.style.setProperty('--share', String(Math.min(line.recibido / Math.max(line.pedido, 1), 1)));
    row.append(el('span', '', line.nombre + ' · ' + line.variante),
      el('b', '', line.recibido + '/' + line.pedido + (line.pendiente ? ' · faltan ' + line.pendiente : '')), bar);
    lines.append(row);
  });
  card.append(lines);
  if (order.nota) card.append(el('p', 'order-meta', order.nota));
  card.append(el('p', 'order-meta', 'Registrado ' + whenText(order.creada)));
  if (order.eventos?.length) {
    const history = el('details', 'order-history');
    history.append(el('summary', '', 'Historial (' + order.eventos.length + ')'));
    const steps = el('ol', 'timeline compact');
    order.eventos.forEach(event => {
      const step = el('li');
      step.append(el('time', '', whenText(event.hora) + ' · ' + event.quien), el('span', '', event.accion + (event.detalle ? ': ' + event.detalle : '')));
      steps.append(step);
    });
    history.append(steps);
    card.append(history);
  }
  if (order.estado === 'pedido' || order.estado === 'parcial') card.append(poActions(order));
  return card;
}

function poActions(order) {
  const actions = el('div', 'order-actions');
  const receive = button('primary', 'Llegó', 'truck');
  receive.setAttribute('aria-label', 'Registrar la llegada del pedido ' + order.oc);
  receive.addEventListener('click', () => openReceipt(state.refresh, order));
  const date = el('input');
  date.type = 'date';
  date.value = order.fecha_estimada || '';
  date.setAttribute('aria-label', 'Nueva fecha de llegada de ' + order.oc);
  const move = button('secondary small', 'Cambiar fecha', 'calendar');
  move.addEventListener('click', () => busy(move, () => post('/api/abastecimiento/reprogramar',
    {oc:order.oc, fecha_estimada:date.value, motivo:'Cambio acordado con el proveedor'}, 'Nueva fecha para ' + order.oc + '.')));
  const cancel = button('danger small', 'Cancelar lo pendiente', 'x');
  twoTap(cancel, 'Toca otra vez para cancelar', () => post('/api/abastecimiento/cancelar',
    {oc:order.oc, motivo:'Cancelado por el tendero'}, order.oc + ' cancelado. La bodega no cambia.'));
  const dateBox = el('span', 'search');
  dateBox.append(date);
  actions.append(receive, dateBox, move, cancel);
  return actions;
}

async function post(path, body, done) {
  try {
    await api(path, body);
    toast(done, 'ok');
  } catch (error) {
    toast(error.message, 'error');
  }
  await state.refresh?.();
}

function receiptItem(receipt) {
  const step = el('li');
  const body = el('div');
  const extras = receipt.lineas.filter(line => line.adicional).length;
  body.append(el('strong', '', receipt.recepcion + ' · ' + receipt.proveedor + (receipt.oc ? ' · ' + receipt.oc : ' · sin pedido')),
    el('span', '', receipt.lineas.map(line => units(line.recibido, line.unidad) + ' ' + line.nombre).join(' · ')));
  if (extras) body.append(pill(plural(extras, 'producto adicional', 'productos adicionales'), 'warning', 'alert'));
  step.append(el('time', '', whenText(receipt.hora)), body);
  return step;
}

export async function loadSupply(refresh) {
  state.refresh = refresh;
  const data = state.data = await api('/api/abastecimiento');
  const open = order => order.estado === 'pedido' || order.estado === 'parcial';
  const counts = {abiertos:data.pedidos.filter(open).length, todos:data.pedidos.length};
  data.pedidos.forEach(order => { counts[order.estado] = (counts[order.estado] || 0) + 1; });
  $('#po-filter').replaceChildren(...PO_FILTERS.map(([key, label]) => {
    const chip = el('button');
    chip.type = 'button';
    chip.setAttribute('aria-pressed', String(key === state.filter));
    chip.append(el('span', '', label), el('b', 'count', String(counts[key] || 0)));
    chip.addEventListener('click', () => { state.filter = key; loadSupply(refresh); });
    return chip;
  }));
  const shown = data.pedidos.filter(order => state.filter === 'todos' || (state.filter === 'abiertos' ? open(order) : order.estado === state.filter));
  fill($('#po-list'), $('#po-empty'), shown, poCard);
  fill($('#receipt-list'), $('#receipt-empty'), data.recepciones, receiptItem);
}

// ---------- Hoja compartida: llegada o pedido al proveedor ----------
function lineRow(line = {}) {
  const row = el('li', 'line-row');
  const product = el('label', '', 'Producto');
  const input = el('input');
  input.setAttribute('list', 'sku-options');
  input.placeholder = 'Busca por nombre o SKU';
  input.value = line.sku ? state.products.get(line.sku)?.label || line.sku : '';
  input.required = true;
  product.append(input);
  const amount = el('label', '', state.mode === 'llegada' ? 'Llegaron' : 'Cantidad');
  const quantity = el('input');
  quantity.type = 'number';
  quantity.inputMode = 'numeric';
  quantity.min = '1';
  quantity.max = '100000';
  quantity.value = line.cantidad ? String(line.cantidad) : '';
  amount.append(quantity);
  const costLabel = el('label', 'cost', 'Costo unitario (opcional)');
  const cost = el('input');
  cost.type = 'number';
  cost.inputMode = 'numeric';
  cost.min = '0';
  cost.value = line.costo_unitario ? String(line.costo_unitario) : '';
  costLabel.append(cost);
  const remove = el('button', 'icon-button');
  remove.type = 'button';
  remove.setAttribute('aria-label', 'Quitar este producto');
  remove.append(icon('trash'));
  remove.addEventListener('click', () => { row.remove(); invalidate(); });
  const hint = el('span', 'line-hint', line.pendiente ? 'Pendientes de este pedido: ' + line.pendiente : '');
  [input, quantity, cost].forEach(node => node.addEventListener('input', invalidate));
  row.append(product, amount, costLabel, remove, hint);
  return row;
}

function readLines() {
  const lines = [];
  for (const row of $('#sd-lines').children) {
    const [product, quantity, cost] = row.querySelectorAll('input');
    const sku = state.products.get(product.value)?.sku || [...state.products.values()].find(item => item.label === product.value)?.sku
      || product.value.split(' · ')[0].trim().toUpperCase();
    if (!product.value.trim() && !quantity.value) continue;
    const line = {sku, cantidad:Number(quantity.value)};
    if (cost.value !== '') line.costo_unitario = Number(cost.value);
    lines.push(line);
  }
  return lines;
}

function body() {
  const result = {proveedor:$('#sd-supplier').value, lineas:readLines(), nota:$('#sd-note').value.trim()};
  if (state.mode === 'llegada' && $('#sd-po').value) result.oc = $('#sd-po').value;
  if (state.mode === 'pedido' && $('#sd-date').value) result.fecha_estimada = $('#sd-date').value;
  return result;
}

function invalidate() {
  state.checked = false;
  $('#sd-preview').hidden = true;
  $('#sd-save').disabled = state.mode === 'llegada';
  showError($('#sd-error'), '');
}

function fillLinesFromOrder() {
  const order = state.data?.pedidos.find(item => item.oc === $('#sd-po').value);
  $('#sd-lines').replaceChildren();
  const pending = order ? order.lineas.filter(line => line.pendiente > 0) : [];
  (pending.length ? pending : [{}]).forEach(line => $('#sd-lines').append(lineRow({sku:line.sku, cantidad:line.pendiente,
    costo_unitario:line.costo_unitario_cop, pendiente:line.pendiente})));
  if (order) $('#sd-supplier').value = order.proveedor_id;
  invalidate();
}

async function prepare(mode, order) {
  state.mode = mode;
  if (!state.data) state.data = await api('/api/abastecimiento');
  if (!state.products.size) {
    const all = await api('/api/inventario');
    const options = all.productos.map(product => {
      const label = product.sku + ' · ' + product.nombre + ' ' + product.variante;
      state.products.set(label, {sku:product.sku, label});
      state.products.set(product.sku, {sku:product.sku, label});
      return new Option(label, label);
    });
    $('#sku-options').replaceChildren(...options);
  }
  $('#sd-supplier').replaceChildren(...state.data.proveedores.map(item => new Option(item.nombre, item.proveedor)));
  const open = state.data.pedidos.filter(item => item.estado === 'pedido' || item.estado === 'parcial');
  $('#sd-po').replaceChildren(new Option('Sin pedido (llegó sin pedirlo)', ''),
    ...open.map(item => new Option(item.oc + ' · ' + item.proveedor + (item.fecha_estimada ? ' · ' + dayText(item.fecha_estimada) : ''), item.oc)));
  $('#sd-title').textContent = mode === 'llegada' ? 'Registrar llegada' : 'Pedido al proveedor';
  $('#sd-sub').textContent = mode === 'llegada'
    ? 'Solo lo que confirmes aquí suma a la bodega. Lo que no esté en el pedido queda como adicional.'
    : 'Queda como mercancía pendiente: no suma a la bodega hasta que registres la llegada.';
  $('#sd-lines-legend').textContent = mode === 'llegada' ? 'Productos que llegaron' : 'Productos que pediste';
  $('#sd-po-field').hidden = mode !== 'llegada';
  $('#sd-date-field').hidden = mode !== 'pedido';
  $('#sd-check').hidden = mode !== 'llegada';
  $('#sd-save').textContent = mode === 'llegada' ? 'Confirmar llegada' : 'Registrar pedido';
  $('#sd-note').value = '';
  $('#sd-date').value = '';
  $('#sd-po').value = order?.oc || '';
  fillLinesFromOrder();
  dialog.showModal();
}

export function openReceipt(refresh, order) {
  state.refresh = refresh;
  prepare('llegada', order).catch(error => toast(error.message, 'error'));
}

function renderPreview(result) {
  $('#sd-preview-rows').replaceChildren(...result.lineas.map(line => {
    const row = el('div', 'preview-row');
    row.append(el('strong', '', line.nombre + ' · ' + line.variante), el('span', 'delta', line.stock_antes + ' → ' + line.stock_despues));
    const notes = ['+' + units(line.recibido, line.unidad)];
    if (line.adicional) notes.push(line.cantidad_adicional + ' adicionales: no estaban en el pedido');
    if (line.pendiente) notes.push('siguen pendientes ' + line.pendiente);
    if (line.costo_unitario_cop) notes.push('costo ' + cop(line.costo_unitario_cop) + ' c/u');
    row.append(el('small', '', notes.join(' · ')));
    return row;
  }));
  $('#sd-preview').hidden = false;
}

async function check() {
  try {
    renderPreview(await api('/api/abastecimiento/recepcion', {...body(), aplicar:false}));
    state.checked = true;
    $('#sd-save').disabled = false;
  } catch (error) {
    showError($('#sd-error'), error.message);
  }
}

async function submit(event) {
  event.preventDefault();
  if (state.mode === 'llegada' && !state.checked) return check();
  await busy($('#sd-save'), async () => {
    try {
      if (state.mode === 'llegada') {
        const result = await api('/api/abastecimiento/recepcion', {...body(), aplicar:true});
        toast('Llegada ' + result.recepcion + ' registrada: la bodega ya está al día.', 'ok');
      } else {
        const result = await api('/api/abastecimiento/pedido', body());
        toast('Pedido ' + result.pedido.oc + ' registrado como pendiente.', 'ok');
      }
      dialog.close();
      state.data = null;
      await state.refresh?.();
    } catch (error) {
      showError($('#sd-error'), error.message);
    }
  });
}

export function bindSupply(refresh) {
  state.refresh = refresh;
  $('#new-po').addEventListener('click', () => prepare('pedido').catch(error => toast(error.message, 'error')));
  $('#open-receipt-2').addEventListener('click', () => openReceipt(refresh));
  $('#sd-add-line').addEventListener('click', () => { $('#sd-lines').append(lineRow()); invalidate(); });
  $('#sd-po').addEventListener('change', fillLinesFromOrder);
  $('#sd-supplier').addEventListener('change', invalidate);
  $('#sd-check').addEventListener('click', event => busy(event.currentTarget, check));
  $('#supply-form').addEventListener('submit', submit);
  closeOnDismiss(dialog);
}
