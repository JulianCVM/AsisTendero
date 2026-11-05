// Inventario: pestañas (productos, abastecimiento, movimientos, categorías y alertas) y una sola tabla de productos.
// La tabla tiene dos lecturas: la del tendero (precio, bodega, apartado, para vender, en camino) y «Como lo ve
// AsisTendero» (precio, para vender y lo que responde el chat). Antes eran dos vistas con los mismos 384 productos.
import {$, api, art, cop, dayText, el, fill, plural, toast} from './tendero-core.js';
import {agentText, availabilityPill, bindEditor, historyItem, openEditor, setCategoryOptions} from './tendero-product-editor.js';
import {bindSupply, loadSupply, openReceipt} from './tendero-supply.js';
import {bindCategories, loadCategories} from './tendero-categories.js';
import {loadAssistant} from './tendero-assistant.js';

export {availabilityPill, openEditor};
const PAGE = 50;
const TABS = ['productos', 'abastecimiento', 'movimientos', 'categorias'];
const FILTER_TEXT = {bajo:' por surtir', agotado:' agotados', camino:' con mercancía en camino'};
// Columnas de cada lectura; «opt» se esconde en el celular para que la fila quepa sin desplazarse de lado.
const COLUMNS = {
  tendero: [['Producto', 'name'], ['Precio', 'num'], ['En bodega', 'num opt'], ['Apartado', 'num opt'],
    ['Para vender', 'state'], ['En camino', 'opt']],
  asistente: [['Producto', 'name'], ['Precio', 'num opt'], ['Para vender', 'state'], ['Lo que responde AsisTendero', 'says']],
};
const state = {tab:'productos', stock:'todos', agent:false, products:[], shown:PAGE, names:new Map(), refresh:null};

// Los roles se fijan a mano: en el celular la fila se dibuja como bloque y algunos lectores de pantalla dejan de verla
// como tabla si solo cuentan las etiquetas.
function cell(className, content) {
  const node = el('td', className);
  node.setAttribute('role', 'cell');
  if (content instanceof Node) node.append(content);
  else node.textContent = content;
  return node;
}

function productRow(product) {
  const row = el('tr');
  row.setAttribute('role', 'row');
  const name = el('button', 'row-open');
  name.type = 'button';
  name.setAttribute('aria-label', 'Editar ' + product.nombre + ' ' + product.variante);
  const text = el('span');
  text.append(el('strong', '', product.nombre), el('small', '', product.variante + ' · ' + product.sku));
  name.append(art(product.sku, 'thumb', 36), text);
  name.addEventListener('click', () => openEditor(product, state.refresh));
  const price = cop(product.precio_cop) + ' / ' + product.unidad;
  if (state.agent) {
    row.append(cell('name', name), cell('num opt', price), cell('state', availabilityPill(product)),
      cell('says', agentText(product)));
  } else {
    row.append(cell('name', name), cell('num', price), cell('num opt', String(product.stock)),
      cell('num opt', product.apartado ? String(product.apartado) : '—'), cell('state', availabilityPill(product)),
      cell('opt', product.en_camino ? product.en_camino + (product.llega ? ' · llega ' + dayText(product.llega) : '') : '—'));
  }
  return row;
}

function renderProducts() {
  const columns = COLUMNS[state.agent ? 'asistente' : 'tendero'];
  $('#product-head').replaceChildren(...columns.map(([label, className]) => {
    const head = el('th', className, label);
    head.scope = 'col';
    head.setAttribute('role', 'columnheader');
    return head;
  }));
  $('#product-table').dataset.mode = state.agent ? 'asistente' : 'tendero';
  $('#product-caption').textContent = state.agent ? 'Productos como los ve AsisTendero' : 'Productos de la bodega';
  const shown = state.products.slice(0, state.shown);
  fill($('#product-rows'), $('#products-empty'), shown, productRow);
  $('#product-table').hidden = !shown.length;
  const rest = state.products.length - state.shown;
  $('#show-more').hidden = rest <= 0;
  $('#show-more').textContent = 'Mostrar ' + Math.min(rest, PAGE) + ' más (quedan ' + rest + ')';
  $('#product-count').textContent = plural(state.products.length, 'producto', 'productos') + (FILTER_TEXT[state.stock] || '') +
    (state.agent ? ' · así responde el chat: precio y lo que queda para vender (bodega menos apartado)' : '');
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
  if (filter === 'bajo' || filter === 'agotado') setStock(filter);
  document.querySelectorAll('[data-inv-tab]').forEach(link => {
    if (link.dataset.invTab === state.tab) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  TABS.forEach(tab => { $('#inv-' + tab).hidden = tab !== state.tab; });
  // Las acciones de producto solo van con la lista de productos; Abastecimiento tiene su propio «Registrar llegada».
  $('#inv-actions').hidden = state.tab !== 'productos';
  // En el celular las pestañas se desplazan de lado: la elegida se trae a la vista, solo en horizontal para no mover la
  // página (scrollIntoView también la desplazaría hacia arriba al refrescar después de guardar).
  const tab = document.querySelector('[data-inv-tab][aria-current]');
  const bar = tab.parentElement.getBoundingClientRect();
  const box = tab.getBoundingClientRect();
  if (box.left < bar.left || box.right > bar.right) tab.parentElement.scrollLeft += box.left - bar.left - 8;
  if (state.tab === 'abastecimiento') return loadSupply(refresh);
  if (state.tab === 'movimientos') return Promise.all([loadHistory(), loadAssistant()]);
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
  $('#agent-view').addEventListener('click', () => {
    state.agent = !state.agent;
    $('#agent-view').setAttribute('aria-pressed', String(state.agent));
    renderProducts();
  });
  $('#open-receipt').addEventListener('click', () => openReceipt(refresh));
  bindEditor(refresh);
  bindSupply(refresh);
  bindCategories(refresh);
}
