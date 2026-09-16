/* Modelador de muros de contención — interfaz local. */
'use strict';

// =========================================================== estado ====
let P = null;            // proyecto actual
let LAST = null;         // última respuesta de /api/preview
let SAP_OK = false;

const $  = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

// ============================================================== tema ====
// Los lienzos se pintan con Canvas 2D, que no entiende var(--x): la paleta se
// lee del CSS al arrancar y cada vez que cambia el tema, y de ahi la toman las
// funciones de dibujo. Asi el tema vive en un solo sitio, la hoja de estilos.
const PAL_VARS = {
  bg: '--bg', fg: '--fg', fgDim: '--fg-dim', fgMute: '--fg-mute', line2: '--line-2',
  accent: '--accent', beam: '--beam', pile: '--pile', soil: '--soil', bad: '--bad',
  p2: '--p2', p4: '--p4',
  canvasBg: '--canvas-bg', grid: '--canvas-grid', axis: '--canvas-axis',
  axis2: '--canvas-axis-2', label: '--canvas-label', tipBg: '--canvas-tip-bg',
  soilFill: '--canvas-soil-fill', wallFill: '--canvas-wall-fill',
  wallFill2: '--canvas-wall-fill-2', mesh: '--canvas-mesh', mesh2: '--canvas-mesh-2',
  hair: '--canvas-hair', onAccent: '--canvas-on-accent',
};
let PAL = {};

function readPalette() {
  const cs = getComputedStyle(document.documentElement);
  PAL = {};
  for (const k in PAL_VARS) PAL[k] = cs.getPropertyValue(PAL_VARS[k]).trim();
}

function redrawAll() {
  if (typeof drawElevation === 'function') drawElevation();
  if (typeof draw3D === 'function') draw3D();
  if (typeof drawPressures === 'function') drawPressures();
  if (typeof drawDesign === 'function') drawDesign();
}

function applyTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  try { localStorage.setItem('muros-theme', t); } catch (_) {}
  readPalette();
  const b = $('#btn-theme');
  if (b) {
    b.textContent = t === 'light' ? '☀ Claro' : '☾ Oscuro';
    b.title = t === 'light' ? 'Cambiar a tema oscuro' : 'Cambiar a tema claro';
  }
  redrawAll();
}

// ---------------------------------------------------------- paneles ----
// Plegar los laterales da casi 700 px más al área de trabajo, que es donde se
// miran los diagramas y el refuerzo. La elección se recuerda entre sesiones.
const PANELES = { izq: true, der: true };

function aplicarPaneles(redibujar = true) {
  const l = $('.layout');
  if (!l) return;
  l.classList.toggle('sin-izq', !PANELES.izq);
  l.classList.toggle('sin-der', !PANELES.der);
  const bi = $('#btn-panel-izq'), bd = $('#btn-panel-der'), ba = $('#btn-panel-ambos');
  if (bi) {
    bi.classList.toggle('on', !PANELES.izq);
    bi.title = (PANELES.izq ? 'Ocultar' : 'Mostrar') + ' el panel de entrada (Alt+1)';
  }
  if (bd) {
    bd.classList.toggle('on', !PANELES.der);
    bd.title = (PANELES.der ? 'Ocultar' : 'Mostrar') + ' el panel de resultados (Alt+2)';
  }
  if (ba) ba.classList.toggle('on', !PANELES.izq && !PANELES.der);
  try { localStorage.setItem('muros-paneles', JSON.stringify(PANELES)); } catch (_) {}
  if (redibujar) {
    // Los lienzos se dimensionan con clientWidth, así que hay que repintarlos
    // cuando la rejilla ya ha recalculado; dos cuadros bastan.
    requestAnimationFrame(() => requestAnimationFrame(redrawAll));
  }
}

function togglePanel(cual) {
  if (cual === 'ambos') {
    const plegar = PANELES.izq || PANELES.der;
    PANELES.izq = PANELES.der = !plegar;
  } else {
    PANELES[cual] = !PANELES[cual];
  }
  aplicarPaneles();
}

function initPaneles() {
  try {
    const g = JSON.parse(localStorage.getItem('muros-paneles') || 'null');
    if (g && typeof g.izq === 'boolean' && typeof g.der === 'boolean') {
      PANELES.izq = g.izq;
      PANELES.der = g.der;
    }
  } catch (_) {}
  aplicarPaneles(false);
}

function currentTheme() {
  return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
}

function initTheme() {
  let t = null;
  try { t = localStorage.getItem('muros-theme'); } catch (_) {}
  if (t !== 'light' && t !== 'dark') {
    t = (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches)
      ? 'light' : 'dark';
  }
  applyTheme(t);
}

function get(path) {
  return path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), P);
}
function set(path, value) {
  const keys = path.split('.');
  const last = keys.pop();
  let o = P;
  for (const k of keys) { if (o[k] == null) o[k] = {}; o = o[k]; }
  o[last] = value;
}

function toast(msg, kind = 'info', ms = 3600) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast ' + kind;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add('hidden'), ms);
}

const fmt = (v, d = 2) => (v == null || Number.isNaN(v) ? '—' : Number(v).toFixed(d));

// ==================================================== esquema de campos =
const BARS = ['#3', '#4', '#5', '#6', '#7', '#8', '#9', '#10', '#11', '#14', '#18'];

const SCHEMA = [
  { title: 'Proyecto', open: false, fields: [
    { p: 'info.name',     l: 'Nombre',     t: 'text' },
    { p: 'info.engineer', l: 'Ingeniero',  t: 'text' },
    { p: 'info.license',  l: 'Matrícula profesional', t: 'text' },
    { p: 'info.client',   l: 'Cliente',    t: 'text' },
  ]},
  { title: 'Pantalla', open: true, fields: [
    { p: 'wall.thickness', l: 'Espesor',            t: 'num', u: 'm',  s: 0.05 },
    { p: 'wall.length',    l: 'Longitud en Y',      t: 'num', u: 'm',  s: 0.1 },
    { p: 'wall.z_base',    l: 'Cota de arranque',   t: 'num', u: 'm',  s: 0.1 },
    { p: 'wall.z_top',     l: 'Cota de corona',     t: 'num', u: 'm',  s: 0.1 },
    { p: 'wall.shell_type', l: 'Formulación shell', t: 'sel', o: ['Shell-Thick', 'Shell-Thin'] },
  ]},
  { title: 'Pilas', open: true, fields: [
    { p: 'piles.diameter',        l: 'Diámetro',              t: 'num', u: 'm', s: 0.05 },
    { p: 'piles.spacing',         l: 'Separación',            t: 'num', u: 'm', s: 0.1 },
    { p: 'piles.count',           l: 'Número (vacío = auto)', t: 'num', u: 'u', s: 1 },
    { p: 'piles.z_top',           l: 'Cota de cabeza',        t: 'num', u: 'm', s: 0.1 },
    { p: 'piles.z_bot',           l: 'Cota de punta',         t: 'num', u: 'm', s: 0.1 },
    { p: 'piles.tip_restraint',   l: 'Punta restringida en Z (U3)', t: 'chk' },
    { p: 'piles.tip_spring_kv',   l: 'Resorte punta (vacío = auto)', t: 'num', u: 'kN/m', s: 1000 },
    { p: 'piles.skip_head_spring', l: 'Sin resorte en la cabeza', t: 'chk' },
  ]},
  { title: 'Viga cabezal', open: true, fields: [
    { p: 'cap_beam.enabled', l: 'Incluir viga cabezal', t: 'chk' },
    { p: 'cap_beam.width',   l: 'Ancho (b)',  t: 'num', u: 'm', s: 0.05 },
    { p: 'cap_beam.depth',   l: 'Canto (h)',  t: 'num', u: 'm', s: 0.05 },
    { p: 'cap_beam.z',       l: 'Cota del eje', t: 'num', u: 'm', s: 0.1 },
  ]},
  { title: 'Materiales', open: false, fields: [
    { p: 'materials.concrete.fc',    l: "f'c",             t: 'num', u: 'kPa', s: 1000 },
    { p: 'materials.concrete.E',     l: 'E (vacío = ACI)', t: 'num', u: 'kPa', s: 1e6 },
    { p: 'materials.concrete.nu',    l: 'Poisson',         t: 'num', u: '',    s: 0.01 },
    { p: 'materials.concrete.gamma', l: 'Peso específico', t: 'num', u: 'kN/m³', s: 0.5 },
    { p: 'materials.rebar.fy',       l: 'fy del refuerzo', t: 'num', u: 'kPa', s: 10000 },
  ]},
  { title: 'Empuje de tierras', open: true, fields: [
    { p: 'earth.method',    l: 'Método',     t: 'sel', o: ['rankine', 'coulomb', 'usuario'] },
    { p: 'earth.condition', l: 'Condición',  t: 'sel', o: ['activo', 'reposo', 'pasivo'] },
    { p: 'earth.K_user',    l: 'K impuesto', t: 'num', u: '', s: 0.01 },
    { p: 'earth.gamma',     l: 'γ del relleno',      t: 'num', u: 'kN/m³', s: 0.5 },
    { p: 'earth.gamma_sat', l: 'γ saturado',         t: 'num', u: 'kN/m³', s: 0.5 },
    { p: 'earth.phi',       l: 'φ del relleno',      t: 'num', u: '°', s: 1 },
    { p: 'earth.beta',      l: 'β terreno',          t: 'num', u: '°', s: 1 },
    { p: 'earth.delta',     l: 'δ muro-suelo',       t: 'num', u: '°', s: 1 },
    { p: 'earth.theta',     l: 'θ paramento',        t: 'num', u: '°', s: 1 },
    { p: 'earth.surcharge', l: 'Sobrecarga',         t: 'num', u: 'kPa', s: 1 },
  ]},
  { title: 'Sismo', open: true, fields: [
    { p: 'seismic.enabled',      l: 'Incluir incremento sísmico', t: 'chk' },
    { p: 'seismic.kh',           l: 'kh', t: 'num', u: '', s: 0.01 },
    { p: 'seismic.kv',           l: 'kv', t: 'num', u: '', s: 0.01 },
    { p: 'seismic.method',       l: 'Método', t: 'sel', o: ['mononobe', 'usuario'] },
    { p: 'seismic.dK_user',      l: 'ΔKae impuesto', t: 'num', u: '', s: 0.01 },
    { p: 'seismic.distribution', l: 'Distribución', t: 'sel',
      o: ['triangular_invertida', 'uniforme', 'triangular'] },
  ]},
  { title: 'Suelo de cimentación', open: false, custom: 'layers', fields: [
    { p: 'soil.water_table_z', l: 'Nivel freático (vacío = sin agua)', t: 'num', u: 'm', s: 0.5 },
    { p: 'soil.gamma_w',       l: 'γ del agua', t: 'num', u: 'kN/m³', s: 0.1 },
  ]},
  { title: 'Profundidad de cada pila', open: false, custom: 'puntas', fields: [] },
  { title: 'Refuerzo de pilas', open: false, custom: 'zones', fields: [] },
  { title: 'Mallado', open: false, fields: [
    { p: 'mesh.wall_div_per_bay', l: 'Divisiones por vano', t: 'num', u: 'u', s: 1 },
    { p: 'mesh.wall_target_dz',   l: 'Altura de shell',     t: 'num', u: 'm', s: 0.1 },
    { p: 'mesh.pile_segment',     l: 'Segmento de pila',    t: 'num', u: 'm', s: 0.1 },
    { p: 'mesh.wall_design_strips', l: 'Franjas de diseño', t: 'num', u: 'u', s: 1 },
  ]},
  { title: 'Análisis', open: false, fields: [
    { p: 'analysis.modal',       l: 'Caso modal (eigen)', t: 'chk' },
    { p: 'analysis.modal_modes', l: 'Número de modos',    t: 'num', u: 'u', s: 1 },
    { p: 'analysis.pdelta',      l: 'Caso no lineal P-Delta', t: 'chk' },
  ]},
  { title: 'Combinaciones', open: false, custom: 'combos', fields: [] },
];

// ===================================================== render del form =
function renderForm() {
  const root = $('#form-root');
  root.innerHTML = '';
  for (const g of SCHEMA) {
    const det = document.createElement('details');
    det.className = 'group';
    if (g.open) det.open = true;
    det.innerHTML = `<summary>${g.title}</summary>`;
    const body = document.createElement('div');
    body.className = 'group-body';

    for (const f of g.fields) body.appendChild(fieldEl(f));
    if (g.custom === 'layers') body.appendChild(layersEditor());
    if (g.custom === 'puntas') body.appendChild(puntasEditor());
    if (g.custom === 'zones')  body.appendChild(zonesEditor());
    if (g.custom === 'combos') body.appendChild(combosEditor());

    det.appendChild(body);
    root.appendChild(det);
  }
}

function fieldEl(f) {
  const wrap = document.createElement('div');
  const val = get(f.p);

  if (f.t === 'chk') {
    wrap.className = 'field field-check';
    const id = 'f_' + f.p.replace(/\./g, '_');
    wrap.innerHTML = `<input type="checkbox" id="${id}" ${val ? 'checked' : ''}><label for="${id}">${f.l}</label>`;
    wrap.querySelector('input').addEventListener('change', (e) => { set(f.p, e.target.checked); onChange(); });
    return wrap;
  }

  wrap.className = 'field';
  const lab = document.createElement('label');
  lab.innerHTML = f.l + (f.u ? ` <span class="unit">${f.u}</span>` : '');
  wrap.appendChild(lab);

  let inp;
  if (f.t === 'sel') {
    inp = document.createElement('select');
    for (const o of f.o) {
      const op = document.createElement('option');
      op.value = o; op.textContent = o.replace(/_/g, ' ');
      inp.appendChild(op);
    }
    inp.value = val;
    inp.addEventListener('change', (e) => { set(f.p, e.target.value); onChange(); });
  } else if (f.t === 'num') {
    inp = document.createElement('input');
    inp.type = 'number'; inp.step = f.s ?? 'any';
    inp.value = val == null ? '' : val;
    inp.addEventListener('input', (e) => {
      const s = e.target.value.trim();
      set(f.p, s === '' ? null : Number(s));
      onChange();
    });
  } else {
    inp = document.createElement('input');
    inp.type = 'text'; inp.value = val ?? '';
    inp.addEventListener('input', (e) => { set(f.p, e.target.value); onChange(); });
  }
  wrap.appendChild(inp);
  return wrap;
}

