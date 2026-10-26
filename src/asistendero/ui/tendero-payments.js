// Pago de un pedido. El monto lo pone el servidor (el total del pedido); aquí solo se dice cómo pagó y qué tiene el
// tendero: un comprobante no es un pago confirmado, y nada se verifica contra un banco (payments.py).
import {$, api, closeOnDismiss, cop, el, pill, showError, toast} from './tendero-core.js';

export const METHODS = {
  efectivo:'Efectivo', datafono:'Datáfono (tarjeta)', nequi:'Nequi', daviplata:'Daviplata',
  transferencia:'Transferencia bancaria', bre_b:'Bre-B',
};
const IN_PERSON = new Set(['efectivo', 'datafono']);
export const PAY_STATES = {
  pendiente: {label:'Sin pagar todavía', tone:'warning', help:'Lo paga al recoger.'},
  comprobante_recibido: {label:'Comprobante recibido', tone:'info',
    help:'El cliente mostró o envió un soporte. Todavía no es plata confirmada.'},
  confirmado: {label:'Pago confirmado', tone:'success', help:''},
  rechazado: {label:'Comprobante rechazado', tone:'danger', help:'El soporte no coincide con lo que entró a tu cuenta.'},
};
const SOURCE_TEXT = {
  mostrador: 'Lo recibiste en el mostrador (efectivo o datáfono).',
  revision_tendero: 'Lo viste en tu app del banco o en el extracto. Un pantallazo del cliente no basta.',
};
const dialog = $('#pay-dialog');
let current = null;
let onSaved = null;

export function paymentPill(payment) {
  const info = PAY_STATES[payment.estado] || {label:payment.estado, tone:''};
  return pill(info.label, info.tone, payment.estado === 'confirmado' ? 'check' : payment.estado === 'pendiente' ? 'clock' : 'alert');
}

function allowedStates(method) {
  return IN_PERSON.has(method) ? ['pendiente', 'confirmado'] : ['pendiente', 'comprobante_recibido', 'confirmado', 'rechazado'];
}
function selectedState() {
  return dialog.querySelector('input[name="pay-state"]:checked')?.value || 'pendiente';
}
function source() {
  return IN_PERSON.has($('#pay-method').value) ? 'mostrador' : 'revision_tendero';
}
function renderStates() {
  const method = $('#pay-method').value;
  const allowed = allowedStates(method);
  const chosen = allowed.includes(selectedState()) ? selectedState() : allowed[0];
  $('#pay-states').replaceChildren(...allowed.map(key => {
    const option = el('label');
    const radio = el('input');
    radio.type = 'radio';
    radio.name = 'pay-state';
    radio.value = key;
    radio.checked = key === chosen;
    radio.addEventListener('change', renderSource);
    const help = key === 'confirmado' ? SOURCE_TEXT[IN_PERSON.has(method) ? 'mostrador' : 'revision_tendero'] : PAY_STATES[key].help;
    option.append(radio, el('strong', '', PAY_STATES[key].label), el('small', '', help));
    return option;
  }));
  renderSource();
}
function renderSource() {
  const confirming = selectedState() === 'confirmado';
  $('#pay-source-field').hidden = !confirming;
  const select = $('#pay-source');
  select.replaceChildren(new Option(source() === 'mostrador' ? 'En el mostrador' : 'Revisé mi app o extracto', source()));
  select.disabled = true;
  $('#pay-hint').textContent = confirming
    ? 'Al guardar, este pago cuenta como cobrado y ya no se puede cambiar desde el panel.'
    : 'No cuenta como cobrado hasta que lo confirmes.';
}

export function openPayment(order, refresh) {
  current = order;
  onSaved = refresh;
  const select = $('#pay-method');
  if (!select.options.length) Object.entries(METHODS).forEach(([key, label]) => select.append(new Option(label, key)));
  select.value = order.pago.metodo || 'efectivo';
  $('#pay-sub').textContent = order.pedido + ' · total ' + cop(order.total_cop) + ' (el monto sale del pedido)';
  $('#pay-ref').value = order.pago.referencia || '';
  showError($('#pay-error'), '');
  renderStates();
  const state = dialog.querySelector(`input[value="${order.pago.estado}"]`);
  if (state) state.checked = true;
  renderSource();
  dialog.showModal();
}

$('#pay-method').addEventListener('change', renderStates);
closeOnDismiss(dialog);
$('#pay-form').addEventListener('submit', async event => {
  event.preventDefault();
  const body = {pedido:current.pedido, metodo:$('#pay-method').value, estado:selectedState(), referencia:$('#pay-ref').value.trim()};
  if (body.estado === 'confirmado') body.fuente = source();
  const save = event.submitter || $('#pay-form').querySelector('[type="submit"]');
  save.disabled = true;
  try {
    await api('/api/pagos/registrar', body);
    dialog.close();
    toast('Pago de ' + current.pedido + ': ' + PAY_STATES[body.estado].label.toLowerCase() + '.', 'ok');
    await onSaved?.();
  } catch (error) {
    showError($('#pay-error'), error.message);
  } finally {
    save.disabled = false;
  }
});
