// Construye la escena de la portada de /inicio: `node tools/mostrador/build.mjs`.
//
// Un negocio de barrio en isométrico, sin rubro: el estante con el catálogo (el producto del ejemplo, con su precio),
// el mostrador, el celular por donde escribe el cliente y la bolsa de la solicitud por recoger. inicio-mostrador.js
// recorre la consulta iluminando cada pieza; aquí solo se calcula la geometría, una vez, con el kit isométrico de anatomy (MIT, en
// tools/castillo/vendor/). Los colores no van en el SVG: cada sólido lleva su material (data-mat) y
// inicio-mostrador.css lo pinta con los tokens de la página, en claro y en oscuro.
//
// Escribe el SVG dentro de src/asistendero/entregas/web/pagina/inicio.html, entre <!-- mostrador:inicio --> y <!-- mostrador:fin -->.
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import * as k from "../castillo/vendor/iso-kit.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const PAGE = join(HERE, "..", "..", "src", "asistendero", "entregas", "web", "pagina", "inicio.html");

const WIDTH = 560;
const HEIGHT = 430;

const BOARD = { x: -120, y: -96, w: 240, d: 192, r: 14 };
const SHELF = { x: -112, y: -82, w: 28, d: 140 };
const SHELF_TOP = 112;
const BOARDS = [0, 38, 76, SHELF_TOP - 4];
const COUNTER = { x: -6, y: -70, w: 34, d: 118, r: 2 };
const COUNTER_TOP = 52;
const PHONE = { x: 8, y: -58, w: 3.4, d: 26, r: 1.2 };
const PHONE_Z = [55, 103];
const BAG = { x: -2, y: 16, w: 18, d: 24, r: 1 };
const BAG_TOP = 82;
const PRODUCT_X = -98;

const P = k.fitProjection(
  [...k.boxCorners(BOARD, -12, 0), [-116, -86, SHELF_TOP], [-84, 62, SHELF_TOP], [PHONE.x, PHONE.y, PHONE_Z[1]]],
  WIDTH, HEIGHT, { pad: 10 },
);
const at = (point) => k.iso(point, P);
const r1 = (value) => Math.round(value * 10) / 10;

// Un sólido del kit pintado por material: relleno, caras laterales con su sombra (0 oscura, 3 iluminada), tapa y borde.
function solid(paths, mat, extra = "") {
  const shades = paths.shades.map((d, shade) => (d ? `<path class="mo-shade" data-shade="${shade}" d="${d}"/>` : "")).join("");
  return `<g class="mo-solid" data-mat="${mat}"${extra}><path class="mo-fill" d="${paths.fill}"/>${shades}` +
    `<path class="mo-top" d="${paths.top}"/><path class="mo-edge" d="${paths.outline}"/></g>`;
}
const slab = (plan, z, height, mat, extra = "") => solid(k.slabOf({ r: 0, ...plan }, z, height, P, 3), mat, extra);
const can = (x, y, radius, z, height, mat, extra = "") => solid(k.cylinder(x, y, radius, z, height, P, 24), mat, extra);
const line = (d, kind) => `<path class="mo-line" data-line="${kind}" d="${d}"/>`;

// Un rectángulo dibujado en la cara que mira hacia +x (pantalla del celular, etiquetas): u va hacia -y, v hacia abajo.
function onFront(x, yMax, zTop, shapes) {
  return `<g transform="${k.sideMatrix([x, yMax], zTop, P, "right")}">${shapes}</g>`;
}

function floor() {
  const out = [`<path class="mo-halo" d="${k.haloOf(BOARD, -12, 12, P)}"/>`, slab(BOARD, -12, 12, "floor")];
  const tiles = [];
  for (let x = BOARD.x + 24; x < BOARD.x + BOARD.w; x += 24) tiles.push(k.lineOnTop([x, BOARD.y + 6], [x, BOARD.y + BOARD.d - 6], 0, P));
  for (let y = BOARD.y + 24; y < BOARD.y + BOARD.d; y += 24) tiles.push(k.lineOnTop([BOARD.x + 6, y], [BOARD.x + BOARD.w - 6, y], 0, P));
  out.push(line(tiles.join(""), "tile"));
  return out.join("");
}