// -- editores de tabla --------------------------------------------------
function tableEditor(cols, rows, onAdd, rerender) {
  const box = document.createElement('div');
  const tbl = document.createElement('table');
  tbl.className = 'tbl';
  tbl.innerHTML = '<thead><tr>' + cols.map((c) => `<th>${c.h}</th>`).join('') + '<th></th></tr></thead>';
  const tb = document.createElement('tbody');

  rows.forEach((row, i) => {
    const tr = document.createElement('tr');
    for (const c of cols) {
      const td = document.createElement('td');
      let inp;
      if (c.type === 'sel') {
        inp = document.createElement('select');
        for (const o of c.options) {
          const op = document.createElement('option');
          op.value = o; op.textContent = o;
          inp.appendChild(op);
        }
      } else {
        inp = document.createElement('input');
        inp.type = c.type === 'text' ? 'text' : 'number';
        if (c.step) inp.step = c.step;
      }
      inp.value = c.get(row) ?? '';
      if (c.ro) { inp.disabled = true; inp.className = 'ro'; }
      inp.addEventListener('input', () => {
        const v = inp.value;
        c.set(row, c.type === 'text' || c.type === 'sel' ? v : (v === '' ? null : Number(v)));
        onChange();
      });
      td.appendChild(inp);
      tr.appendChild(td);
    }
    const tdx = document.createElement('td');
    // Sin `onAdd` las filas son derivadas (una por pila, por ejemplo) y no se
    // anaden ni se borran a mano: solo se editan sus valores.
    if (onAdd) {
      const x = document.createElement('button');
      x.className = 'x'; x.textContent = '×'; x.title = 'Eliminar fila';
      x.addEventListener('click', () => { rows.splice(i, 1); rerender(); onChange(); });
      tdx.appendChild(x);
    }
    tr.appendChild(tdx);
    tb.appendChild(tr);
  });

  tbl.appendChild(tb);
  box.appendChild(tbl);

  if (onAdd) {
    const act = document.createElement('div');
    act.className = 'row-actions';
    const add = document.createElement('button');
    add.className = 'btn btn-sm'; add.textContent = '+ Añadir';
    add.addEventListener('click', () => { onAdd(); rerender(); onChange(); });
    act.appendChild(add);
    box.appendChild(act);
  }
  return box;
}

function layersEditor() {
  const host = document.createElement('div');
  const draw = () => {
    host.innerHTML = '';
    host.appendChild(tableEditor(
      [
        { h: 'Estrato', type: 'text', get: (r) => r.name,  set: (r, v) => r.name = v },
        { h: 'Z sup',  type: 'num', step: 0.5, get: (r) => r.z_top, set: (r, v) => r.z_top = v },
        { h: 'Z inf',  type: 'num', step: 0.5, get: (r) => r.z_bot, set: (r, v) => r.z_bot = v },
        { h: 'γ',      type: 'num', step: 0.5, get: (r) => r.gamma, set: (r, v) => r.gamma = v },
        { h: 'φ°',     type: 'num', step: 1,   get: (r) => r.phi,   set: (r, v) => r.phi = v },
        { h: 'ks h',   type: 'num', step: 1000, get: (r) => r.ks_h, set: (r, v) => r.ks_h = v },
        { h: 'ks v',   type: 'num', step: 1000, get: (r) => r.ks_v, set: (r, v) => r.ks_v = v },
      ],
      P.soil.layers,
      () => {
        const last = P.soil.layers[P.soil.layers.length - 1];
        const zt = last ? last.z_bot : P.piles.z_top;
        P.soil.layers.push({ name: 'Estrato ' + (P.soil.layers.length + 1), z_top: zt, z_bot: zt - 3,
                             gamma: 18, gamma_sat: 20, phi: 30, cohesion: 0, ks_h: 20000, ks_v: 50000 });
      },
      draw));
  };
  draw();
  return host;
}

function zonesEditor() {
  const host = document.createElement('div');
  const draw = () => {
    host.innerHTML = '';
    host.appendChild(tableEditor(
      [
        { h: 'Sección', type: 'text', get: (r) => r.name,   set: (r, v) => r.name = v },
        { h: 'Z de',   type: 'num', step: 0.5, get: (r) => r.z_from, set: (r, v) => r.z_from = v },
        { h: 'Z a',    type: 'num', step: 0.5, get: (r) => r.z_to,   set: (r, v) => r.z_to = v },
        { h: 'n barras', type: 'num', step: 1, get: (r) => r.rebar.num_bars, set: (r, v) => r.rebar.num_bars = v },
        { h: 'Barra',  type: 'sel', options: BARS, get: (r) => r.rebar.bar_size, set: (r, v) => r.rebar.bar_size = v },
        { h: 'Rec.',   type: 'num', step: 0.005, get: (r) => r.rebar.cover, set: (r, v) => r.rebar.cover = v },
        { h: 'Estribo', type: 'sel', options: BARS, get: (r) => r.rebar.tie_size, set: (r, v) => r.rebar.tie_size = v },
        { h: 's',      type: 'num', step: 0.05, get: (r) => r.rebar.tie_spacing, set: (r, v) => r.rebar.tie_spacing = v },
        // Vacio = la zona arma todas las pilas. Con numeros, solo esas, y manda
        // sobre la zona general que ocupe la misma cota.
        { h: 'Pilas', type: 'text',
          get: (r) => (r.piles || []).join(', '),
          set: (r, v) => {
            const ns = String(v).split(',').map((x) => parseInt(x, 10)).filter((x) => x > 0);
            r.piles = ns.length ? ns : null;
          } },
      ],
      P.piles.zones,
      () => {
        const last = P.piles.zones[P.piles.zones.length - 1];
        const zf = last ? last.z_to : P.piles.z_top;
        P.piles.zones.push({ name: 'P_ZONA' + (P.piles.zones.length + 1), z_from: zf, z_to: P.piles.z_bot,
                             piles: null,
                             rebar: { cover: 0.075, num_bars: 20, bar_size: '#8', tie_size: '#4', tie_spacing: 0.15 } });
      },
      draw));
  };
  draw();
  return host;
}

function puntasEditor() {
  const host = document.createElement('div');
  const draw = () => {
    host.innerHTML = '';
    const n = nPilas();
    const info = document.createElement('div');
    info.className = 'tnote';
    info.innerHTML = `Cota de punta de cada pila. Vac\u00edo = todas terminan en
      <b>Z inferior</b> (${fmt(P.piles.z_bot, 2)} m). Con un corte de profundidad
      variable, cada pila termina donde le toca.`;
    host.appendChild(info);

    const filas = [];
    for (let i = 0; i < n; i += 1) {
      filas.push({ i, z: (P.piles.z_bots || [])[i] });
    }
    host.appendChild(tableEditor(
      [
        { h: 'Pila', type: 'text', ro: true, get: (r) => String(r.i + 1), set: () => {} },
        { h: 'Punta Z', type: 'num', step: 0.25,
          get: (r) => (P.piles.z_bots || [])[r.i],
          set: (r, v) => {
            const z = Array.isArray(P.piles.z_bots) && P.piles.z_bots.length === n
              ? P.piles.z_bots.slice()
              : new Array(n).fill(P.piles.z_bot);
            z[r.i] = v;
            P.piles.z_bots = z;
          } },
        { h: 'Longitud', type: 'text', ro: true,
          get: (r) => {
            const zb = (P.piles.z_bots || [])[r.i];
            return zb == null ? '\u2014' : fmt(P.piles.z_top - zb, 2) + ' m';
          },
          set: () => {} },
      ],
      filas, null, draw));

    const btn = document.createElement('button');
    btn.className = 'btn btn-sm';
    btn.textContent = 'Todas iguales';
    btn.addEventListener('click', () => { P.piles.z_bots = null; draw(); });
    host.appendChild(btn);
  };
  draw();
  return host;
}

function nPilas() {
  if (Array.isArray(P.piles.y_positions) && P.piles.y_positions.length) {
    return P.piles.y_positions.length;
  }
  if (P.piles.count && P.piles.count >= 2) return P.piles.count;
  const L = (P.wall.crown_profile && P.wall.crown_profile.length)
    ? Math.max(...P.wall.crown_profile.map((q) => q[0]))
      - Math.min(...P.wall.crown_profile.map((q) => q[0]))
    : P.wall.length;
  return Math.max(Math.round(L / (P.piles.spacing || 1)), 1) + 1;
}

function combosEditor() {
  const host = document.createElement('div');
  const draw = () => {
    host.innerHTML = '';
    host.appendChild(tableEditor(
      [
        { h: 'Nombre', type: 'text', get: (r) => r.name, set: (r, v) => r.name = v },
        { h: 'Factores (PATRON:factor, …)', type: 'text',
          get: (r) => r.factors.map((f) => `${f.pattern}:${f.factor}`).join(', '),
          set: (r, v) => {
            r.factors = v.split(',').map((s) => s.trim()).filter(Boolean).map((s) => {
              const [pat, fac] = s.split(':');
              return { pattern: (pat || '').trim(), factor: Number(fac) || 0 };
            });
          }},
        { h: 'Diseño', type: 'sel', options: ['None', 'Strength', 'Service'],
          get: (r) => r.design, set: (r, v) => r.design = v },
      ],
      P.combos,
      () => P.combos.push({ name: 'COMB' + (P.combos.length + 1),
                            factors: [{ pattern: 'DEAD', factor: 1.2 }, { pattern: 'SUELO', factor: 1.6 }],
                            design: 'Strength' }),
      draw));
    const note = document.createElement('div');
    note.className = 'hint';
    note.style.marginTop = '6px';
    note.textContent = 'Patrones disponibles: DEAD, SUELO, SOBRECARGA, AGUA, SISMO_SUELO. Los que no existan se omiten.';
    host.appendChild(note);
  };
  draw();
  return host;
}

// =================================================== canvas: utilidades =
function fitCanvas(cv) {
  const r = cv.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  cv.width = Math.max(1, Math.round(r.width * dpr));
  cv.height = Math.max(1, Math.round(r.height * dpr));
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w: r.width, h: r.height };
}

function gridBg(ctx, w, h) {
  ctx.fillStyle = PAL.canvasBg;
  ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = PAL.grid;
  ctx.lineWidth = 1;
  for (let x = 0; x < w; x += 40) { ctx.beginPath(); ctx.moveTo(x + .5, 0); ctx.lineTo(x + .5, h); ctx.stroke(); }
  for (let y = 0; y < h; y += 40) { ctx.beginPath(); ctx.moveTo(0, y + .5); ctx.lineTo(w, y + .5); ctx.stroke(); }
}

// ============================================ vista 1: perfil del muro =
const elev = { drag: null, hover: null };

function wallProfile() {
  if (P.wall.crown_profile && P.wall.crown_profile.length >= 2) return P.wall.crown_profile;
  return [[0, P.wall.z_top], [P.wall.length, P.wall.z_top]];
}

