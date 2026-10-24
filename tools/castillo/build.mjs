// Construye el castillo isométrico del harness para el visor: `node tools/castillo/build.mjs`.
//
// Cada edificio es un nodo o una barrera real del flujo (graph.py) y el camino entre ellos es la ruta que puede
// tomar un mensaje. La geometría estática se calcula aquí, una vez, con el kit isométrico de anatomy (MIT, en
// vendor/); castillo.js solo mueve el mensaje, el rastrillo, la talanquera, el letrero y la balanza.
//
// Escribe:
//   - el SVG dentro de src/asistendero/ui/index.html, entre <!-- castillo:inicio --> y <!-- castillo:fin -->;
//   - src/asistendero/ui/iso.css, los estilos del kit;
//   - .local/castillo-preview.html, una página suelta para revisar el dibujo (no se sube).
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import * as k from "./vendor/iso-kit.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..", "..");
const UI = join(ROOT, "src", "asistendero", "ui");

const WIDTH = 760;
const HEIGHT = 500;

const BOARD = { x: -218, y: -186, w: 436, d: 400, r: 10 };
const PLINTH = { x: -196, y: -166, w: 392, d: 332, r: 6 };
const KEEP = { x: -28, y: -118, w: 56, d: 56, r: 1 };
const KEEP_TOP = 118;
const STORE = { x: 70, y: -120, w: 80, d: 58, r: 2 };
const STORE_TOP = 42;
const BOOTH = { x: 158, y: 92, w: 30, d: 36, r: 1.5 };
const BOOTH_TOP = 30;
const GATE_TOWER = [-82, 152];
const GATE_TOP = 52;
const PORTCULLIS = { x0: -170, x1: -97, y: 151, z0: 0, z1: 34 };
const LIFT = 30;
const BARRIER = { pivot: [96, 0, 12], length: 24 };
const SCALE = { at: [70, 84], beam: 18, z: 36, drop: 16 };
const SIGN = { at: [-16, 24], z: 27, length: 15 };

// Los puntos del camino. Cada estación tiene el suyo, delante de su fachada visible.
const POINTS = {
  cliente: [-134, 198], puerta: [-134, 172], patio: [-134, 40], cruce: [0, 40], torre: [0, -50],
  calle: [110, 40], aduana: [110, 12], bodega: [110, -44], plaza: [0, 110], balanza: [70, 110],
  mostrador: [150, 110], salida: [206, 110],
};
const EDGES = [
  ["cliente", "puerta"], ["puerta", "patio"], ["patio", "cruce"], ["cruce", "torre"], ["cruce", "calle"],
  ["calle", "aduana"], ["aduana", "bodega"], ["cruce", "plaza"], ["plaza", "balanza"], ["balanza", "mostrador"],
  ["mostrador", "salida"],
];
// Dentro de la caseta del mostrador el mensaje no se ve: pasa por la ventana hacia el cliente.
const HIDDEN = [[BOOTH.x, BOOTH.y, BOOTH.x + BOOTH.w, BOOTH.y + BOOTH.d]];

const P = k.fitProjection(
  [...k.boxCorners(BOARD, -34, -18), [0, -90, 158], [-185, -155, 72], [172, 110, 68], [-134, 214, 0]],
  WIDTH, HEIGHT, { pad: 14, azimuth: 45 },
);
const at = (point) => k.iso(point, P);
const S = (paths, style) => k.solidSvg(paths, style);
const L = (d, style) => k.lineSvg(d, style);
const D = (points, style) => k.dotsSvg(points, style);
const slab = (plan, z, h, steps = 3, bevel = 0) => k.slabOf(plan, z, h, P, steps, bevel);
const near = ([x, y]) => x + y;

// Lo que se pinta va en una lista con su profundidad; el mensaje se inserta en su lugar mientras viaja.
const scene = [];
const put = (key, markup, extra = "") => scene.push({ key, markup: `<g data-key="${key.toFixed(1)}"${extra}>${markup}</g>` });

