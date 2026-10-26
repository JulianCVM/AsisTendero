// Piezas comunes del panel del tendero. Todo dato se pinta con textContent: nombres, notas y códigos vienen de la
// base y nunca se interpretan como HTML.

export const STATUS = {
  pendiente: {label:'Por confirmar', icon:'clock'},
  confirmado: {label:'Confirmado', icon:'check'},
  entregado: {label:'Entregado', icon:'bag'},
  cancelado: {label:'Cancelado', icon:'x'},
  vencido: {label:'Vencido', icon:'alert'},
};
export const LOW_STOCK = 5;  // El mismo umbral que inventory.LOW_STOCK: «por surtir» es 5 o menos para vender.

const PLURAL = {metro:'metros', unidad:'unidades', bulto:'bultos', 'galón':'galones', libra:'libras', rollo:'rollos',
  par:'pares', pliego:'pliegos', bolsa:'bolsas', caja:'cajas'};
// Colombia no cambia de hora en el año: las horas del servidor (AAAA-MM-DD HH:MM, hora de Bogotá) se leen en -05:00.
const ZONE = 'America/Bogota';
const DAY_KEY = new Intl.DateTimeFormat('en-CA', {timeZone:ZONE, year:'numeric', month:'2-digit', day:'2-digit'});
const CLOCK = new Intl.DateTimeFormat('es-CO', {timeZone:ZONE, hour:'2-digit', minute:'2-digit', hourCycle:'h23'});
const SHORT_DAY = new Intl.DateTimeFormat('es-CO', {timeZone:ZONE, weekday:'short', day:'numeric', month:'short'});
const LONG_DAY = new Intl.DateTimeFormat('es-CO', {timeZone:ZONE, weekday:'long', day:'numeric', month:'long'});

export const $ = selector => document.querySelector(selector);
export const cop = value => '$' + Number(value).toLocaleString('es-CO');
export const units = (amount, unit) => amount + ' ' + (amount === 1 ? unit : (PLURAL[unit] || unit));

export function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}
export function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'icon');
  svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', '#i-' + name);
  svg.append(use);
  return svg;
}
export function button(className, label, iconName) {
  const node = el('button', className);
  node.type = 'button';
  if (iconName) node.append(icon(iconName));
  node.append(el('span', '', label));
  return node;
}
export function statusPill(status) {
  const info = STATUS[status] || {label:status, icon:'alert'};
  const pill = el('span', 'pill');
  pill.dataset.status = status;
  pill.append(icon(info.icon), el('span', '', info.label));
  return pill;
}
export function fill(list, emptyNode, items, render) {
  list.replaceChildren(...items.map(render));
  if (emptyNode) emptyNode.hidden = items.length > 0;
}

export async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || 'No se pudo completar (error ' + response.status + '). Intenta de nuevo.');
  return data;
}

export function toDate(text) {
  if (!text) return null;
  const date = new Date(/T/.test(text) ? text : text.replace(' ', 'T') + ':00-05:00');
  return Number.isNaN(date.getTime()) ? null : date;
}
export const clockText = date => CLOCK.format(date);
export const longDay = (date = new Date()) => LONG_DAY.format(date);
export function whenText(text) {
  const date = toDate(text);
  if (!date) return '—';
  const days = Math.round((Date.parse(DAY_KEY.format(date)) - Date.parse(DAY_KEY.format(new Date()))) / 86400000);
  const day = {'-1':'ayer', 0:'hoy', 1:'mañana'}[days] ?? SHORT_DAY.format(date).replace(/\./g, '');
  return day + ' ' + clockText(date);
}
export function minutesLeft(text) {
  const date = toDate(text);
  return date ? Math.ceil((date.getTime() - Date.now()) / 60000) : null;
}
export function restockText(plan) {
  if (!plan) return 'Sin dato';
  if (plan === 'descontinuado') return 'Ya no se trae';
  if (/^\d{4}-\d{2}-\d{2}$/.test(plan)) return 'Llega el ' + SHORT_DAY.format(toDate(plan + ' 12:00')).replace(/\./g, '');
  return 'Llega los ' + ({miercoles:'miércoles', sabado:'sábados'}[plan] || plan);
}

export function toast(text, kind = 'ok') {
  const region = $('#toasts');
  const item = el('div', 'toast');
  item.dataset.kind = kind;
  item.append(icon(kind === 'error' ? 'alert' : 'check'), el('span', '', text));
  region.append(item);
  while (region.children.length > 3) region.firstElementChild.remove();
  setTimeout(() => item.remove(), kind === 'error' ? 8000 : 5000);
}

// Mientras la acción corre, el botón queda deshabilitado y anuncia que está trabajando; así no se envía dos veces.
export async function busy(node, action) {
  node.disabled = true;
  node.setAttribute('aria-busy', 'true');
  try {
    return await action();
  } finally {
    node.disabled = false;
    node.removeAttribute('aria-busy');
  }
}

// Confirmación en dos toques y sin diálogos del navegador: el primer toque arma el botón por 4 segundos.
export function twoTap(node, armedLabel, action) {
  const label = node.querySelector('span');
  const idle = label.textContent;
  let timer = null;
  node.addEventListener('click', () => {
    if (node.dataset.armed === 'true') {
      clearTimeout(timer);
      node.dataset.armed = 'false';
      label.textContent = idle;
      busy(node, action);
      return;
    }
    node.dataset.armed = 'true';
    label.textContent = armedLabel;
    timer = setTimeout(() => { node.dataset.armed = 'false'; label.textContent = idle; }, 4000);
  });
}

// Imagen generada del producto (product_art.py): un pictograma por familia, sin fotos reales ni marcas.
export function art(sku, className = 'art', size = 64) {
  const image = el('img', className);
  image.src = '/img/producto/' + encodeURIComponent(sku) + '.svg';
  image.alt = '';
  image.width = size;
  image.height = size;
  image.loading = 'lazy';
  image.decoding = 'async';
  return image;
}
export function pill(text, tone, iconName) {
  const node = el('span', 'pill');
  if (tone) node.dataset.tone = tone;
  if (iconName) node.append(icon(iconName));
  node.append(el('span', '', text));
  return node;
}
export const plural = (amount, one, many) => amount + ' ' + (amount === 1 ? one : many);
export function dayText(text) {
  if (!text) return 'sin fecha';
  return whenText(text + ' 12:00').replace(/ \d{2}:\d{2}$/, '');
}
export const todayKey = () => DAY_KEY.format(new Date());
// Un formulario de una hoja: limpia el error y lo muestra en texto, sin diálogos del navegador.
export function showError(node, message) {
  node.textContent = message || '';
  node.hidden = !message;
}
export function closeOnDismiss(dialog) {
  dialog.querySelectorAll('[data-close]').forEach(node => node.addEventListener('click', () => dialog.close()));
  // Un toque sobre el fondo cierra la hoja, como en las apps del celular.
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
}
