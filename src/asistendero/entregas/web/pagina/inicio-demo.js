// Motor de la demo de /inicio: reproduce los casos de inicio-escenas.js en el celular, en «Qué comprobó» y en el panel.
// Todo es texto fijo pintado con textContent; no hay red. Se pausa con el botón, fuera de pantalla y con la pestaña
// oculta, para no correr sin que nadie mire.
import {SCENES, TAGS} from './inicio-escenas.js';

const STOP = Symbol('demo-detenida');
const SVG = 'http://www.w3.org/2000/svg';
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

function icon(name) {
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('class', 'icon');
  svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS(SVG, 'use');
  use.setAttribute('href', '#i-' + name);
  svg.append(use);
  return svg;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

const WHO = {cliente: 'Cliente', agente: 'AsisTendero', tendero: 'Tendero'};
const STYLE = {cliente: 'from-customer', agente: 'from-agent', tendero: 'from-staff', aviso: 'from-notice'};
const ONLINE = 'AsisTendero · en línea';

export function startDemo({calm}) {
  const stage = document.querySelector('.demo-stage');
  if (!stage) return;
  const thread = document.getElementById('phone-thread');
  const composer = document.getElementById('composer-field');
  const send = document.querySelector('.composer-send');
  const presence = document.getElementById('phone-presence');
  const insideList = document.getElementById('inside-list');
  const mirrorList = document.getElementById('mirror-list');
  const toggle = document.getElementById('demo-toggle');
  const panelTab = document.querySelector('.pane-tab[data-pane="panel"]');
  const rail = document.getElementById('scenario-rail');
  const count = document.getElementById('demo-count');
  const state = {generation: 0, paused: false, hidden: true, index: 0};
  const reduced = () => calm.matches;

  // Espera que solo avanza mientras la demo está a la vista y sin pausa; un caso nuevo corta la espera del anterior.
  // Descuenta el tiempo real transcurrido: si el navegador frena los temporizadores, la demo no se atrasa.
  async function wait(ms, generation) {
    let left = ms;
    let last = performance.now();
    while (left > 0) {
      if (generation !== state.generation) throw STOP;
      await sleep(Math.min(left, 80));
      const now = performance.now();
      if (!state.paused && !state.hidden) left -= now - last;
      last = now;
    }
    if (generation !== state.generation) throw STOP;
  }
  const readTime = text => Math.min(4200, Math.max(1400, 700 + text.length * 26));

  function scrollThread() {
    thread.scrollTo({top: thread.scrollHeight, behavior: reduced() ? 'auto' : 'smooth'});
  }

  function bubble(step) {
    const item = el('li', 'msg ' + STYLE[step.say]);
    if (step.say === 'aviso') {
      const text = el('p', 'msg-text');
      text.append(icon('lock'), document.createTextNode(step.text));
      item.append(text);
    } else {
      item.append(el('span', 'msg-who', WHO[step.say]), el('p', 'msg-text', step.text));
      if (step.check) {
        const check = el('span', 'msg-check');
        check.append(icon('check'), document.createTextNode(step.check));
        item.append(check);
      }
    }
    thread.append(item);
    scrollThread();
  }

  async function customerTypes(step, generation) {
    composer.classList.add('is-typing');
    if (reduced()) {
      composer.textContent = step.text;
      await wait(500, generation);
    } else {
      for (let length = 1; length <= step.text.length; length++) {
        composer.textContent = step.text.slice(0, length);
        await wait(32, generation);
      }
      await wait(260, generation);
    }
    send.classList.add('is-sending');
    composer.classList.remove('is-typing');
    composer.textContent = 'Escribe un mensaje';
    bubble(step);
    await wait(180, generation);
    send.classList.remove('is-sending');
  }

  async function replyWithTyping(step, generation) {
    const busy = step.say === 'tendero' ? 'Tendero · escribiendo…' : 'AsisTendero · escribiendo…';
    const before = presence.textContent;
    presence.textContent = busy;
    presence.classList.add('is-busy');
    const typing = el('li', 'typing');
    typing.setAttribute('aria-hidden', 'true');
    typing.append(el('span'), el('span'), el('span'));
    thread.append(typing);
    scrollThread();
    try {
      await wait(1100, generation);
    } finally {
      typing.remove();
      presence.textContent = before;
      presence.classList.remove('is-busy');
    }
    bubble(step);
  }

  function insideStep(data) {
    insideList.querySelector('.is-now')?.classList.remove('is-now');
    const item = el('li', 'step is-now');
    item.append(el('span', 'tag tag-' + data.tag, TAGS[data.tag]), el('p', '', data.text));
    insideList.append(item);
    insideList.scrollTo({top: insideList.scrollHeight, behavior: reduced() ? 'auto' : 'smooth'});
    document.getElementById('inside-empty').hidden = true;
  }

  function panelCard(data) {
    let card = mirrorList.querySelector(`[data-id="${data.id}"]`);
    const fresh = !card;
    if (fresh) {
      card = el('li', 'mirror');
      card.dataset.id = data.id;
      mirrorList.prepend(card);
    }
    card.replaceChildren(icon(data.icon), el('strong', '', data.title), el('p', '', data.detail),
      el('span', 'pill ' + data.tone, data.state));
    if (!fresh) {
      card.classList.remove('flash');
      void card.offsetWidth;  // reinicia la animación del destello en cada cambio
      card.classList.add('flash');
    }
    document.getElementById('mirror-empty').hidden = true;
    if (panelTab && panelTab.getAttribute('aria-pressed') !== 'true') panelTab.classList.add('has-news');
  }

  async function run(step, generation) {
    if (step.say === 'cliente') return customerTypes(step, generation).then(() => wait(700, generation));
    if (step.say === 'aviso') { bubble(step); return wait(900, generation); }
    if (step.say) {
      await replyWithTyping(step, generation);
      return wait(readTime(step.text), generation);
    }
    if (step.inside) { insideStep(step.inside); return wait(750, generation); }
    if (step.panel) { panelCard(step.panel); return wait(850, generation); }
    if (step.presence) { presence.textContent = step.presence; presence.classList.add('is-busy'); return wait(300, generation); }
  }

  const buttons = SCENES.map((scene, index) => {
    const button = el('button', 'scenario', scene.label);
    button.type = 'button';
    button.setAttribute('aria-pressed', 'false');
    // Elegir un caso es pedir verlo: si estaba en pausa, sigue.
    button.addEventListener('click', () => { setPaused(false); play(index); });
    return button;
  });
  const list = document.getElementById('scenario-list');
  list.append(...buttons);

  // La fila de casos se desplaza en pantallas angostas: un borde difuminado avisa de que hay más casos a ese lado.
  function updateFade() {
    const sides = [];
    if (list.scrollLeft > 4) sides.push('start');
    if (list.scrollLeft + list.clientWidth < list.scrollWidth - 4) sides.push('end');
    rail.dataset.fade = sides.join(' ');
  }
  list.addEventListener('scroll', updateFade, {passive: true});
  new ResizeObserver(updateFade).observe(list);

  function reset() {
    thread.replaceChildren();
    insideList.replaceChildren();
    mirrorList.replaceChildren();
    document.getElementById('inside-empty').hidden = false;
    document.getElementById('mirror-empty').hidden = false;
    composer.classList.remove('is-typing');
    composer.textContent = 'Escribe un mensaje';
    presence.textContent = ONLINE;
    presence.classList.remove('is-busy');
    panelTab?.classList.remove('has-news');
  }

  async function play(index) {
    const generation = ++state.generation;
    state.index = index;
    const scene = SCENES[index];
    buttons.forEach((button, position) => {
      button.setAttribute('aria-pressed', String(position === index));
      button.style.setProperty('--progress', '0');
    });
    const current = buttons[index];
    // Solo se desplaza la fila de casos, nunca la página: la demo puede avanzar mientras se lee otra sección.
    const offset = current.getBoundingClientRect().left - list.getBoundingClientRect().left - 8;
    list.scrollBy({left: offset, behavior: reduced() ? 'auto' : 'smooth'});
    count.textContent = `Caso ${index + 1} de ${SCENES.length}`;
    reset();
    try {
      await wait(500, generation);
      for (const [position, step] of scene.steps.entries()) {
        await run(step, generation);
        current.style.setProperty('--progress', String((position + 1) / scene.steps.length));
      }
      await wait(3200, generation);
      play((index + 1) % SCENES.length);
    } catch (error) {
      if (error !== STOP) throw error;
    }
  }

  function setPaused(paused) {
    state.paused = paused;
    toggle.querySelector('use').setAttribute('href', paused ? '#i-play' : '#i-pause');
    toggle.setAttribute('aria-label', paused ? 'Reanudar la simulación' : 'Pausar la simulación');
  }
  toggle.addEventListener('click', () => setPaused(!state.paused));
  document.getElementById('demo-restart').addEventListener('click', () => { setPaused(false); play(state.index); });
  const step = delta => { setPaused(false); play((state.index + delta + SCENES.length) % SCENES.length); };
  document.getElementById('demo-prev').addEventListener('click', () => step(-1));
  document.getElementById('demo-next').addEventListener('click', () => step(1));

  // En el celular se ve una vista a la vez debajo del chat; desde 760 px las dos (lo resuelve el CSS).
  stage.dataset.pane = 'inside';
  document.querySelectorAll('.pane-tab').forEach(tab => tab.addEventListener('click', () => {
    stage.dataset.pane = tab.dataset.pane;
    document.querySelectorAll('.pane-tab').forEach(other => other.setAttribute('aria-pressed', String(other === tab)));
    tab.classList.remove('has-news');
  }));

  const section = document.getElementById('demo');
  const visible = {screen: false};
  const update = () => { state.hidden = !visible.screen || document.hidden; };
  new IntersectionObserver(entries => {
    visible.screen = entries[0].isIntersecting;
    update();
  }, {threshold: .15}).observe(section);
  document.addEventListener('visibilitychange', update);
  play(0);
}