function board() {
  const out = [`<path class="iso-halo" d="${k.haloOf(BOARD, -34, 16, P)}"/>`];
  for (const [x, y] of [...k.corners(BOARD, 20)].sort((a, b) => near(a) - near(b))) {
    out.push(S(k.cylinder(x, y, 8, -34, 2, P, 28), { tone: "lo" }));
    out.push(S(k.cylinder(x, y, 6, -32, 6, P, 28), { tone: "lo" }));
  }
  out.push(S(slab(BOARD, -26, 8, 8, 1.4), { tone: "mid" }));
  out.push(L(k.planOutline(k.insetPlan(BOARD, 6), -18, P), { tone: "faint" }));
  const screws = k.corners(BOARD, 11);
  out.push(L(screws.map(([x, y]) => k.ring(x, y, 2.2, -18, P, 16)).join(""), { tone: "lo" }));
  out.push(D(screws.map(([x, y]) => at([x, y, -18])), { size: 0.5 }));
  // La placa del modelo, con tres renglones grabados, en la esquina del cliente.
  const plate = { x: -200, y: 180, w: 56, d: 22, r: 1.5 };
  out.push(S(slab(plate, -18, 0.8, 3), { tone: "lo", crease: "none" }));
  for (const [row, width] of [[186, 40], [192, 30], [197, 34]]) {
    out.push(L(k.lineOnTop([plate.x + 6, row], [plate.x + 6 + width, row], -17.2, P), { tone: "faint", free: true }));
  }
  out.push(D([at([plate.x + 3, plate.y + 3, -17.2]), at([plate.x + plate.w - 3, plate.y + plate.d - 3, -17.2])], { size: 0.4 }));
  return out.join("");
}

function plinth() {
  const out = [S(slab(PLINTH, -18, 18, 6, 1.2), { tone: "mid" })];
  // Hiladas de piedra en el zócalo: dos costuras que siguen la cara visible.
  out.push(L(k.sideSeam(PLINTH, -6, P, 6) + k.sideSeam(PLINTH, -12, P, 6), { tone: "faint" }));
  out.push(L(k.planOutline(k.insetPlan(PLINTH, 8), 0, P), { tone: "faint" }));
  return out.join("");
}

function bridge() {
  const out = [];
  for (const x of [-145, -123]) out.push(S(k.cylinder(x, 192, 2.6, -18, 14, P, 16), { tone: "lo" }));
  out.push(S(slab({ x: -148, y: 164, w: 28, d: 44, r: 1 }, -4, 4, 2, 0.4), { tone: "mid" }));
  for (const y of [172, 182, 192, 202]) out.push(L(k.lineOnTop([-148, y], [-120, y], 0, P), { tone: "faint" }));
  for (const x of [-148, -122]) {
    out.push(S(slab({ x, y: 166, w: 2, d: 42, r: 0.4 }, 0, 5, 2), { tone: "mid", crease: "none" }));
  }
  return out.join("");
}

function road() {
  const out = [];
  const strips = [
    { x: -141, y: 40, w: 14, d: 126 }, { x: -141, y: 33, w: 115, d: 14 }, { x: -7, y: -62, w: 14, d: 76 },
    { x: 26, y: 33, w: 91, d: 14 }, { x: 103, y: -56, w: 14, d: 89 }, { x: -7, y: 66, w: 14, d: 51 },
    { x: -7, y: 103, w: 166, d: 14 },
  ];
  for (const strip of strips) out.push(S(slab({ ...strip, r: 0.8 }, 0, 0.6, 2), { tone: "lo", flat: true, crease: "none" }));
  // La plaza del cruce, con su rosa de rumbos.
  out.push(S(k.cylinder(0, 40, 26, 0, 1.2, P, 56), { tone: "lo", crease: "none" }));
  out.push(L(k.ring(0, 40, 22, 1.2, P, 56), { tone: "faint" }));
  const ticks = k.radialTicks(0, 40, 22, 16, 4, 1.2, [1.6, 3.4], P);
  out.push(L(ticks.minor, { tone: "faint" }), L(ticks.major, { tone: "lo" }));
  // Cada tramo del camino lleva su línea de recorrido; castillo.js enciende las que el mensaje ya pisó.
  for (const [from, to] of EDGES) {
    const [a, b] = [POINTS[from], POINTS[to]];
    const z = from === "cliente" ? 0.1 : 1.3;
    out.push(`<path class="iso-line castle-trail" data-edge="${from}-${to}" data-dotted="" d="${k.lineOnTop(a, b, z, P)}"/>`);
  }
  out.push(D([at([...POINTS.cliente, 0.1])], { size: 0.8, tone: "lo" }));
  return out.join("");
}

