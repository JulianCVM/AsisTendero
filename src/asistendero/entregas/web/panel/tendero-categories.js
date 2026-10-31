// Categorías (crear, renombrar, ordenar y borrar las vacías) y alertas de stock bajo (mínimo general y los propios de
// cada producto). Borrar pide dos toques; una categoría con productos no se borra (catalog_admin.py).
import {$, api, busy, button, el, fill, icon, plural, toast, twoTap} from './tendero-core.js';
import {openEditor} from './tendero-product-editor.js';

const state = {refresh:null};

async function post(path, body, done) {
  try {
    await api(path, body);
    toast(done, 'ok');
  } catch (error) {
    toast(error.message, 'error');
  }
  await state.refresh?.();
}

function categoryRow(category, index, all) {
  const row = el('li', 'cat-row');
  const swatch = el('span', 'cat-swatch');
  swatch.style.setProperty('--swatch', category.color);
  const name = el('input');
  name.value = category.nombre;
  name.maxLength = 40;
  name.setAttribute('aria-label', 'Nombre de la categoría ' + category.nombre);
  const info = el('span', 'cat-info');
  info.append(name, el('small', '', plural(category.productos, 'producto', 'productos')));
  const save = button('ghost small', 'Renombrar', 'edit');
  save.hidden = true;
  name.addEventListener('input', () => { save.hidden = !name.value.trim() || name.value.trim() === category.nombre; });
  save.addEventListener('click', () => busy(save, () => post('/api/categorias/renombrar',
    {nombre:category.nombre, nuevo:name.value.trim()}, 'Ahora se llama «' + name.value.trim() + '».')));
  const up = el('button', 'icon-button');
  up.type = 'button';
  up.disabled = index === 0;
  up.setAttribute('aria-label', 'Subir ' + category.nombre);
  up.append(icon('up'));
  up.addEventListener('click', () => post('/api/categorias/mover', {nombre:category.nombre, posicion:index}, 'Orden guardado.'));
  const down = el('button', 'icon-button');
  down.type = 'button';
  down.disabled = index === all.length - 1;
  down.setAttribute('aria-label', 'Bajar ' + category.nombre);
  down.append(icon('down'));
  down.addEventListener('click', () => post('/api/categorias/mover', {nombre:category.nombre, posicion:index + 2}, 'Orden guardado.'));
  row.append(swatch, info, save, up, down);
  if (!category.productos) {
    const remove = button('danger small', 'Borrar', 'trash');
    remove.setAttribute('aria-label', 'Borrar la categoría ' + category.nombre);
    twoTap(remove, 'Toca otra vez', () => post('/api/categorias/borrar', {nombre:category.nombre}, 'Categoría borrada.'));
    row.append(remove);
  }
  return row;
}

function alertRow(item) {
  const row = el('li');
  const open = el('button', 'mini-row');
  open.type = 'button';
  const text = el('span', 'mini-name');
  const label = el('span');
  label.append(el('strong', '', item.nombre + ' · ' + item.variante), el('small', '', item.sku));
  text.append(label);
  open.append(text, el('span', 'pill', 'Alerta en ' + item.alerta));
  open.setAttribute('aria-label', 'Editar la alerta de ' + item.nombre + ' ' + item.variante);
  open.addEventListener('click', async () => {
    const all = await api('/api/inventario?q=' + encodeURIComponent(item.sku));
    const product = all.productos.find(candidate => candidate.sku === item.sku);
    if (product) openEditor(product, state.refresh);
  });
  row.append(open);
  return row;
}

export async function loadCategories(refresh) {
  state.refresh = refresh;
  const data = await api('/api/categorias');
  $('#cat-list').replaceChildren(...data.categorias.map(categoryRow));
  if (document.activeElement !== $('#alert-global')) $('#alert-global').value = String(data.alerta_general);
  fill($('#alert-list'), null, data.alertas, alertRow);
}

export function bindCategories(refresh) {
  state.refresh = refresh;
  $('#cat-form').addEventListener('submit', event => {
    event.preventDefault();
    const name = $('#cat-name').value.trim();
    if (!name) return;
    busy(event.submitter, () => post('/api/categorias/crear', {nombre:name}, 'Categoría «' + name + '» creada.'))
      .then(() => { $('#cat-name').value = ''; });
  });
  $('#alert-form').addEventListener('submit', event => {
    event.preventDefault();
    const value = Number($('#alert-global').value);
    if (!$('#alert-global').checkValidity() || !Number.isInteger(value)) {
      toast('El mínimo general es un entero de 0 a 100.000.', 'error');
      return;
    }
    busy(event.submitter, () => post('/api/alertas', {general:value}, 'Mínimo general: ' + value + '.'));
  });
}
