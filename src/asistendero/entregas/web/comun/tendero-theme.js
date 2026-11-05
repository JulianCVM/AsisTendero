// Apariencia común de la página pública, el panel del tendero y el visor de pruebas.
// Script clásico en <head>: aplica el tema guardado antes de pintar, para que el modo oscuro no parpadee en claro, y al
// cargar la página conecta cada selector [data-theme-switch] (sol = claro, luna = oscuro, «Sistema» = el del equipo).
// La elección se guarda en una cookie y no en localStorage porque el visor (8765) y el panel (8766) son orígenes
// distintos: localStorage se separa por puerto y la cookie de 127.0.0.1 no, así las tres pantallas usan el mismo tema.
(function () {
  var KEY = 'tendero-tema';
  var CHOICES = ['claro', 'oscuro', 'sistema'];
  var root = document.documentElement;
  var systemDark = window.matchMedia('(prefers-color-scheme: dark)');
  var calm = window.matchMedia('(prefers-reduced-motion: reduce)');

  function read() {
    var match = document.cookie.match(/(?:^|;\s*)tendero-tema=(claro|oscuro|sistema)/);
    if (match) return match[1];
    // Quien eligió tema antes de la cookie lo tenía en localStorage: se respeta y se copia a la cookie.
    var saved = null;
    try { saved = localStorage.getItem(KEY); } catch (error) { saved = null; }
    return CHOICES.indexOf(saved) >= 0 ? saved : 'sistema';
  }
  function save(choice) {
    document.cookie = KEY + '=' + choice + '; path=/; max-age=31536000; SameSite=Strict';
    try { localStorage.setItem(KEY, choice); } catch (error) { /* sin almacenamiento: queda la cookie */ }
  }
  function darkFor(choice) {
    return choice === 'oscuro' || (choice === 'sistema' && systemDark.matches);
  }
  function apply(choice) {
    if (choice === 'sistema') delete root.dataset.theme;
    else root.dataset.theme = choice === 'oscuro' ? 'dark' : 'light';
    var dark = darkFor(choice);
    // Lo que tiene su propio tema (el castillo isométrico del visor) sigue al de la página.
    document.querySelectorAll('[data-follow-theme]').forEach(function (node) { node.dataset.theme = dark ? 'dark' : 'light'; });
    document.querySelectorAll('[data-theme-choice]').forEach(function (button) {
      button.setAttribute('aria-pressed', String(button.dataset.themeChoice === choice));
    });
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) {
      if (!meta.dataset.light) meta.dataset.light = meta.content;
      meta.content = dark ? (meta.dataset.dark || '#0A1519') : meta.dataset.light;
    }
  }
  // El círculo se abre desde el botón tocado; sin View Transitions o con movimiento reducido, el cambio es directo.
  function choose(choice, button) {
    var before = darkFor(read());
    save(choice);
    if (before === darkFor(choice) || calm.matches || !document.startViewTransition) { apply(choice); return; }
    var box = button.getBoundingClientRect();
    var x = box.left + box.width / 2;
    var y = box.top + box.height / 2;
    root.style.setProperty('--vt-x', x + 'px');
    root.style.setProperty('--vt-y', y + 'px');
    root.style.setProperty('--vt-r', Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y)) + 'px');
    document.startViewTransition(function () { apply(choice); });
  }

  apply(read());
  document.addEventListener('DOMContentLoaded', function () {
    apply(read());
    document.addEventListener('click', function (event) {
      var button = event.target.closest('[data-theme-choice]');
      if (button && CHOICES.indexOf(button.dataset.themeChoice) >= 0) choose(button.dataset.themeChoice, button);
    });
  });
  systemDark.addEventListener('change', function () { apply(read()); });
  // Otra pestaña cambió el tema: al volver a esta, se aplica el mismo.
  document.addEventListener('visibilitychange', function () { if (!document.hidden) apply(read()); });
})();