function plaques() {
  const marks = [[1, -100, 180, -18], [2, 22, -46], [3, -30, 64], [4, 84, 18], [5, 134, -50], [6, 44, 128], [7, 136, 128]];
  return marks.map(([number, x, y, z = 0]) => {
    const plan = { x: x - 6, y: y - 5, w: 12, d: 10, r: 1 };
    return `<g data-plaque="${number}">${S(slab(plan, z, 1.2, 3, 0.3), { tone: "mid" })}${
      k.faceTextSvg(k.topMatrix([x, y + 2.6], z + 1.2, P, "x"), String(number), { size: 7, tone: "hi", anchor: "middle" })}</g>`;
  }).join("");
}

function wallBack() {
  const out = [];
  const left = { x: -190, y: -160, w: 10, d: 310, r: 1 };
  const back = { x: -180, y: -160, w: 360, d: 10, r: 1 };
  out.push(S(slab(back, 0, 36, 2, 0.5), { tone: "mid" }));
  for (let x = -172; x <= 168; x += 16) out.push(S(slab({ x, y: -160, w: 9, d: 10, r: 0.5 }, 36, 7, 2), { tone: "mid", crease: "lo" }));
  out.push(S(slab(left, 0, 36, 2, 0.5), { tone: "mid" }));
  for (let y = -150; y <= 140; y += 16) out.push(S(slab({ x: -190, y, w: 10, d: 9, r: 0.5 }, 36, 7, 2), { tone: "mid", crease: "lo" }));
  // Hiladas de sillares en la cara interior.
  out.push(L(k.sideSeam(back, 12, P, 2) + k.sideSeam(back, 24, P, 2), { tone: "faint" }));
  out.push(L(k.sideSeam(left, 12, P, 2) + k.sideSeam(left, 24, P, 2), { tone: "faint" }));
  return out.join("");
}

function tower(cx, cy, r, top, slits = true) {
  const out = [`<path class="iso-halo" d="${k.haloOf({ x: cx - r, y: cy - r, w: r * 2, d: r * 2, r }, 0, 1, P)}"/>`];
  out.push(S(k.cylinder(cx, cy, r, 0, top, P, 40, 0.5), { tone: "mid" }));
  out.push(L(k.sideArc(cx, cy, r, top * 0.33, P, 24) + k.sideArc(cx, cy, r, top * 0.66, P, 24), { tone: "faint" }));
  if (slits) {
    const [vx, vy] = k.towardViewer(P);
    const facing = Math.atan2(vy, vx);
    for (const turn of [-0.5, 0.5]) {
      const angle = facing + turn;
      const [x, y] = [cx + Math.cos(angle) * r, cy + Math.sin(angle) * r];
      out.push(L(k.rise([x, y], top * 0.45, top * 0.6, P), { tone: "hi" }),
        D([at([x, y, top * 0.45]), at([x, y, top * 0.6])], { size: 0.45, tone: "hi" }));
    }
  }
  out.push(S(k.cylinder(cx, cy, r + 2, top, 5, P, 40, 0.5), { tone: "mid" }));
  const crown = top + 5;
  const merlons = [];
  for (let index = 0; index < 10; index++) {
    const angle = (index / 10) * Math.PI * 2;
    merlons.push([cx + Math.cos(angle) * (r - 0.5), cy + Math.sin(angle) * (r - 0.5)]);
  }
  for (const [x, y] of merlons.sort((a, b) => near(a) - near(b))) {
    out.push(S(slab({ x: x - 2.6, y: y - 2.6, w: 5.2, d: 5.2, r: 0.6 }, crown, 6, 2), { tone: "mid", crease: "lo" }));
  }
  return out.join("");
}