function drawElevation() {
  const cv = $('#canvas-elev');
  const { ctx, w, h } = fitCanvas(cv);
  if (w < 40 || h < 40) return;          // la vista esta oculta
  gridBg(ctx, w, h);
  if (!P) return;

  const prof = wallProfile();
  const y0 = 0, y1 = Math.max(P.wall.length, prof[prof.length - 1][0]);
  const zBot = P.piles.z_bot;
  const zTop = Math.max(P.wall.z_top, ...prof.map((p) => p[1]));

  const pad = 52;
  const sx = (w - 2 * pad) / Math.max(y1 - y0, 0.001);
  const sy = (h - 2 * pad) / Math.max(zTop - zBot, 0.001);
  const s = Math.min(sx, sy);
  const ox = pad + ((w - 2 * pad) - (y1 - y0) * s) / 2;
  const oy = h - pad - ((h - 2 * pad) - (zTop - zBot) * s) / 2;

  const X = (y) => ox + (y - y0) * s;
  const Y = (z) => oy - (z - zBot) * s;
  elev.X = X; elev.Y = Y; elev.s = s;
  elev.inv = (px, pz) => [(px - ox) / s + y0, (oy - pz) / s + zBot];

  // superficie del relleno retenido: banda rayada justo sobre la corona
  ctx.save();
  ctx.beginPath();
  ctx.moveTo(X(y0), Y(crownAt(y0)));
  for (const [py, pz] of prof) ctx.lineTo(X(py), Y(pz));
  ctx.strokeStyle = PAL.soil;
  ctx.lineWidth = 2;
  ctx.stroke();
  ctx.lineWidth = 1;
  for (let px = X(y0); px <= X(y1); px += 9) {
    const yy = elev.inv(px, 0)[0];
    const top = Y(crownAt(yy));
    ctx.beginPath();
    ctx.moveTo(px, top - 1);
    ctx.lineTo(px - 7, top - 8);
    ctx.strokeStyle = PAL.soilFill;
    ctx.stroke();
  }
  ctx.restore();

  // pantalla: se cierra contra la base real, que puede ir en pendiente
  ctx.save();
  ctx.beginPath();
  ctx.moveTo(X(y0), Y(baseAt(y0)));
  for (const [py, pz] of prof) ctx.lineTo(X(py), Y(pz));
  ctx.lineTo(X(y1), Y(baseAt(y1)));
  for (let k = 20; k >= 0; k -= 1) {
    const yy = y0 + (y1 - y0) * k / 20;
    ctx.lineTo(X(yy), Y(baseAt(yy)));
  }
  ctx.closePath();
  ctx.fillStyle = PAL.wallFill;
  ctx.fill();
  ctx.strokeStyle = PAL.accent;
  ctx.lineWidth = 2;
  ctx.stroke();
  ctx.restore();

  // malla de shells
  const nDiv = P.mesh.wall_div_per_bay;
  const piles = pilePositions();
  ctx.strokeStyle = PAL.wallFill2;
  ctx.lineWidth = 1;
  const hMax = Math.max(...prof.map((q) => q[1] - baseAt(q[0])));
  const nz = Math.max(1, Math.ceil(hMax / P.mesh.wall_target_dz - 1e-9));
  const ys = [];
  for (let i = 0; i < piles.length - 1; i++)
    for (let k = 0; k < nDiv; k++) ys.push(piles[i] + (piles[i + 1] - piles[i]) * k / nDiv);
  ys.push(piles[piles.length - 1]);
  for (const yy of ys) {
    ctx.beginPath(); ctx.moveTo(X(yy), Y(baseAt(yy))); ctx.lineTo(X(yy), Y(crownAt(yy))); ctx.stroke();
  }
  for (let k = 1; k < nz; k++) {
    ctx.beginPath();
    ys.forEach((yy, i) => {
      const zb = baseAt(yy);
      const z = zb + (crownAt(yy) - zb) * k / nz;
      i ? ctx.lineTo(X(yy), Y(z)) : ctx.moveTo(X(yy), Y(z));
    });
    ctx.stroke();
  }

  // viga cabezal: si la base del muro va en pendiente, la viga va con ella
  const zCab = (yy) => (P.wall.base_profile && P.wall.base_profile.length
    ? interpPerfil(P.wall.base_profile, yy)
    : (P.cap_beam.z ?? P.piles.z_top));
  if (P.cap_beam.enabled) {
    const ext = P.cap_beam.overhangs === false
      ? [piles[0], piles[piles.length - 1]] : [y0, y1];
    ctx.strokeStyle = PAL.beam; ctx.lineWidth = Math.max(3, P.cap_beam.depth * s);
    ctx.beginPath();
    ctx.moveTo(X(ext[0]), Y(zCab(ext[0])));
    ctx.lineTo(X(ext[1]), Y(zCab(ext[1])));
    ctx.stroke();
  }

  // pilas: cada una cuelga de su cabeza y baja hasta SU punta
  ctx.strokeStyle = PAL.pile;
  ctx.lineWidth = Math.max(2.5, P.piles.diameter * s);
  ctx.font = '10px ui-monospace, monospace';
  piles.forEach((py, i) => {
    const zt = zCab(py);
    const zb = (P.piles.z_bots || [])[i] ?? P.piles.z_bot;
    ctx.beginPath(); ctx.moveTo(X(py), Y(zt)); ctx.lineTo(X(py), Y(zb)); ctx.stroke();
    if (P.piles.z_bots) {
      ctx.save();
      ctx.fillStyle = PAL.axis2;
      ctx.textAlign = 'center';
      ctx.fillText(`${fmt(zt - zb, 2)} m`, X(py), Y(zb) + 12);
      ctx.restore();
    }
  });

  // estratos
  ctx.save();
  ctx.setLineDash([5, 4]);
  ctx.strokeStyle = PAL.axis;
  ctx.lineWidth = 1;
  ctx.font = '10px ui-monospace, monospace';
  ctx.fillStyle = PAL.axis2;
  for (const L of P.soil.layers) {
    ctx.beginPath(); ctx.moveTo(X(y0), Y(L.z_bot)); ctx.lineTo(X(y1), Y(L.z_bot)); ctx.stroke();
    const txt = `${L.name} · ks=${L.ks_h} kN/m³`;
    const tw = ctx.measureText(txt).width;
    const tx = Math.min(X(y1) + 8, w - tw - 8);
    ctx.setLineDash([]);
    ctx.fillStyle = PAL.tipBg;
    ctx.fillRect(tx - 3, Y(L.z_bot) - 12, tw + 6, 14);
    ctx.fillStyle = PAL.label;
    ctx.fillText(txt, tx, Y(L.z_bot) - 2);
    ctx.setLineDash([5, 4]);
  }
  if (P.soil.water_table_z != null) {
    ctx.setLineDash([2, 3]);
    ctx.strokeStyle = PAL.p4;
    ctx.beginPath(); ctx.moveTo(X(y0), Y(P.soil.water_table_z)); ctx.lineTo(X(y1), Y(P.soil.water_table_z)); ctx.stroke();
    ctx.fillStyle = PAL.p4;
    ctx.fillText('N.F.', X(y1) - 26, Y(P.soil.water_table_z) - 4);
  }
  ctx.restore();

  // nodos editables
  if ($('#chk-draw').checked) {
    prof.forEach(([py, pz], i) => {
      const px = X(py), pzz = Y(pz);
      ctx.beginPath(); ctx.arc(px, pzz, elev.hover === i ? 7 : 5, 0, 7);
      ctx.fillStyle = elev.hover === i ? PAL.onAccent : PAL.accent;
      ctx.fill();
      ctx.strokeStyle = PAL.canvasBg; ctx.lineWidth = 2; ctx.stroke();
    });
  }

  // ejes
  ctx.fillStyle = PAL.fgMute;
  ctx.font = '11px ui-monospace, monospace';
  ctx.fillText(`Y = ${fmt(y0, 1)} m`, X(y0) - 4, h - 22);
  ctx.fillText(`Y = ${fmt(y1, 1)} m`, X(y1) - 44, h - 22);
  ctx.save();
  ctx.translate(14, oy); ctx.rotate(-Math.PI / 2);
  ctx.fillText(`Z de ${fmt(zBot, 1)} a ${fmt(zTop, 1)} m`, 0, 0);
  ctx.restore();
}

function interpPerfil(perfil, y) {
  // Interpolacion lineal sobre [[y, z], ...], acotada en los extremos.
  const pts = perfil.slice().sort((a, b) => a[0] - b[0]);
  if (!pts.length) return 0;
  if (y <= pts[0][0]) return pts[0][1];
  if (y >= pts[pts.length - 1][0]) return pts[pts.length - 1][1];
  for (let i = 1; i < pts.length; i += 1) {
    if (y <= pts[i][0]) {
      const [ya, za] = pts[i - 1];
      const [yb, zb] = pts[i];
      const t = yb === ya ? 0 : (y - ya) / (yb - ya);
      return za + t * (zb - za);
    }
  }
  return pts[pts.length - 1][1];
}

function baseAt(y) {
  // Base del muro: perfil propio si lo hay, y si no la cota unica de siempre.
  return (P.wall.base_profile && P.wall.base_profile.length)
    ? interpPerfil(P.wall.base_profile, y)
    : P.wall.z_base;
}

function crownAt(y) {
  const prof = wallProfile();
  const pts = [...prof].sort((a, b) => a[0] - b[0]);
  if (y <= pts[0][0]) return pts[0][1];
  if (y >= pts[pts.length - 1][0]) return pts[pts.length - 1][1];
  for (let i = 0; i < pts.length - 1; i++) {
    const [y0, z0] = pts[i], [y1, z1] = pts[i + 1];
    if (y >= y0 && y <= y1) return y1 === y0 ? z1 : z0 + (z1 - z0) * (y - y0) / (y1 - y0);
  }
  return pts[pts.length - 1][1];
}

function pilePositions() {
  const prof = wallProfile();
  const y0 = 0, y1 = Math.max(P.wall.length, prof[prof.length - 1][0]);
  if (P.piles.y_positions && P.piles.y_positions.length) return [...P.piles.y_positions].sort((a, b) => a - b);
  if (P.piles.count && P.piles.count >= 2) {
    const n = P.piles.count, st = (y1 - y0) / (n - 1);
    return Array.from({ length: n }, (_, i) => y0 + i * st);
  }
  const nb = Math.max(1, Math.round((y1 - y0) / P.piles.spacing));
  const st = (y1 - y0) / nb;
  return Array.from({ length: nb + 1 }, (_, i) => y0 + i * st);
}

function setupElevation() {
  const cv = $('#canvas-elev');

  const pick = (ev) => {
    const r = cv.getBoundingClientRect();
    const px = ev.clientX - r.left, py = ev.clientY - r.top;
    const prof = wallProfile();
    for (let i = 0; i < prof.length; i++) {
      const dx = elev.X(prof[i][0]) - px, dy = elev.Y(prof[i][1]) - py;
      if (dx * dx + dy * dy < 100) return i;
    }
    return null;
  };

  cv.addEventListener('mousemove', (ev) => {
    if (!$('#chk-draw').checked || !elev.X) return;
    if (elev.drag != null) {
      const r = cv.getBoundingClientRect();
      const [yy, zz] = elev.inv(ev.clientX - r.left, ev.clientY - r.top);
      const prof = P.wall.crown_profile;
      const i = elev.drag;
      const lo = i === 0 ? 0 : prof[i - 1][0] + 0.05;
      const hi = i === prof.length - 1 ? Math.max(P.wall.length, yy) : prof[i + 1][0] - 0.05;
      prof[i] = [Math.round(Math.min(Math.max(yy, lo), hi) * 100) / 100,
                 Math.round(Math.max(zz, P.wall.z_base) * 100) / 100];
      drawElevation();
      return;
    }
    const h = pick(ev);
    if (h !== elev.hover) { elev.hover = h; drawElevation(); }
  });

  cv.addEventListener('mousedown', (ev) => {
    if (!$('#chk-draw').checked || ev.button !== 0) return;
    const i = pick(ev);
    if (i != null) { elev.drag = i; ensureProfile(); }
  });
  window.addEventListener('mouseup', () => {
    if (elev.drag != null) { elev.drag = null; onChange(); }
  });

  cv.addEventListener('dblclick', (ev) => {
    if (!$('#chk-draw').checked) return;
    ensureProfile();
    const r = cv.getBoundingClientRect();
    const [yy, zz] = elev.inv(ev.clientX - r.left, ev.clientY - r.top);
    const prof = P.wall.crown_profile;
    let k = prof.findIndex((p) => p[0] > yy);
    if (k < 0) k = prof.length;
    prof.splice(k, 0, [Math.round(yy * 100) / 100, Math.round(Math.max(zz, P.wall.z_base) * 100) / 100]);
    drawElevation(); onChange();
  });

  cv.addEventListener('contextmenu', (ev) => {
    ev.preventDefault();
    if (!$('#chk-draw').checked) return;
    const i = pick(ev);
    const prof = P.wall.crown_profile;
    if (i != null && prof && prof.length > 2) { prof.splice(i, 1); drawElevation(); onChange(); }
  });

  $('#chk-draw').addEventListener('change', (e) => {
    if (e.target.checked) {
      ensureProfile();
      $('#draw-hint').innerHTML = 'Modo dibujo: la corona sigue el perfil editado.';
    } else {
      P.wall.crown_profile = null;
      P.wall.base_profile = null;
      $('#draw-hint').innerHTML = `Modo paramétrico: la corona es horizontal a la cota <b id="hint-ztop">${fmt(P.wall.z_top)}</b> m.`;
    }
    drawElevation(); onChange();
  });

  $('#btn-add-pt').addEventListener('click', () => {
    ensureProfile();
    $('#chk-draw').checked = true;
    const prof = P.wall.crown_profile;
    const a = prof[prof.length - 2], b = prof[prof.length - 1];
    prof.splice(prof.length - 1, 0, [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]);
    drawElevation(); onChange();
  });

  $('#btn-reset-profile').addEventListener('click', () => {
    P.wall.crown_profile = null;
    $('#chk-draw').checked = false;
    drawElevation(); onChange();
  });
}

function ensureProfile() {
  if (!P.wall.crown_profile || P.wall.crown_profile.length < 2) {
    P.wall.crown_profile = [[0, P.wall.z_top], [P.wall.length / 2, P.wall.z_top], [P.wall.length, P.wall.z_top]];
  }
}

// =================================================== vista 2: modelo 3D =
const view3d = { az: -0.75, el: 0.42, zoom: 1, panx: 0, pany: 0, drag: null };

function project3(p) {
  const ca = Math.cos(view3d.az), sa = Math.sin(view3d.az);
  const x = p[0] * ca - p[1] * sa;
  const y = p[0] * sa + p[1] * ca;
  const z = p[2];
  const ce = Math.cos(view3d.el), se = Math.sin(view3d.el);
  return { x, y: -(y * se + z * ce), d: y * ce - z * se };
}

