(() => {
  const form = document.querySelector('#form');
  const query = document.querySelector('#query');
  const run = document.querySelector('#run');
  const status = document.querySelector('#status');
  const answer = document.querySelector('#answer');
  const responseBox = document.querySelector('#response-box');
  const customerMessage = document.querySelector('#customer-message');
  const customerText = document.querySelector('#customer-text');
  const list = document.querySelector('#event-list');
  const empty = document.querySelector('#empty-events');
  const counter = document.querySelector('#counter');
  const download = document.querySelector('#download');
  const copy = document.querySelector('#copy-answer');
  const expand = document.querySelector('#expand-events');
  const costAmount = document.querySelector('#cost-amount');
  const costBasis = document.querySelector('#cost-basis');
  const costLines = document.querySelector('#cost-lines');
  const filterButtons = [...document.querySelectorAll('[data-filter]')];
  const nodeNames = ['validate', 'interpret', 'retrieve', 'respond'];
  const nodeLabels = {validate:'Validar mensaje', interpret:'Grok decide', retrieve:'Ejecutar herramienta', respond:'Resolver y verificar'};
  const stateLabels = {found:'Productos encontrados', partial:'Resultado parcial', clarify:'Falta aclaración', not_found:'Sin coincidencia', answered:'Respondido', model_invalid:'Respuesta no válida', quoted:'Cotización informativa', nearby:'Opciones cercanas', insufficient_stock:'Existencias insuficientes', quote_error:'Cotización no disponible', tool_error:'Catálogo no disponible', not_verified:'Sin verificar', model_error:'Fallo del modelo', limit_reached:'Límite de herramientas'};
  let events = [];
  let activeFilter = 'all';
  let tokenTotal = 0;
  let tokenKnown = false;
  let currentAnswer = '';
  let runningNode = null;
  let callCosts = [];

  function formatUsd(value) {
    const amount = Number(value);
    return Number.isFinite(amount) ? '$' + amount.toLocaleString('en-US', {
      minimumFractionDigits: 6, maximumFractionDigits: 8
    }) : 'No disponible';
  }
  function costLabel(basis) {
    return ({api_reported:'Informado por la API', xai_public_estimate:'Estimado con tarifa pública xAI',
      mixed:'Mezcla de costo informado y estimado'})[basis] || 'Costo no disponible';
  }
  function renderCost(finalCost, finished = false) {
    const known = callCosts.filter(item => item.cost);
    if (finalCost) {
      costAmount.textContent = formatUsd(finalCost.usd);
      costBasis.textContent = costLabel(finalCost.basis) + ' · ' + finalCost.calls +
        (finalCost.calls === 1 ? ' llamada' : ' llamadas');
    } else if (!known.length) {
      costAmount.textContent = '—';
      costBasis.textContent = finished ? 'No disponible para esta ejecución.' : 'Esperando uso de Grok…';
    } else {
      const subtotal = known.reduce((sum, item) => sum + Number(item.cost.usd), 0);
      costAmount.textContent = formatUsd(subtotal);
      costBasis.textContent = 'Parcial' + (finished ? ' · ejecución incompleta' : '') +
        ' · ' + known.length + ' de ' + callCosts.length + ' llamadas con costo';
    }
  }
  function addCallCost(details) {
    callCosts.push({phase:details.phase, cost:details.cost});
    const line = document.createElement('div');
    line.className = 'cost-line';
    const phase = document.createElement('span');
    phase.textContent = details.phase === 'resolve' ? 'Resolver productos' : 'Interpretar mensaje';
    const amount = document.createElement('span');
    amount.textContent = details.cost ? formatUsd(details.cost.usd) : 'No disponible';
    line.append(phase, amount);
    costLines.append(line);
    renderCost(null);
  }

  function setStatus(label, tone) {
    status.textContent = label;
    if (tone) status.dataset.tone = tone;
    else status.removeAttribute('data-tone');
  }
  function setStep(name, state) {
    const element = document.querySelector('#step-' + name);
    if (!element) return;
    element.className = 'step ' + state;
    element.querySelector('.step-state').textContent =
      ({running:'En curso', complete:'Completado', skipped:'Omitido', error:'Error'})[state] || 'Pendiente';
    if (state === 'running') runningNode = name;
  }
  function updateCount() {
    document.querySelector('#char-count').textContent = query.value.length + ' / 2000';
  }
  function reset() {
    customerText.textContent = query.value.trim();
    customerMessage.hidden = false;
    events = [];
    tokenTotal = 0;
    tokenKnown = false;
    currentAnswer = '';
    runningNode = null;
    callCosts = [];
    costLines.replaceChildren();
    costAmount.textContent = '—';
    costBasis.textContent = 'Esperando uso de Grok…';
    list.replaceChildren(empty);
    empty.hidden = false;
    counter.textContent = '0 eventos · expande uno para ver sus parámetros.';
    answer.textContent = 'Estoy revisando tu consulta…';
    responseBox.classList.remove('is-empty');
    setStatus('Ejecutando', 'warning');
    document.querySelector('#metric-route').textContent = '—';
    document.querySelector('#metric-calls').textContent = '—';
    document.querySelector('#metric-tokens').textContent = '—';
    document.querySelector('#metric-duration').textContent = '—';
    download.disabled = true;
    copy.disabled = true;
    expand.disabled = true;
    expand.textContent = 'Expandir visibles';
    nodeNames.forEach(name => setStep(name, ''));
    // harness.js escucha estos eventos para iluminar el mapa del harness.
    document.dispatchEvent(new CustomEvent('asistendero:reset'));
  }
  function kindOf(event) {
    if (event.type === 'model_request' || event.type === 'model_response') return 'model';
    if (event.type === 'node' && event.node === 'retrieve') return 'tool';
    if (event.type === 'error') return 'system';
    return 'system';
  }
  function titleOf(event) {
    if (event.type === 'node') return nodeLabels[event.node] + ' · ' + (event.status === 'running' ? 'iniciando' : 'completado');
    if (event.type === 'model_request') return 'Solicitud a Grok · ' + (event.details?.phase === 'resolve' ? 'resolver' : 'interpretar');
    if (event.type === 'model_response') return 'Respuesta de Grok · ' + (event.details?.phase === 'resolve' ? 'resolver' : 'interpretar');
    return ({input:'Mensaje recibido', route:'Ruta decidida', final:'Resultado final', error:'Error de ejecución'})[event.type] || event.type;
  }
  function subtitleOf(event) {
    if (event.type === 'node' && event.node === 'retrieve' && event.status === 'complete') {
      const call = event.details?.tool_call || {};
      return (call.requested_tool || 'Herramienta') + ' · ' + (call.response?.status || '—');
    }
    return ({model:'Grok', tool:'Catálogo', system:'Sistema', error:'Error'})[kindOf(event)];
  }
  function renderFilter() {
    let visible = 0;
    list.querySelectorAll('.event').forEach(row => {
      row.hidden = activeFilter !== 'all' && row.dataset.kind !== activeFilter;
      if (!row.hidden) visible += 1;
    });
    empty.hidden = events.length > 0 && visible > 0;
    if (!empty.hidden) {
      empty.textContent = events.length ? 'No hay eventos de esta categoría en la ejecución.' :
        'La traza aparecerá aquí. Prueba «Horario» o «Dos productos» para recorrer el agente.';
    }
    counter.textContent = events.length + (events.length === 1 ? ' evento' : ' eventos') +
      (activeFilter === 'all' ? '' : ' · ' + visible + ' visibles');
  }
  function addEvent(event) {
    events.push(event);
    const row = document.createElement('details');
    row.className = 'event';
    row.dataset.kind = kindOf(event);
    row.dataset.type = event.type;
    if (event.type === 'final' || event.type === 'error') row.open = true;
    const summary = document.createElement('summary');
    const index = document.createElement('span');
    index.className = 'event-index';
    index.textContent = String(events.length).padStart(2, '0');
    const main = document.createElement('span');
    main.className = 'event-main';
    const title = document.createElement('span');
    title.className = 'event-title';
    title.textContent = titleOf(event);
    const subtitle = document.createElement('span');
    subtitle.className = 'event-kind';
    subtitle.textContent = subtitleOf(event);
    main.append(title, subtitle);
    const time = document.createElement('span');
    time.className = 'event-time';
    time.textContent = (event.elapsed_ms ?? 0) + ' ms';
    const data = document.createElement('pre');
    data.textContent = JSON.stringify(event.details ?? event, null, 2);
    summary.append(index, main, time);
    row.append(summary, data);
    list.append(row);
    renderFilter();
    download.disabled = false;
    expand.disabled = false;
    if (!row.hidden) list.scrollTop = list.scrollHeight;
  }
  function show(event) {
    document.dispatchEvent(new CustomEvent('asistendero:event', {detail:event}));
    if (event.type === 'node') {
      setStep(event.node, event.status);
      if (event.status === 'running') setStatus(nodeLabels[event.node], 'warning');
    }
    if (event.type === 'route') setStep('retrieve', 'skipped');
    if (event.type === 'model_response') {
      addCallCost(event.details || {});
      for (const value of [event.details?.input_tokens, event.details?.output_tokens]) {
        if (typeof value === 'number') { tokenTotal += value; tokenKnown = true; }
      }
      document.querySelector('#metric-tokens').textContent = tokenKnown ? tokenTotal.toLocaleString('es-CO') : 's/d';
      if (event.details?.phase === 'interpret') {
        const plan = event.details;
        const route = plan.action === 'call_tool' ? 'Herramientas' : 'Directa';
        document.querySelector('#metric-route').textContent = route;
      }
    }
    if (event.type === 'final') {
      const result = event.details || {};
      currentAnswer = result.respuesta || '';
      answer.textContent = currentAnswer;
      document.querySelector('#metric-calls').textContent = String(result.model_calls ?? '—');
      document.querySelector('#metric-duration').textContent = (event.elapsed_ms ?? 0).toLocaleString('es-CO') + ' ms';
      renderCost(result.cost, true);
      setStatus(stateLabels[result.estado] || result.estado || 'Finalizado',
        ['found', 'answered'].includes(result.estado) || result.estado === 'quoted' ? 'success' : 'warning');
      copy.disabled = !currentAnswer;
    }
    if (event.type === 'error') {
      setStatus('Error de ejecución', 'error');
      answer.textContent = event.message || 'No se pudo completar la prueba.';
      if (runningNode) setStep(runningNode, 'error');
      responseBox.classList.remove('is-empty');
      renderCost(null, true);
    }
    addEvent(event);
  }

  query.addEventListener('input', updateCount);
  document.querySelectorAll('[data-example]').forEach(button => button.addEventListener('click', () => {
    query.value = button.dataset.example;
    updateCount();
    query.focus();
  }));
  filterButtons.forEach(button => button.addEventListener('click', () => {
    activeFilter = button.dataset.filter;
    filterButtons.forEach(item => item.setAttribute('aria-pressed', String(item === button)));
    renderFilter();
  }));
  expand.addEventListener('click', () => {
    const visible = [...list.querySelectorAll('.event:not([hidden])')];
    const shouldOpen = visible.some(row => !row.open);
    visible.forEach(row => { row.open = shouldOpen; });
    expand.textContent = shouldOpen ? 'Contraer visibles' : 'Expandir visibles';
  });
  copy.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(currentAnswer);
      copy.textContent = 'Copiado';
      setTimeout(() => { copy.textContent = 'Copiar respuesta'; }, 1600);
    } catch {
      copy.textContent = 'No se pudo copiar';
      setTimeout(() => { copy.textContent = 'Copiar respuesta'; }, 2000);
    }
  });
  download.addEventListener('click', () => {
    const blob = new Blob([JSON.stringify(events, null, 2)], {type:'application/json'});
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'asistendero-traza-' + Date.now() + '.json';
    link.click();
    URL.revokeObjectURL(url);
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!query.value.trim()) return;
    reset();
    run.disabled = true;
    run.textContent = 'Ejecutando…';
    try {
      const response = await fetch('/api/trace', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({consulta:query.value})
      });
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || 'Error HTTP ' + response.status);
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let pending = '';
      while (true) {
        const {done, value} = await reader.read();
        if (done) break;
        pending += decoder.decode(value, {stream:true});
        const lines = pending.split('\n');
        pending = lines.pop();
        for (const line of lines) if (line.trim()) show(JSON.parse(line));
      }
      pending += decoder.decode();
      if (pending.trim()) show(JSON.parse(pending));
      if (!events.some(item => item.type === 'final' || item.type === 'error')) {
        throw new Error('La traza terminó sin resultado.');
      }
    } catch (error) {
      show({type:'error', message:error.message, elapsed_ms:0});
    } finally {
      run.disabled = false;
      run.textContent = 'Ejecutar prueba ↗';
    }
  });
  updateCount();
})();