function keep() {
  const out = [`<path class="iso-halo" d="${k.haloOf(k.insetPlan(KEEP, -6), 0, 1, P)}"/>`];
  out.push(S(slab(k.insetPlan(KEEP, -6), 0, 8, 2, 0.6), { tone: "mid" }));
  out.push(S(slab(KEEP, 8, KEEP_TOP - 8, 2, 0.8), { tone: "hi", crease: "lo",
    inner: L(k.sideSeam(KEEP, 44, P, 2) + k.sideSeam(KEEP, 82, P, 2), { tone: "faint" }) }));
  const front = KEEP.y + KEEP.d;
  const side = KEEP.x + KEEP.w;
  // Puerta en arco y aspilleras en las dos caras visibles.
  const arch = [[-9, front, 8], [-9, front, 26]];
  for (let step = 0; step <= 10; step++) {
    const angle = Math.PI - (step / 10) * Math.PI;
    arch.push([Math.cos(angle) * 9, front, 26 + Math.sin(angle) * 7]);
  }
  arch.push([9, front, 8]);
  out.push(L(k.pathOf(arch.map(at)), { tone: "hi" }));
  out.push(L(k.segment([-9, front, 8], [9, front, 8], P), { tone: "hi" }));
  for (const x of [-15, 15]) {
    for (const z of [48, 88]) out.push(L(k.segment([x, front, z], [x, front, z + 12], P), { tone: "hi" }),
      D([at([x, front, z]), at([x, front, z + 12])], { size: 0.45, tone: "hi" }));
  }
  for (const y of [-104, -76]) {
    for (const z of [48, 88]) out.push(L(k.segment([side, y, z], [side, y, z + 12], P), { tone: "hi" }),
      D([at([side, y, z]), at([side, y, z + 12])], { size: 0.45, tone: "hi" }));
  }
  // Cornisa, almenas y la linterna: donde Grok lee y decide.
  const ledge = k.insetPlan(KEEP, -3);
  out.push(S(slab(ledge, KEEP_TOP, 6, 2, 0.6), { tone: "mid" }));
  const crown = KEEP_TOP + 6;
  const rim = [];
  for (let offset = 0; offset <= ledge.w - 6; offset += 10.4) {
    rim.push([ledge.x + offset, ledge.y], [ledge.x + offset, ledge.y + ledge.d - 6]);
    rim.push([ledge.x, ledge.y + offset], [ledge.x + ledge.w - 6, ledge.y + offset]);
  }
  const unique = [...new Map(rim.map((point) => [point.join(","), point])).values()].sort((a, b) => near(a) - near(b));
  const back = unique.filter(([x, y]) => near([x + 3, y + 3]) < -90);
  const forward = unique.filter(([x, y]) => near([x + 3, y + 3]) >= -90);
  const merlon = ([x, y]) => S(slab({ x, y, w: 6, d: 6, r: 0.6 }, crown, 7, 2), { tone: "mid", crease: "lo" });
  out.push(...back.map(merlon));
  out.push(`<g data-part="lantern">${S(k.cylinder(0, -90, 8, crown, 18, P, 40, 0.6), { tone: "hi", lit: true })}${
    L(k.sideArc(0, -90, 8, crown + 9, P, 24), { tone: "lo" })}${
    S(k.cylinder(0, -90, 10.5, crown + 18, 3, P, 40, 0.5), { tone: "hi" })}${
    S(k.cylinder(0, -90, 1.2, crown + 21, 10, P, 12), { tone: "hi", crease: "none" })}${
    D([at([0, -90, crown + 32])], { size: 1.4, tone: "hi" })}</g>`);
  out.push(...forward.map(merlon));
  return out.join("");
}

function gate() {
  // El rastrillo baja cuando el mensaje trae una inyección: el mensaje no entra y nunca llega a Grok.
  const bars = [];
  for (let x = PORTCULLIS.x0 + 4; x <= PORTCULLIS.x1 - 3; x += 6) {
    bars.push(k.segment([x, PORTCULLIS.y, PORTCULLIS.z0 + 3], [x, PORTCULLIS.y, PORTCULLIS.z1], P));
  }
  const rails = [8, 18, 28, PORTCULLIS.z1].map((z) => k.segment([PORTCULLIS.x0, PORTCULLIS.y, z], [PORTCULLIS.x1, PORTCULLIS.y, z], P));
  const spikes = [];
  for (let x = PORTCULLIS.x0 + 4; x <= PORTCULLIS.x1 - 3; x += 6) spikes.push(at([x, PORTCULLIS.y, PORTCULLIS.z0 + 3]));
  put(near([-134, PORTCULLIS.y]) - 0.2, `<g data-part="portcullis" transform="${k.translateAlong(P, [0, 0, LIFT])}">${
    `<path class="iso-line castle-grille" data-tone="hi" d="${bars.join("")}"/>`}${
    L(rails.join(""), { tone: "mid" })}${D(spikes, { size: 0.9, tone: "hi" })}</g>`);
  const lintel = { x: -176, y: 146, w: 84, d: 12, r: 1 };
  put(near([-134, PORTCULLIS.y]), `${S(slab(lintel, 34, 10, 2, 0.5), { tone: "mid" })}${
    D([at([-166, 158, 44]), at([-102, 158, 44])], { size: 0.5 })}${
    S(slab({ x: -142, y: 157, w: 16, d: 1.4, r: 0.3 }, 36, 6, 2), { tone: "hi" })}`);
  put(near(GATE_TOWER), tower(GATE_TOWER[0], GATE_TOWER[1], 13, GATE_TOP));
}

