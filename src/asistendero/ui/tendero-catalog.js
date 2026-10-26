// Catálogo de consulta: lo mismo que lee el asistente (precio y lo que queda para vender), sin costos ni edición.
// Sirve para comprobar una respuesta del chat: si el asistente dijo un precio, aquí se ve si es el del catálogo.
import {$, api, art, cop, el, fill, plural, restockText, units} from './tendero-core.js';
import {availabilityPill} from './tendero-product-editor.js';

const state = {category:'', products:[], categories:[]};
const dialog = $('#catalog-dialog');

function chip(label, value) {
  const node = el('button', 'chip', label);
  node.type = 'button';
  node.setAttribute('aria-pressed', String(state.category === value));
  node.addEventListener('click', () => { state.category = value; render(); });
  return node;
}

function agentText(product) {
  if (product.disponible <= 0) {
    return 'El asistente dice que está agotado' + (product.surtido ? ' y que ' + restockText(product.surtido).toLowerCase() : '') + '.';
  }
  return 'El asistente cotiza ' + cop(product.precio_cop) + ' por ' + product.unidad + ' y ofrece hasta ' +
    units(product.disponible, product.unidad) + '.';
}

function fact(label, value) {
  const box = el('div');
  box.append(el('dt', '', label), el('dd', '', value));
  return box;
}

function open(product) {
  $('#cd-art').src = '/img/producto/' + encodeURIComponent(product.sku) + '.svg';
  $('#cd-title').textContent = product.nombre + ' · ' + product.variante;
  $('#cd-meta').textContent = product.sku + ' · ' + product.categoria + ' · por ' + product.unidad;
  const free = el('div');
  const pillBox = el('dd');
  pillBox.append(availabilityPill(product));
  free.append(el('dt', '', 'Para vender'), pillBox);
  $('#cd-facts').replaceChildren(fact('Precio', cop(product.precio_cop)), free,
    fact('Apartado en pedidos', String(product.apartado)), fact('Surtido', restockText(product.surtido)));
  $('#cd-agent').textContent = agentText(product);
  dialog.showModal();
}

function item(product) {
  const card = el('button', 'catalog-item');
  card.type = 'button';
  card.setAttribute('aria-label', product.nombre + ' ' + product.variante + ', ' + cop(product.precio_cop));
  const text = el('span', 'catalog-text');
  text.append(el('strong', '', product.nombre), el('small', '', product.variante), el('b', '', cop(product.precio_cop)));
  card.append(art(product.sku, 'art', 56), text, availabilityPill(product));
  card.addEventListener('click', () => open(product));
  return card;
}

function render() {
  $('#cat-chips').replaceChildren(chip('Todo', ''), ...state.categories.map(name => chip(name, name)));
  const words = $('#cat-search').value.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').split(/\s+/).filter(Boolean);
  const shown = state.products.filter(product => {
    if (state.category && product.categoria !== state.category) return false;
    const text = (product.nombre + ' ' + product.variante + ' ' + product.sku + ' ' + product.categoria)
      .toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
    return words.every(word => text.includes(word));
  });
  $('#cat-count').textContent = plural(shown.length, 'producto', 'productos');
  fill($('#catalog-grid'), $('#catalog-empty'), shown, item);
}

export async function loadCatalog() {
  const data = await api('/api/catalogo');
  state.products = data.productos;
  state.categories = data.categorias;
  if (state.category && !state.categories.includes(state.category)) state.category = '';
  render();
}

export function bindCatalog() {
  $('#cat-search').addEventListener('input', render);
  dialog.querySelectorAll('[data-close]').forEach(node => node.addEventListener('click', () => dialog.close()));
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
}