// El estante es el catálogo: frascos, cajas y paquetes genéricos y, en el segundo nivel, el producto del ejemplo.
function shelf() {
  const out = [slab({ x: -116, y: -86, w: 4, d: 148 }, 0, SHELF_TOP, "shelf"), slab({ x: -112, y: -86, w: 28, d: 4 }, 0, SHELF_TOP, "shelf")];
  const goods = [
    [can(-98, -66, 7, 6, 15, "amber"), can(-98, -48, 7, 6, 15, "info"), slab({ x: -106, y: -34, w: 18, d: 26 }, 6, 12, "box"),
      slab({ x: -106, y: -4, w: 18, d: 22 }, 6, 16, "green"), slab({ x: -104, y: 24, w: 14, d: 26 }, 6, 20, "box")],
    [slab({ x: -106, y: -76, w: 16, d: 20 }, 42, 14, "box"), slab({ x: -106, y: -52, w: 16, d: 18 }, 42, 22, "green"),
      slab({ x: -106, y: -30, w: 16, d: 30 }, 42, 10, "amber"),
      `<g class="mo-product">${[8, 22].map((y) => slab({ x: PRODUCT_X - 7, y, w: 13, d: 12 }, 42, 22, "product")).join("")}` +
      `${slab({ x: PRODUCT_X - 7, y: 36, w: 13, d: 12 }, 42, 14, "product")}</g>`],
    [slab({ x: -106, y: -70, w: 16, d: 26 }, 80, 18, "green"), slab({ x: -106, y: -40, w: 16, d: 20 }, 80, 12, "box"),
      can(-98, 0, 6, 80, 22, "info"), can(-98, 20, 6, 80, 22, "info"), slab({ x: -106, y: 36, w: 16, d: 18 }, 80, 14, "amber")],
  ];
  BOARDS.forEach((z, level) => {
    out.push(slab({ ...SHELF, y: SHELF.y - 2, d: SHELF.d + 2 }, z, level === 0 ? 6 : 4, "wood"));
    if (goods[level]) out.push(...goods[level]);
  });
  // La etiqueta de precio cuelga del borde del segundo nivel, frente al producto.
  out.push(onFront(SHELF.x + SHELF.w, 34, 38, `<rect class="mo-label" x="0" y="0.6" width="24" height="7" rx="1"/>` +
    `<text class="mo-label-text" x="12" y="5.6" font-size="4.4" text-anchor="middle">$1.500</text>`));
  out.push(slab({ x: -112, y: 58, w: 28, d: 4 }, 0, SHELF_TOP, "shelf"));
  return `<g class="mo-piece" data-piece="catalogo">${out.join("")}</g>`;
}

// Mostrador con su letrero; encima, el celular del chat y la bolsa del pedido.
function counter() {
  const sign = onFront(COUNTER.x + COUNTER.w, COUNTER.y + COUNTER.d - 14, 36,
    `<rect class="mo-sign" x="0" y="0" width="90" height="16" rx="2"/>` +
    `<text class="mo-sign-text" x="45" y="10.6" font-size="7.4" text-anchor="middle">TU NEGOCIO</text>`);
  return `<g class="mo-piece" data-piece="mostrador">${slab(COUNTER, 0, COUNTER_TOP - 6, "brand")}${sign}` +
    `${slab({ x: COUNTER.x - 4, y: COUNTER.y - 4, w: COUNTER.w + 8, d: COUNTER.d + 8 }, COUNTER_TOP - 6, 6, "wood")}</g>`;
}

function phone() {
  const [z0, z1] = PHONE_Z;
  const tall = z1 - z0;
  const yMax = PHONE.y + PHONE.d;
  const screen = `<rect class="mo-screen" x="2" y="3.4" width="${PHONE.d - 4}" height="${tall - 7}" rx="2"/>` +
    `<g class="mo-bubble" data-bubble="q"><rect x="4" y="8" width="15" height="8" rx="2.4"/><rect class="mo-bar" x="6" y="10.6" width="10" height="1.2"/><rect class="mo-bar" x="6" y="13" width="7" height="1.2"/></g>` +
    `<g class="mo-bubble" data-bubble="a"><rect x="5" y="19" width="17" height="11" rx="2.4"/><rect class="mo-bar" x="7" y="21.6" width="12" height="1.2"/><rect class="mo-bar" x="7" y="24" width="13" height="1.2"/><rect class="mo-bar" x="7" y="26.4" width="8" height="1.2"/></g>` +
    `<g class="mo-bubble" data-bubble="ok"><rect x="4" y="33" width="9" height="6" rx="2.4"/><path class="mo-tick" d="M6.4 36l1.6 1.6 3-3.2"/></g>`;
  return `<g class="mo-piece" data-piece="celular">` +
    `${slab({ x: PHONE.x - 6, y: PHONE.y + 4, w: 12, d: 18 }, COUNTER_TOP, 2.4, "ink")}` +
    `${solid(k.slabOf(PHONE, z0, tall, P, 4), "ink")}` +
    `${onFront(PHONE.x + PHONE.w, yMax, z1, screen)}</g>`;
}

