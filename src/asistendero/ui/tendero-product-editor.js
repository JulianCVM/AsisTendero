// Editor de un producto (precio, conteo físico, alerta propia y surtido) y alta de productos. Solo envía lo que cambió;
// lo que el tendero guarda es lo que el asistente lee en la siguiente consulta.
import {$, api, art, busy, closeOnDismiss, cop, el, fill, icon, restockText, showError, toast, whenText} from './tendero-core.js';

const UNITS = ['unidad', 'metro', 'bulto', 'galón', 'libra', 'rollo', 'par', 'pliego', 'bolsa', 'caja'];
const RESTOCK = [['', 'Sin dato'], ['lunes', 'Los lunes'], ['martes', 'Los martes'], ['miercoles', 'Los miércoles'],
  ['jueves', 'Los jueves'], ['viernes', 'Los viernes'], ['sabado', 'Los sábados'], ['descontinuado', 'Ya no se trae']];
const FIELDS = {precio:'Precio', existencias:'En bodega', surtido:'Surtido', alta:'Producto nuevo', alerta:'Alerta de stock'};
const state = {editing:null, onSaved:null};

export function availability(product) {
  if (product.disponible <= 0) return {kind:'out', icon:'alert', text:'Agotado'};
  if (product.disponible <= product.alerta) return {kind:'low', icon:'truck', text:'Pocas · ' + product.disponible};
  return {kind:'ok', icon:'check', text:product.disponible + ' para vender'};
}
export function availabilityPill(product) {
  const info = availability(product);
  const node = el('span', 'pill stock');
  node.dataset.stock = info.kind;
  node.append(icon(info.icon), el('span', '', info.text));
  return node;
}

function changeText(item) {
  if (item.campo === 'precio') return cop(item.antes ?? 0) + ' → ' + cop(item.despues);
  if (item.campo === 'surtido') return restockText(item.antes) + ' → ' + restockText(item.despues);
  if (item.campo === 'alta') return 'Agregado: ' + item.despues;
  return (item.antes ?? '—') + ' → ' + item.despues;
}
export function historyItem(item, name) {
  const step = el('li');
  const body = el('div');
  body.append(el('strong', '', (FIELDS[item.campo] || item.campo) + (name ? ' · ' + name : '')), el('span', '', changeText(item)));
  if (item.origen) body.append(el('small', 'hint', 'Origen: ' + item.origen));
  step.append(el('time', '', whenText(item.hora) + (item.quien ? ' · ' + item.quien : '')), body);
  return step;
}

function changes() {
  const product = state.editing;
  const result = {};
  const price = Number($('#pd-price').value);
  const stock = Number($('#pd-stock').value);
  if ($('#pd-price').value !== '' && price !== product.precio_cop) result.precio_cop = price;
  if ($('#pd-stock').value !== '' && stock !== product.stock) result.stock = stock;
  const plan = $('#pd-date').value || $('#pd-restock').value;
  if (plan !== (product.surtido || '')) result.surtido = plan;
  const alert = $('#pd-alert').value === '' ? null : Number($('#pd-alert').value);
  if (alert !== (product.alerta_propia ? product.alerta : null)) result.alerta = alert;
  return result;
}
function problem() {
  const product = state.editing;
  const whole = (node, max) => node.value === '' || !Number.isInteger(Number(node.value)) || Number(node.value) < 0 || Number(node.value) > max;
  if (whole($('#pd-price'), 50000000)) return [$('#pd-price'), 'Escribe un precio entero entre $0 y $50.000.000.'];
  if (whole($('#pd-stock'), 100000)) return [$('#pd-stock'), 'Escribe cuántas unidades hay en bodega, de 0 a 100.000.'];
  if (Number($('#pd-stock').value) < product.apartado) {
    return [$('#pd-stock'), 'No puede quedar por debajo de los ' + product.apartado + ' apartados en pedidos.'];
  }
  if ($('#pd-alert').value !== '' && whole($('#pd-alert'), 100000)) return [$('#pd-alert'), 'La alerta es un entero de 0 a 100.000.'];
  return null;
}
function update() {
  if (!state.editing) return;
  const product = state.editing;
  const price = Number($('#pd-price').value);
  const stock = Number($('#pd-stock').value);
  $('#pd-price-hint').textContent = $('#pd-price').value === '' ? 'Precio por ' + product.unidad
    : cop(price) + ' por ' + product.unidad + (price !== product.precio_cop ? ' · antes ' + cop(product.precio_cop) : '');
  $('#pd-stock-hint').textContent = (product.apartado
    ? 'Quedan ' + Math.max(stock - product.apartado, 0) + ' para vender: ' + product.apartado + ' están apartados en pedidos. '
    : 'Ninguna unidad está apartada. ') + 'Para mercancía que llegó, usa «Llegó mercancía»: queda asociada al proveedor.';
  $('#pd-alert-hint').textContent = 'Vacío: usa el mínimo general (' + product.alerta_general + ').';
  const found = problem();
  ['#pd-price', '#pd-stock', '#pd-alert'].forEach(id => $(id).removeAttribute('aria-invalid'));
  if (found) found[0].setAttribute('aria-invalid', 'true');
  showError($('#pd-error'), found ? found[1] : '');
  const changed = Object.keys(changes()).length > 0;
  $('#pd-save').disabled = Boolean(found) || !changed;
  $('#pd-save').textContent = changed ? 'Guardar cambios' : 'Sin cambios';
}