function draw3D() {
  const cv = $('#canvas-3d');
  const { ctx, w, h } = fitCanvas(cv);
  if (w < 40 || h < 40) return;
  gridBg(ctx, w, h);
  if (!LAST) {
    ctx.fillStyle = PAL.fgMute; ctx.font = '13px system-ui'; ctx.textAlign = 'center';
    ctx.fillText('Pulse «Actualizar modelo» para generar la geometría.', w / 2, h / 2);
    ctx.textAlign = 'left';
    return;
  }

  const G = LAST.geometry;
  const J = new Map(G.joints.map((j) => [j[0], [j[1], j[2], j[3]]]));

  const pts = G.joints.map((j) => project3([j[1], j[2], j[3]]));
  const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
  const spanX = Math.max(...xs) - Math.min(...xs) || 1;
  const spanY = Math.max(...ys) - Math.min(...ys) || 1;
  const s = Math.min((w - 90) / spanX, (h - 90) / spanY) * view3d.zoom;
  const cx = w / 2 - ((Math.max(...xs) + Math.min(...xs)) / 2) * s + view3d.panx;
  const cy = h / 2 - ((Math.max(...ys) + Math.min(...ys)) / 2) * s + view3d.pany;
  const S = (p) => [cx + p.x * s, cy + p.y * s];

  const showPress = $('#chk-press').checked;
  let pmax = 1;
  if (showPress) pmax = Math.max(1, ...Object.values(G.pressure || {}));

  const prims = [];

  if ($('#chk-shells').checked) {
    for (const a of G.areas) {
      const ids = a.slice(1);
      const ps = ids.map((id) => project3(J.get(id)));
      const depth = ps.reduce((t, p) => t + p.d, 0) / ps.length;
      let fill = PAL.mesh;
      if (showPress) {
        const v = ids.reduce((t, id) => t + (G.pressure[id] ?? 0), 0) / ids.length;
        fill = heat(v / pmax);
      }
      prims.push({ depth, type: 'poly', pts: ps.map(S), fill, stroke: PAL.mesh2 });
    }
  }

  if ($('#chk-frames').checked) {
    for (const f of G.frames) {
      const a = project3(J.get(f[1])), b = project3(J.get(f[2]));
      const col = f[3] === 'PILAS' ? PAL.pile : (f[3] === 'VIGA_CABEZAL' ? PAL.beam : PAL.fgDim);
      prims.push({ depth: (a.d + b.d) / 2 + 0.01, type: 'line', a: S(a), b: S(b),
                   stroke: col, width: f[3] === 'PILAS' ? 3 : 4 });
    }
  }

  if ($('#chk-springs').checked) {
    for (const sp of G.springs) {
      const p = project3(J.get(sp[0]));
      prims.push({ depth: p.d + 0.02, type: 'spring', p: S(p), tip: sp[2] > 0 });
    }
  }

  prims.sort((a, b) => b.depth - a.depth);
  for (const pr of prims) {
    if (pr.type === 'poly') {
      ctx.beginPath();
      pr.pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
      ctx.closePath();
      ctx.fillStyle = pr.fill; ctx.fill();
      ctx.strokeStyle = pr.stroke; ctx.lineWidth = 1; ctx.stroke();
    } else if (pr.type === 'line') {
      ctx.beginPath(); ctx.moveTo(...pr.a); ctx.lineTo(...pr.b);
      ctx.strokeStyle = pr.stroke; ctx.lineWidth = pr.width; ctx.lineCap = 'round'; ctx.stroke();
    } else {
      ctx.beginPath(); ctx.arc(pr.p[0], pr.p[1], pr.tip ? 4 : 2.5, 0, 7);
      ctx.fillStyle = pr.tip ? PAL.bad : PAL.beam; ctx.fill();
    }
  }

  drawAxes(ctx, w, h);

  const g = LAST.report.modelo;
  ctx.fillStyle = PAL.fgDim; ctx.font = '11px ui-monospace, monospace';
  ctx.fillText(`${g.joints} nudos · ${g.frames} frames · ${g.areas} shells · ${g.springs} resortes`, 12, h - 12);
  if (showPress) {
    ctx.fillText(`Empuje 0 – ${fmt(pmax, 1)} kPa`, 12, h - 28);
    for (let i = 0; i < 60; i++) {
      ctx.fillStyle = heat(i / 59);
      ctx.fillRect(150 + i * 2, h - 37, 2, 9);
    }
  }
}

function heat(t) {
  t = Math.max(0, Math.min(1, t));
  const r = Math.round(40 + 215 * t);
  const g = Math.round(150 - 90 * t);
  const b = Math.round(255 - 180 * t);
  return `rgba(${r},${g},${b},.75)`;
}

function drawAxes(ctx, w, h) {
  const o = [w - 62, h - 62], L = 26;
  const axes = [[[1, 0, 0], PAL.bad, 'X'], [[0, 1, 0], PAL.beam, 'Y'], [[0, 0, 1], PAL.accent, 'Z']];
  ctx.font = '10px ui-monospace, monospace';
  for (const [v, col, name] of axes) {
    const p = project3(v);
    ctx.beginPath(); ctx.moveTo(o[0], o[1]); ctx.lineTo(o[0] + p.x * L, o[1] + p.y * L);
    ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.stroke();
    ctx.fillStyle = col;
    ctx.fillText(name, o[0] + p.x * L * 1.35 - 3, o[1] + p.y * L * 1.35 + 3);
  }
}

function setup3D() {
  const cv = $('#canvas-3d');
  cv.addEventListener('mousedown', (e) => {
    view3d.drag = { x: e.clientX, y: e.clientY, btn: e.button,
                    az: view3d.az, el: view3d.el, px: view3d.panx, py: view3d.pany };
    cv.classList.add('dragging');
  });
  window.addEventListener('mouseup', () => { view3d.drag = null; cv.classList.remove('dragging'); });
  window.addEventListener('mousemove', (e) => {
    if (!view3d.drag) return;
    const dx = e.clientX - view3d.drag.x, dy = e.clientY - view3d.drag.y;
    if (view3d.drag.btn === 1 || e.shiftKey) {
      view3d.panx = view3d.drag.px + dx; view3d.pany = view3d.drag.py + dy;
    } else {
      view3d.az = view3d.drag.az + dx * 0.008;
      view3d.el = Math.max(-1.45, Math.min(1.45, view3d.drag.el - dy * 0.006));
    }
    draw3D();
  });
  cv.addEventListener('wheel', (e) => {
    e.preventDefault();
    view3d.zoom = Math.max(0.2, Math.min(9, view3d.zoom * (e.deltaY < 0 ? 1.12 : 0.89)));
    draw3D();
  }, { passive: false });

  $('#btn-view-iso').addEventListener('click', () => { Object.assign(view3d, { az: -0.75, el: 0.42, zoom: 1, panx: 0, pany: 0 }); draw3D(); });
  $('#btn-view-yz').addEventListener('click',  () => { Object.assign(view3d, { az: -Math.PI / 2, el: 0, zoom: 1, panx: 0, pany: 0 }); draw3D(); });
  $('#btn-view-xz').addEventListener('click',  () => { Object.assign(view3d, { az: 0, el: 0, zoom: 1, panx: 0, pany: 0 }); draw3D(); });
  ['chk-shells', 'chk-frames', 'chk-springs', 'chk-press'].forEach((id) =>
    $('#' + id).addEventListener('change', draw3D));
}

// ============================================ vista 3: diagrama empujes =
function drawPressures() {
  const cv = $('#canvas-press');
  const { ctx, w, h } = fitCanvas(cv);
  if (w < 40 || h < 40) return;
  gridBg(ctx, w, h);
  if (!LAST || !LAST.report.diagrama) {
    ctx.fillStyle = PAL.fgMute; ctx.font = '13px system-ui'; ctx.textAlign = 'center';
    ctx.fillText('Pulse «Actualizar modelo» para calcular los empujes.', w / 2, h / 2);
    ctx.textAlign = 'left';
    return;
  }

  const D = LAST.report.diagrama;
  const zMin = Math.min(...D.map((d) => d.z)), zMax = Math.max(...D.map((d) => d.z));
  const pMax = Math.max(0.001, ...D.map((d) => d.total));

  const pad = 60, padTop = 104, axX = pad + 110;
  const Y = (z) => h - pad - (z - zMin) / Math.max(zMax - zMin, 1e-6) * (h - pad - padTop);
  const X = (p) => axX + p / pMax * (w - axX - pad - 90);

  // eje del muro
  ctx.strokeStyle = PAL.accent; ctx.lineWidth = 3;
  ctx.beginPath(); ctx.moveTo(axX, Y(zMin)); ctx.lineTo(axX, Y(zMax)); ctx.stroke();

  const layers = [
    ['suelo', PAL.accent, 'Empuje del relleno'],
    ['sobrecarga', PAL.p2, 'Sobrecarga'],
    ['sismo', PAL.bad, 'Incremento sísmico'],
    ['agua', PAL.p4, 'Agua'],
  ];

  // apilado
  const stack = D.map(() => 0);
  for (const [key, col] of layers) {
    if (!D.some((d) => Math.abs(d[key]) > 1e-9)) continue;
    ctx.beginPath();
    D.forEach((d, i) => { const x = X(stack[i]); i ? ctx.lineTo(x, Y(d.z)) : ctx.moveTo(x, Y(d.z)); });
    for (let i = D.length - 1; i >= 0; i--) ctx.lineTo(X(stack[i] + D[i][key]), Y(D[i].z));
    ctx.closePath();
    ctx.fillStyle = col + '55'; ctx.fill();
    ctx.strokeStyle = col; ctx.lineWidth = 1.5; ctx.stroke();
    D.forEach((d, i) => { stack[i] += d[key]; });
  }

  // envolvente total
  ctx.beginPath();
  D.forEach((d, i) => { const x = X(d.total); i ? ctx.lineTo(x, Y(d.z)) : ctx.moveTo(x, Y(d.z)); });
  ctx.strokeStyle = PAL.fg; ctx.lineWidth = 2; ctx.setLineDash([4, 3]); ctx.stroke();
  ctx.setLineDash([]);

  // cotas y etiquetas
  ctx.fillStyle = PAL.fgDim; ctx.font = '11px ui-monospace, monospace';
  for (let i = 0; i <= 6; i++) {
    const z = zMin + (zMax - zMin) * i / 6;
    const d = D.reduce((a, b) => (Math.abs(b.z - z) < Math.abs(a.z - z) ? b : a));
    ctx.fillText(`Z ${fmt(z, 2)}`, 12, Y(z) + 4);
    ctx.strokeStyle = PAL.hair;
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(axX, Y(z)); ctx.lineTo(w - pad, Y(z)); ctx.stroke();
    ctx.fillStyle = PAL.fgMute;
    ctx.fillText(`${fmt(d.total, 1)} kPa`, X(d.total) + 6, Y(z) + 4);
    ctx.fillStyle = PAL.fgDim;
  }

  const e = LAST.report.empujes;
  const info = [
    `K      = ${fmt(e.K, 4)}`,
    `K·γ    = ${fmt(e.Ka_gamma, 3)} kN/m³`,
    `ΔKae   = ${fmt(e.dK, 4)}`,
    `ΔKae·γ = ${fmt(e.dKae_gamma, 3)} kN/m³`,
    `ΣP     = ${fmt(e.P_total, 1)} kN/m`,
  ];
  ctx.font = '11.5px ui-monospace, monospace';
  const bw = Math.max(...info.map((t) => ctx.measureText(t).width)) + 18;
  const bx = w - bw - 14, by = 14;
  ctx.fillStyle = PAL.tipBg;
  ctx.fillRect(bx, by, bw, info.length * 16 + 12);
  ctx.strokeStyle = PAL.line2; ctx.lineWidth = 1;
  ctx.strokeRect(bx + .5, by + .5, bw - 1, info.length * 16 + 11);
  info.forEach((t, i) => {
    ctx.fillStyle = i < 2 ? PAL.accent : (i < 4 ? PAL.bad : PAL.fg);
    ctx.fillText(t, bx + 9, by + 20 + i * 16);
  });
}

// ========================================= vista 4: fuerzas de diseño ===
// Las tres vistas se alimentan de `LAST.checks`, que ya trae la curva de
// interacción por zona, las envolventes crudas por elemento con la combinación
// que gobierna cada componente, y el valor por shell del muro. Nada de esto
// vuelve a pedirse a SAP.
const design = { mode: 'pm', comp: 'M22' };

function rampa(t) {
  // Azul → verde → ámbar → rojo. t en [0,1].
  t = Math.max(0, Math.min(1, t));
  const paradas = [[0, 58, 130, 200], [0.35, 40, 165, 130], [0.7, 215, 160, 40], [1, 210, 60, 60]];
  for (let i = 1; i < paradas.length; i++) {
    if (t <= paradas[i][0]) {
      const [t0, r0, g0, b0] = paradas[i - 1];
      const [t1, r1, g1, b1] = paradas[i];
      const k = (t - t0) / (t1 - t0 || 1);
      return `rgb(${Math.round(r0 + k * (r1 - r0))},${Math.round(g0 + k * (g1 - g0))},${Math.round(b0 + k * (b1 - b0))})`;
    }
  }
  return 'rgb(210,60,60)';
}

function ejes(ctx, x0, y0, x1, y1) {
  ctx.strokeStyle = PAL.axis2; ctx.lineWidth = 1.2;
  ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y0); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x0, y1); ctx.stroke();
}

function sinDatos(ctx, w, h, texto) {
  ctx.fillStyle = PAL.fgMute;
  ctx.font = '13px system-ui';
  ctx.textAlign = 'center';
  ctx.fillText(texto, w / 2, h / 2);
  ctx.textAlign = 'left';
}

function drawDesign() {
  const cv = $('#canvas-design');
  if (!cv) return;
  const { ctx, w, h } = fitCanvas(cv);
  if (w < 40 || h < 40) return;
  gridBg(ctx, w, h);
  const C = LAST && LAST.checks;
  $('#wrap-muro-comp').hidden = design.mode !== 'muro';
  if (!C) {
    sinDatos(ctx, w, h, 'Pulse «Correr y verificar» para obtener las solicitaciones.');
    return;
  }
  if (design.mode === 'pm') drawPM(ctx, w, h, C);
  else if (design.mode === 'viga') drawBeamEnv(ctx, w, h, C);
  else drawWallMap(ctx, w, h, C);
}

