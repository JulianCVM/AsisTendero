// Lo que cada nodo del mapa puede mostrar a pedido, leído de /api/harness: códigos, herramientas, avisos, estados y
// las instrucciones completas de Grok. Va plegado para que el detalle del nodo se lea primero.
import {el} from './visor-comun.js';

function codeList(entries) {
  const list = el('ul', 'code-list');
  for (const [code, text, example] of entries) {
    const item = el('li');
    item.dataset.state = code;
    item.append(el('code', '', code), el('span', '', text));
    if (example) item.append(el('code', 'code-example', example));
    list.append(item);
  }
  return list;
}
function fold(title, ...content) {
  const box = el('details', 'flow-extra');
  box.append(el('summary', '', title), ...content);
  return box;
}

export function extrasFor(id, info) {
  if (id === 'validate') {
    return [
      fold('Temas que no se entregan (' + Object.keys(info.guardrails).length + ')',
        codeList(Object.entries(info.guardrails).map(([code, reply]) => [code, reply]))),
      fold('Inyecciones que bloquean y banean (' + Object.keys(info.injections).length + ')',
        codeList(Object.entries(info.injections).map(([code, text]) => [code, text]))),
    ];
  }
  if (id === 'interpret') {
    const prompt = el('pre', 'flow-prompt', info.instructions);
    return [
      fold('Instrucciones completas que recibe Grok · ' + info.prompt_version, prompt),
      fold('Fallos del modelo (' + Object.keys(info.errors.model).length + ')',
        codeList(Object.entries(info.errors.model).map(([code, text]) => [code, text]))),
    ];
  }
  if (id === 'route') {
    return [fold('Avisos del servidor (' + info.reminders.length + ')',
      codeList(info.reminders.map(item => [item.code, item.message])))];
  }
  if (id === 'aduana') {
    return [fold('Rechazos antes de ejecutar (' + Object.keys(info.rejections).length + ')',
      codeList(Object.entries(info.rejections).map(([code, text]) => [code, text])))];
  }
  if (id === 'bodega') {
    return [
      fold('Herramientas que puede pedir Grok (' + info.tools.length + ')',
        codeList(info.tools.map(tool => [tool.name, tool.returns, tool.arguments]))),
      fold('Errores de las herramientas (' + Object.keys(info.errors.tool).length + ')',
        codeList(Object.entries(info.errors.tool).map(([code, text]) => [code, text]))),
    ];
  }
  if (id === 'outcome') {
    return Object.entries(info.outcomes).map(([group, data]) => {
      const box = fold(data.label + ' (' + Object.keys(data.states).length + ')',
        codeList(Object.entries(data.states).map(([state, label]) => [state, label])));
      box.dataset.group = group;
      return box;
    });
  }
  return [];
}