function parapets() {
  put(near([60, 149]), S(slab({ x: -69, y: 146, w: 245, d: 6, r: 0.6 }, 0, 9, 2, 0.4), { tone: "mid" }));
  put(near([179, -30]), S(slab({ x: 176, y: -150, w: 6, d: 242, r: 0.6 }, 0, 9, 2, 0.4), { tone: "mid" }));
  put(near([179, 137]), S(slab({ x: 176, y: 128, w: 6, d: 18, r: 0.6 }, 0, 9, 2, 0.4), { tone: "mid" }));
}

function store() {
  const out = [`<path class="iso-halo" d="${k.haloOf(STORE, 0, 1, P)}"/>`];
  out.push(S(slab(STORE, 0, STORE_TOP, 3, 0.8), { tone: "hi", crease: "lo",
    inner: L(k.sideSeam(STORE, 14, P, 3) + k.sideSeam(STORE, 28, P, 3), { tone: "faint" }) }));
  const front = STORE.y + STORE.d;
  const side = STORE.x + STORE.w;
  // Puerta de dos hojas con candado: el catálogo se lee en solo lectura.
  out.push(L(k.pathOf([[98, front, 0], [98, front, 26], [122, front, 26], [122, front, 0]].map(at)), { tone: "hi" }));
  out.push(L(k.segment([110, front, 0], [110, front, 26], P), { tone: "lo" }));
  out.push(`<g data-part="lock">${S(slab({ x: 107, y: front, w: 6, d: 1.6, r: 0.4 }, 10, 6, 2), { tone: "hi", lit: true })}${
    L(k.pathOf([[108, front + 1.6, 16], [108, front + 1.6, 19], [112, front + 1.6, 19], [112, front + 1.6, 16]].map(at)), { tone: "hi" })}</g>`);
  for (const y of [-112, -96, -80]) {
    out.push(L(k.pathOf([[side, y, 22], [side, y, 32], [side, y + 10, 32], [side, y + 10, 22]].map(at), true), { tone: "hi" }));
  }
  out.push(S(slab(k.insetPlan(STORE, -4), STORE_TOP, 5, 3, 0.6), { tone: "mid" }));
  out.push(S(slab({ x: 98, y: -104, w: 24, d: 26, r: 1 }, STORE_TOP + 5, 6, 2, 0.4), { tone: "mid" }));
  out.push(D([at([102, -82, STORE_TOP + 11]), at([118, -82, STORE_TOP + 11])], { size: 0.5 }));
  return out.join("");
}

function crates() {
  // Cajas del catálogo al lado de la bodega: se encienden cuando una herramienta lee la base.
  const boxes = [{ x: 154, y: -100, w: 14, d: 14 }, { x: 154, y: -84, w: 14, d: 14 }, { x: 155, y: -99, w: 12, d: 12 }];
  const parts = boxes.map((box, index) => {
    const z = index === 2 ? 12 : 0;
    const plan = { ...box, r: 0.8 };
    return S(slab(plan, z, index === 2 ? 10 : 12, 2, 0.4), { tone: "hi", crease: "lo",
      inner: L(k.sideSeam(plan, z + (index === 2 ? 5 : 6), P, 2), { tone: "lo" }) });
  });
  return `<g data-part="crates">${parts.join("")}</g>`;
}

function customs() {
  const booth = { x: 124, y: -14, w: 18, d: 16, r: 1 };
  const out = [S(slab(booth, 0, 20, 2, 0.5), { tone: "mid" })];
  out.push(L(k.pathOf([[booth.x + 4, booth.y + booth.d, 8], [booth.x + 4, booth.y + booth.d, 15],
    [booth.x + 14, booth.y + booth.d, 15], [booth.x + 14, booth.y + booth.d, 8]].map(at), true), { tone: "hi" }));
  out.push(S(slab(k.insetPlan(booth, -2), 20, 3, 2, 0.4), { tone: "mid" }));
  return out.join("");
}

