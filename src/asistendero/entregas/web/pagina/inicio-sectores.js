// «Cómo podría adaptarse a tu negocio»: pestañas de ejemplos por tipo de negocio (patrón de pestañas de ARIA, con flechas).
// Sin JS las pestañas no aparecen y los ejemplos se leen uno tras otro; con JS se ve uno a la vez, los otros quedan
// ocultos de verdad (hidden) y el CSS los apila en la misma celda para que la altura no salte al cambiar.
export function startSectors() {
  const list = document.querySelector('.sector-tabs');
  if (!list) return;
  const tabs = [...list.querySelectorAll('[role="tab"]')];
  function select(tab, focus) {
    tabs.forEach(other => {
      const on = other === tab;
      other.setAttribute('aria-selected', String(on));
      other.tabIndex = on ? 0 : -1;
      document.getElementById(other.getAttribute('aria-controls')).hidden = !on;
    });
    if (focus) tab.focus();
  }
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => select(tab, false));
    tab.addEventListener('keydown', event => {
      const moves = {ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: tabs.length - 1};
      if (!(event.key in moves)) return;
      event.preventDefault();
      select(tabs[(moves[event.key] + tabs.length) % tabs.length], true);
    });
  });
  list.hidden = false;
  list.parentElement.classList.add('is-live');
  select(tabs.find(tab => tab.getAttribute('aria-selected') === 'true') || tabs[0], false);
}
