(() => {
  // Todo dato se pinta con textContent: nombres, notas y códigos vienen de la base y nunca se interpretan como HTML.
  const PAGE = 60;
  const STATUS_LABELS = {pendiente:'Pendiente de confirmar', confirmado:'Confirmado', entregado:'Entregado',
    cancelado:'Cancelado', vencido:'Vencido'};
  const UNITS = ['unidad', 'metro', 'bulto', 'galón', 'libra', 'rollo', 'par', 'pliego', 'bolsa', 'caja'];
  const notice = document.querySelector('#notice');
  const tabs = [...document.querySelectorAll('[data-tab]')];
  let activeTab = 'resumen';
  let statusFilter = '';
  let products = [];
  let shown = PAGE;
  let searchTimer = null;

  const PLURAL = {metro:'metros', unidad:'unidades', bulto:'bultos', 'galón':'galones', libra:'libras', rollo:'rollos',
    par:'pares', pliego:'pliegos', bolsa:'bolsas', caja:'cajas'};
  const cop = value => '$' + Number(value).toLocaleString('es-CO') + ' COP';
  const units = (amount, unit) => amount + ' ' + (amount === 1 ? unit : (PLURAL[unit] || unit));
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function say(text, kind) {
    notice.textContent = text;
    notice.className = 'notice ' + (kind || '');
    notice.hidden = false;
  }
  async function api(path, body) {
    const response = await fetch(path, body === undefined ? {} : {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || 'Error ' + response.status);
    return data;
  }
  function fill(list, emptyNode, items, render) {
    list.replaceChildren(...items.map(render));
    emptyNode.hidden = items.length > 0;
  }

  async function loadSummary() {
    const [summary, low] = await Promise.all([api('/api/resumen'), api('/api/inventario?bajo=1')]);
    document.querySelector('#summary-day').textContent = '· ' + summary.dia;
    document.querySelector('#tile-sales').textContent = String(summary.ventas);
    document.querySelector('#tile-total').textContent = cop(summary.total_cop);
    document.querySelector('#tile-pending').textContent = String(summary.por_estado.pendiente);
    document.querySelector('#tile-confirmed').textContent = String(summary.por_estado.confirmado);
    fill(document.querySelector('#pickup-list'), document.querySelector('#pickup-empty'), summary.por_recoger, order => {
      const item = el('li', '', order.pedido + ' · ' + STATUS_LABELS[order.estado] + ' · ' + cop(order.total_cop));
      const when = order.recogida ? 'Recoge: ' + order.recogida : 'Apartado hasta ' + (order.aparta_hasta || '—');
      item.append(el('span', 'meta', when + (order.nota ? ' · Nota: ' + order.nota : '')));
      return item;
    });
    fill(document.querySelector('#top-list'), document.querySelector('#top-empty'), summary.mas_vendidos, line => {
      const item = el('li', '', line.nombre + ' ' + line.variante);
      item.append(el('span', 'meta', units(line.cantidad, line.unidad) + ' · ' + line.sku));
      return item;
    });
    fill(document.querySelector('#low-list'), document.querySelector('#low-empty'), low.productos.slice(0, 12), product => {
      const item = el('li', '', product.nombre + ' ' + product.variante);
      item.append(el('span', 'meta', (product.disponible ? product.disponible + ' disponibles' : 'Agotado') + ' · ' +
        product.apartado + ' apartados · ' + product.sku));
      return item;
    });
  }

  function orderCard(order) {
    const card = el('article', 'order');
    card.dataset.status = order.estado;
    const head = el('div', 'order-head');
    const badge = el('span', 'badge', STATUS_LABELS[order.estado] || order.estado);
    badge.dataset.status = order.estado;
    head.append(el('span', 'order-code', order.pedido), badge);
    const lines = el('ul');
    order.lineas.forEach(line => lines.append(el('li', '', units(line.cantidad, line.unidad) + ' · ' + line.nombre +
      ' ' + line.variante + ' (' + line.sku + ') · ' + cop(line.subtotal_cop))));
    card.append(head, lines, el('p', '', 'Total: ' + cop(order.total_cop)));
    if (order.recogida) card.append(el('p', '', 'Recogida: ' + order.recogida));
    if (order.aparta_hasta) card.append(el('p', '', 'Apartado hasta: ' + order.aparta_hasta));
    if (order.nota) card.append(el('p', '', 'Nota del cliente: ' + order.nota));
    card.append(el('p', 'muted', 'Creado ' + order.creado + ' · conversación ' + order.conversacion));
    const history = el('details');
    history.append(el('summary', '', 'Historial'));
    order.historial.forEach(event => history.append(el('div', '', event.hora + ' · ' + event.estado + ' · ' + event.detalle)));
    card.append(history);
    if (order.estado === 'pendiente' || order.estado === 'confirmado') {
      const actions = el('div', 'actions');
      const deliver = el('button', 'primary', 'Marcar entregado');
      deliver.type = 'button';
      deliver.addEventListener('click', () => act('/api/pedidos/entregar', order.pedido, 'Entregado: ' + order.pedido));
      const cancel = el('button', 'danger', 'Cancelar pedido');
      cancel.type = 'button';
      // Confirmación en dos toques y sin diálogos del navegador: el primer toque arma el botón por 4 segundos.
      cancel.addEventListener('click', () => {
        if (cancel.dataset.armed === 'true') {
          act('/api/pedidos/cancelar', order.pedido, 'Cancelado: ' + order.pedido);
          return;
        }
        cancel.dataset.armed = 'true';
        cancel.textContent = 'Toca de nuevo para cancelar';
        setTimeout(() => { cancel.dataset.armed = 'false'; cancel.textContent = 'Cancelar pedido'; }, 4000);
      });
      actions.append(deliver, cancel);
      card.append(actions);
    }
    return card;
  }
  async function act(path, code, done) {
    try {
      await api(path, {pedido:code});
      say(done, 'ok');
    } catch (error) {
      say(error.message, 'error');
    }
    refresh();
  }
  async function loadOrders() {
    const data = await api('/api/pedidos' + (statusFilter ? '?estado=' + encodeURIComponent(statusFilter) : ''));
    const chips = document.querySelector('#status-filter');
    if (!chips.children.length) {
      ['', ...data.estados].forEach(status => {
        const chip = el('button', '', status ? STATUS_LABELS[status] : 'Todos');
        chip.type = 'button';
        chip.dataset.status = status;
        chip.setAttribute('aria-pressed', String(status === statusFilter));
        chip.addEventListener('click', () => {
          statusFilter = status;
          chips.querySelectorAll('button').forEach(item => item.setAttribute('aria-pressed', String(item === chip)));
          loadOrders().catch(error => say(error.message, 'error'));
        });
        chips.append(chip);
      });
    }
    fill(document.querySelector('#order-list'), document.querySelector('#orders-empty'), data.pedidos, orderCard);
  }

  function productCard(product) {
    const card = el('article', 'product');
    card.append(el('div', 'product-title', product.nombre + ' · ' + product.variante),
      el('div', 'product-meta', product.sku + ' · ' + product.categoria + ' · ' + cop(product.precio_cop) + ' por ' + product.unidad));
    const stock = el('div', 'stock-line');
    const available = el('span', product.disponible <= 5 ? 'low' : '', product.disponible + ' disponibles' +
      (product.disponible <= 5 ? ' (pocas)' : ''));
    stock.append(el('span', '', product.stock + ' en bodega'), el('span', '', product.apartado + ' apartados'), available);
    const form = el('form', 'edit-row');
    const price = el('input');
    Object.assign(price, {type:'number', min:'0', max:'50000000', step:'1', value:String(product.precio_cop), required:true});
    const stockInput = el('input');
    Object.assign(stockInput, {type:'number', min:'0', max:'100000', step:'1', value:String(product.stock), required:true});
    const priceLabel = el('label', '', 'Precio (COP)');
    priceLabel.append(price);
    const stockLabel = el('label', '', 'En bodega');
    stockLabel.append(stockInput);
    // Surtido: lo que el agente responde a «¿cuándo le llega más?». Vacío es «sin dato»: el agente no inventa.
    const restock = el('select');
    restock.setAttribute('aria-label', 'Surtido de ' + product.sku);
    [['', 'Sin dato'], ['lunes', 'Llega los lunes'], ['martes', 'Llega los martes'], ['miercoles', 'Llega los miércoles'],
     ['jueves', 'Llega los jueves'], ['viernes', 'Llega los viernes'], ['sabado', 'Llega los sábados'],
     ['descontinuado', 'Ya no se trae']].forEach(([value, text]) => {
      const option = el('option', '', text);
      option.value = value;
      restock.append(option);
    });
    const dated = /^\d{4}-\d{2}-\d{2}$/.test(product.surtido || '');
    const dateInput = el('input');
    Object.assign(dateInput, {type:'date', value: dated ? product.surtido : ''});
    dateInput.setAttribute('aria-label', 'Fecha de surtido de ' + product.sku);
    restock.value = dated ? '' : (product.surtido || '');
    const restockLabel = el('label', '', 'Surtido');
    restockLabel.append(restock);
    const dateLabel = el('label', '', 'O llega el');
    dateLabel.append(dateInput);
    const save = el('button', 'secondary', 'Guardar cambios');
    save.type = 'submit';
    save.setAttribute('aria-label', 'Guardar precio, existencias y surtido de ' + product.sku);
    form.append(priceLabel, stockLabel, restockLabel, dateLabel, save);
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const changes = {sku:product.sku};
      if (Number(price.value) !== product.precio_cop) changes.precio_cop = Number(price.value);
      if (Number(stockInput.value) !== product.stock) changes.stock = Number(stockInput.value);
      const plan = dateInput.value || restock.value;
      if (plan !== (product.surtido || '')) changes.surtido = plan;
      if (Object.keys(changes).length === 1) { say('No hay cambios en ' + product.sku + '.'); return; }
      try {
        await api('/api/inventario/actualizar', changes);
        say('Guardado: ' + product.sku, 'ok');
        loadProducts();
      } catch (error) {
        say(error.message, 'error');
      }
    });
    card.append(stock, form);
    return card;
  }
  function renderProducts() {
    const list = document.querySelector('#product-list');
    list.replaceChildren(...products.slice(0, shown).map(productCard));
    if (products.length > shown) {
      const more = el('button', 'secondary', 'Mostrar más (' + (products.length - shown) + ' restantes)');
      more.type = 'button';
      more.addEventListener('click', () => { shown += PAGE; renderProducts(); });
      list.append(more);
    }
    document.querySelector('#product-count').textContent = products.length + ' productos';
  }
  async function loadProducts() {
    const query = new URLSearchParams({q:document.querySelector('#search').value,
      categoria:document.querySelector('#category').value, bajo:document.querySelector('#low-only').checked ? '1' : '0'});
    const data = await api('/api/inventario?' + query);
    products = data.productos;
    shown = PAGE;
    const select = document.querySelector('#category');
    if (select.options.length === 1) {
      data.categorias.forEach(name => {
        select.append(new Option(name, name));
        document.querySelector('#category-options').append(new Option(name, name));
      });
    }
    renderProducts();
  }

  async function loadHistory() {
    const data = await api('/api/movimientos');
    fill(document.querySelector('#history-list'), document.querySelector('#history-empty'), data.movimientos, item =>
      el('li', '', item.hora + ' · ' + item.sku + ' · ' + item.campo + ': ' + (item.antes ?? '—') + ' → ' + item.despues));
  }

  function banCard(ban, codes) {
    const card = el('article', 'order');
    card.dataset.status = ban.vigente ? 'cancelado' : 'entregado';
    const head = el('div', 'order-head');
    const badge = el('span', 'badge', ban.vigente ? 'Bloqueada' : 'Desbloqueada');
    badge.dataset.status = card.dataset.status;
    head.append(el('span', 'order-code', 'Conversación ' + ban.sesion.slice(0, 8)), badge);
    card.append(head, el('p', '', (codes[ban.codigo] || ban.codigo) + ' (' + ban.tecnica + ')'),
      el('p', '', 'Mensaje: ' + ban.mensaje), el('p', 'muted', 'Bloqueada ' + ban.baneada));
    if (ban.vigente) {
      const actions = el('div', 'actions');
      const lift = el('button', 'secondary', 'Desbloquear');
      lift.type = 'button';
      lift.setAttribute('aria-label', 'Desbloquear la conversación ' + ban.sesion.slice(0, 8));
      lift.addEventListener('click', async () => {
        try {
          await api('/api/bloqueos/levantar', {sesion:ban.sesion});
          say('Desbloqueada: conversación ' + ban.sesion.slice(0, 8), 'ok');
        } catch (error) {
          say(error.message, 'error');
        }
        refresh();
      });
      actions.append(lift);
      card.append(actions);
    }
    return card;
  }
  async function loadBans() {
    const data = await api('/api/bloqueos');
    fill(document.querySelector('#ban-list'), document.querySelector('#bans-empty'), data.bloqueos,
      ban => banCard(ban, data.codigos));
  }

  const loaders = {resumen:loadSummary, pedidos:loadOrders, inventario:loadProducts, movimientos:loadHistory,
    bloqueos:loadBans};
  function refresh() {
    loaders[activeTab]().catch(error => say(error.message, 'error'));
  }
  tabs.forEach(tab => tab.addEventListener('click', () => {
    activeTab = tab.dataset.tab;
    tabs.forEach(item => item.setAttribute('aria-pressed', String(item === tab)));
    document.querySelectorAll('.panel').forEach(panel => { panel.hidden = panel.id !== 'tab-' + activeTab; });
    notice.hidden = true;
    refresh();
  }));
  document.querySelector('#refresh-orders').addEventListener('click', refresh);
  document.querySelector('#inventory-filter').addEventListener('submit', event => { event.preventDefault(); refresh(); });
  document.querySelector('#search').addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(refresh, 300);
  });
  document.querySelector('#category').addEventListener('change', refresh);
  document.querySelector('#low-only').addEventListener('change', refresh);
  const unitSelect = document.querySelector('#unit-select');
  UNITS.forEach(unit => unitSelect.append(new Option(unit, unit)));
  document.querySelector('#add-form').addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.target;
    const data = Object.fromEntries(new FormData(form));
    data.precio_cop = Number(data.precio_cop);
    data.stock = Number(data.stock);
    if (!data.terminos) delete data.terminos;
    try {
      const result = await api('/api/inventario/nuevo', data);
      say('Producto agregado: ' + result.producto.sku, 'ok');
      form.reset();
      loadProducts();
    } catch (error) {
      say(error.message, 'error');
    }
  });
  // Los pedidos del chat llegan solos: el resumen y la lista de pedidos se refrescan cada 15 s.
  setInterval(() => { if (activeTab === 'resumen' || activeTab === 'pedidos') refresh(); }, 15000);
  refresh();
})();
