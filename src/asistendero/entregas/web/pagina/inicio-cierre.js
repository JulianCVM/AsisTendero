// Confianza en /inicio: el ejemplo «dato del negocio → respuesta comprobada → decisión humana» se arma paso a paso la
// primera vez que se ve. Con movimiento reducido, o si el navegador no sabe observar, queda completo y quieto desde el inicio.
export function startProofs({calm}) {
  const demos = [...document.querySelectorAll('.g-demo')];
  if (calm.matches || !('IntersectionObserver' in window)) return;
  const watch = new IntersectionObserver(entries => entries.forEach(entry => {
    if (!entry.isIntersecting) return;
    entry.target.classList.add('is-playing');
    watch.unobserve(entry.target);
  }), {threshold: .6});
  demos.forEach(demo => watch.observe(demo));
}

// Las preguntas frecuentes comparten `name` y el navegador deja una sola abierta. Donde `<details name>` no existe,
// se cierra la anterior a mano para que la lista no crezca de golpe.
export function startFaq() {
  const list = document.querySelector('.faq');
  const items = [...document.querySelectorAll('details[name="faq"]')];
  if (!list || !items.length) return;
  if (!('name' in HTMLDetailsElement.prototype)) {
    items.forEach(item => item.addEventListener('toggle', () => {
      if (item.open) items.filter(other => other !== item).forEach(other => { other.open = false; });
    }));
  }
  reserveRoom(list, items);
}

// La lista guarda el alto que tiene con la respuesta más larga abierta: abrir o cambiar de pregunta crece dentro de
// esa caja y lo que sigue (llamado final y pie) no se mueve. Se mide de nuevo si cambia el ancho o llegan las fuentes.
function reserveRoom(list, items) {
  let measuredWidth = 0;
  const measure = () => {
    measuredWidth = list.clientWidth;
    const opened = items.find(item => item.open);
    list.classList.add('is-measuring');
    list.style.setProperty('min-height', '0px');
    let tallest = list.offsetHeight;
    items.forEach(item => {
      item.open = true;
      tallest = Math.max(tallest, list.offsetHeight);
      item.open = false;
    });
    if (opened) opened.open = true;
    list.style.setProperty('min-height', tallest + 'px');
    list.classList.remove('is-measuring');
  };
  measure();
  document.fonts?.ready.then(measure);
  if ('ResizeObserver' in window) {
    new ResizeObserver(() => { if (list.clientWidth !== measuredWidth) measure(); }).observe(list);
  }
}
