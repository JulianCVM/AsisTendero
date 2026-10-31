// Panel del tendero: navegación, tema, contadores y sincronización. Cada sección vive en su módulo.
// Los pedidos y los chats llegan solos, así que Hoy, Pedidos y Chats se refrescan cada 15 s con la pestaña visible.
// PulsoTienda es el panel; AsisTendero, el agente que atiende el chat.
import {$, api, busy, clockText, longDay, toast} from './tendero-core.js';
import {bindOrderSearch, loadOrders} from './tendero-orders.js';
import {bindInventory, loadInventory} from './tendero-inventory.js';
import {loadToday} from './tendero-today.js';
import {bindSales, loadSales} from './tendero-sales.js';
import {bindAssistant} from './tendero-assistant.js';
import {bindChats, loadChats} from './tendero-chats.js';

const VIEWS = {
  hoy: {title:'Hoy', subtitle:() => longDay().replace(/^./, letter => letter.toUpperCase())},
  pedidos: {title:'Pedidos', subtitle:() => 'Los pedidos del chat, del más urgente al más antiguo'},
  ventas: {title:'Ventas y pagos', subtitle:() => 'Lo vendido, lo cobrado y lo que falta por verificar'},
  inventario: {title:'Inventario', subtitle:() => 'Productos, abastecimiento y movimientos; cuéntale a la bodega qué pasó'},
  conversaciones: {title:'Chats', subtitle:() => 'Lo que AsisTendero conversa con tus clientes'},
};
// Direcciones de las vistas que se unieron al inventario: un enlace guardado sigue llevando a su lugar.
const MOVED = {catalogo:'inventario', asistente:'inventario'};
const LIVE = new Set(['hoy', 'pedidos', 'conversaciones']);
const REFRESH_MS = 15000;
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
  setBadge('#badge-hoy', counts.chats_atencion, 'clientes que piden hablar contigo');
  setBadge('#badge-pedidos', counts.pedidos_activos, 'pedidos por atender');
  setBadge('#badge-inventario', counts.agotados, 'productos agotados');
  setBadge('#badge-chats', counts.chats_atencion + counts.bloqueos, 'chats que necesitan atención');
  setBadge('#badge-ventas', counts.pagos_por_verificar, 'pagos por verificar');
  $('#more-ventas').textContent = counts.pagos_por_verificar ? counts.pagos_por_verificar + ' por verificar' : '';
  // Ventas vive dentro de «Más» en el celular: su aviso se ve en el botón, con número y no solo con color.
  setBadge('#badge-more', counts.pagos_por_verificar, 'pagos por verificar en Ventas');
}

const loaders = {
  hoy: () => loadToday(refresh),
  pedidos: () => loadOrders(refresh, takeFilter()),
  ventas: () => loadSales(),
  inventario: () => loadInventory(route.sub, takeFilter(), refresh),
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
  if (MOVED[name]) {
    location.replace('#' + MOVED[name]);
    if (name === 'asistente') requestAnimationFrame(() => document.getElementById('assist-text')?.focus());
    return;
  }
  const changed = name !== route.view;
  route.view = VIEWS[name] ? name : 'hoy';
  route.sub = rest.join('/');
  document.querySelectorAll('.view').forEach(section => { section.hidden = section.id !== 'view-' + route.view; });
  document.querySelectorAll('[data-view]').forEach(link => {
    if (link.dataset.view === route.view) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  // En el celular, «Más» se marca cuando la sección actual está dentro de su menú.
  $('#more-toggle').dataset.current = String(route.view === 'ventas');
  closeMore();
  $('#view-title').textContent = VIEWS[route.view].title;
  $('#view-subtitle').textContent = VIEWS[route.view].subtitle();
  document.title = VIEWS[route.view].title + ' · PulsoTienda';
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
  // Con teclado, el foco entra al menú; con el dedo no hace falta, pero tampoco estorba.
  if (open) $('#more-menu a').focus();
});
document.addEventListener('keydown', event => {
  if (event.key !== 'Escape' || $('#more-menu').hidden) return;
  closeMore();
  $('#more-toggle').focus();
});
document.addEventListener('click', event => {
  if (!$('#more-menu').hidden && !event.target.closest('#more-menu, #more-toggle')) closeMore();
});

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
bindOrderSearch(refresh);
bindInventory(refresh);
bindSales();
bindAssistant(refresh);
bindChats(refresh);
setInterval(() => {
  if (!document.hidden && LIVE.has(route.view) && !document.querySelector('dialog[open]')
      && !document.activeElement?.matches('textarea, input')) refresh();
}, REFRESH_MS);
show();