function bag() {
  const top = BAG_TOP;
  const handle = k.sideArc(BAG.x + BAG.w / 2, BAG.y + BAG.d / 2, 6, top + 3, P, 18);
  const tag = onFront(BAG.x + BAG.w, BAG.y + BAG.d - 4, top - 6,
    `<rect class="mo-tag" x="0" y="0" width="16" height="10" rx="1.4"/><path class="mo-tick" d="M4.4 5.2l2.2 2.2 4.6-4.6"/>`);
  return `<g class="mo-piece" data-piece="pedido">${slab(BAG, COUNTER_TOP, top - COUNTER_TOP, "kraft")}` +
    `${slab({ x: BAG.x + 0.6, y: BAG.y - 0.6, w: BAG.w - 1.2, d: BAG.d + 1.2 }, top, 3, "kraft-top")}` +
    `${line(handle, "handle")}${tag}</g>`;
}

// Al frente, una estiba con cajas para que el local se lea como bodega y no como oficina.
function pallet() {
  const plan = { x: 56, y: -86, w: 46, d: 40 };
  return slab(plan, 0, 6, "wood") + slab({ x: 60, y: -82, w: 38, d: 15 }, 6, 12, "box") +
    slab({ x: 60, y: -64, w: 38, d: 15 }, 6, 12, "box") + slab({ x: 62, y: -80, w: 34, d: 14 }, 18, 12, "box");
}

// Recorridos punteados de la consulta: celular → estante (2), estante → celular (3), celular → bolsa (4).
function links() {
  const screen = at([PHONE.x + PHONE.w, PHONE.y + PHONE.d / 2, PHONE_Z[0] + 30]);
  const tubes = at([PRODUCT_X + 4, 20, 64]);
  const bagFace = at([BAG.x + BAG.w, BAG.y + BAG.d / 2, BAG_TOP - 8]);
  const arc = ([x1, y1], [x2, y2], lift) => `M${r1(x1)} ${r1(y1)}Q${r1((x1 + x2) / 2)} ${r1(Math.min(y1, y2) - lift)} ${r1(x2)} ${r1(y2)}`;
  return `<path class="mo-link" data-link="2" d="${arc(screen, tubes, 46)}"/>` +
    `<path class="mo-link" data-link="3" d="${arc(tubes, screen, 46)}"/>` +
    `<path class="mo-link" data-link="4" d="${arc(screen, bagFace, 26)}"/>`;
}

// Dónde se ancla el globo de texto de cada paso, en porcentaje del dibujo (inicio-mostrador.js lo lee).
function anchors() {
  const percent = ([x, y]) => `${r1((x / WIDTH) * 100)} ${r1((y / HEIGHT) * 100)}`;
  return {
    celular: percent(at([PHONE.x, PHONE.y + PHONE.d / 2, PHONE_Z[1] + 4])),
    catalogo: percent(at([PRODUCT_X + 14, 20, 74])),
    pedido: percent(at([BAG.x + BAG.w / 2, BAG.y + BAG.d / 2, BAG_TOP + 10])),
  };
}

const marks = anchors();
const svg = `<svg class="mo-svg" viewBox="0 0 ${WIDTH} ${HEIGHT}" aria-hidden="true" focusable="false" ` +
  `data-anchor-celular="${marks.celular}" data-anchor-catalogo="${marks.catalogo}" data-anchor-pedido="${marks.pedido}">` +
  `${floor()}${shelf()}${counter()}${phone()}${bag()}${pallet()}<g class="mo-links">${links()}</g></svg>`;

const page = readFileSync(PAGE, "utf8");
const start = "<!-- mostrador:inicio -->";
const end = "<!-- mostrador:fin -->";
const from = page.indexOf(start);
const to = page.indexOf(end);
if (from < 0 || to < from) throw new Error("inicio.html no tiene los marcadores <!-- mostrador:inicio --> y <!-- mostrador:fin -->");
writeFileSync(PAGE, page.slice(0, from + start.length) + svg + page.slice(to));
console.log(`Escena escrita en inicio.html: ${(svg.length / 1024).toFixed(1)} KB`);