// ---- diagrama de interacción P-M ---------------------------------------
function drawPM(ctx, w, h, C) {
  const zonas = Object.entries(C.interaccion || {});
  if (!zonas.length) return sinDatos(ctx, w, h, 'Sin diagrama de interacción.');

  let mMax = 0, pMin = 0, pMax = 0;
  for (const [, z] of zonas) {
    for (const [p, m] of z.curva) { mMax = Math.max(mMax, m); pMin = Math.min(pMin, p); pMax = Math.max(pMax, p); }
    for (const d of z.demanda) { mMax = Math.max(mMax, d[1]); pMin = Math.min(pMin, d[0]); pMax = Math.max(pMax, d[0]); }
  }
  mMax *= 1.08; pMax *= 1.08; pMin *= 1.08;

  const pad = 62, padTop = 46, padR = 190;
  const X = (m) => pad + m / (mMax || 1) * (w - pad - padR);
  const Y = (p) => h - pad - (p - pMin) / ((pMax - pMin) || 1) * (h - pad - padTop);
  ejes(ctx, X(0), Y(pMin), X(mMax), Y(pMax));

  ctx.font = '10px ui-monospace, monospace';
  ctx.fillStyle = PAL.fgMute;
  for (let i = 0; i <= 5; i++) {
    const m = mMax * i / 5;
    ctx.fillText(fmt(m, 0), X(m) - 12, h - pad + 15);
    const p = pMin + (pMax - pMin) * i / 5;
    ctx.fillText(fmt(p, 0), 8, Y(p) + 4);
    ctx.strokeStyle = PAL.hair; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(X(0), Y(p)); ctx.lineTo(X(mMax), Y(p)); ctx.stroke();
  }
  // la línea P = 0 separa compresión de tracción
  if (pMin < 0) {
    ctx.strokeStyle = PAL.axis; ctx.setLineDash([4, 3]);
    ctx.beginPath(); ctx.moveTo(X(0), Y(0)); ctx.lineTo(X(mMax), Y(0)); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = PAL.fgMute;
    ctx.fillText('P = 0', X(mMax) - 34, Y(0) - 5);
  }
  ctx.fillStyle = PAL.fgDim;
  ctx.font = '11px system-ui';
  ctx.fillText('φMn [kN·m]', (X(0) + X(mMax)) / 2 - 28, h - 16);
  ctx.save();
  ctx.translate(16, (Y(pMin) + Y(pMax)) / 2 + 30);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText('φPn [kN]  (compresión +)', 0, 0);
  ctx.restore();

  const colores = [PAL.accent, PAL.beam, PAL.p2, PAL.p4];
  let ly = padTop + 6;
  zonas.forEach(([nombre, z], i) => {
    const col = colores[i % colores.length];
    ctx.strokeStyle = col; ctx.lineWidth = 2;
    ctx.beginPath();
    z.curva.forEach(([p, m], k) => (k ? ctx.lineTo(X(m), Y(p)) : ctx.moveTo(X(m), Y(p))));
    ctx.stroke();

    let peor = null;
    for (const d of z.demanda) {
      ctx.beginPath();
      ctx.arc(X(d[1]), Y(d[0]), 3, 0, 7);
      ctx.fillStyle = d[2] <= 0.85 ? PAL.beam : (d[2] <= 1 ? PAL.pile : PAL.bad);
      ctx.fill();
      if (!peor || d[2] > peor[2]) peor = d;
    }
    // etiqueta de la zona y de su punto más solicitado
    ctx.fillStyle = col; ctx.fillRect(w - padR + 4, ly - 7, 9, 9);
    ctx.fillStyle = PAL.fg; ctx.font = '11px system-ui';
    ctx.fillText(`${nombre}  (${z.num_bars}${z.bar_size})`, w - padR + 18, ly + 1);
    ly += 15;
    if (peor) {
      ctx.fillStyle = PAL.fgMute; ctx.font = '10px ui-monospace, monospace';
      ctx.fillText(`Pu ${fmt(peor[0], 0)}  Mu ${fmt(peor[1], 0)}  D/C ${fmt(peor[2], 2)}`,
                   w - padR + 18, ly + 1);
      ly += 13;
      ctx.beginPath(); ctx.arc(X(peor[1]), Y(peor[0]), 6, 0, 7);
      ctx.strokeStyle = PAL.bad; ctx.lineWidth = 1.5; ctx.stroke();
    }
    ly += 6;
  });

  ctx.fillStyle = PAL.fgDim; ctx.font = '11px system-ui';
  ctx.fillText('Curva de capacidad por zona de refuerzo; cada punto es un elemento de pila.',
               pad, 22);
  ctx.fillStyle = PAL.fgMute; ctx.font = '10px system-ui';
  ctx.fillText('El círculo rojo marca el elemento con mayor D/C de cada zona.', pad, 36);
}

// ---- envolventes a lo largo de la viga cabezal --------------------------
function drawBeamEnv(ctx, w, h, C) {
  const env = (C.envolventes && C.envolventes.viga_cabezal) || [];
  if (!env.length) return sinDatos(ctx, w, h, 'La viga cabezal no está habilitada.');
  const filas = env.slice().sort((a, b) => a.y - b.y);

  // El modelo da una envolvente POR ELEMENTO, no por estación: se dibuja como
  // escalones, que es la resolución real, en vez de fingir una curva continua.
  const series = [
    { k: 'M', lbl: 'Momento  M [kN·m]', col: PAL.accent,
      val: (r) => Math.max(r.M2.abs, r.M3.abs), caso: (r) => (r.M2.abs >= r.M3.abs ? r.M2.caso : r.M3.caso) },
    { k: 'V', lbl: 'Cortante  V [kN]', col: PAL.beam,
      val: (r) => Math.max(r.V2.abs, r.V3.abs), caso: (r) => (r.V2.abs >= r.V3.abs ? r.V2.caso : r.V3.caso) },
    { k: 'T', lbl: 'Torsión  T [kN·m]', col: PAL.bad,
      val: (r) => r.T.abs, caso: (r) => r.T.caso },
  ];

  const pad = 70, padTop = 54, padBot = 42, gap = 22;
  const alto = (h - padTop - padBot - gap * 2) / 3;
  const yIni = filas[0].y, yFin = filas[filas.length - 1].y;
  const anchoEl = (yFin - yIni) / Math.max(filas.length - 1, 1);
  const y0 = yIni - anchoEl / 2, y1 = yFin + anchoEl / 2;
  const X = (y) => pad + (y - y0) / ((y1 - y0) || 1) * (w - pad - 24);

  series.forEach((s, si) => {
    const top = padTop + si * (alto + gap);
    const base = top + alto;
    const vMax = Math.max(...filas.map(s.val), 1e-6) * 1.12;
    const Y = (v) => base - v / vMax * alto;

    ctx.strokeStyle = PAL.axis2; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(pad, base); ctx.lineTo(w - 24, base); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(pad, base); ctx.lineTo(pad, top); ctx.stroke();

    filas.forEach((r) => {
      const v = s.val(r);
      const xa = X(r.y - anchoEl / 2), xb = X(r.y + anchoEl / 2);
      ctx.fillStyle = s.col + '';
      ctx.globalAlpha = 0.20;
      ctx.fillRect(xa, Y(v), xb - xa, base - Y(v));
      ctx.globalAlpha = 1;
      ctx.strokeStyle = s.col; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(xa, Y(v)); ctx.lineTo(xb, Y(v)); ctx.stroke();
      ctx.strokeStyle = PAL.hair; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(xb, base); ctx.lineTo(xb, Y(v)); ctx.stroke();
      ctx.fillStyle = PAL.fgDim; ctx.font = '10px ui-monospace, monospace';
      ctx.textAlign = 'center';
      ctx.fillText(fmt(v, 0), (xa + xb) / 2, Y(v) - 4);
      ctx.textAlign = 'left';
    });

    ctx.fillStyle = PAL.fg; ctx.font = '11px system-ui';
    ctx.fillText(s.lbl, pad, top - 7);
    const peor = filas.reduce((a, b) => (s.val(b) > s.val(a) ? b : a));
    ctx.fillStyle = PAL.fgMute; ctx.font = '10px ui-monospace, monospace';
    ctx.textAlign = 'right';
    ctx.fillText('máx ' + fmt(s.val(peor), 0) + '   gobierna ' + s.caso(peor), w - 24, top - 7);
    ctx.textAlign = 'left';
    ctx.fillText(fmt(vMax, 0), 8, top + 9);
    ctx.fillText('0', 8, base + 3);
  });

  ctx.fillStyle = PAL.fgMute; ctx.font = '10px ui-monospace, monospace';
  filas.forEach((r) => {
    ctx.textAlign = 'center';
    ctx.fillText('Y ' + fmt(r.y, 2), X(r.y), h - padBot + 16);
    ctx.textAlign = 'left';
  });
  ctx.fillStyle = PAL.fgDim; ctx.font = '11px system-ui';
  ctx.fillText('Envolvente por elemento de la viga cabezal a lo largo de Y', pad, 20);
  ctx.fillStyle = PAL.fgMute; ctx.font = '10px system-ui';
  ctx.fillText('Un escalón por elemento: es la resolución real del modelo, no una curva interpolada.',
               pad, 34);
}

// ---- mapa de solicitaciones del muro ------------------------------------
function drawWallMap(ctx, w, h, C) {
  const els = (C.muro && C.muro.elementos) || [];
  const geo = LAST && LAST.geometry;
  if (!els.length || !geo) return sinDatos(ctx, w, h, 'Sin solicitaciones de la pantalla.');

  const porId = new Map(els.map((e) => [e.id, e]));
  const J = new Map(geo.joints.map((j) => [j[0], j]));
  const comp = design.comp;
  let vMax = 0;
  for (const e of els) vMax = Math.max(vMax, Math.abs(e[comp] || 0));
  if (vMax <= 0) vMax = 1;

  // Los límites salen de los nudos de LOS SHELL, no de todos: `geo.joints`
  // incluye las pilas, que bajan a -10 m, y encuadrar con ellas dejaría la
  // pantalla aplastada en la parte de arriba.
  const ys = [], zs = [];
  for (const a of geo.areas) {
    if (!porId.has(a[0])) continue;
    for (const id of a.slice(1)) {
      const j = J.get(id);
      if (j) { ys.push(j[2]); zs.push(j[3]); }
    }
  }
  if (!ys.length) return sinDatos(ctx, w, h, 'Sin geometría de la pantalla.');
  const y0 = Math.min(...ys), y1 = Math.max(...ys);
  const z0 = Math.min(...zs), z1 = Math.max(...zs);
  const pad = 54, padTop = 36, padBot = 76;
  const k = Math.min((w - 2 * pad) / ((y1 - y0) || 1), (h - padTop - padBot) / ((z1 - z0) || 1));
  const ox = (w - (y1 - y0) * k) / 2, oz = h - padBot;
  const X = (y) => ox + (y - y0) * k;
  const Y = (z) => oz - (z - z0) * k;

  for (const a of geo.areas) {
    const e = porId.get(a[0]);
    if (!e) continue;
    const pts = a.slice(1).map((id) => J.get(id)).filter(Boolean);
    if (pts.length < 3) continue;
    ctx.beginPath();
    pts.forEach((p, i) => (i ? ctx.lineTo(X(p[2]), Y(p[3])) : ctx.moveTo(X(p[2]), Y(p[3]))));
    ctx.closePath();
    ctx.fillStyle = rampa(Math.abs(e[comp] || 0) / vMax);
    ctx.fill();
    ctx.strokeStyle = PAL.hair; ctx.lineWidth = 0.6; ctx.stroke();
  }

  // franjas de diseño superpuestas
  const F = C.muro.franjas;
  if (F && F.franjas) {
    ctx.strokeStyle = PAL.fg; ctx.lineWidth = 1.2; ctx.setLineDash([6, 4]);
    ctx.fillStyle = PAL.fg; ctx.font = '10px ui-monospace, monospace';
    for (const f of F.franjas) {
      ctx.beginPath(); ctx.moveTo(X(y0), Y(f.z_fin)); ctx.lineTo(X(y1), Y(f.z_fin)); ctx.stroke();
      ctx.fillText(`F${f.franja}  As ${fmt(f.vertical.As, 0)} mm²/m`,
                   X(y0) + 6, Y((f.z_ini + f.z_fin) / 2));
    }
    ctx.setLineDash([]);
  }

  // barra de color
  const bx = pad, by = h - 46, bw = Math.min(280, w - 2 * pad), bh = 12;
  for (let i = 0; i < bw; i++) {
    ctx.fillStyle = rampa(i / bw);
    ctx.fillRect(bx + i, by, 1, bh);
  }
  ctx.strokeStyle = PAL.line2; ctx.lineWidth = 1;
  ctx.strokeRect(bx + 0.5, by + 0.5, bw - 1, bh - 1);
  ctx.fillStyle = PAL.fgMute; ctx.font = '10px ui-monospace, monospace';
  ctx.fillText('0', bx, by + bh + 13);
  ctx.fillText(fmt(vMax, 0), bx + bw - 24, by + bh + 13);
  const unidad = comp === 'V' ? 'kN/m' : 'kN·m/m';
  ctx.fillStyle = PAL.fg; ctx.font = '11px system-ui';
  ctx.fillText(`${comp} promediado por elemento  [${unidad}]`, bx + bw + 14, by + bh - 1);
  ctx.fillStyle = PAL.fgDim;
  ctx.fillText('Alzado Y-Z de la pantalla; las líneas de trazos son las franjas de diseño.',
               pad, 20);
}

// ============================================ vista 5: refuerzo ========
// El dibujo lo genera el servidor con el MISMO motor que produce el DXF, así
// que lo que se revisa en pantalla y lo que recibe el dibujante no pueden
// divergir. Los ajustes viven en P.rebar_overrides, dentro del proyecto, de
// modo que se guardan con «Guardar datos» y llegan solos a la lámina, al Excel
// y a la memoria.
const refuerzo = { vista: 'conjunto', data: null, cargando: false, n_laminas: 2 };

