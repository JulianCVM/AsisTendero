// Lectura de cada evento de la traza en paneles: entradas, decisión de Grok, resultado de la herramienta, evidencia
// (costo, tokens, verificación) y errores con su código. Solo se muestran campos que el evento trae; el JSON original
// sigue disponible debajo (traza.js).
import {el, formatMs, formatUsd, STATE_LABELS} from './visor-comun.js';

const yesNo = value => value ? 'Sí' : 'No';
const cop = value => typeof value === 'number' ? '$' + value.toLocaleString('es-CO') : '—';

function facts(pairs) {
  const list = el('dl', 'read-facts');
  for (const [term, value] of pairs) {
    if (value === undefined || value === null || value === '') continue;
    const pair = el('div');
    pair.append(el('dt', '', term), el('dd', '', value));
    list.append(pair);
  }
  return list;
}
function block(title, ...content) {
  const box = el('section', 'read-block');
  box.append(el('h4', '', title), ...content.filter(Boolean));
  return box;
}
function quote(text) {
  return text ? el('p', 'read-quote', text) : null;
}
function items(lines) {
  const list = el('ul', 'read-list');
  lines.forEach(line => list.append(el('li', '', line)));
  return lines.length ? list : el('p', 'read-empty', 'Sin elementos.');
}
function argumentLines(args) {
  if (!args || typeof args !== 'object') return [];
  return Object.entries(args).map(([key, value]) => key + ': ' + (typeof value === 'string' ? value : JSON.stringify(value)));
}
function product(item) {
  return [item.sku, item.name, item.variant].filter(Boolean).join(' · ') +
    (typeof item.stock === 'number' ? ' · ' + item.stock + ' en bodega' : '');
}

export function dataSummary(data) {
  if (!data || typeof data !== 'object') return [];
  if (Array.isArray(data.results)) {
    return data.results.flatMap((result, index) => [
      'Artículo ' + (index + 1) + ': ' + (result.matches?.length ?? 0) + ' coincidencias, ' + (result.nearby?.length ?? 0) + ' cercanas',
      ...(result.matches || []).slice(0, 4).map(item => '  ✓ ' + product(item)),
      ...(result.nearby || []).slice(0, 3).map(item => '  ≈ ' + product(item)),
    ]);
  }
  if (Array.isArray(data.lines)) {
    return [...data.lines.map(line => line.sku + ' × ' + line.quantity + ' · ' + cop(line.unit_price_cop) + ' c/u · ' +
      cop(line.subtotal_cop)), 'Total ' + cop(data.total_cop) + ' · reserva creada: ' + yesNo(data.reservation_created)];
  }
  if (Array.isArray(data.lineas)) {
    return [data.pedido + ' · ' + data.estado + ' · total ' + cop(data.total_cop),
      ...data.lineas.map(line => line.sku + ' × ' + line.cantidad + ' · ' + cop(line.subtotal_cop))];
  }
  if (Array.isArray(data.pedidos)) return data.pedidos.map(order => order.pedido + ' · ' + order.estado + ' · ' + cop(order.total_cop));
  if (Array.isArray(data.categorias)) return data.categorias.map(item => item.categoria + ' · ' + item.variantes + ' variantes');
  if (Array.isArray(data.productos)) return [data.categoria, ...data.productos.map(item => item.nombre + ' · ' + item.variantes + ' variantes')];
  if (data.sku) return [data.sku + ': ' + data.stock + ' ' + (data.unit || '') + (data.restock ? ' · surtido: ' + data.restock : '')];
  if (data.tema) {
    return ['Tema: ' + data.tema, ...(typeof data.abierto_ahora === 'boolean' ? ['Abierta ahora: ' + yesNo(data.abierto_ahora)] : []),
      ...(data.texto ? [data.texto] : [])];
  }
  return Object.keys(data).map(key => key);
}

function decisionBlock(decision) {
  if (!decision) return null;
  return block('Decisión de Grok',
    facts([['Acción', decision.action], ['Intención', decision.intent], ['Herramienta', decision.tool],
      ['JSON válido', yesNo(decision.valid_json)]]),
    decision.arguments ? items(argumentLines(decision.arguments)) : null,
    decision.reply ? quote('Redacción propuesta: «' + decision.reply + '»') : null);
}
function errorBlock(error) {
  return error ? block('Error', facts([['Código', error.code], ['Mensaje', error.message]])) : null;
}

function toolBlock(call, terms) {
  const response = call.response || {};
  const changed = call.executed && JSON.stringify(call.arguments) !== JSON.stringify(call.requested_arguments);
  return [
    block('Solicitud', facts([['Herramienta', call.requested_tool], ['Paso', call.step],
      ['Aduana', call.executed ? 'Aprobada y ejecutada' : 'Rechazada: no se ejecutó'], ['Duración', formatMs(call.duration_ms)]]),
    items(argumentLines(call.requested_arguments)),
    changed ? block('Argumentos validados', items(argumentLines(call.arguments))) : null),
    block('Resultado', facts([['Estado', response.status], ['Fuente', response.source], ['Leído', response.observed_at]]),
      response.status === 'ok' ? items(dataSummary(response.data)) : null,
      terms ? quote('Términos de búsqueda: ' + terms.map(group => group.join(' ')).join(' | ')) : null),
    errorBlock(response.error),
  ];
}

