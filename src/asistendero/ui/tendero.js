// Panel del tendero: navegación, tema, contadores y sincronización. Cada sección vive en su módulo.
// Los pedidos y los chats llegan solos, así que Hoy, Pedidos y Chats se refrescan cada 15 s con la pestaña visible.
import {$, api, busy, clockText, longDay, toast} from './tendero-core.js';
import {bindOrderSearch, loadOrders} from './tendero-orders.js';
import {bindInventory, loadInventory} from './tendero-inventory.js';
import {loadToday} from './tendero-today.js';
import {bindSales, loadSales} from './tendero-sales.js';
import {bindCatalog, loadCatalog} from './tendero-catalog.js';
import {bindAssistant, loadAssistant} from './tendero-assistant.js';
import {bindChats, loadChats} from './tendero-chats.js';

const VIEWS = {
  hoy: {title:'Hoy', subtitle:() => longDay().replace(/^./, letter => letter.toUpperCase())},
  pedidos: {title:'Pedidos', subtitle:() => 'Los pedidos del chat, del más urgente al más antiguo'},
  ventas: {title:'Ventas y pagos', subtitle:() => 'Lo vendido, lo cobrado y lo que falta por verificar'},
  inventario: {title:'Inventario', subtitle:() => 'Precios, existencias, abastecimiento y movimientos'},
  catalogo: {title:'Catálogo', subtitle:() => 'Lo que ve el asistente, para comprobar sus respuestas'},
  asistente: {title:'Asistente de bodega', subtitle:() => 'Actualiza el inventario conversando; tú confirmas'},
  conversaciones: {title:'Chats', subtitle:() => 'Lo que el asistente conversa con tus clientes'},
};
const LIVE = new Set(['hoy', 'pedidos', 'conversaciones']);
const REFRESH_MS = 15000;
const THEMES = [
  {key:'sistema', icon:'auto', label:'igual al del equipo'},
  {key:'claro', icon:'sun', label:'claro'},
  {key:'oscuro', icon:'moon', label:'oscuro'},
];
const route = {view:'hoy', sub:''};
let pendingFilter = null;

function setBadge(id, amount, label) {
  const badge = $(id);
  if (!badge) return;
  badge.hidden = !amount;
  badge.textContent = String(amount);
  badge.setAttribute('aria-label', amount + ' ' + label);
}
async function loadBadges() {
  const counts = await api('/api/alertas');
  setBadge('#badge-pedidos', counts.pedidos_activos, 'pedidos por atender');
  setBadge('#badge-inventario', counts.agotados, 'productos agotados');
  setBadge('#badge-chats', counts.chats_atencion + counts.bloqueos, 'chats que necesitan atención');
  setBadge('#badge-ventas', counts.pagos_por_verificar, 'pagos por verificar');
  $('#more-ventas').textContent = counts.pagos_por_verificar ? counts.pagos_por_verificar + ' por verificar' : '';
  $('#more-toggle').dataset.alert = String(counts.pagos_por_verificar > 0);
}

const loaders = {
  hoy: () => loadToday(refresh),
  pedidos: () => loadOrders(refresh, takeFilter()),
  ventas: () => loadSales(),
  inventario: () => loadInventory(route.sub, takeFilter(), refresh),
  catalogo: () => loadCatalog(),
  asistente: () => loadAssistant(),
  conversaciones: () => loadChats(route.sub, refresh),
};
function takeFilter() {
  const filter = pendingFilter;
  pendingFilter = null;
  return filter;
}

async function refresh() {
  const sync = $('#sync-status');
  try {
    await Promise.all([loaders[route.view](), loadBadges()]);
    sync.textContent = 'Actualizado ' + clockText(new Date());
    sync.dataset.state = 'ok';
    $('#offline').hidden = true;
  } catch (error) {
    sync.textContent = 'Sin conexión con la tienda';
    sync.dataset.state = 'error';
    $('#offline').hidden = !(error instanceof TypeError);
    if (!(error instanceof TypeError)) toast(error.message, 'error');
  }
}