const BARRAS = ['#3', '#4', '#5', '#6', '#7', '#8', '#9', '#10', '#11'];
const ELEM_DE_VISTA = {
  conjunto: 'Pantalla', arranque: 'Pantalla', alzado_muro: 'Pantalla',
  viga: 'Viga cabezal', alzado: 'Viga cabezal',
  pila: 'Pila',
  planta: null, lamina: null, lamina1: null, lamina2: null, lamina3: null,
};

async function loadRefuerzo() {
  const wrap = $('#svg-refuerzo');
  if (!(LAST && LAST.checks && LAST.checks.muro)) {
    wrap.innerHTML = '<div class="placeholder">Pulse «Correr y verificar» para calcular el refuerzo.</div>';
    $('#edit-refuerzo').innerHTML = '';
    return;
  }
  if (refuerzo.cargando) return;
  // Si el despiece se encogió hasta caber en la L-02, la tercera lámina ya no
  // existe: se vuelve a la segunda en vez de pedir una hoja que no está.
  if (refuerzo.vista === 'lamina3' && refuerzo.n_laminas === 2) {
    refuerzo.vista = 'lamina2';
    $$('#view-refuerzo .tab-r').forEach((x) =>
      x.classList.toggle('active', x.dataset.vista === 'lamina2'));
  }
  refuerzo.cargando = true;
  $('#hint-refuerzo').textContent = 'Dibujando…';
  try {
    const r = await post('/api/design/detalle',
      Object.assign(designBody(), { vista: refuerzo.vista }));
    refuerzo.data = await r.json();
    // El juego tiene dos láminas salvo que el despiece no quepa con las
    // secciones; el botón de la tercera solo se muestra cuando existe.
    refuerzo.n_laminas = refuerzo.data.n_laminas || 2;
    const b3 = $('#view-refuerzo .tab-r[data-vista="lamina3"]');
    if (b3) b3.hidden = refuerzo.n_laminas < 3;
    wrap.innerHTML = refuerzo.data.svg;
    // El SVG viene con tamaño en milímetros porque es una lámina imprimible.
    // En pantalla eso desborda: se le quita el tamaño intrínseco y se deja que
    // el viewBox se ajuste al hueco, que conserva la proporción por sí solo.
    const svg = wrap.querySelector('svg');
    if (svg) {
      svg.removeAttribute('width');
      svg.removeAttribute('height');
      svg.style.width = '100%';
      svg.style.height = '100%';
    }
    $('#hint-refuerzo').textContent = refuerzo.data.titulo;
    renderEdit();
  } catch (err) {
    wrap.innerHTML = `<div class="placeholder">${err.message || err}</div>`;
    $('#hint-refuerzo').textContent = '';
  } finally {
    refuerzo.cargando = false;
  }
}

function selBarra(id, valor, placeholder) {
  const ops = [`<option value="">${placeholder}</option>`].concat(
    BARRAS.map((b) => `<option value="${b}"${b === valor ? ' selected' : ''}>${b}</option>`));
  return `<select id="${id}">${ops.join('')}</select>`;
}

function ov() {
  if (!P.rebar_overrides) P.rebar_overrides = { bar_v: '#5', bar_h: '#5', muro: [], viga: {} };
  if (!P.rebar_overrides.muro) P.rebar_overrides.muro = [];
  if (!P.rebar_overrides.viga) P.rebar_overrides.viga = {};
  return P.rebar_overrides;
}

function ovFranja(i) {
  const o = ov();
  let f = o.muro.find((x) => x.franja === i);
  if (!f) { f = { franja: i }; o.muro.push(f); }
  return f;
}

async function aplicarAjuste() {
  await loadRefuerzo();
  await fetchPlanilla();
}

function renderEdit() {
  const panel = $('#edit-refuerzo');
  const d = refuerzo.data;
  if (!d) { panel.innerHTML = ''; return; }
  const elem = ELEM_DE_VISTA[refuerzo.vista];
  const partes = [];

  if (elem === 'Pantalla') partes.push(editPantalla(d));
  else if (elem === 'Viga cabezal') partes.push(editViga(d));
  else if (elem === 'Pila') partes.push(editPila());

  partes.push(verificacion(d));
  partes.push(`<div class="row-actions">
    <button class="btn btn-sm" id="btn-reset-ref">Restablecer recomendado</button>
  </div>`);
  partes.push(`<div class="tnote">Peso total ${fmt(d.peso_total_kg, 0)} kg ·
    cuantía ${fmt(d.cuantia_kg_m3, 0)} kg/m³. Los ajustes se guardan con el
    proyecto y salen en el DXF, el PDF, el Excel y la memoria.</div>`);
  panel.innerHTML = partes.join('');
  cablearEdit();
}

function editPantalla(d) {
  const o = ov();
  const franjas = ((LAST.checks.muro.franjas || {}).franjas) || [];
  const marcaDe = (fr, tipo, dir) => d.marcas.find((m) =>
    m.franja === fr && m.posicion.includes(dir) && m.posicion.includes('tierra'));
  const filas = franjas.map((f) => {
    const mv = marcaDe(f.franja, 'v', 'vertical');
    const mh = marcaDe(f.franja, 'h', 'horizontal');
    const of_ = o.muro.find((x) => x.franja === f.franja) || {};
    return `<div class="tnote" style="margin:8px 0 2px">Franja ${f.franja}
        · z ${fmt(f.z_ini, 2)}–${fmt(f.z_fin, 2)} m</div>
      <div class="erow"><span>Vertical</span>
        ${selBarra('bv-' + f.franja, of_.bar_v || '', mv ? mv.diametro : '#5')}
        <input type="number" id="sv-${f.franja}" min="50" step="25"
               value="${of_.s_v ?? ''}" placeholder="${mv ? fmt(mv.s_rec_mm, 0) : ''}"></div>
      <div class="erow"><span>Horizontal</span>
        ${selBarra('bh-' + f.franja, of_.bar_h || '', mh ? mh.diametro : '#5')}
        <input type="number" id="sh-${f.franja}" min="50" step="25"
               value="${of_.s_h ?? ''}" placeholder="${mh ? fmt(mh.s_rec_mm, 0) : ''}"></div>`;
  }).join('');
  return `<h4>Pantalla · malla por franja</h4>
    <div class="erow"><span>Barra por defecto</span>
      ${selBarra('bar-v-def', o.bar_v, '#5')}${selBarra('bar-h-def', o.bar_h, '#5')}</div>
    <div class="tnote">Izquierda vertical, derecha horizontal. En cada franja:
      diámetro y separación en mm; vacío = el recomendado (en gris).</div>
    ${filas}`;
}

function editViga(d) {
  const v = ov().viga;
  const sup = d.marcas.find((m) => m.posicion.includes('superior'));
  const est = d.marcas.find((m) => m.forma === 'estribo_rect');
  const tor = d.marcas.find((m) => m.posicion.includes('torsion'));
  return `<h4>Viga cabezal</h4>
    <div class="erow"><span>Longitudinal</span>
      ${selBarra('vc-bar', v.bar_size || '', sup ? sup.diametro : '')}
      <input type="number" id="vc-nsup" min="2" step="1" value="${v.n_sup ?? ''}"
             placeholder="${sup ? sup.n_elem : ''}"></div>
    <div class="erow"><span>&nbsp;&nbsp;inferior</span><span></span>
      <input type="number" id="vc-ninf" min="2" step="1" value="${v.n_inf ?? ''}"
             placeholder="${sup ? sup.n_elem : ''}"></div>
    <div class="erow"><span>Estribo cerrado</span>
      ${selBarra('vc-tie', v.tie_size || '', est ? est.diametro : '')}
      <input type="number" id="vc-stie" min="50" step="10" value="${v.s_tie ?? ''}"
             placeholder="${est ? fmt(est.s_rec_mm, 0) : ''}"></div>
    <div class="erow"><span>Torsión, perímetro</span>
      ${selBarra('vc-btor', v.bar_torsion || '', tor ? tor.diametro : '')}
      <input type="number" id="vc-ntor" min="4" step="1" value="${v.n_torsion ?? ''}"
             placeholder="${tor ? tor.n_elem : ''}"></div>
    <div class="tnote">Segunda columna: número de barras o separación en mm.
      Vacío = el recomendado por el cálculo.</div>`;
}

function editPila() {
  return `<h4>Pilas</h4>
    <div class="tnote">El armado de las pilas se define por zonas en el panel
      izquierdo, en <b>Refuerzo de pilas</b>: número de barras, diámetro,
      estribo y separación. Los cambios se reflejan aquí al recalcular.</div>`;
}

function verificacion(d) {
  const filas = d.marcas.map((m) => {
    const clase = m.cumple ? 'chk-ok' : 'chk-bad';
    const req = m.as_req > 0 ? `${fmt(m.as_req, 0)}` : '—';
    return `<div class="chk-row ${clase}">
      <span>${m.ajustado ? '<span class="chk-adj">✎</span> ' : ''}${m.marca}
        <span class="combo">${m.diametro}</span></span>
      <b>${fmt(m.as_prov, 0)} / ${req}</b></div>`;
  }).join('');
  const malas = d.insuficientes.length;
  const aviso = malas
    ? `<div class="msg msg-bad">${malas} marca(s) por debajo de lo requerido:
        ${d.insuficientes.join(', ')}. Corrija antes de exportar.</div>`
    : `<div class="msg msg-ok">Todo el refuerzo de esta vista cubre lo requerido.</div>`;
  return `<h4>Colocado / requerido [mm² o mm²/m]</h4>${aviso}
    <div class="chk-list">${filas}</div>`;
}

function cablearEdit() {
  const franjas = ((LAST.checks.muro.franjas || {}).franjas) || [];
  const num = (v) => (v === '' || v == null ? null : Number(v));

  for (const f of franjas) {
    const bv = $('#bv-' + f.franja), sv = $('#sv-' + f.franja);
    const bh = $('#bh-' + f.franja), sh = $('#sh-' + f.franja);
    if (bv) bv.addEventListener('change', () => { ovFranja(f.franja).bar_v = bv.value || null; aplicarAjuste(); });
    if (sv) sv.addEventListener('change', () => { ovFranja(f.franja).s_v = num(sv.value); aplicarAjuste(); });
    if (bh) bh.addEventListener('change', () => { ovFranja(f.franja).bar_h = bh.value || null; aplicarAjuste(); });
    if (sh) sh.addEventListener('change', () => { ovFranja(f.franja).s_h = num(sh.value); aplicarAjuste(); });
  }
  const def = [['#bar-v-def', 'bar_v'], ['#bar-h-def', 'bar_h']];
  for (const [id, k] of def) {
    const el = $(id);
    if (el) el.addEventListener('change', () => { ov()[k] = el.value || '#5'; aplicarAjuste(); });
  }
  const viga = [['#vc-bar', 'bar_size', 's'], ['#vc-nsup', 'n_sup', 'n'],
                ['#vc-ninf', 'n_inf', 'n'], ['#vc-tie', 'tie_size', 's'],
                ['#vc-stie', 's_tie', 'n'], ['#vc-btor', 'bar_torsion', 's'],
                ['#vc-ntor', 'n_torsion', 'n']];
  for (const [id, k, tipo] of viga) {
    const el = $(id);
    if (el) el.addEventListener('change', () => {
      ov().viga[k] = tipo === 'n' ? num(el.value) : (el.value || null);
      aplicarAjuste();
    });
  }
  const reset = $('#btn-reset-ref');
  if (reset) reset.addEventListener('click', () => {
    const elem = ELEM_DE_VISTA[refuerzo.vista];
    if (elem === 'Pantalla') { ov().muro = []; ov().bar_v = '#5'; ov().bar_h = '#5'; }
    else if (elem === 'Viga cabezal') ov().viga = {};
    else { ov().muro = []; ov().viga = {}; }
    aplicarAjuste();
    toast('Refuerzo restablecido al recomendado por el cálculo', 'ok');
  });
}

// ======================================================== resultados ====
function ratioClass(r) { return r == null ? '' : (r <= 0.85 ? 'ok' : (r <= 1.0 ? 'warn' : 'bad')); }

function renderResults() {
  const root = $('#results-root');
  if (!LAST) return;
  const R = LAST.report;
  const parts = [];

  for (const wmsg of LAST.warnings || []) parts.push(`<div class="msg msg-warn">${wmsg}</div>`);

  const g = R.geometria;
  parts.push(card('Geometría', [
    ['Altura del muro', fmt(g.altura_muro) + ' m'],
    ['Longitud', fmt(g.longitud_muro) + ' m'],
    ['Espesor', fmt(g.espesor_muro) + ' m'],
    ['Pilas', `${g.n_pilas} Ø${fmt(g.diametro_pila)} m @ ${fmt(g.separacion_pilas)} m`],
    ['Longitud de pila', fmt(g.longitud_pila) + ' m'],
  ]));

  const e = R.empujes, p = R.presiones_kPa;
  parts.push(card('Empujes', [
    ['K', fmt(e.K, 4), true],
    ['K·γ', fmt(e.Ka_gamma, 3) + ' kN/m³'],
    ['ΔKae', fmt(e.dK, 4)],
    ['ΔKae·γ', fmt(e.dKae_gamma, 3) + ' kN/m³'],
    ['Empuje en la base', fmt(p.suelo_base, 2) + ' kPa'],
    ['Sismo en corona', fmt(p.sismo_corona, 2) + ' kPa'],
    ['P suelo', fmt(e.P_suelo, 1) + ' kN/m'],
    ['P sismo', fmt(e.P_sismo, 1) + ' kN/m'],
    ['P total', fmt(e.P_total, 1) + ' kN/m', true],
  ]));

  const m = R.modelo;
  parts.push(card('Modelo', [
    ['Nudos', m.joints], ['Frames', m.frames], ['Shells', m.areas], ['Resortes', m.springs],
    ['Patrones', m.load_patterns.join(', ')],
    ['Combinaciones', String(m.combos.length)],
  ]));

  if (R.balasto && R.balasto.length) {
    const rows = R.balasto.map((l) =>
      `<tr><td>${l.estrato}</td><td>${fmt(l.z_top, 1)}</td><td>${fmt(l.z_bot, 1)}</td>
       <td>${l.ks_h}</td><td>${fmt(l.k_lat_nodal, 0)}</td></tr>`).join('');
    parts.push(`<div class="card"><h3>Balasto</h3><div class="card-body">
      <table class="rtable"><thead><tr><th>Estrato</th><th>Z sup</th><th>Z inf</th><th>ks h</th><th>k nodal</th></tr></thead>
      <tbody>${rows}</tbody></table></div></div>`);
  }

  if (LAST.checks) parts.push(renderChecks(LAST.checks));

  root.innerHTML = parts.join('');
}

