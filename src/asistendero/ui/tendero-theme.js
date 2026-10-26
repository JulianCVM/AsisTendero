// Tema del panel: se aplica antes de pintar (script clásico en <head>) para que el modo oscuro no parpadee en claro.
// «sistema» sigue la preferencia del equipo; «claro» y «oscuro» la fijan. La elección vive en este navegador.
(function () {
  var KEY = 'tendero-tema';
  var saved = null;
  try { saved = localStorage.getItem(KEY); } catch (error) { saved = null; }
  if (saved === 'claro' || saved === 'oscuro') {
    document.documentElement.dataset.theme = saved === 'oscuro' ? 'dark' : 'light';
  }
})();
