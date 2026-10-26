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
  const sessionMode = document.querySelector('#session-mode');
  const newSession = document.querySelector('#new-session');
  const sessionLabel = document.querySelector('#session-label');
  const history = document.querySelector('#chat-history');
  const scroller = document.querySelector('#chat-scroll');
  const thread = document.querySelector('#chat-thread');
  const jumpLatest = document.querySelector('#jump-latest');
  // En celular, Enter es salto de línea y el mensaje se manda con el botón, como en las apps de chat.
  const touch = window.matchMedia('(pointer: coarse)');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const MAX_INPUT_HEIGHT = 180;
  const SEND_LABEL = 'Enviar ↗';
  // Si quien lee subió a ver mensajes anteriores, un mensaje nuevo no lo arrastra al final: aparece el botón.
  let followLatest = true;
  // El servidor crea el identificador de la sesión; el visor solo lo devuelve en el turno siguiente.
  let sessionId = null;
  let turnNumber = 0;
  const nodeNames = ['validate', 'interpret', 'retrieve', 'respond'];
  const nodeLabels = {validate:'Validar mensaje', interpret:'Grok decide', retrieve:'Ejecutar herramienta', respond:'Resolver y verificar'};
  const stateLabels = {order_pending:'Pedido por confirmar', order_confirmed:'Pedido confirmado', pickup_scheduled:'Recogida agendada', order_cancelled:'Pedido cancelado', order_status:'Estado del pedido', order_issue:'Pedido con novedad', informed:'Información de la tienda', refused:'Pedido no permitido', blocked:'Mensaje bloqueado', found:'Productos encontrados', partial:'Resultado parcial', clarify:'Falta aclaración', not_found:'Sin coincidencia', answered:'Respondido', model_invalid:'Respuesta no válida', quoted:'Cotización informativa', nearby:'Opciones cercanas', insufficient_stock:'Existencias insuficientes', quote_error:'Cotización no disponible', tool_error:'Catálogo no disponible', not_verified:'Sin verificar', model_error:'Fallo del modelo', limit_reached:'Límite de herramientas', handoff:'Avisado al tendero', staff:'Atiende el tendero'};
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
  function fitInput() {
    query.style.height = 'auto';
    query.style.height = Math.min(query.scrollHeight + 2, MAX_INPUT_HEIGHT) + 'px';
  }
  function atBottom() {
    return scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 48;
  }
  function toLatest(smooth = false) {
    scroller.scrollTo({top:scroller.scrollHeight, behavior:smooth && !reducedMotion.matches ? 'smooth' : 'auto'});
    followLatest = true;
    jumpLatest.hidden = true;
  }
  function followThread() {
    if (followLatest) toLatest();
    else jumpLatest.hidden = false;
  }
  function historyRow(role, text) {
    const row = document.createElement('div');
    row.className = 'chat-row ' + role;
    const icon = document.createElement('span');
    icon.className = 'chat-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = role === 'customer' ? 'C' : (role === 'notice' ? '!' : 'AT');
    const body = document.createElement('div');
    const speaker = document.createElement('span');
    speaker.className = 'speaker';
    speaker.textContent = {customer:'Cliente', notice:'AsisTendero · aviso automático'}[role] || 'AsisTendero';
    const bubble = document.createElement('div');
    bubble.className = role === 'customer' ? 'bubble' : (role === 'notice' ? 'bubble agent-bubble notice-bubble' : 'bubble agent-bubble');
    bubble.textContent = text;
    body.append(speaker, bubble);
    row.append(icon, body);
    return row;
  }
  function renderSessionLabel() {
    sessionLabel.textContent = !sessionMode.checked ? 'Una consulta por ejecución' :
      (turnNumber ? 'Conversación con memoria · turno ' + turnNumber : 'Conversación con memoria · sin turnos');
    newSession.disabled = !sessionMode.checked || !sessionId;
  }
  function clearSession() {
    sessionId = null;
    turnNumber = 0;
    history.replaceChildren();
    renderSessionLabel();
  }
  function reset() {
    // En una conversación, el turno anterior pasa al historial antes de mostrar el nuevo.
    if (sessionMode.checked && sessionId && !customerMessage.hidden && currentAnswer) {
      history.append(historyRow('customer', customerText.textContent), historyRow('agent', currentAnswer));
    } else if (!sessionMode.checked) {
      history.replaceChildren();
    }
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
    responseBox.classList.add('is-typing');
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
    return ({input:'Mensaje recibido', route:'Ruta decidida', final:'Resultado final', error:'Error de ejecución',
      session:'Memoria de la sesión', ban:'Conversación bloqueada'})[event.type] || event.type;
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
      responseBox.classList.remove('is-typing');
      document.querySelector('#metric-calls').textContent = String(result.model_calls ?? '—');
      document.querySelector('#metric-duration').textContent = (event.elapsed_ms ?? 0).toLocaleString('es-CO') + ' ms';
      renderCost(result.cost, true);
      setStatus(stateLabels[result.estado] || result.estado || 'Finalizado',
        ['found', 'answered', 'quoted', 'informed', 'refused', 'order_pending', 'order_confirmed', 'pickup_scheduled',
          'order_cancelled', 'order_status', 'handoff', 'staff'].includes(result.estado) ? 'success' : 'warning');
      copy.disabled = !currentAnswer;
    }
    if (event.type === 'session') {
      sessionId = event.session_id;
      turnNumber = event.turno;
      renderSessionLabel();
    }
    if (event.type === 'error') {
      if (event.code && event.code.startsWith('SESSION_')) clearSession();
      setStatus('Error de ejecución', 'error');
      answer.textContent = event.message || 'No se pudo completar la prueba.';
      responseBox.classList.remove('is-typing');
      if (runningNode) setStep(runningNode, 'error');
      responseBox.classList.remove('is-empty');
      renderCost(null, true);
    }
    addEvent(event);
  }

  // Los avisos (pedido por vencer o vencido) los escribe el servidor sin Grok; el visor los recoge cada 10 s.
  async function pollNotices() {
    if (!sessionMode.checked || !sessionId || run.disabled) return;
    try {
      const response = await fetch('/api/avisos?sesion=' + encodeURIComponent(sessionId));
      if (!response.ok) return;
      const data = await response.json();
      if (!Array.isArray(data.avisos) || !data.avisos.length) return;
      if (!customerMessage.hidden && currentAnswer) {
        history.append(historyRow('customer', customerText.textContent), historyRow('agent', currentAnswer));
      }
      data.avisos.forEach(text => history.append(historyRow('notice', String(text))));
      customerMessage.hidden = true;
      currentAnswer = '';
      answer.textContent = 'Llegó un aviso sobre tu pedido. Puedes responder abajo.';
      responseBox.classList.add('is-empty');
    } catch {
      // Sin conexión con el visor no hay avisos que mostrar; se intenta en el siguiente ciclo.
    }
  }
  setInterval(pollNotices, 10000);

  query.addEventListener('input', () => { updateCount(); fitInput(); });
  query.addEventListener('keydown', event => {
    // isComposing: con un teclado de acentos o predictivo, Enter confirma la palabra y no envía.
    if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229 || touch.matches) return;
    event.preventDefault();
    if (!run.disabled && query.value.trim()) form.requestSubmit();
  });
  scroller.addEventListener('scroll', () => {
    followLatest = atBottom();
    if (followLatest) jumpLatest.hidden = true;
  }, {passive:true});
  jumpLatest.addEventListener('click', () => toLatest(true));
  // Las burbujas cambian por textContent y por avisos del servidor: se observa el hilo, no cada función.
  new MutationObserver(followThread).observe(thread, {childList:true, subtree:true, characterData:true});
  sessionMode.addEventListener('change', clearSession);
  newSession.addEventListener('click', () => {
    clearSession();
    customerMessage.hidden = true;
    currentAnswer = '';
    answer.textContent = 'Conversación nueva. Escribe el primer mensaje.';
    responseBox.classList.add('is-empty');
    query.focus();
  });
  document.querySelectorAll('[data-example]').forEach(button => button.addEventListener('click', () => {
    query.value = button.dataset.example;
    updateCount();
    fitInput();
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
    if (!query.value.trim() || run.disabled) return;
    const sent = query.value;
    reset();
    // Como en un chat, el cuadro queda libre para el siguiente mensaje mientras el agente responde.
    query.value = '';
    updateCount();
    fitInput();
    toLatest();
    run.disabled = true;
    run.textContent = 'Enviando…';
    try {
      const response = await fetch('/api/trace', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify(sessionMode.checked ?
          {consulta:sent, sesion:true, session_id:sessionId} : {consulta:sent})
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
      // fetch solo lanza TypeError cuando no hay conexión: su texto («Failed to fetch») no le dice nada a quien prueba.
      const message = error instanceof TypeError ?
        'No pude conectar con el visor. Revisa que siga abierto en la terminal y vuelve a enviar el mensaje.' : error.message;
      show({type:'error', message, elapsed_ms:0});
      // Si no llegó a responder, el mensaje vuelve al cuadro para reenviarlo sin escribirlo de nuevo.
      if (!query.value) { query.value = sent; updateCount(); fitInput(); }
    } finally {
      run.disabled = false;
      run.textContent = SEND_LABEL;
      const idle = [document.body, query, run].includes(document.activeElement);
      if (idle && !touch.matches) query.focus();
    }
  });
  updateCount();
  fitInput();
})();