function card(title, rows) {
  const body = rows.map(([k, v, hi]) =>
    `<div class="kv ${hi ? 'hi' : ''}"><span>${k}</span><span>${v}</span></div>`).join('');
  return `<div class="card"><h3>${title}</h3><div class="card-body">${body}</div></div>`;
}

// La planilla se pide al servidor una vez hay solicitaciones: es el mismo
// cálculo que alimenta la lámina y la memoria, así que lo que se ve en pantalla
// y lo que se entrega al dibujante no pueden divergir.
let PLANILLA = null;

async function fetchPlanilla() {
  if (!(LAST && LAST.checks && LAST.checks.muro)) { PLANILLA = null; return; }
  try {
    const r = await post('/api/design/despiece', designBody());
    PLANILLA = await r.json();
    renderResults();
  } catch (err) {
    PLANILLA = null;
    toast('No se pudo calcular el despiece: ' + (err.message || err), 'bad', 6000);
  }
}

function tablaHTML(titulo, cabecera, filas, nota) {
  const th = cabecera.map((c) => `<th>${c}</th>`).join('');
  const tb = filas.map((f) => '<tr>' + f.map((c) => `<td>${c}</td>`).join('') + '</tr>').join('');
  return `<div class="card"><h3>${titulo}</h3><div class="card-body">
    <table class="rtable"><thead><tr>${th}</tr></thead><tbody>${tb}</tbody></table>
    ${nota ? `<div class="tnote">${nota}</div>` : ''}</div></div>`;
}

function renderVigaTabla(C) {
  const v = C.viga_cabezal || [];
  if (!v.length) return '';
  const env = new Map(((C.envolventes && C.envolventes.viga_cabezal) || [])
    .map((e) => [e.elemento, e]));
  const filas = v.slice().sort((a, b) => (a.y ?? 0) - (b.y ?? 0)).map((r) => {
    const e = env.get(r.elemento);
    const gob = e ? (e.M2.abs >= e.M3.abs ? e.M2.caso : e.M3.caso) : '—';
    return [
      r.elemento, fmt(r.y, 2), fmt(r.Mu, 0), fmt(r.Vu, 0), fmt(r.Tu, 0),
      `<span class="ratio ${ratioClass(r.ratio_M)}">${fmt(r.ratio_M, 2)}</span>`,
      `<span class="ratio ${ratioClass(r.ratio_V)}">${fmt(r.ratio_V, 2)}</span>`,
      `<span class="ratio ${ratioClass(r.ratio_VT)}">${fmt(r.ratio_VT, 2)}</span>`,
      `<span class="combo">${gob}</span>`,
    ];
  });
  return tablaHTML('Solicitaciones de la viga cabezal',
    ['Frame', 'Y', 'Mu<br>kN·m', 'Vu<br>kN', 'Tu<br>kN·m', 'D/C M', 'D/C V', 'D/C V+T', 'Gobierna'],
    filas,
    'Envolvente por elemento. «Gobierna» es la combinación que produce el momento máximo.');
}

function renderPilasResumen(C) {
  const f = C.pilas_resumen || [];
  if (!f.length) return '';
  // Una fila por pila, no por elemento: en un muro de altura variable las
  // pilas no son intercambiables y el maximo del grupo no describe a ninguna.
  const filas = f.map((r) => [
    `<b>${r.pila}</b>`, fmt(r.y, 2), `\u00d8${fmt(r.diametro, 2)}`,
    fmt(r.z_cabeza, 2), fmt(r.z_punta, 2), fmt(r.longitud, 2),
    fmt(r.Pu_max, 0), fmt(r.Mu_max, 0), fmt(r.Vu_max, 0),
    `<span class="ratio ${ratioClass(r.ratio_PM)}">${fmt(r.ratio_PM, 2)}</span>`,
    `<span class="ratio ${ratioClass(r.ratio_V)}">${fmt(r.ratio_V, 2)}</span>`,
    `<span class="combo">${(r.zonas || []).join(' + ')}</span>`,
  ]);
  return tablaHTML('Pilas, una por una',
    ['Pila', 'Y', '\u00d8', 'Cabeza<br>Z', 'Punta<br>Z', 'L<br>m', 'Pu<br>kN',
     'Mu<br>kN\u00b7m', 'Vu<br>kN', 'D/C P-M', 'D/C V', 'Zonas'],
    filas,
    'Cada pila con su geometr\u00eda y lo que gobierna su armado. Las zonas con sufijo __P\u2099 son propias de esa pila.');
}

function renderPilasTabla(C) {
  const p = (C.pilas || []).slice().sort((a, b) =>
    Math.max(b.ratio_PM, b.ratio_V) - Math.max(a.ratio_PM, a.ratio_V)).slice(0, 8);
  if (!p.length) return '';
  const env = new Map(((C.envolventes && C.envolventes.pilas) || [])
    .map((e) => [e.elemento, e]));
  const filas = p.map((r) => {
    const e = env.get(r.elemento);
    const gob = e ? (e.M2.abs >= e.M3.abs ? e.M2.caso : e.M3.caso) : '—';
    return [
      r.elemento, fmt(r.z, 1), r.seccion, fmt(r.Pu, 0), fmt(r.Mu, 0), fmt(r.phiMn, 0),
      `<span class="ratio ${ratioClass(r.ratio_PM)}">${fmt(r.ratio_PM, 2)}</span>`,
      fmt(r.Vu, 0),
      `<span class="ratio ${ratioClass(r.ratio_V)}">${fmt(r.ratio_V, 2)}</span>`,
      `<span class="combo">${gob}</span>`,
    ];
  });
  return tablaHTML('Pilas más solicitadas',
    ['Frame', 'Z', 'Sección', 'Pu<br>kN', 'Mu<br>kN·m', 'φMn', 'D/C P-M', 'Vu<br>kN', 'D/C V', 'Gobierna'],
    filas, 'Ocho elementos con mayor demanda/capacidad.');
}

function renderPlanilla() {
  if (!PLANILLA || !PLANILLA.marcas) return '';
  const out = [];
  const malas = PLANILLA.marcas_insuficientes || [];
  const ajust = PLANILLA.marcas_ajustadas || [];
  if (malas.length) {
    out.push(`<div class="msg msg-bad">${malas.length} marca(s) con menos acero del
      requerido: ${malas.join(', ')}. Revíselas en la pestaña <b>Refuerzo</b> antes
      de exportar.</div>`);
  }
  if (ajust.length) {
    out.push(`<div class="msg msg-warn">${ajust.length} marca(s) ajustadas a mano
      (${ajust.join(', ')}). El DXF, el PDF, el Excel y la memoria salen con el
      armado ajustado, no con el recomendado.</div>`);
  }
  const filas = PLANILLA.marcas.map((m) => [
    `<b>${m.marca}</b>`, m.elemento, m.posicion, m.diametro, m.forma,
    fmt(m.largo_m, 2), m.cantidad, fmt(m.peso_total_kg, 0),
  ]);
  out.push(tablaHTML('Despiece recomendado',
    ['Marca', 'Elemento', 'Posición', 'Ø', 'Forma', 'Largo m', 'Cant.', 'Peso kg'],
    filas, PLANILLA.nota));

  out.push(tablaHTML('Resumen por diámetro',
    ['Ø', 'db mm', 'Longitud m', 'Peso kg'],
    PLANILLA.por_diametro.map((d) => [d.diametro, fmt(d.db_mm, 1),
                                      fmt(d.largo_m, 0), fmt(d.peso_kg, 0)])));

  const porElem = Object.entries(PLANILLA.por_elemento)
    .map(([k, v]) => [k, fmt(v, 0) + ' kg']);
  out.push(card('Materiales', porElem.concat([
    ['Acero total', fmt(PLANILLA.peso_total_kg, 0) + ' kg', true],
    ['Concreto', fmt(PLANILLA.volumen_concreto_m3, 1) + ' m³'],
    ['Cuantía', fmt(PLANILLA.cuantia_kg_m3, 0) + ' kg/m³', true],
  ])));
  return out.join('');
}