function barrierPost() {
  const [x, y] = BARRIER.pivot;
  return `${S(k.cylinder(x, y, 3.4, 0, 2, P, 20), { tone: "mid" })}${S(k.cylinder(x, y, 2.2, 2, 12, P, 20), { tone: "mid" })}${
    S(slab({ x: x - 6, y: y - 2, w: 4, d: 4, r: 0.6 }, 10, 5, 2), { tone: "mid" })}`;
}

function scaleBase() {
  const [x, y] = SCALE.at;
  return `${S(slab({ x: x - 14, y: y - 8, w: 28, d: 16, r: 1.5 }, 0, 5, 3, 0.5), { tone: "mid" })}${
    S(k.cylinder(x, y, 2.2, 5, SCALE.z - 5, P, 20), { tone: "mid" })}${
    S(k.cylinder(x, y, 3.2, SCALE.z - 2, 3, P, 20), { tone: "hi" })}`;
}

function pan(side) {
  const [x, y] = SCALE.at;
  const cx = x + side * SCALE.beam;
  const z = SCALE.z - SCALE.drop;
  const load = side < 0
    ? S(slab({ x: cx - 5, y: y - 4, w: 10, d: 8, r: 0.6 }, z + 1.5, 2.2, 2), { tone: "hi", lit: true })
    : [0, 1, 2].map((row) => S(slab({ x: cx - 4.5, y: y - 3.5, w: 9, d: 7, r: 0.5 }, z + 1.5 + row * 1.6, 1.4, 2), { tone: "hi" })).join("");
  return `<g data-part="pan-${side < 0 ? "left" : "right"}">${S(k.cylinder(cx, y, 8, z, 1.5, P, 32, 0.3), { tone: "hi" })}${load}</g>`;
}

function booth() {
  const out = [`<path class="iso-halo" d="${k.haloOf(BOOTH, 0, 1, P)}"/>`];
  out.push(S(slab(BOOTH, 0, BOOTH_TOP, 2, 0.6), { tone: "hi", crease: "lo" }));
  const side = BOOTH.x + BOOTH.w;
  out.push(L(k.pathOf([[side, 100, 10], [side, 100, 24], [side, 120, 24], [side, 120, 10]].map(at), true), { tone: "hi" }));
  out.push(S(slab({ x: side, y: 98, w: 6, d: 24, r: 0.5 }, 9, 2, 2), { tone: "mid" }));
  out.push(S(slab({ x: side, y: 96, w: 9, d: 28, r: 0.5 }, 26, 1.6, 2), { tone: "mid" }));
  out.push(S(slab(k.insetPlan(BOOTH, -3), BOOTH_TOP, 4, 2, 0.5), { tone: "mid" }));
  out.push(S(k.cylinder(172, 110, 1, BOOTH_TOP + 4, 32, P, 12), { tone: "hi", crease: "none" }));
  out.push(`<g data-part="flag">${S(slab({ x: 173, y: 109.4, w: 22, d: 1.2, r: 0.2 }, 54, 12, 2), { tone: "hi", className: "castle-flag" })}</g>`);
  out.push(D([at([172, 110, BOOTH_TOP + 36.5])], { size: 1.1, tone: "hi" }));
  return out.join("");
}

function token() {
  const [x, y] = POINTS.cliente;
  const cube = { x: x - 5, y: y - 5, w: 10, d: 10, r: 1.2 };
  // El mensaje se dibuja en el origen y castillo.js lo traslada; así una sola figura sirve para todo el camino.
  const home = { ...cube, x: -5, y: -5 };
  return `<g data-part="token" class="castle-token">${`<path class="iso-halo" d="${k.haloOf(home, 0, 0.1, P)}"/>`}${
    S(slab(home, 0.6, 9, 3, 0.6), { tone: "hi", lit: true })}${D([at([0, 0, 9.6])], { size: 0.8, tone: "hi" })}</g>`;
}