export async function openEditor(product, onSaved) {
  state.editing = product;
  state.onSaved = onSaved;
  $('#pd-art').src = '/img/producto/' + encodeURIComponent(product.sku) + '.svg';
  $('#pd-title').textContent = product.nombre + ' · ' + product.variante;
  $('#pd-meta').textContent = product.sku + ' · ' + product.categoria + ' · se vende por ' + product.unidad;
  $('#pd-now-stock').textContent = String(product.stock);
  $('#pd-now-held').textContent = String(product.apartado);
  $('#pd-now-free').replaceChildren(availabilityPill(product));
  $('#pd-now-coming').textContent = product.en_camino ? product.en_camino + (product.llega ? ' · ' + product.llega : '') : '—';
  $('#pd-price').value = String(product.precio_cop);
  $('#pd-stock').value = String(product.stock);
  $('#pd-stock').min = String(product.apartado);
  $('#pd-alert').value = product.alerta_propia ? String(product.alerta) : '';
  const dated = /^\d{4}-\d{2}-\d{2}$/.test(product.surtido || '');
  $('#pd-restock').value = dated ? '' : (product.surtido || '');
  $('#pd-date').value = dated ? product.surtido : '';
  update();
  $('#product-dialog').showModal();
  $('#pd-history').replaceChildren();
  $('#pd-history-empty').hidden = true;
  try {
    const history = (await api('/api/movimientos?sku=' + encodeURIComponent(product.sku))).movimientos.slice(0, 8);
    fill($('#pd-history'), $('#pd-history-empty'), history, item => historyItem(item, ''));
  } catch (error) {
    $('#pd-history-empty').hidden = false;
  }
}

async function save(event) {
  event.preventDefault();
  const product = state.editing;
  const body = changes();
  if (problem() || !Object.keys(body).length) return;
  await busy($('#pd-save'), async () => {
    try {
      await api('/api/inventario/actualizar', {sku:product.sku, ...body});
      $('#product-dialog').close();
      toast('Guardado: ' + product.nombre + ' ' + product.variante + '. El asistente ya usa estos datos.', 'ok');
      await state.onSaved?.();
    } catch (error) {
      showError($('#pd-error'), error.message);
    }
  });
}

async function add(event, onSaved) {
  event.preventDefault();
  const form = event.target;
  const invalid = [...form.elements].find(field => field.willValidate && !field.checkValidity());
  if (invalid) {
    const label = invalid.closest('label')?.querySelector('span')?.textContent || invalid.name;
    showError($('#np-error'), label + ': ' + invalid.validationMessage);
    invalid.focus();
    return;
  }
  const data = Object.fromEntries(new FormData(form));
  data.precio_cop = Number(data.precio_cop);
  data.stock = Number(data.stock);
  if (!data.terminos) delete data.terminos;
  await busy(form.querySelector('[type=submit]'), async () => {
    try {
      const result = await api('/api/inventario/nuevo', data);
      $('#new-dialog').close();
      form.reset();
      toast('Producto agregado: ' + result.producto.nombre + ' (' + result.producto.sku + ').', 'ok');
      await onSaved?.();
    } catch (failure) {
      showError($('#np-error'), failure.message);
    }
  });
}

export function setCategoryOptions(names) {
  const select = $('#np-category');
  const chosen = select.value;
  select.replaceChildren(...names.map(name => new Option(name, name)));
  if (names.includes(chosen)) select.value = chosen;
}

export function bindEditor(onSaved) {
  RESTOCK.forEach(([value, text]) => $('#pd-restock').append(new Option(text, value)));
  UNITS.forEach(unit => $('#unit-select').append(new Option(unit, unit)));
  // Un día de la semana y una fecha se excluyen: elegir uno borra el otro, como en el servidor (restock.valid_plan).
  $('#pd-restock').addEventListener('change', () => { if ($('#pd-restock').value) $('#pd-date').value = ''; update(); });
  $('#pd-date').addEventListener('input', () => { if ($('#pd-date').value) $('#pd-restock').value = ''; update(); });
  ['#pd-price', '#pd-stock', '#pd-alert'].forEach(id => $(id).addEventListener('input', update));
  const step = delta => {
    $('#pd-stock').value = String(Math.max(0, (Number($('#pd-stock').value) || 0) + delta));
    update();
  };
  $('#pd-minus').addEventListener('click', () => step(-1));
  $('#pd-plus').addEventListener('click', () => step(1));
  $('#product-form').addEventListener('submit', save);
  $('#add-form').addEventListener('submit', event => add(event, onSaved));
  $('#add-form').elements.sku.addEventListener('input', event => { event.target.value = event.target.value.toUpperCase(); });
  $('#new-product').addEventListener('click', () => {
    showError($('#np-error'), '');
    $('#new-dialog').showModal();
  });
  closeOnDismiss($('#product-dialog'));
  closeOnDismiss($('#new-dialog'));
}
