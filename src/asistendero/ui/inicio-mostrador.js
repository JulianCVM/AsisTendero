// Escena de la portada: recorre una consulta en la ferretería isométrica (pregunta → catálogo → respuesta → pedido).
// Cada paso ilumina su pieza y escribe su detalle en el globo. Pasa solo cada 3,6 s; se detiene al mirarlo o enfocarlo,
// fuera de pantalla y con la pestaña oculta. Tocar un paso o una pieza lo deja en pausa hasta pulsar reproducir.
// Con movimiento reducido no avanza solo: se recorre con los botones. Sin JS, los cuatro pasos se leen como lista.
const STEP_MS = 3600;

export function startMostrador({calm}) {
  const figure = document.getElementById('mostrador');
  if (!figure) return;
  const svg = figure.querySelector('.mo-svg');
  const callout = document.getElementById('mo-callout');
  const play = document.getElementById('mo-play');
  const steps = [...figure.querySelectorAll('.mo-step')];
  let current = 0;
  let stopped = calm.matches;   // pausa elegida por quien lee (o movimiento reducido)
  let hovering = false;
  let visible = true;
  let timer = null;

  // El globo se coloca en px sobre la pieza (con 130 px de margen a los lados) y se mueve con translate.
  function anchor(piece) {
    const [x, y] = (svg?.dataset['anchor' + piece[0].toUpperCase() + piece.slice(1)] || '50 0').split(' ').map(Number);
    const stage = callout.parentElement;
    const width = stage.clientWidth;
    callout.style.setProperty('--tx', Math.min(Math.max(130, width * x / 100), width - 130) + 'px');
    callout.style.setProperty('--ty', stage.clientHeight * y / 100 + 'px');
  }
  function show(index) {
    current = (index + steps.length) % steps.length;
    const step = steps[current];
    steps.forEach(button => button.setAttribute('aria-pressed', String(button === step)));
    figure.dataset.step = step.dataset.step;
    figure.dataset.active = step.dataset.piece;
    anchor(step.dataset.piece);
    callout.textContent = step.querySelector('.mo-detail').textContent;
  }
  function running() { return !stopped && !hovering && visible && !document.hidden; }
  function schedule() {
    clearTimeout(timer);
    if (running()) timer = setTimeout(() => { show(current + 1); schedule(); }, STEP_MS);
  }
  function renderPlay() {
    play.setAttribute('aria-pressed', String(stopped));
    play.setAttribute('aria-label', stopped ? 'Reproducir el recorrido' : 'Pausar el recorrido');
    play.querySelector('use').setAttribute('href', stopped ? '#i-play' : '#i-pause');
  }
  function stop() { stopped = true; renderPlay(); schedule(); }

  figure.classList.add('is-live');
  play.hidden = false;
  steps.forEach((button, index) => button.addEventListener('click', () => { show(index); stop(); }));
  // Tocar una pieza del dibujo lleva a su primer paso (el celular, a la pregunta).
  svg?.addEventListener('click', event => {
    const piece = event.target.closest('[data-piece]')?.dataset.piece;
    const index = steps.findIndex(button => button.dataset.piece === piece);
    if (index >= 0) { show(index); stop(); }
  });
  play.addEventListener('click', () => { stopped = !stopped; renderPlay(); schedule(); });
  figure.addEventListener('pointerenter', event => { if (event.pointerType === 'mouse') { hovering = true; schedule(); } });
  figure.addEventListener('pointerleave', () => { hovering = false; schedule(); });
  figure.addEventListener('focusin', () => { hovering = true; schedule(); });
  figure.addEventListener('focusout', event => { if (!figure.contains(event.relatedTarget)) { hovering = false; schedule(); } });
  document.addEventListener('visibilitychange', schedule);
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; schedule(); }, {threshold: .25}).observe(figure);
  }
  calm.addEventListener?.('change', () => { if (calm.matches) stop(); });
  // El globo va en px: si la escena cambia de tamaño, se vuelve a poner sobre la pieza del paso actual.
  if ('ResizeObserver' in window) new ResizeObserver(() => anchor(steps[current].dataset.piece)).observe(callout.parentElement);
  show(0);
  renderPlay();
  schedule();
}
