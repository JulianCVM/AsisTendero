(() => {
  const statusPill = document.querySelector('#harness-status');
  const verdict = document.querySelector('#harness-verdict');
  const path = document.querySelector('#harness-path');
  const instructions = document.querySelector('#harness-instructions');
  const stageNames = ['validate', 'interpret', 'route', 'retrieve', 'respond', 'outcome'];
  const stageLabels = {running:'En curso', complete:'Completada', skipped:'Omitida', error:'Error'};
  const routeTexts = {
    retrieve:'Ruta: ejecutar la herramienta que pidió Grok',
    respond:'Ruta: pasar a verificar y responder',
    interpret:'Ruta: volver a Grok con un aviso del servidor (SEARCH_REQUIRED o QUOTE_REQUIRED)',
  };
  const groupTones = {verified:'success', clarify:'warning', human:'warning', safe_failure:'error'};
  let outcomes = {};
  let visits = {};
  let lastDecision = null;
  let routePending = false;
  let runningStage = null;

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function setPill(label, tone) {
    statusPill.textContent = label;
    if (tone) statusPill.dataset.tone = tone;
    else statusPill.removeAttribute('data-tone');
  }
  function setStage(name, state) {
    const stage = document.querySelector('#hstage-' + name);
    if (!stage) return;
    if (state) stage.dataset.state = state;
    else stage.removeAttribute('data-state');
    const count = (visits[name] || 0) > 1 ? ' · ' + visits[name] + ' veces' : '';
    stage.querySelector('.hstage-state').textContent = (stageLabels[state] || 'Pendiente') + count;
    if (state === 'running') runningStage = name;
  }
  function addStep(stage, text, tone) {
    const item = element('li', 'path-step');
    item.dataset.tone = tone || 'neutral';
    item.append(element('span', 'path-stage', 'Etapa ' + stage), element('span', 'path-text', text));
    path.append(item);
  }
  function codeItem(code, text, extra) {
    const item = element('li');
    item.append(element('code', '', code), element('span', '', text));
    if (extra) item.append(element('code', 'code-example', extra));
    return item;
  }

  function fill(info) {
    document.querySelectorAll('[data-harness]').forEach(node => {
      const key = node.dataset.harness;
      const value = key in info ? info[key] : info.limits?.[key];
      if (value === undefined) return;
      node.textContent = typeof value === 'number' ? value.toLocaleString('es-CO') : String(value);
    });
    instructions.textContent = info.instructions;
    document.querySelector('#harness-tools').replaceChildren(
      ...info.tools.map(tool => codeItem(tool.name, tool.returns, tool.arguments)));
    document.querySelector('#harness-rejections').replaceChildren(
      ...Object.entries(info.rejections).map(([code, text]) => codeItem(code, text)));
    const groups = document.querySelector('#harness-outcomes');
    groups.replaceChildren();
    outcomes = {};
    for (const [group, data] of Object.entries(info.outcomes)) {
      const box = element('div', 'outcome-group');
      box.dataset.group = group;
      const list = element('ul', 'code-list');
      for (const [state, label] of Object.entries(data.states)) {
        const item = codeItem(state, label);
        item.dataset.state = state;
        list.append(item);
        outcomes[state] = {group, groupLabel:data.label, label};
      }
      box.append(element('h4', '', data.label), list);
      groups.append(box);
    }
  }

  function reset() {
    visits = {};
    lastDecision = null;
    routePending = false;
    runningStage = null;
    path.replaceChildren();
    verdict.textContent = 'Ejecutando la prueba…';
    stageNames.forEach(name => setStage(name, ''));
    document.querySelectorAll('.outcome-group li').forEach(item => {
      item.removeAttribute('aria-current');
      item.querySelector('.current-mark')?.remove();
    });
    setPill('En curso', 'warning');
  }

  function onNodeRunning(node) {
    if (routePending) {
      routePending = false;
      visits.route = (visits.route || 0) + 1;
      setStage('route', 'complete');
      addStep(3, routeTexts[node] || 'Ruta: ' + node, node === 'interpret' ? 'warning' : 'neutral');
    }
    visits[node] = (visits[node] || 0) + 1;
    setStage(node, 'running');
  }

  function onNodeComplete(node, details) {
    setStage(node, 'complete');
    if (node === 'validate') {
      if (details.inyeccion) {
        addStep(1, 'Inyección detectada: ' + details.inyeccion.code + ' (' + details.inyeccion.technique +
          '); no llega a Grok', 'error');
      } else addStep(1, 'Mensaje válido: ' + (details.longitud ?? '—') + ' caracteres');
    } else if (node === 'interpret') {
      const decision = details.decision;
      if (details.error) addStep(2, 'Grok falló: ' + details.error.code, 'error');
      else if (decision && !decision.valid_json) addStep(2, 'Grok devolvió una decisión con formato inválido', 'error');
      else if (decision?.action === 'call_tool') addStep(2, 'Grok pide la herramienta ' + decision.tool);
      else addStep(2, 'Grok decide responder al cliente');
      lastDecision = decision || null;
      routePending = true;
    } else if (node === 'retrieve') {
      const call = details.tool_call || {};
      const code = call.response?.error?.code;
      if (!call.executed) addStep(4, 'El servidor rechaza ' + call.requested_tool + ' (' + code + '); no se ejecuta', 'warning');
      else if (call.response?.status === 'ok') addStep(4, 'El servidor ejecuta ' + call.requested_tool + ' · ok', 'success');
      else addStep(4, 'El servidor ejecuta ' + call.requested_tool + ' · error ' + code, 'warning');
    }
  }

  function onFinal(details) {
    const outcome = outcomes[details.estado] || {group:'', groupLabel:'Estado sin clasificar', label:details.estado};
    const tone = groupTones[outcome.group] || 'warning';
    const grokText = lastDecision?.reply?.trim();
    const usedGrok = Boolean(grokText) && details.respuesta === grokText;
    addStep(5, usedGrok ? 'Se entrega la redacción de Grok: pasó la verificación'
      : 'Se entrega la respuesta armada por el servidor con los datos de las herramientas');
    addStep(6, 'Estado ' + details.estado + ' · ' + outcome.groupLabel +
      (details.error ? ' · ' + details.error.code : ''), tone);
    if (!visits.retrieve) setStage('retrieve', 'skipped');
    setStage('outcome', 'complete');
    const current = document.querySelector('.outcome-group li[data-state="' + details.estado + '"]');
    if (current) {
      current.setAttribute('aria-current', 'true');
      current.append(element('span', 'current-mark', 'esta corrida'));
    }
    const executed = details.tools_executed?.length ?? 0;
    const rejected = (details.tools_requested?.length ?? 0) - executed;
    verdict.textContent = outcome.groupLabel + ': ' + outcome.label + '. ' + details.model_calls +
      (details.model_calls === 1 ? ' llamada' : ' llamadas') + ' a Grok, ' + executed +
      (executed === 1 ? ' herramienta ejecutada' : ' herramientas ejecutadas') + ' y ' + rejected +
      (rejected === 1 ? ' rechazada.' : ' rechazadas.');
    setPill(outcome.groupLabel, tone);
  }

  document.addEventListener('asistendero:reset', reset);
  document.addEventListener('asistendero:event', ({detail:event}) => {
    if (event.type === 'node' && event.status === 'running') onNodeRunning(event.node);
    else if (event.type === 'node') onNodeComplete(event.node, event.details || {});
    else if (event.type === 'final') onFinal(event.details || {});
    else if (event.type === 'error') {
      if (runningStage) setStage(runningStage, 'error');
      verdict.textContent = 'La prueba se detuvo: ' + (event.message || 'error de ejecución') + '.';
      setPill('Error de ejecución', 'error');
    }
  });

  fetch('/api/harness')
    .then(response => response.ok ? response.json() : Promise.reject(new Error('HTTP ' + response.status)))
    .then(fill)
    .catch(() => { instructions.textContent = 'No se pudo cargar la descripción del harness desde el visor local.'; });
})();
