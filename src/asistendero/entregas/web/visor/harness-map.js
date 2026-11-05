// Mapa de decisión del harness: nodos y conexiones reales (harness_flow.py), con un panel por nodo que dice qué
// hace, qué recibe, qué decide y a dónde sigue. Se explora con mouse, toque y teclado (flechas, Inicio, Fin, Enter,
// Escape). En escritorio es un grafo con flechas en SVG; en celular, una lista vertical con el detalle bajo el nodo.
import {el} from './visor-comun.js';
import {extrasFor} from './harness-extras.js';

const SVG = 'http://www.w3.org/2000/svg';
const LAYER_TEXT = {prompt: 'Instrucción', model: 'Decide Grok', rule: 'Regla', data: 'Dato'};
// Conexiones que pasan por encima de la fila principal para no cruzar nodos: el aviso y la salida sin Grok.
const ARCS = {'route>interpret': 46, 'validate>respond': 78};
// Las dos salidas nuevas de la bodega van por debajo de la fila de abajo: [corrimiento en la bodega, profundidad].
// La auto-cotización vuelve a la aduana; «sin Grok» pasa bajo la aduana y sube a la balanza por su derecha.
const BELOW = {'bodega>aduana': [40, 24], 'bodega>respond': [-40, 58]};
const narrow = matchMedia('(max-width: 760px)');

function svg(tag, attributes) {
  const node = document.createElementNS(SVG, tag);
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
  return node;
}

