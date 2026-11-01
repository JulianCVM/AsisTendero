// Chat de prueba: envía el mensaje, lee la traza en streaming y la reparte como eventos («asistendero:event»).
// El resultado, el mapa, la inspección y el castillo escuchan esos eventos en sus propios módulos.
const form = document.querySelector('#form');
const query = document.querySelector('#query');
const run = document.querySelector('#run');
const answer = document.querySelector('#answer');
const responseBox = document.querySelector('#response-box');
const customerMessage = document.querySelector('#customer-message');
const customerText = document.querySelector('#customer-text');
const sessionMode = document.querySelector('#session-mode');
const newSession = document.querySelector('#new-session');
const sessionLabel = document.querySelector('#session-label');
const history = document.querySelector('#chat-history');
const scroller = document.querySelector('#chat-scroll');
const thread = document.querySelector('#chat-thread');
const jumpLatest = document.querySelector('#jump-latest');
const customerImg = document.querySelector('#customer-img');
const imageInput = document.querySelector('#image-input');
const attachButton = document.querySelector('#attach-button');
const imagePreviewContainer = document.querySelector('#image-preview-container');
const imagePreview = document.querySelector('#image-preview');
const imagePreviewName = document.querySelector('#image-preview-name');
const removeImage = document.querySelector('#remove-image');
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
let currentAnswer = '';
let finished = false;
let selectedImageData = null;
let currentSentImage = null;

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
  scroller.scrollTo({top: scroller.scrollHeight, behavior: smooth && !reducedMotion.matches ? 'smooth' : 'auto'});
  followLatest = true;
  jumpLatest.hidden = true;
}
function followThread() {
  if (followLatest) toLatest();
  else jumpLatest.hidden = false;
}
function downscaleImage(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = e => {
      const img = new Image();
      img.onload = () => {
        const maxDim = 1024;
        let width = img.width;
        let height = img.height;
        if (width > maxDim || height > maxDim) {
          if (width > height) {
            height = Math.round((height * maxDim) / width);
            width = maxDim;
          } else {
            width = Math.round((width * maxDim) / height);
            height = maxDim;
          }
        }
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        canvas.getContext('2d').drawImage(img, 0, 0, width, height);
        resolve(canvas.toDataURL('image/jpeg', 0.85));
      };
      img.onerror = reject;
      img.src = e.target.result;
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}
function clearSelectedImage() {
  selectedImageData = null;
  imageInput.value = '';
  imagePreview.removeAttribute('src');
  imagePreviewContainer.hidden = true;
}
function historyRow(role, text, imageSrc) {
  const row = document.createElement('div');
  row.className = 'chat-row ' + role;
  const icon = document.createElement('span');
  icon.className = 'chat-icon';
  icon.setAttribute('aria-hidden', 'true');
  icon.textContent = role === 'customer' ? 'C' : (role === 'notice' ? '!' : 'AT');
  const body = document.createElement('div');
  const speaker = document.createElement('span');
  speaker.className = 'speaker';
  speaker.textContent = {customer: 'Cliente', notice: 'AsisTendero · aviso automático'}[role] || 'AsisTendero';
  const bubble = document.createElement('div');
  bubble.className = role === 'customer' ? 'bubble' : (role === 'notice' ? 'bubble agent-bubble notice-bubble' : 'bubble agent-bubble');
  if (imageSrc && role === 'customer') {
    const img = document.createElement('img');
    img.className = 'chat-bubble-img';
    img.src = imageSrc;
    img.alt = 'Foto adjuntada por el cliente';
    bubble.append(img);
  }
  if (text) {
    const line = document.createElement('div');
    line.textContent = text;
    bubble.append(line);
  }
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
function reset(sentText, sentImage) {
  // En una conversación, el turno anterior pasa al historial antes de mostrar el nuevo.
  if (sessionMode.checked && sessionId && !customerMessage.hidden && currentAnswer) {
    history.append(historyRow('customer', customerText.textContent, currentSentImage), historyRow('agent', currentAnswer));
  } else if (!sessionMode.checked) {
    history.replaceChildren();
  }
  currentSentImage = sentImage || null;
  customerImg.hidden = !currentSentImage;
  if (currentSentImage) customerImg.src = currentSentImage;
  else customerImg.removeAttribute('src');
  customerText.textContent = sentText;
  customerMessage.hidden = false;
  currentAnswer = '';
  finished = false;
  answer.textContent = 'Estoy revisando tu consulta…';
  responseBox.classList.remove('is-empty');
  responseBox.classList.add('is-typing');
  document.dispatchEvent(new CustomEvent('asistendero:reset'));
}
function show(event) {
  if (event.type === 'final') {
    finished = true;
    currentAnswer = event.details?.respuesta || '';
    answer.textContent = currentAnswer;
    responseBox.classList.remove('is-typing');
  }
  if (event.type === 'session') {
    sessionId = event.session_id;
    turnNumber = event.turno;
    renderSessionLabel();
  }
  if (event.type === 'error') {
    finished = true;
    if (event.code && event.code.startsWith('SESSION_')) clearSession();
    answer.textContent = event.message || 'No se pudo completar la prueba.';
    responseBox.classList.remove('is-typing', 'is-empty');
  }
  document.dispatchEvent(new CustomEvent('asistendero:event', {detail: event}));
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
      history.append(historyRow('customer', customerText.textContent, currentSentImage), historyRow('agent', currentAnswer));
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

attachButton.addEventListener('click', () => imageInput.click());
imageInput.addEventListener('change', async () => {
  const file = imageInput.files && imageInput.files[0];
  if (!file) return;
  try {
    selectedImageData = await downscaleImage(file);
    imagePreview.src = selectedImageData;
    imagePreviewName.textContent = file.name;
    imagePreviewContainer.hidden = false;
    query.focus();
  } catch {
    clearSelectedImage();
  }
});
removeImage.addEventListener('click', () => { clearSelectedImage(); query.focus(); });
query.addEventListener('input', () => { updateCount(); fitInput(); });
query.addEventListener('keydown', event => {
  // isComposing: con un teclado de acentos o predictivo, Enter confirma la palabra y no envía.
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229 || touch.matches) return;
  event.preventDefault();
  if (!run.disabled && (query.value.trim() || selectedImageData)) form.requestSubmit();
});
scroller.addEventListener('scroll', () => {
  followLatest = atBottom();
  if (followLatest) jumpLatest.hidden = true;
}, {passive: true});
jumpLatest.addEventListener('click', () => toLatest(true));
// Las burbujas cambian por textContent y por avisos del servidor: se observa el hilo, no cada función.
new MutationObserver(followThread).observe(thread, {childList: true, subtree: true, characterData: true});
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
form.addEventListener('submit', async event => {
  event.preventDefault();
  const sent = query.value.trim();
  const sentImage = selectedImageData;
  if ((!sent && !sentImage) || run.disabled) return;
  clearSelectedImage();
  reset(sent, sentImage);
  // Como en un chat, el cuadro queda libre para el siguiente mensaje mientras el agente responde.
  query.value = '';
  updateCount();
  fitInput();
  toLatest();
  run.disabled = true;
  run.textContent = 'Enviando…';
  try {
    const payload = sessionMode.checked ? {consulta: sent, sesion: true, session_id: sessionId} : {consulta: sent};
    if (sentImage) payload.image_data = sentImage;
    const response = await fetch('/api/trace', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload),
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
      pending += decoder.decode(value, {stream: true});
      const lines = pending.split('\n');
      pending = lines.pop();
      for (const line of lines) if (line.trim()) show(JSON.parse(line));
    }
    pending += decoder.decode();
    if (pending.trim()) show(JSON.parse(pending));
    if (!finished) throw new Error('La traza terminó sin resultado.');
  } catch (error) {
    // fetch solo lanza TypeError cuando no hay conexión: su texto («Failed to fetch») no le dice nada a quien prueba.
    const message = error instanceof TypeError ?
      'No pude conectar con el visor. Revisa que siga abierto en la terminal y vuelve a enviar el mensaje.' : error.message;
    show({type: 'error', message, elapsed_ms: 0});
    // Si no llegó a responder, el mensaje vuelve al cuadro para reenviarlo sin escribirlo de nuevo.
    if (!query.value && sent) { query.value = sent; updateCount(); fitInput(); }
  } finally {
    run.disabled = false;
    run.textContent = SEND_LABEL;
    const idle = [document.body, query, run].includes(document.activeElement);
    if (idle && !touch.matches) query.focus();
  }
});
updateCount();
fitInput();
