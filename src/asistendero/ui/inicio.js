// Página pública /inicio (el tema lo pone tendero-theme.js): cabecera, menú, sección activa y apariciones al desplazarse.
// Arranca la escena de «Cómo funciona» (inicio-mostrador.js), los ejemplos por negocio (inicio-sectores.js), la demo
// del celular (inicio-demo.js) y el ejemplo de Confianza que se arma al verse (inicio-cierre.js).
// Sin red ni HTML inyectado.
import {startFaq, startProofs} from './inicio-cierre.js';
import {startDemo} from './inicio-demo.js';
import {startMostrador} from './inicio-mostrador.js';
import {startSectors} from './inicio-sectores.js';

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const calm = matchMedia('(prefers-reduced-motion: reduce)');

// ---------- Cabecera: vidrio más denso al bajar y medidor de lectura ----------
const header = $('#land-top');
const meter = $('#scroll-meter');
let ticking = false;
function onScroll() {
  ticking = false;
  header.classList.toggle('is-scrolled', scrollY > 12);
  const room = document.documentElement.scrollHeight - innerHeight;
  meter.style.setProperty('--p', room > 0 ? String(Math.min(1, scrollY / room)) : '0');
}
addEventListener('scroll', () => { if (!ticking) { ticking = true; requestAnimationFrame(onScroll); } }, {passive: true});
onScroll();

// ---------- Menú del celular ----------
const menuToggle = $('#menu-toggle');
function setMenu(open) {
  header.dataset.open = String(open);
  menuToggle.setAttribute('aria-expanded', String(open));
  menuToggle.setAttribute('aria-label', open ? 'Cerrar el menú' : 'Abrir el menú');
  menuToggle.querySelector('use').setAttribute('href', open ? '#i-x' : '#i-menu');
}
menuToggle.addEventListener('click', () => setMenu(header.dataset.open !== 'true'));
$$('#land-nav a').forEach(link => link.addEventListener('click', () => setMenu(false)));
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && header.dataset.open === 'true') { setMenu(false); menuToggle.focus(); }
});
document.addEventListener('click', event => {
  if (header.dataset.open === 'true' && !event.target.closest('#land-top')) setMenu(false);
});
matchMedia('(min-width: 980px)').addEventListener('change', () => setMenu(false));

// ---------- Sección activa en la navegación, con una píldora que se desliza ----------
const glow = $('#nav-glow');
const sectionLinks = $$('#land-nav a[href^="#"]');
function markSection(id) {
  let active = null;
  sectionLinks.forEach(link => {
    const on = link.getAttribute('href') === '#' + id;
    if (on) { link.setAttribute('aria-current', 'location'); active = link; } else link.removeAttribute('aria-current');
  });
  glow.classList.toggle('is-on', Boolean(active));
  if (active) {
    glow.style.setProperty('--x', active.offsetLeft + 'px');
    glow.style.setProperty('--w', active.offsetWidth + 'px');
  }
}
const sectionWatch = new IntersectionObserver(entries => {
  entries.filter(entry => entry.isIntersecting).forEach(entry => markSection(entry.target.id));
}, {rootMargin: '-45% 0px -50% 0px'});
// Todas las secciones de primer nivel: la navegación marca la que tenga enlace, sin repetir aquí la lista de ids.
$$('main > section[id]').forEach(section => sectionWatch.observe(section));
addEventListener('resize', () => {
  const current = sectionLinks.find(link => link.hasAttribute('aria-current'));
  if (current) markSection(current.getAttribute('href').slice(1));
});

// ---------- Apariciones: solo lo que estaba abajo al cargar, para no esconder lo que ya se ve ----------
if (!calm.matches && 'IntersectionObserver' in window) {
  const appear = new IntersectionObserver(entries => entries.forEach(entry => {
    if (!entry.isIntersecting) return;
    entry.target.classList.remove('is-pending');
    appear.unobserve(entry.target);
  }), {rootMargin: '0px 0px -8% 0px', threshold: .12});
  $$('.reveal').forEach(element => {
    if (element.getBoundingClientRect().top < innerHeight) return;
    const siblings = [...element.parentElement.children].filter(child => child.classList.contains('reveal'));
    element.style.setProperty('--delay', Math.min(siblings.indexOf(element), 4) * 90 + 'ms');
    element.classList.add('is-pending');
    appear.observe(element);
  });
}

// ---------- Explicaciones que flotan (`details[data-float]`): se cierran con Escape o tocando fuera ----------
const floating = $$('details[data-float]');
document.addEventListener('keydown', event => {
  if (event.key !== 'Escape') return;
  floating.filter(item => item.open).forEach(item => { item.open = false; item.querySelector('summary').focus(); });
});
document.addEventListener('click', event => {
  floating.filter(item => item.open && !item.contains(event.target)).forEach(item => { item.open = false; });
});

startMostrador({calm});
startSectors();
startProofs({calm});
startFaq();
startDemo({calm});