export function createMap(info) {
  const {nodes, edges} = info.flow;
  const byId = Object.fromEntries(nodes.map(node => [node.id, node]));
  const map = document.querySelector('#flow-map');
  const list = document.querySelector('#flow-nodes');
  const links = document.querySelector('#flow-links');
  const detail = document.querySelector('#flow-detail');
  const buttons = {};
  let selected = null;
  let run = {visits: {}, walked: {}, notes: {}, final: null, tone: ''};

  const exitsOf = id => edges.filter(edge => edge.from === id);
  const entriesOf = id => edges.filter(edge => edge.to === id);

  for (const node of nodes) {
    const item = el('li', 'flow-node');
    item.dataset.node = node.id;
    const button = el('button', 'flow-button');
    button.type = 'button';
    button.setAttribute('aria-expanded', 'false');
    button.setAttribute('aria-controls', 'flow-detail');
    const tags = el('span', 'flow-tags');
    node.layers.forEach(layer => {
      const tag = el('span', 'layer-tag', LAYER_TEXT[layer]);
      tag.dataset.layer = layer;
      tags.append(tag);
    });
    const next = exitsOf(node.id).map(edge => byId[edge.to].station).join(', ');
    button.append(el('span', 'flow-station', node.station), el('strong', 'flow-title', node.title),
      el('code', 'flow-code', node.code), tags, el('span', 'flow-next', next ? 'Sigue a: ' + next : 'Fin de la corrida'),
      el('span', 'flow-state', 'Sin ejecutar'));
    button.addEventListener('click', () => select(selected === node.id ? null : node.id));
    button.addEventListener('keydown', event => onKey(event, node.id));
    buttons[node.id] = button;
    item.append(button);
    list.append(item);
  }

  function onKey(event, id) {
    const order = nodes.map(node => node.id);
    const index = order.indexOf(id);
    const moves = {ArrowRight: index + 1, ArrowDown: index + 1, ArrowLeft: index - 1, ArrowUp: index - 1,
      Home: 0, End: order.length - 1};
    if (event.key === 'Escape' && selected) {
      event.preventDefault();
      const was = selected;
      select(null);
      buttons[was].focus();
      return;
    }
    if (!(event.key in moves)) return;
    event.preventDefault();
    const target = order[(moves[event.key] + order.length) % order.length];
    buttons[target].focus();
    if (selected) select(target);
  }

  function section(title, text) {
    const box = el('section', 'flow-part');
    box.append(el('h4', '', title), el('p', '', text));
    return box;
  }
  function jumpList(title, items, pick) {
    const box = el('section', 'flow-part flow-jumps');
    const listNode = el('ul');
    for (const edge of items) {
      const target = byId[pick(edge)];
      const entry = el('li');
      const jump = el('button', 'flow-jump', target.station + ' · ' + target.title);
      jump.type = 'button';
      jump.addEventListener('click', () => { select(target.id); buttons[target.id].focus(); });
      const label = el('span', 'flow-edge-label', edge.label);
      entry.append(jump, label, el('span', 'flow-when', edge.when));
      listNode.append(entry);
    }
    box.append(el('h4', '', title), items.length ? listNode : el('p', '', 'Aquí termina la corrida.'));
    return box;
  }

  function renderDetail(id) {
    const node = byId[id];
    const close = el('button', 'flow-close', '×');
    close.type = 'button';
    close.setAttribute('aria-label', 'Cerrar el detalle de ' + node.station);
    close.addEventListener('click', () => { select(null); buttons[id].focus(); });
    const head = el('header', 'flow-detail-head');
    const titles = el('div');
    const heading = el('h3', '', node.station + ': ' + node.title);
    heading.id = 'flow-detail-title';
    titles.append(el('span', 'section-label', 'Nodo ' + node.code), heading);
    head.append(titles, close);
    const notes = run.notes[id] || [];
    const runBox = el('section', 'flow-part flow-run');
    runBox.append(el('h4', '', 'En la última ejecución'));
    if (notes.length) {
      const items = el('ol');
      notes.forEach(text => items.append(el('li', '', text)));
      runBox.append(items);
    } else {
      runBox.append(el('p', '', Object.keys(run.visits).length ? 'Esta ejecución no pasó por aquí.'
        : 'Ejecuta una prueba para ver qué pasó en este nodo.'));
    }
    const grid = el('div', 'flow-detail-grid');
    grid.append(section('Qué hace', node.does), section('Qué recibe', node.receives),
      section('Qué decide o qué regla aplica', node.decides));
    const routes = el('div', 'flow-detail-grid flow-routes');
    routes.append(jumpList('Llega desde', entriesOf(id), edge => edge.from), jumpList('A dónde sigue', exitsOf(id), edge => edge.to));
    detail.replaceChildren(head, grid, routes, runBox, ...extrasFor(id, info));
  }

  function select(id) {
    selected = id;
    Object.entries(buttons).forEach(([key, button]) => {
      button.setAttribute('aria-expanded', String(key === id));
      button.parentElement.toggleAttribute('data-selected', key === id);
    });
    detail.hidden = !id;
    if (!id) return;
    renderDetail(id);
    // En celular el detalle va justo debajo del nodo elegido; en escritorio, debajo del grafo.
    if (narrow.matches) buttons[id].parentElement.append(detail);
    else map.after(detail);
  }

  function anchor(box, side, shift = 0) {
    const points = {
      left: [box.left, box.top + box.height / 2 + shift], right: [box.right, box.top + box.height / 2 + shift],
      top: [box.left + box.width / 2 + shift, box.top], bottom: [box.left + box.width / 2 + shift, box.bottom],
    };
    return points[side];
  }
  function drawLinks() {
    links.replaceChildren();
    if (narrow.matches) return;
    const origin = map.getBoundingClientRect();
    const rect = id => {
      const box = buttons[id].getBoundingClientRect();
      return {left: box.left - origin.left, right: box.right - origin.left, top: box.top - origin.top,
        bottom: box.bottom - origin.top, width: box.width, height: box.height};
    };
    links.setAttribute('viewBox', '0 0 ' + origin.width + ' ' + origin.height);
    const defs = svg('defs', {});
    const marker = svg('marker', {id: 'flow-arrow', viewBox: '0 0 10 10', refX: '9', refY: '5', markerWidth: '7',
      markerHeight: '7', orient: 'auto-start-reverse'});
    marker.append(svg('path', {d: 'M0 0 10 5 0 10z', class: 'flow-arrow'}));
    defs.append(marker);
    links.append(defs);
    for (const edge of edges) {
      const key = edge.from + '>' + edge.to;
      const a = rect(edge.from);
      const b = rect(edge.to);
      let d;
      let label;
      let room = 0;
      if (BELOW[key]) {
        const [shift, depth] = BELOW[key];
        const [x1, y1] = anchor(a, 'bottom', shift);
        const [x2, y2] = anchor(b, 'bottom');
        const drop = y1 + depth * 1.4;
        d = `M${x1} ${y1} C${x1} ${drop} ${x2} ${drop} ${x2} ${y2}`;
        label = [(x1 + x2) / 2, y1 + depth + 4];
      } else if (ARCS[key]) {
        const [x1, y1] = anchor(a, 'top', 18);
        const [x2, y2] = anchor(b, 'top', -18);
        const lift = Math.min(y1, y2) - ARCS[key];
        d = `M${x1} ${y1} C${x1} ${lift} ${x2} ${lift} ${x2} ${y2}`;
        label = [(x1 + x2) / 2, lift + 18];
      } else if (Math.abs(a.top - b.top) < 8) {
        const forward = b.left > a.left;
        const [x1, y1] = anchor(a, forward ? 'right' : 'left');
        const [x2, y2] = anchor(b, forward ? 'left' : 'right');
        d = `M${x1} ${y1} L${x2} ${y2}`;
        label = [(x1 + x2) / 2, y1 - 8];
        room = Math.abs(x2 - x1);
      } else {
        // Entre filas: de la fila de abajo sube a la de arriba (o al revés), corrida para no montarse en otra flecha.
        const down = b.top > a.top;
        const shift = edge.from === 'aduana' && edge.to === 'interpret' ? 26 : (edge.from === 'bodega' ? -26 : 0);
        const [x1, y1] = anchor(a, down ? 'bottom' : 'top', edge.from === 'aduana' ? -a.width / 3 : shift);
        const [x2, y2] = anchor(b, down ? 'top' : 'bottom', shift);
        const middle = (y1 + y2) / 2;
        d = `M${x1} ${y1} C${x1} ${middle} ${x2} ${middle} ${x2} ${y2}`;
        label = [(x1 + x2) / 2 + 6, middle];
      }
      const group = svg('g', {class: 'flow-link', 'data-edge': key});
      if (run.walked[key]) group.setAttribute('data-walked', String(run.walked[key]));
      group.append(svg('path', {d, 'marker-end': 'url(#flow-arrow)'}));
      const text = svg('text', {x: label[0], y: label[1], 'text-anchor': 'middle'});
      text.textContent = edge.label + (run.walked[key] > 1 ? ' ×' + run.walked[key] : '');
      group.append(text);
      links.append(group);
      if (room && text.getComputedTextLength() + 10 > room) text.remove();
    }
  }

  // Estado de la última ejecución: visitas por nodo, conexiones recorridas y el nodo donde terminó.
  function update(next) {
    run = next;
    for (const [id, button] of Object.entries(buttons)) {
      const visits = run.visits[id] || 0;
      const item = button.parentElement;
      item.dataset.run = !Object.keys(run.visits).length ? '' : (visits ? 'visited' : 'skipped');
      item.toggleAttribute('data-final', run.final === id);
      if (run.final === id && run.tone) item.dataset.tone = run.tone;
      else item.removeAttribute('data-tone');
      button.querySelector('.flow-state').textContent = !Object.keys(run.visits).length ? 'Sin ejecutar'
        : run.final === id ? 'Terminó aquí' : visits > 1 ? 'Recorrido ×' + visits : visits ? 'Recorrido' : 'No pasó';
    }
    drawLinks();
    if (selected) renderDetail(selected);
  }

  new ResizeObserver(() => drawLinks()).observe(map);
  narrow.addEventListener('change', () => { drawLinks(); if (selected) select(selected); });
  document.fonts?.ready.then(drawLinks);
  drawLinks();
  return {update, select};
}