function renderChecks(C) {
  const s = C.resumen || {};
  const out = [];
  const bad = s.elementos_no_conformes || 0;
  out.push(`<div class="msg ${bad ? 'msg-bad' : 'msg-ok'}">${
    bad ? `${bad} elemento(s) no cumplen la verificación.` : 'Todos los elementos verifican.'}</div>`);

  if (s.torsion_viga_significativa) {
    out.push(`<div class="msg msg-warn">La torsión en la viga cabezal supera el umbral de
      ACI 318 22.7: el refuerzo necesario está en la tarjeta de diseño por torsión.</div>`);
  }
  if (C.lecturas_fallidas && C.lecturas_fallidas.length) {
    out.push(`<div class="msg msg-warn">Lecturas de resultados con problemas:<br>${
      C.lecturas_fallidas.join('<br>')}</div>`);
  }

  out.push(card('Relaciones demanda/capacidad', [
    ['Pilas (P-M y cortante)', spanRatio(s.ratio_max_pilas)],
    ['Viga cabezal', spanRatio(s.ratio_max_viga)],
    ['Muro (cortante)', spanRatio(s.ratio_cortante_muro)],
  ]));

  if (C.muro && C.muro.horizontal) {
    out.push(card('Refuerzo del muro (diseñado)', [
      ['M11 máx', fmt(C.muro.M11_max, 1) + ' kN·m/m'],
      ['As horizontal', fmt(C.muro.horizontal.As, 0) + ' mm²/m'],
      ['&nbsp;&nbsp;gobierna', C.muro.horizontal.gobierna || '—'],
      ['M22 máx', fmt(C.muro.M22_max, 1) + ' kN·m/m'],
      ['As vertical', fmt(C.muro.vertical.As, 0) + ' mm²/m'],
      ['&nbsp;&nbsp;gobierna', C.muro.vertical.gobierna || '—'],
      ['D/C cortante', spanRatio(C.muro.cortante.ratio)],
      ['Pico nodal M22', fmt(C.muro.pico_M22, 0) + ' kN·m/m'],
    ]));
    if (!(C.muro.franjas && C.muro.franjas.franjas.length)) {
      out.push(`<div class="msg msg-warn">Los momentos son promedios por elemento. Los picos
        nodales sobre los apoyos son singularidades de malla —crecen al refinar— y no son
        solicitación de diseño.</div>`);
    }
  }

  if (C.muro && C.muro.franjas && C.muro.franjas.franjas.length) {
    const F = C.muro.franjas;
    const rows = F.franjas.map((f) => {
      const ok = f.vertical.ok && f.horizontal_apoyo.ok && f.horizontal_vano.ok && f.cortante.ok;
      return `<tr><td>${f.franja}</td>
        <td>${fmt(f.z_ini, 1)}–${fmt(f.z_fin, 1)}</td>
        <td>${fmt(f.M22_diseno, 1)}</td>
        <td>${fmt(f.vertical.As, 0)}</td>
        <td>${fmt(f.M11_cara, 1)}</td>
        <td>${fmt(f.horizontal_apoyo.As, 0)}</td>
        <td>${fmt(f.horizontal_vano.As, 0)}</td>
        <td class="ratio ${ratioClass(f.cortante.ratio)}">${fmt(f.cortante.ratio, 2)}</td>
        <td class="ratio ${ok ? 'ok' : 'bad'}">${ok ? 'SÍ' : 'NO'}</td></tr>`;
    }).join('');
    const red = [];
    if (F.reduccion_cara_vertical_pct) red.push(`vertical ${fmt(F.reduccion_cara_vertical_pct, 1)} %`);
    if (F.reduccion_cara_horizontal_pct) red.push(`horizontal ${fmt(F.reduccion_cara_horizontal_pct, 1)} %`);
    out.push(`<div class="card"><h3>Franjas de diseño de la pantalla</h3><div class="card-body">
      <table class="rtable"><thead><tr>
        <th>#</th><th>Z [m]</th><th>M22 dis.</th><th>As vert<br>mm²/m</th>
        <th>M11 cara</th><th>As h apoyo<br>mm²/m</th><th>As h vano<br>mm²/m</th>
        <th>D/C V</th><th>OK</th></tr></thead>
      <tbody>${rows}</tbody></table>
      <div class="kv"><span>Cara de la viga cabezal</span><span>z = ${fmt(F.z_cara_viga, 2)} m</span></div>
      <div class="kv"><span>Cara de la pila</span><span>± ${fmt(F.radio_pila, 2)} m del eje</span></div>
      ${red.length ? `<div class="kv"><span>Reducción por cara de apoyo</span><span>${red.join(' · ')}</span></div>` : ''}
      </div></div>`);
    out.push(`<div class="msg msg-ok">Cada franja se arma con su propia solicitación. El momento
      vertical de la franja inferior se toma en la cara de la viga cabezal y el horizontal en la
      cara de la pila (ACI 318 9.4.2.1); los valores en el eje quedan como referencia.</div>`);
  }

  if (C.torsion_viga) {
    const t = C.torsion_viga;
    out.push(card('Diseño por torsión de la viga cabezal (ACI 318 22.7)', [
      ['Tu (elemento ' + t.elemento_critico + ')', fmt(t.Tu, 1) + ' kN·m', true],
      ['Umbral 22.7.4', fmt(t.T_umbral, 1) + ' kN·m'],
      ['Tcr de agrietamiento', fmt(t.T_cr, 1) + ' kN·m'],
      ['D/C límite de sección V+T', spanRatio(t.ratio_VT)],
      ['At/s por torsión (una rama)', fmt(t.At_s, 0) + ' mm²/m'],
      ['(Av+2At)/s total', fmt(t.Avt_s, 0) + ' mm²/m', true],
      ['Estribo cerrado', `${t.estribo} @ ${fmt(t.s_estribo, 0)} mm`, true],
      ['&nbsp;&nbsp;separación máxima', fmt(t.s_max, 0) + ' mm'],
      ['Al longitudinal por torsión', fmt(t.Al, 0) + ' mm²'],
      ['Barras en el perímetro', `${t.n_barras_torsion} × ${t.barra_torsion}`, true],
      ['Elementos afectados', String(t.n_elementos)],
    ]));
    if (!t.seccion_ok) {
      out.push(`<div class="msg msg-bad">La sección de la viga cabezal no admite la combinación
        de cortante y torsión (ACI 318 22.7.7.1): amplíe el ancho o el canto.</div>`);
    }
  }

  out.push(renderVigaTabla(C));

  if (C.comparacion_torsion) {
    const c = C.comparacion_torsion;
    out.push(card('Contraste con el diseño de SAP2000', [
      ['Código', c.codigo_sap || '—'],
      ['Al propio / SAP', `${fmt(c.Al_propio, 0)} / ${fmt(c.Al_sap, 0)} mm²`],
      ['&nbsp;&nbsp;diferencia', c.dif_Al_pct == null ? '—' : fmt(c.dif_Al_pct, 1) + ' %'],
      ['At/s propio / SAP', `${fmt(c.At_s_propio, 0)} / ${fmt(c.At_s_sap, 0)} mm²/m`],
      ['&nbsp;&nbsp;diferencia', c.dif_At_s_pct == null ? '—' : fmt(c.dif_At_s_pct, 1) + ' %'],
    ]));
  }

  if (C.modal && C.modal.modos && C.modal.modos.length) {
    const M = C.modal;
    const rows = M.modos.slice(0, 12).map((m) =>
      `<tr><td>${m.modo}</td><td>${fmt(m.T, 3)}</td><td>${fmt(m.f, 2)}</td>
       <td>${fmt(m.Ux, 3)}</td><td>${fmt(m.Uy, 3)}</td>
       <td>${fmt(m.SumUx, 3)}</td><td>${fmt(m.SumUy, 3)}</td></tr>`).join('');
    out.push(`<div class="card"><h3>Análisis modal</h3><div class="card-body">
      <div class="kv hi"><span>T₁</span><span>${fmt(M.T1, 3)} s</span></div>
      <div class="kv"><span>Modo dominante en X</span><span>#${M.modo_dominante_X} · T = ${fmt(M.T_dominante_X, 3)} s</span></div>
      <div class="kv"><span>Masa acumulada X / Y</span><span>${fmt(M.masa_acumulada_X, 3)} / ${fmt(M.masa_acumulada_Y, 3)}</span></div>
      <table class="rtable"><thead><tr><th>Modo</th><th>T [s]</th><th>f [Hz]</th>
        <th>Ux</th><th>Uy</th><th>ΣUx</th><th>ΣUy</th></tr></thead>
      <tbody>${rows}</tbody></table></div></div>`);
    if (M.masa_acumulada_X < 0.9 && M.masa_acumulada_Y < 0.9) {
      out.push(`<div class="msg msg-warn">La masa acumulada no llega a 0.90 en ninguna dirección:
        amplíe el número de modos.</div>`);
    }
  }


  const plan = renderPlanilla();
  if (plan) {
    out.push(plan);
    if (C.despiece) {
      out.push(`<div class="msg msg-ok">Lámina y memoria escritas en <code>salidas/</code>:
        DXF, PDF, SVG y Word. Los botones de la barra superior descargan una copia.</div>`);
    }
  } else if (C.muro) {
    out.push(`<div class="msg msg-warn">Calculando el despiece…</div>`);
  }
  if (C.despiece_error) {
    out.push(`<div class="msg msg-warn">El despiece no se pudo generar:
      ${C.despiece_error}</div>`);
  }

  if (C.reaccion_vertical) {
    out.push(card('Reacción vertical por combinación',
      Object.entries(C.reaccion_vertical).map(([k, v]) => [k, fmt(v, 0) + ' kN'])));
  }

  if (C.section_cuts && C.section_cuts.length) {
    const rows = C.section_cuts.map((r) =>
      `<tr><td>${r.cut.replace('CUT_', '')}</td><td>${r.case}</td>
       <td>${fmt(r.F1, 0)}</td><td>${fmt(r.F3, 0)}</td><td>${fmt(r.M2, 0)}</td></tr>`).join('');
    out.push(`<div class="card"><h3>Cortes de sección</h3><div class="card-body">
      <table class="rtable"><thead><tr><th>Corte</th><th>Caso</th><th>F1 kN</th><th>F3 kN</th><th>M2 kN·m</th></tr></thead>
      <tbody>${rows}</tbody></table></div></div>`);
  }

  out.push(renderPilasResumen(C));
  out.push(renderPilasTabla(C));
  return out.join('');
}

function spanRatio(r) {
  return r == null ? '—' : `<span class="ratio ${ratioClass(r)}">${fmt(r, 2)}</span>`;
}

// ============================================================== API =====
let pending = null;
function onChange() {
  $('#hint-ztop') && ($('#hint-ztop').textContent = fmt(P.wall.z_top));
  drawElevation();
  clearTimeout(pending);
  pending = setTimeout(refresh, 450);
}

async function post(url, body) {
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = j.detail ?? msg; } catch (_) {}
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  return r;
}

async function refresh() {
  try {
    const r = await post('/api/preview', P);
    LAST = await r.json();
    renderResults();
    draw3D();
    drawPressures();
    drawDesign();
  } catch (err) {
    toast(String(err.message || err), 'bad', 6000);
  }
}

async function download(url, fallbackName, body) {
  // No se bloquea la exportación: si el ingeniero decide sacar planos con un
  // armado corto, es su decisión; lo que no puede pasar es que no se entere.
  const malas = (PLANILLA && PLANILLA.marcas_insuficientes) || [];
  if (malas.length && /despiece|memoria/.test(url)) {
    toast(`Atención: ${malas.length} marca(s) por debajo de lo requerido `
          + `(${malas.join(', ')}). Se exporta igualmente.`, 'bad', 8000);
  }
  try {
    const r = await post(url, body === undefined ? P : body);
    const blob = await r.blob();
    const cd = r.headers.get('Content-Disposition') || '';
    const m = cd.match(/filename="?([^"]+)"?/);
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = m ? m[1] : fallbackName;
    a.click();
    URL.revokeObjectURL(a.href);
    toast('Archivo generado: ' + a.download, 'ok');
  } catch (err) {
    toast(String(err.message || err), 'bad', 6000);
  }
}

// El despiece y la memoria salen de las solicitaciones reales, asi que solo
// tienen sentido despues de correr el analisis.
function designBody() {
  return { project: P, checks: (LAST && LAST.checks) || null };
}

function updateDesignButtons() {
  const listo = !!(LAST && LAST.checks && LAST.checks.muro);
  for (const id of ['#btn-dxf', '#btn-pdf']) {
    const b = $(id);
    if (!b) continue;
    b.disabled = !listo;
    b.classList.toggle('btn-dis', !listo);
    b.title = listo ? 'Lámina de despiece a partir de las solicitaciones del modelo'
                    : 'Primero pulse «Correr y verificar» para tener solicitaciones';
  }
  const mem = $('#btn-memoria');
  if (mem) {
    mem.disabled = false;
    mem.classList.toggle('btn-dis', !listo);
    mem.title = listo ? 'Memoria completa con verificaciones y despiece'
                      : 'Memoria con datos de partida y empujes; corra el modelo para incluir las verificaciones';
  }
}

async function sendToSap(run) {
  const btn = run ? $('#btn-sap-run') : $('#btn-sap');
  const prev = btn.textContent;
  btn.disabled = true;
  btn.textContent = run ? 'Analizando…' : 'Abriendo SAP…';
  try {
    const r = await post('/api/sap/build', { project: P, filename: P.info.name, run, attach: true });
    const j = await r.json();
    const ch = j.checks ? Object.assign({}, j.checks) : null;
    if (ch && j.despiece) ch.despiece = j.despiece;
    if (ch && j.despiece_error) ch.despiece_error = j.despiece_error;
    LAST = { report: j.report, warnings: j.warnings, geometry: LAST ? LAST.geometry : null, checks: ch };
    if (!LAST.geometry) await refresh(); else renderResults();
    updateDesignButtons();
    drawDesign();
    fetchPlanilla();
    loadRefuerzo();
    toast(j.message, 'ok', 7000);
  } catch (err) {
    toast(String(err.message || err), 'bad', 9000);
  } finally {
    btn.disabled = false;
    btn.textContent = prev;
  }
}

// ============================================================= arranque =
async function init() {
  initTheme();
  initPaneles();
  P = await (await fetch('/api/defaults')).json();
  renderForm();
  setupElevation();
  setup3D();

  $('#btn-preview').addEventListener('click', refresh);
  $('#btn-s2k').addEventListener('click', () => download('/api/export/s2k', 'modelo.s2k'));
  // El Excel va con los resultados si ya se corrio el modelo, igual que el Word
  $('#btn-excel').addEventListener('click',
    () => download('/api/export/excel', 'memoria.xlsx', designBody()));
  $('#btn-json').addEventListener('click', () => download('/api/export/json', 'proyecto.json'));
  $$('#view-refuerzo .tab-r').forEach((b) => b.addEventListener('click', () => {
    $$('#view-refuerzo .tab-r').forEach((x) => x.classList.remove('active'));
    b.classList.add('active');
    refuerzo.vista = b.dataset.vista;
    loadRefuerzo();
  }));

  $$('#view-diseno .tab-d').forEach((b) => b.addEventListener('click', () => {
    $$('#view-diseno .tab-d').forEach((x) => x.classList.remove('active'));
    b.classList.add('active');
    design.mode = b.dataset.mode;
    $('#hint-diseno').textContent = {
      pm: 'Curva de capacidad de cada zona de refuerzo frente a la demanda de cada pila.',
      viga: 'Envolvente de momento, cortante y torsión a lo largo de la viga cabezal.',
      muro: 'Solicitación promediada por shell, con las franjas de diseño superpuestas.',
    }[design.mode] || '';
    drawDesign();
  }));
  $('#sel-muro-comp').addEventListener('change', (e) => {
    design.comp = e.target.value;
    drawDesign();
  });

  $('#btn-dxf').addEventListener('click',
    () => download('/api/export/despiece.dxf', 'despiece.dxf', designBody()));
  $('#btn-pdf').addEventListener('click',
    () => download('/api/export/despiece.pdf', 'despiece.pdf', designBody()));
  $('#btn-memoria').addEventListener('click',
    () => download('/api/export/memoria', 'memoria.docx', designBody()));
  updateDesignButtons();
  $('#btn-sap').addEventListener('click', () => sendToSap(false));
  $('#btn-sap-run').addEventListener('click', () => sendToSap(true));

  $('#file-json').addEventListener('change', async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    try {
      P = JSON.parse(await f.text());
      renderForm(); onChange();
      toast('Datos cargados desde ' + f.name, 'ok');
    } catch (err) { toast('El archivo no es un proyecto válido.', 'bad'); }
    e.target.value = '';
  });

  $$('#view-tabs .tab').forEach((t) => t.addEventListener('click', () => {
    $$('#view-tabs .tab').forEach((x) => x.classList.remove('active'));
    $$('.view').forEach((v) => v.classList.remove('active'));
    t.classList.add('active');
    $('#view-' + t.dataset.view).classList.add('active');
    requestAnimationFrame(redrawAll);
    if (t.dataset.view === 'refuerzo' && !refuerzo.data) loadRefuerzo();
  }));

  window.addEventListener('resize', redrawAll);

  $('#btn-theme').addEventListener('click',
    () => applyTheme(currentTheme() === 'light' ? 'dark' : 'light'));

  $('#btn-panel-izq').addEventListener('click', () => togglePanel('izq'));
  $('#btn-panel-der').addEventListener('click', () => togglePanel('der'));
  $('#btn-panel-ambos').addEventListener('click', () => togglePanel('ambos'));
  window.addEventListener('keydown', (e) => {
    if (!e.altKey || e.ctrlKey || e.metaKey) return;
    const cual = { '1': 'izq', '2': 'der', '0': 'ambos' }[e.key];
    if (!cual) return;
    e.preventDefault();
    togglePanel(cual);
  });
  // Si el usuario nunca eligio, seguimos al sistema cuando cambie
  if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', (e) => {
      let guardado = null;
      try { guardado = localStorage.getItem('muros-theme'); } catch (_) {}
      if (guardado !== 'light' && guardado !== 'dark') applyTheme(e.matches ? 'light' : 'dark');
    });
  }

  const st = await (await fetch('/api/sap/status')).json();
  SAP_OK = st.available;
  if (!SAP_OK) {
    $('#btn-sap').disabled = true;
    $('#btn-sap-run').disabled = true;
    $('#btn-sap').title = $('#btn-sap-run').title = st.message;
    $('#subtitle').textContent = 'Generación paramétrica de modelos SAP2000 — ' + st.message;
  }

  drawElevation();
  await refresh();
}

init();
