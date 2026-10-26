// Inventario: pestañas (productos, abastecimiento, movimientos, categorías y alertas) y la cuadrícula de productos con
// imagen, precio, lo que queda para vender y lo que viene en camino. Pensada para el celular: tarjetas, no una tabla.
import {$, api, art, button, cop, el, fill, icon, plural, toast, whenText} from './tendero-core.js';
import {availabilityPill, bindEditor, historyItem, openEditor, setCategoryOptions} from './tendero-product-editor.js';
import {bindSupply, loadSupply, openReceipt} from './tendero-supply.js';
import {bindCategories, loadCategories} from './tendero-categories.js';

export {availabilityPill, openEditor};
const PAGE = 48;
const TABS = ['productos', 'abastecimiento', 'movimientos', 'categorias'];
const FILTER_TEXT = {bajo:' por surtir', agotado:' agotados', camino:' con mercancía en camino'};
const state = {tab:'productos', stock:'todos', products:[], shown:PAGE, names:new Map(), refresh:null};

function productCard(product) {
  const card = el('button', 'product-card');
  card.type = 'button';
  card.setAttribute('aria-label', 'Editar ' + product.nombre + ' ' + product.variante + ', ' + cop(product.precio_cop) +
    ', ' + (product.disponible ? product.disponible + ' para vender' : 'agotado'));
  const info = el('span', 'product-info');
  info.append(el('strong', '', product.nombre), el('small', '', product.variante + ' · ' + product.sku));
  const stats = el('span', 'product-stats');
  const price = el('span', 'product-price', cop(product.precio_cop));
  price.append(el('small', '', ' / ' + product.unidad));
  stats.append(price, availabilityPill(product));
  const foot = el('span', 'product-foot');
  const stock = el('span');
  stock.append(icon('box'), el('span', '', product.stock + ' en bodega' + (product.apartado ? ' · ' + product.apartado + ' apartados' : '')));
  foot.append(stock);
  if (product.en_camino) {
    const coming = el('span');
    coming.append(icon('truck'), el('span', '', product.en_camino + ' en camino' + (product.llega ? ' · ' + product.llega : '')));
    foot.append(coming);
  }
  card.append(art(product.sku), info, stats, foot);
  card.addEventListener('click', () => openEditor(product, state.refresh));
  return card;
}

function renderProducts() {
  const shown = state.products.slice(0, state.shown);
  fill($('#product-grid'), $('#products-empty'), shown, productCard);
  const rest = state.products.length - state.shown;
  $('#show-more').hidden = rest <= 0;
  $('#show-more').textContent = 'Mostrar ' + Math.min(rest, PAGE) + ' más (quedan ' + rest + ')';
  $('#product-count').textContent = plural(state.products.length, 'producto', 'productos') + (FILTER_TEXT[state.stock] || '');
}

async function loadProducts() {
  const query = new URLSearchParams({q:$('#search').value, categoria:$('#category').value, estado:state.stock});
  const data = await api('/api/inventario?' + query);
  state.products = data.productos;
  state.shown = PAGE;
  const select = $('#category');
  const chosen = select.value;
  select.replaceChildren(new Option('Todas las categorías', ''), ...data.categorias.map(name => new Option(name, name)));
  select.value = data.categorias.includes(chosen) ? chosen : '';
  setCategoryOptions(data.categorias);
  renderProducts();
}

async function loadHistory() {
  const [history, all] = await Promise.all([api('/api/movimientos'), state.names.size ? null : api('/api/inventario')]);
  if (all) all.productos.forEach(product => state.names.set(product.sku, product.nombre + ' ' + product.variante));
  fill($('#history-list'), $('#history-empty'), history.movimientos, item => historyItem(item, state.names.get(item.sku) || item.sku));
}

function setStock(kind) {
  state.stock = kind;
  document.querySelectorAll('[data-stock]').forEach(node => node.setAttribute('aria-pressed', String(node.dataset.stock === kind)));
}

export function loadInventory(sub, filter, refresh) {
  state.refresh = refresh;
  state.tab = TABS.includes(sub) ? sub : 'productos';
  if (filter === 'bajo') setStock('bajo');
  document.querySelectorAll('[data-inv-tab]').forEach(link => {
    if (link.dataset.invTab === state.tab) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  TABS.forEach(tab => { $('#inv-' + tab).hidden = tab !== state.tab; });
  if (state.tab === 'abastecimiento') return loadSupply(refresh);
  if (state.tab === 'movimientos') return loadHistory();
  if (state.tab === 'categorias') return loadCategories(refresh);
  return loadProducts();
}

export function bindInventory(refresh) {
  let timer = null;
  const reload = () => loadProducts().catch(error => toast(error.message, 'error'));
  $('#inventory-filter').addEventListener('submit', event => { event.preventDefault(); reload(); });
  $('#search').addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(reload, 300); });
  $('#category').addEventListener('change', reload);
  document.querySelectorAll('[data-stock]').forEach(node => node.addEventListener('click', () => {
    setStock(node.dataset.stock);
    reload();
  }));
  $('#show-more').addEventListener('click', () => { state.shown += PAGE; renderProducts(); });
  $('#open-receipt').addEventListener('click', () => openReceipt(refresh));
  bindEditor(refresh);
  bindSupply(refresh);
  bindCategories(refresh);
}