// La escena, de atrás hacia adelante. Las capas del suelo van primero; lo demás, por profundidad.
const floor = [board(), plinth(), bridge(), road(), plaques()].join("");
put(-1000, wallBack());
put(near([-185, -155]), tower(-185, -155, 16, 62));
put(near([180, -155]), tower(180, -155, 13, 46));
put(near([-185, 150]), tower(-185, 150, 13, 46));
put(near([0, -90]), keep());
put(near([110, -91]), store());
put(near([161, -86]), crates());
put(near([SIGN.at[0], SIGN.at[1]]), `<g data-part="sign-post">${S(k.cylinder(SIGN.at[0], SIGN.at[1], 3, 1.2, 2, P, 16), { tone: "mid" })}${
  S(k.cylinder(SIGN.at[0], SIGN.at[1], 1.4, 3.2, SIGN.z + 3 - 3.2, P, 16), { tone: "mid" })}</g>${
  `<path data-part="sign" class="iso-line" data-tone="hi" d=""/>`}${D([at([SIGN.at[0], SIGN.at[1], SIGN.z])], { size: 0.9, tone: "hi" })}`);
put(near(BARRIER.pivot) - 0.5, barrierPost());
put(near(BARRIER.pivot) + 0.5, `<g data-part="barrier"><path class="castle-arm" d=""/><path class="castle-arm-stripes" d=""/></g>`);
put(near([133, -6]), customs());
put(near(SCALE.at) - 1, `${pan(-1)}${pan(1)}`);
put(near(SCALE.at), `${scaleBase()}<path data-part="strings" class="iso-line" data-tone="lo" d=""/>`);
put(near(SCALE.at) + 1, `<path data-part="beam" class="iso-line castle-beam" data-tone="hi" d=""/>`);
gate();
parapets();
put(near([173, 110]), booth());
put(near([180, 150]), tower(180, 150, 10, 22, false));
scene.sort((a, b) => a.key - b.key);

const camera = {
  o: at([0, 0, 0]), x: k.axisVector(P, [1, 0, 0]), y: k.axisVector(P, [0, 1, 0]), z: k.axisVector(P, [0, 0, 1]),
};
const route = { points: POINTS, edges: EDGES, hidden: HIDDEN };
const parts = { lift: LIFT, barrier: BARRIER, scale: SCALE, sign: SIGN };
const json = (value) => JSON.stringify(value).replace(/"/g, "&quot;");

const svg = k.figureSvg({
  width: WIDTH,
  height: HEIGHT,
  className: "castle-svg",
  label: "Maqueta de un castillo sobre una base. El mensaje del cliente entra por el puente y la puerta (1), sube a "
    + "la torre de Grok (2), llega al cruce donde el servidor elige la ruta (3), pasa por la aduana que valida cada "
    + "herramienta (4) hasta la bodega del catálogo (5), y vuelve a la torre; al final, la balanza compara la "
    + "redacción con los datos (6) y la respuesta sale por el mostrador (7).",
  body: [
    `<g data-layer="floor">${floor}</g>`,
    `<g data-layer="scene">${scene.map((item) => item.markup).join("")}</g>`,
    `<g class="castle-spare" data-layer="spare">${token()}</g>`,
  ],
}).replace("<svg ", `<svg data-camera="${json(camera)}" data-route="${json(route)}" data-parts="${json(parts)}" `);

const START = "<!-- castillo:inicio -->";
const END = "<!-- castillo:fin -->";
const indexPath = join(UI, "index.html");
const page = readFileSync(indexPath, "utf8");
const from = page.indexOf(START);
const to = page.indexOf(END);
if (from < 0 || to < from) throw new Error("index.html no tiene los marcadores del castillo");
writeFileSync(indexPath, page.slice(0, from + START.length) + svg + page.slice(to));

const license = "/* Estilos del kit isométrico de anatomy (MIT, Copyright (c) 2026 Ryan; ver tools/castillo/vendor/LICENSE-anatomy).\n"
  + "   Generado por tools/castillo/build.mjs: no se edita a mano. */\n";
writeFileSync(join(UI, "iso.css"), license + k.ISO_CSS.trim() + "\n");

mkdirSync(join(ROOT, ".local"), { recursive: true });
const preview = `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Castillo</title><link rel="stylesheet" href="../src/asistendero/ui/iso.css"><link rel="stylesheet" href="../src/asistendero/ui/castillo.css"></head><body class="iso castle-preview" data-theme="light"><div id="castle-stage" class="castle-stage">${svg}</div><p id="castle-readout"></p><button id="castle-pause" hidden>p</button><script src="../src/asistendero/ui/castillo.js"></script></body></html>`;
writeFileSync(join(ROOT, ".local", "castillo-preview.html"), preview);
console.log(`castillo: ${scene.length} piezas en escena, ${svg.length.toLocaleString("es-CO")} caracteres`);