export function readable(event) {
  const d = event.details || {};
  if (event.type === 'input') {
    return [block('Entrada', facts([['Prompt', d.prompt_version], ['Con memoria', yesNo(d.sesion)]]),
      quote(d.consulta), el('p', 'read-note', 'Los datos personales ya vienen omitidos en la traza.'))];
  }
  if (event.type === 'node' && event.status === 'running') {
    return [el('p', 'read-note', 'El servidor entra al nodo ' + event.node + '.')];
  }
  if (event.type === 'node' && event.node === 'validate') {
    return [block('Barreras de la puerta', facts([['Longitud', d.longitud + ' caracteres'],
      ['Temas quitados', d.barreras?.length ? d.barreras.join(', ') : 'Ninguno'],
      ['Datos personales omitidos', yesNo(d.datos_personales_omitidos)],
      ['Inyección', d.inyeccion ? d.inyeccion.code + ' · ' + d.inyeccion.technique : 'No']]),
    quote(d.consulta_normalizada ? 'Lo que sigue a Grok: «' + d.consulta_normalizada + '»' : 'No sigue nada a Grok.'))];
  }
  if (event.type === 'node' && event.node === 'interpret') {
    return [decisionBlock(d.decision), block('Cuenta', facts([['Llamadas a Grok en la corrida', d.model_calls]])),
      errorBlock(d.error)].filter(Boolean);
  }
  if (event.type === 'node' && event.node === 'retrieve') return toolBlock(d.tool_call || {}, d.terminos).filter(Boolean);
  if (event.type === 'node' && event.node === 'respond') {
    return [block('Respuesta verificada', facts([['Estado', d.estado + ' · ' + (STATE_LABELS[d.estado] || '')],
      ['Llamadas a Grok', d.model_calls]]), quote(d.respuesta)), errorBlock(d.error)].filter(Boolean);
  }
  if (event.type === 'model_request') {
    const observations = (d.observaciones || []).map(item => item?.estado === 'aviso' ? 'Aviso ' + item.error?.code
      : (item?.herramienta || 'observación') + ' · ' + (item?.estado || item?.status || '—'));
    return [block('Lo que recibe Grok', facts([['Fase', d.phase], ['Paso', d.step], ['Modelo', d.model],
      ['Pasarela', d.endpoint], ['Llamadas disponibles', d.llamadas_disponibles],
      ['Turnos previos', d.conversacion ? (d.conversacion.turnos?.length ?? 0) : 'Sin sesión'], ['Llave', d.api_key]]),
    quote(d.mensaje)), block('Observaciones (' + observations.length + ')', items(observations))];
  }
  if (event.type === 'model_response') {
    return [decisionBlock(d.error ? null : d), block('Evidencia de la llamada', facts([['Duración', formatMs(d.duration_ms)],
      ['Tokens de entrada', d.input_tokens], ['Tokens de salida', d.output_tokens], ['Tokens en caché', d.cached_input_tokens],
      ['Costo', d.cost ? formatUsd(d.cost.usd) + ' · ' + d.cost.basis : 'No disponible']])), errorBlock(d.error)].filter(Boolean);
  }
  if (event.type === 'route') {
    return [block('Ruta del servidor', quote(d.motivo), facts([['Aviso a Grok', d.aviso ? 'Sí' : undefined]]))];
  }
  if (event.type === 'final') {
    return [block('Resultado', facts([['Estado', d.estado + ' · ' + (STATE_LABELS[d.estado] || '')],
      ['Herramientas pedidas', (d.tools_requested || []).join(', ') || 'Ninguna'],
      ['Herramientas ejecutadas', (d.tools_executed || []).join(', ') || 'Ninguna'],
      ['Barreras', d.barreras?.length ? d.barreras.join(', ') : undefined],
      ['Inyección', d.inyeccion ? d.inyeccion.code : undefined]]), quote(d.respuesta)),
    block('Evidencia', facts([['Llamadas a Grok', d.model_calls], ['Tokens', d.total_tokens ?? (d.model_calls ? 's/d' : 0)],
      ['Duración', formatMs(d.duration_ms)], ['Costo', d.cost ? formatUsd(d.cost.usd) + ' · ' + d.cost.basis : 'No disponible'],
      ['Prompt', d.prompt_version]])), errorBlock(d.error)].filter(Boolean);
  }
  if (event.type === 'error') return [errorBlock({code: event.code || 'sin código', message: event.message})];
  if (event.type === 'session') return [block('Memoria', facts([['Turno', event.turno], ['Sesión', event.session_id]]))];
  return [block('Datos', facts(Object.entries({...event, ...d}).filter(([, value]) => typeof value !== 'object')
    .map(([key, value]) => [key, String(value)])))];
}