function show() {
  const [name, ...rest] = location.hash.slice(1).split('/');
  const changed = name !== route.view;
  route.view = VIEWS[name] ? name : 'hoy';
  route.sub = rest.join('/');
  document.querySelectorAll('.view').forEach(section => { section.hidden = section.id !== 'view-' + route.view; });
  document.querySelectorAll('[data-view]').forEach(link => {
    if (link.dataset.view === route.view) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  // En el celular, «Más» se marca cuando la sección actual está dentro de su menú.
  $('#more-toggle').dataset.current = String(['ventas', 'catalogo', 'asistente'].includes(route.view));
  closeMore();
  $('#view-title').textContent = VIEWS[route.view].title;
  $('#view-subtitle').textContent = VIEWS[route.view].subtitle();
  document.title = VIEWS[route.view].title + ' · Panel del tendero';
  if (changed) window.scrollTo({top:0});
  refresh();
}

function closeMore() {
  $('#more-menu').hidden = true;
  $('#more-toggle').setAttribute('aria-expanded', 'false');
}
$('#more-toggle').addEventListener('click', () => {
  const open = $('#more-menu').hidden;
  $('#more-menu').hidden = !open;
  $('#more-toggle').setAttribute('aria-expanded', String(open));
});
document.addEventListener('keydown', event => { if (event.key === 'Escape') closeMore(); });
document.addEventListener('click', event => {
  if (!$('#more-menu').hidden && !event.target.closest('#more-menu, #more-toggle')) closeMore();
});

function readTheme() {
  try { return localStorage.getItem('tendero-tema') || 'sistema'; } catch (error) { return 'sistema'; }
}
function applyTheme(key) {
  const theme = THEMES.find(item => item.key === key) || THEMES[0];
  const root = document.documentElement;
  if (theme.key === 'sistema') delete root.dataset.theme;
  else root.dataset.theme = theme.key === 'oscuro' ? 'dark' : 'light';
  const next = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
  const toggle = $('#theme-toggle');
  toggle.querySelector('use').setAttribute('href', '#i-' + theme.icon);
  toggle.setAttribute('aria-label', 'Tema: ' + theme.label + '. Cambiar a ' + next.label);
  toggle.title = 'Tema ' + theme.label;
  const dark = root.dataset.theme === 'dark' || (!root.dataset.theme && matchMedia('(prefers-color-scheme: dark)').matches);
  document.querySelector('meta[name="theme-color"]').content = dark ? '#0A1519' : '#173B4A';
}
$('#theme-toggle').addEventListener('click', () => {
  const current = THEMES.findIndex(item => item.key === readTheme());
  const next = THEMES[(current + 1) % THEMES.length].key;
  try { localStorage.setItem('tendero-tema', next); } catch (error) { /* sin almacenamiento: dura esta visita */ }
  applyTheme(next);
});
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => applyTheme(readTheme()));

// Un indicador de Hoy lleva a su lista ya filtrada: «Por confirmar» abre los pedidos pendientes.
document.addEventListener('click', event => {
  const link = event.target.closest('a[data-filter]');
  if (!link) return;
  pendingFilter = link.dataset.filter;
  // Si ya estamos en esa sección no hay hashchange: se vuelve a mostrar a mano para aplicar el filtro.
  if (link.hash === location.hash) {
    event.preventDefault();
    show();
  }
});
window.addEventListener('hashchange', show);
$('#refresh').addEventListener('click', event => busy(event.currentTarget, refresh));
applyTheme(readTheme());
bindOrderSearch(refresh);
bindInventory(refresh);
bindSales();
bindCatalog();
bindAssistant(refresh);
bindChats(refresh);
setInterval(() => {
  if (!document.hidden && LIVE.has(route.view) && !document.querySelector('dialog[open]')
      && !document.activeElement?.matches('textarea, input')) refresh();
}, REFRESH_MS);
show();
