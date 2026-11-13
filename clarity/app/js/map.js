import { h, sv, api, chip, toast, clear, modal, confirmBox, promptBox, field, trunc, KINDS } from './util.js';
import { S, commit, nodes, root, kids, byId } from './state.js';
import { blank, addProposal, descendants, isDesc, isLocked, moveNode, deleteNode, mergeNodes, splitNode, ensureRoot, nid } from './maptools.js';
import { ensureScope } from './scope.js';
import { go } from './main.js';

const NW = 214, NH = 52, GX = 64, GY = 14;
const ui = { view: 'map', sel: [], tx: 40, ty: 40, k: 1, tab: 'inspector', sugg: [], fit: true };
const kcss = (n) => `var(--k-${n.kind || 'theme'})`;
let rerender = () => {};

export async function render(rootEl) {
  const p = S.project;
  const page = h('div', { class: 'page wide' });
  rootEl.append(page);
  rerender = () => { clear(page); build(page); };
  ui.fit = true;
  build(page);
}

function build(page) {
  const p = S.project;
  page.append(h('div', { class: 'row between' }, h('div', {}, h('h1', { style: { marginBottom: 2 } }, 'Organise the thinking'), h('p', { class: 'muted', style: { margin: 0 } }, 'Drag to regroup. Tab adds a child, Enter adds a sibling, Delete removes. AI suggestions stay dashed until you accept them.')),
    h('div', { class: 'row' }, h('button', { class: 'btn primary', onclick: () => go('story') }, 'Next: storyline'))));
  if (!root()) {
    const t = h('input', { type: 'text', placeholder: 'The central message', value: p.governing || '' });
    page.append(h('div', { class: 'card stack' }, h('h3', {}, 'Start the map'), h('p', { class: 'muted' }, 'The centre of the map is your main message. Everything else supports it.'), t,
      h('div', { class: 'row' }, h('button', { class: 'btn primary', onclick: () => { ensureRoot(t.value || p.governing || 'Main message'); if (!p.governing) p.governing = t.value; commit('map'); rerender(); } }, 'Create the map'),
        h('button', { class: 'btn', onclick: () => go('brief') }, 'Capture thoughts first'), h('button', { class: 'btn', onclick: () => proposeFromSources() }, 'Build from my sources'))));
    return;
  }
  const bar = h('div', { class: 'row between', style: { marginBottom: 10 } },
    h('div', { class: 'row' }, h('div', { class: 'seg' }, ['map', 'outline', 'cards'].map((v) => h('button', { 'aria-pressed': ui.view === v, onclick: () => { ui.view = v; rerender(); } }, { map: 'Mind map', outline: 'Outline', cards: 'Cards by type' }[v]))),
      h('button', { class: 'btn sm', onclick: () => proposeFromSources() }, 'Build from sources'), h('button', { class: 'btn sm', onclick: healthCheck }, 'Health check'),
      h('button', { class: 'btn sm', onclick: compare }, 'Compare alternatives'), h('button', { class: 'btn sm', onclick: acceptAll, disabled: !nodes().some((n) => n.ai) }, 'Accept all AI suggestions')),
    h('div', { class: 'legend' }, Object.entries(KINDS).map(([k, l]) => h('span', {}, h('i', { style: { background: `var(--k-${k})` } }), l)), h('span', {}, h('i', { style: { border: '1.5px dashed var(--muted)', background: 'transparent' } }), 'AI suggestion')));
  page.append(bar);
  const wrap = h('div', { class: 'mapwrap' });
  const main = h('div', { class: 'canvas', style: ui.view === 'map' ? {} : { overflow: 'auto', background: 'var(--panel)', backgroundImage: 'none' } });
  const insp = h('div', { class: 'inspector' });
  wrap.append(main, insp); page.append(wrap);
  if (ui.view === 'map') drawMap(main); else if (ui.view === 'outline') drawOutline(main); else drawCards(main);
  drawSide(insp);
}

const primary = () => byId(ui.sel[ui.sel.length - 1]);
function select(id, add = false) { ui.sel = add ? (ui.sel.includes(id) ? ui.sel.filter((x) => x !== id) : [...ui.sel, id]) : [id]; }
const touch = (label) => { commit(label); };
function addChild(parentId, text = 'New point') { const n = blank(parentId, text); const par = byId(parentId); if (par) par.collapsed = false; nodes().push(n); touch('map'); ui.sel = [n.id]; return n; }
function addSibling(id) { const n = byId(id); if (!n || !n.parent) return addChild(id); const c = blank(n.parent, 'New point'); const list = nodes(); const last = [n, ...descendants(n.id)].map((x) => list.indexOf(x)).reduce((a, b) => Math.max(a, b)); list.splice(last + 1, 0, c); touch('map'); ui.sel = [c.id]; return c; }

// ------------------------------------------------------------------ mind map canvas
function layout() {
  const pos = {}; let y = 0;
  const walk = (n, d) => {
    const ks = n.collapsed ? [] : kids(n.id);
    if (!ks.length) { pos[n.id] = { x: d * (NW + GX), y }; const m = y + NH / 2; y += NH + GY; return m; }
    const cs = ks.map((k) => walk(k, d + 1)); const mid = (cs[0] + cs[cs.length - 1]) / 2; pos[n.id] = { x: d * (NW + GX), y: mid - NH / 2 }; return mid;
  };
  walk(root(), 0); return pos;
}
const wrapText = (t, n = 27) => { const w = t.split(/\s+/), out = []; let cur = ''; for (const x of w) { if ((cur + ' ' + x).trim().length > n && cur) { out.push(cur); cur = x; } else cur = (cur + ' ' + x).trim(); } if (cur) out.push(cur); return out.length > 2 ? [out[0], trunc(out.slice(1).join(' '), n)] : out; };

function drawMap(box) {
  let pos = layout();
  const svg = sv('svg', { tabindex: 0, role: 'application', 'aria-label': 'Mind map. Use arrow keys to move, Tab to add a child, Enter to add a sibling.' });
  const vp = sv('g'); svg.append(vp);
  const apply = () => vp.setAttribute('transform', `translate(${ui.tx} ${ui.ty}) scale(${ui.k})`);
  const edgeG = sv('g'), nodeG = sv('g'), dropLine = sv('line', { stroke: 'var(--accent)', 'stroke-width': 4, 'stroke-linecap': 'round', visibility: 'hidden' });
  vp.append(edgeG, nodeG, dropLine);
  const edge = (a, b, dashed, label) => { const x1 = a.x + NW, y1 = a.y + NH / 2, x2 = b.x, y2 = b.y + NH / 2, mx = (x1 + x2) / 2;
    const el = sv('path', { d: `M${x1} ${y1} C${mx} ${y1} ${mx} ${y2} ${x2} ${y2}`, fill: 'none', 'stroke-width': 1.6 }); el.style.stroke = 'var(--line)'; if (dashed) { el.setAttribute('stroke-dasharray', '5 4'); el.style.stroke = 'var(--muted)'; } return el; };
  const nodesHere = nodes().filter((n) => pos[n.id]);
  for (const n of nodesHere) {
    if (n.parent && pos[n.parent]) edgeG.append(edge(pos[n.parent], pos[n.id]));
    for (const r of n.rel || []) if (pos[r.to]) { const a = pos[n.id], b = pos[r.to]; const el = sv('path', { d: `M${a.x + NW / 2} ${a.y + NH} Q${(a.x + b.x) / 2 + NW / 2} ${(a.y + b.y) / 2 + NH + 40} ${b.x + NW / 2} ${b.y + NH}`, fill: 'none', 'stroke-width': 1.5, 'stroke-dasharray': '2 4' }); el.style.stroke = 'var(--k-implication)'; edgeG.append(el); }
  }
  for (const n of nodesHere) {
    const { x, y } = pos[n.id]; const sel = ui.sel.includes(n.id);
    const g = sv('g', { class: 'node' + (sel ? ' sel' : ''), transform: `translate(${x} ${y})`, 'data-id': n.id, tabindex: -1, role: 'button', 'aria-label': `${KINDS[n.kind || 'theme']}: ${n.text}` });
    const r = sv('rect', { width: NW, height: NH, rx: 10 }); r.style.fill = 'var(--panel)'; r.style.stroke = sel ? 'var(--accent)' : kcss(n); if (n.ai) r.setAttribute('stroke-dasharray', '6 4');
    const bar = sv('rect', { width: 7, height: NH, rx: 3 }); bar.style.fill = kcss(n);
    g.append(r, bar);
    wrapText(n.text).forEach((l, i, a) => { const t = sv('text', { x: 16, y: (a.length === 1 ? NH / 2 + 4 : 21 + i * 16), }, l); t.style.fill = 'var(--ink)'; if (!n.parent) t.style.fontWeight = 700; g.append(t); });
    let bx = NW - 8;
    const badge = (txt, color) => { const w = 12 + txt.length * 6; bx -= w + 3; const gr = sv('g', { transform: `translate(${bx} -9)` }); const rr = sv('rect', { width: w, height: 16, rx: 8 }); rr.style.fill = color; const tt = sv('text', { x: w / 2, y: 12, 'text-anchor': 'middle' }, txt); tt.style.fill = '#fff'; tt.style.fontSize = '10px'; gr.append(rr, tt); g.append(gr); };
    if (n.locked) badge('locked', 'var(--muted)'); if (n.ai) badge('AI', 'var(--k-insight)'); if (n.votes) badge(`${n.votes} votes`, 'var(--k-action)');
    if (n.status === 'approved') badge('approved', 'var(--ok)'); if (n.kind === 'evidence' && !(n.src || []).length) badge('no source', 'var(--k-risk)');
    if (n.weight) { for (let i = 0; i < n.weight; i++) { const d = sv('circle', { cx: 16 + i * 9, cy: NH - 7, r: 3 }); d.style.fill = 'var(--warn)'; g.append(d); } }
    const ks = kids(n.id);
    if (ks.length) { const tg = sv('g', { class: 'tog', transform: `translate(${NW + 2} ${NH / 2})` }); const c = sv('circle', { r: 9 }); c.style.fill = 'var(--panel)'; c.style.stroke = 'var(--line)'; const tt = sv('text', { 'text-anchor': 'middle', y: 4 }, n.collapsed ? String(descendants(n.id).length) : '–'); tt.style.fontSize = '10px'; tt.style.fill = 'var(--ink)'; tg.append(c, tt);
      tg.addEventListener('pointerdown', (e) => e.stopPropagation()); tg.addEventListener('click', (e) => { e.stopPropagation(); n.collapsed = !n.collapsed; commit('collapse'); rerender(); }); g.append(tg); }
    nodeG.append(g);
  }
  apply(); box.append(svg);
  box.append(h('div', { class: 'row', style: { position: 'absolute', right: 10, bottom: 10, gap: 4 } },
    h('button', { class: 'btn sm', 'aria-label': 'Zoom in', onclick: () => { ui.k = Math.min(2.2, ui.k * 1.2); apply(); } }, '+'), h('button', { class: 'btn sm', 'aria-label': 'Zoom out', onclick: () => { ui.k = Math.max(.3, ui.k / 1.2); apply(); } }, '−'),
    h('button', { class: 'btn sm', onclick: fit }, 'Fit'), h('button', { class: 'btn sm', onclick: () => { nodes().forEach((n) => { if (n.parent) n.collapsed = false; }); rerender(); } }, 'Expand all'),
    h('button', { class: 'btn sm', onclick: () => { kids(root().id).forEach((n) => { n.collapsed = true; }); rerender(); } }, 'Collapse')));
  function fit() { const xs = Object.values(pos); if (!xs.length) return; const maxX = Math.max(...xs.map((p) => p.x)) + NW + 40, maxY = Math.max(...xs.map((p) => p.y)) + NH + 40; const r = box.getBoundingClientRect(); ui.k = Math.min(1.1, r.width / maxX, r.height / maxY); ui.tx = 20; ui.ty = Math.max(20, (r.height - maxY * ui.k) / 2); apply(); }
  if (ui.fit) { ui.fit = false; requestAnimationFrame(fit); }
  const world = (e) => { const r = svg.getBoundingClientRect(); return { x: (e.clientX - r.left - ui.tx) / ui.k, y: (e.clientY - r.top - ui.ty) / ui.k }; };
  const hit = (w, skip) => nodesHere.find((n) => n.id !== skip && w.x >= pos[n.id].x && w.x <= pos[n.id].x + NW && w.y >= pos[n.id].y - 6 && w.y <= pos[n.id].y + NH + 6);
  let mode = null, start = null, dragId = null, tgt = null, zone = 'child';
  svg.addEventListener('pointerdown', (e) => {
    const g = e.target.closest('.node'); svg.focus(); svg.setPointerCapture(e.pointerId);
    start = { x: e.clientX, y: e.clientY, tx: ui.tx, ty: ui.ty, moved: false };
    if (g) { dragId = g.dataset.id; mode = 'node'; } else { mode = 'pan'; }
  });
  svg.addEventListener('pointermove', (e) => {
    if (!mode) return; const dx = e.clientX - start.x, dy = e.clientY - start.y;
    if (!start.moved && Math.hypot(dx, dy) < 5) return; start.moved = true;
    if (mode === 'pan') { ui.tx = start.tx + dx; ui.ty = start.ty + dy; svg.classList.add('pan'); apply(); return; }
    const w = world(e); const t = hit(w, dragId);
    nodeG.querySelectorAll('.drop').forEach((x) => x.classList.remove('drop')); dropLine.setAttribute('visibility', 'hidden'); tgt = null;
    if (t) { const rel = (w.y - pos[t.id].y) / NH; zone = t.parent && rel < .25 ? 'before' : t.parent && rel > .75 ? 'after' : 'child'; tgt = t;
      if (zone === 'child') nodeG.querySelector(`[data-id="${t.id}"]`).classList.add('drop');
      else { const yy = pos[t.id].y + (zone === 'before' ? -5 : NH + 5); dropLine.setAttribute('x1', pos[t.id].x); dropLine.setAttribute('x2', pos[t.id].x + NW); dropLine.setAttribute('y1', yy); dropLine.setAttribute('y2', yy); dropLine.setAttribute('visibility', 'visible'); } }
  });
  svg.addEventListener('pointerup', (e) => {
    svg.classList.remove('pan');
    if (mode === 'node') {
      if (!start.moved) { select(dragId, e.shiftKey || e.ctrlKey || e.metaKey); rerender(); }
      else if (tgt) { let ok; if (zone === 'child') ok = moveNode(dragId, tgt.id, null); else { const sibs = kids(tgt.parent).filter((k) => k.id !== dragId); const i = sibs.findIndex((k) => k.id === tgt.id); ok = moveNode(dragId, tgt.parent, zone === 'before' ? i : i + 1); } if (ok) { tgt.collapsed = false; touch('move'); } rerender(); }
      else rerender();
    } else if (mode === 'pan' && !start.moved) { ui.sel = []; rerender(); }
    mode = null; tgt = null;
  });
  svg.addEventListener('dblclick', (e) => { const g = e.target.closest('.node'); if (g) inlineEdit(g.dataset.id, box, pos); });
  svg.addEventListener('wheel', (e) => { e.preventDefault(); const r = svg.getBoundingClientRect(); const f = e.deltaY < 0 ? 1.1 : 1 / 1.1; const nk = Math.min(2.2, Math.max(.3, ui.k * f)); const mx = e.clientX - r.left, my = e.clientY - r.top; ui.tx = mx - (mx - ui.tx) * (nk / ui.k); ui.ty = my - (my - ui.ty) * (nk / ui.k); ui.k = nk; apply(); }, { passive: false });
  svg.addEventListener('keydown', (e) => {
    const n = primary(); if (!n || e.target !== svg) return; const key = e.key;
    if (key === 'Tab') { e.preventDefault(); if (isLocked(n.id)) return toast('Locked.', 'bad'); addChild(n.id); ui.fit = false; rerender(); const m = primary(); requestAnimationFrame(() => inlineEdit(m.id, box, layout())); }
    else if (key === 'Enter') { e.preventDefault(); if (isLocked(n.id)) return toast('Locked.', 'bad'); const m = addSibling(n.id); rerender(); requestAnimationFrame(() => inlineEdit(m.id, box, layout())); }
    else if (key === 'Delete' || key === 'Backspace') { e.preventDefault(); const ids = [...ui.sel]; let ok = false; ids.forEach((i) => { if (byId(i)) ok = deleteNode(i) || ok; }); if (ok) { ui.sel = []; touch('delete'); rerender(); } }
    else if (key === 'F2') { e.preventDefault(); inlineEdit(n.id, box, pos); }
    else if (key === ' ') { e.preventDefault(); n.collapsed = !n.collapsed; commit('collapse'); rerender(); }
    else if (e.altKey && (key === 'ArrowUp' || key === 'ArrowDown')) { e.preventDefault(); shift(n, key === 'ArrowUp' ? -1 : 1); }
    else if (key.startsWith('Arrow')) { e.preventDefault(); const ks = kids(n.id); let t = null; const sibs = n.parent ? kids(n.parent) : []; const i = sibs.indexOf(n);
      if (key === 'ArrowLeft') t = byId(n.parent); else if (key === 'ArrowRight') t = n.collapsed ? null : ks[0]; else if (key === 'ArrowUp') t = sibs[i - 1]; else t = sibs[i + 1];
      if (t) { select(t.id); rerender(); } }
  });
  svg.addEventListener('focus', () => { if (!ui.sel.length) ui.sel = [root().id]; });
}
function shift(n, d) { if (!n.parent || isLocked(n.id)) return; const sibs = kids(n.parent); const i = sibs.indexOf(n); const j = i + d; if (j < 0 || j >= sibs.length) return; moveNode(n.id, n.parent, d < 0 ? j : j + 1); touch('move'); rerender(); }
function inlineEdit(id, box, pos) {
  const n = byId(id); if (!n) return; if (isLocked(id)) return toast('This section is locked.', 'bad');
  const p = pos[id]; if (!p) return; const svg = box.querySelector('svg'); const r = svg.getBoundingClientRect(), br = box.getBoundingClientRect();
  const inp = h('input', { type: 'text', value: n.text, 'aria-label': 'Edit text', style: { position: 'absolute', left: (r.left - br.left + ui.tx + p.x * ui.k) + 'px', top: (r.top - br.top + ui.ty + p.y * ui.k) + 'px', width: Math.max(180, NW * ui.k) + 'px', height: NH * ui.k + 'px', zIndex: 5, fontSize: 13 * ui.k + 'px' } });
  let done = false; const finish = (save) => { if (done) return; done = true; if (save && inp.value.trim()) { n.text = inp.value.trim(); n.ai = false; touch('edit'); } inp.remove(); rerender(); };
  inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') finish(true); else if (e.key === 'Escape') finish(false); else if (e.key === 'Tab') { e.preventDefault(); finish(true); } });
  inp.addEventListener('blur', () => finish(true)); box.append(inp); inp.focus(); inp.select();
}

// ------------------------------------------------------------------ outline view (drag, indent, reorder)
function drawOutline(box) {
  box.style.padding = '12px';
  let dragId = null;
  const item = (n, d) => {
    const li = h('li', {}, null);
    const row = h('div', { class: 'it kcolor-' + (n.kind || 'theme') + (ui.sel.includes(n.id) ? ' sel' : ''), draggable: !!n.parent, onclick: (e) => { if (e.target.tagName !== 'INPUT') { select(n.id, e.shiftKey); rerender(); } },
      ondragstart: (e) => { dragId = n.id; e.dataTransfer.setData('text/plain', n.id); e.dataTransfer.effectAllowed = 'move'; },
      ondragover: (e) => { e.preventDefault(); row.classList.add('drop'); }, ondragleave: () => row.classList.remove('drop'),
      ondrop: (e) => { e.preventDefault(); row.classList.remove('drop'); const rel = e.offsetY / row.offsetHeight; if (!dragId || dragId === n.id) return; let ok;
        if (n.parent && rel < .3) { const sibs = kids(n.parent).filter((k) => k.id !== dragId); ok = moveNode(dragId, n.parent, sibs.findIndex((k) => k.id === n.id)); }
        else if (n.parent && rel > .7) { const sibs = kids(n.parent).filter((k) => k.id !== dragId); ok = moveNode(dragId, n.parent, sibs.findIndex((k) => k.id === n.id) + 1); } else ok = moveNode(dragId, n.id, null);
        if (ok) { touch('move'); rerender(); } } },
      h('span', { class: 'muted', title: 'Drag to move' }, n.parent ? '⋮⋮' : '◆'), kids(n.id).length ? h('button', { class: 'btn sm ghost', 'aria-label': 'Collapse', onclick: (e) => { e.stopPropagation(); n.collapsed = !n.collapsed; commit('collapse'); rerender(); } }, n.collapsed ? '▸' : '▾') : h('span', { style: { width: 28 } }),
      h('i', { class: 'dot' }),
      h('input', { type: 'text', value: n.text, style: { flex: 1, fontWeight: n.parent ? 400 : 700, fontStyle: n.ai ? 'italic' : 'normal' }, 'aria-label': 'Point text', disabled: isLocked(n.id), oninput: (e) => { n.text = e.target.value.slice(0, 300); n.ai = false; commit('edit'); }, onfocus: () => { ui.sel = [n.id]; },
        onkeydown: (e) => { if (e.key === 'Enter') { e.preventDefault(); const m = addSibling(n.id); rerender(); focusNode(m.id); } else if (e.key === 'Tab') { e.preventDefault(); if (e.shiftKey) outdent(n); else indent(n); } } }),
      n.ai ? chip('AI', 'dashed') : null, n.locked ? chip('locked') : null, n.votes ? chip(n.votes + ' votes', 'ok') : null,
      n.parent ? h('span', { class: 'row', style: { gap: 2 } }, h('button', { class: 'btn sm ghost', title: 'Indent', onclick: (e) => { e.stopPropagation(); indent(n); } }, '→'), h('button', { class: 'btn sm ghost', title: 'Outdent', onclick: (e) => { e.stopPropagation(); outdent(n); } }, '←'),
        h('button', { class: 'btn sm ghost', title: 'Up', onclick: (e) => { e.stopPropagation(); shift(n, -1); } }, '↑'), h('button', { class: 'btn sm ghost', title: 'Down', onclick: (e) => { e.stopPropagation(); shift(n, 1); } }, '↓')) : null,
      h('button', { class: 'btn sm ghost', title: 'Add child', onclick: (e) => { e.stopPropagation(); const m = addChild(n.id); rerender(); focusNode(m.id); } }, '+'));
    li.append(row);
    if (!n.collapsed && kids(n.id).length) li.append(h('ul', { class: 'otl ol' }, kids(n.id).map((k) => item(k, d + 1))));
    return li;
  };
  box.append(h('ul', { class: 'otl' }, item(root(), 0)));
}
const focusNode = (id) => requestAnimationFrame(() => { const el = document.querySelector('.otl .it.sel input'); if (el) { el.focus(); el.select(); } });
function indent(n) { const sibs = kids(n.parent); const i = sibs.indexOf(n); if (i < 1) return; if (moveNode(n.id, sibs[i - 1].id, null)) { sibs[i - 1].collapsed = false; touch('move'); rerender(); focusNode(n.id); } }
function outdent(n) { const par = byId(n.parent); if (!par || !par.parent) return; const sibs = kids(par.parent); if (moveNode(n.id, par.parent, sibs.indexOf(par) + 1)) { touch('move'); rerender(); focusNode(n.id); } }

// ------------------------------------------------------------------ cards by type
function drawCards(box) {
  box.style.padding = '12px';
  const cols = h('div', { class: 'row', style: { alignItems: 'flex-start', flexWrap: 'nowrap' } });
  let dragId = null;
  for (const [k, label] of Object.entries(KINDS)) {
    const col = h('div', { class: 'cardcol kcolor-' + k, ondragover: (e) => { e.preventDefault(); }, ondrop: (e) => { const n = byId(dragId); if (n && !isLocked(n.id)) { n.kind = k; touch('kind'); rerender(); } } }, h('h4', {}, label));
    for (const n of nodes().filter((x) => x.parent && (x.kind || 'theme') === k)) col.append(h('div', { class: 'kcard kcolor-' + k, draggable: true, tabindex: 0, style: { outline: ui.sel.includes(n.id) ? '2px solid var(--accent)' : '' }, ondragstart: () => { dragId = n.id; }, onclick: () => { select(n.id); rerender(); } }, n.text, n.ai ? chip('AI', 'dashed') : null, h('div', { class: 'tiny muted' }, (byId(n.parent) || {}).text ? 'under: ' + trunc(byId(n.parent).text, 32) : '')));
    cols.append(col);
  }
  box.append(h('p', { class: 'muted small' }, 'Drag a card to another column to change what kind of point it is. This helps separate evidence from insights, implications, actions, and risks.'), cols);
}

// ------------------------------------------------------------------ side panel: inspector + suggestions
function drawSide(el) {
  el.append(h('div', { class: 'seg', style: { marginBottom: 10 } }, ['inspector', 'suggestions'].map((t) => h('button', { 'aria-pressed': ui.tab === t, onclick: () => { ui.tab = t; rerender(); } }, t === 'inspector' ? 'Details' : `Suggestions${ui.sugg.length ? ' (' + ui.sugg.length + ')' : ''}`))));
  if (ui.tab === 'suggestions') return drawSuggestions(el);
  const n = primary();
  if (!n) return el.append(h('div', { class: 'empty' }, 'Select a point to edit its details, add a note, tag it, or discuss it.'));
  const lock = isLocked(n.id) && !n.locked;
  const dis = isLocked(n.id);
  const text = h('textarea', { rows: 3, disabled: dis }); text.value = n.text; text.addEventListener('input', () => { n.text = text.value.slice(0, 300); n.ai = false; commit('edit'); });
  const note = h('textarea', { rows: 3, placeholder: 'Evidence, context, speaker thoughts' }); note.value = n.note; note.addEventListener('input', () => { n.note = note.value; commit('note'); });
  const sel = (opts, val, fn, d = false) => { const s = h('select', { disabled: d }, opts.map(([v, l]) => h('option', { value: v }, l))); s.value = val; s.addEventListener('change', () => fn(s.value)); return s; };
  const inp = (val, fn, ph = '') => { const i = h('input', { type: 'text', value: val, placeholder: ph }); i.addEventListener('input', () => fn(i.value)); return i; };
  el.append(h('div', { class: 'card stack' },
    h('div', { class: 'row' }, h('h3', { style: { margin: 0, flex: 1 } }, n.parent ? 'Point' : 'Central message'), n.ai ? h('button', { class: 'btn sm', onclick: () => { n.ai = false; touch('accept'); rerender(); } }, 'Accept suggestion') : null),
    ui.sel.length > 1 ? h('div', { class: 'notice' }, `${ui.sel.length} selected. `, h('button', { class: 'btn sm', onclick: () => { const k = mergeNodes(ui.sel); if (k) { ui.sel = [k.id]; touch('merge'); rerender(); } else toast('Select two or more unlocked points to merge.', 'bad'); } }, 'Merge into first')) : null,
    lock ? h('div', { class: 'notice warn small' }, 'Inside a locked section.') : null,
    field('Text', text), field('Type', sel(Object.entries(KINDS), n.kind || 'theme', (v) => { n.kind = v; touch('kind'); rerender(); }, dis)),
    h('div', { class: 'stack' }, h('span', { class: 'small' }, h('b', {}, 'Importance')), h('div', { class: 'seg' }, [0, 1, 2, 3].map((w) => h('button', { 'aria-pressed': n.weight === w, onclick: () => { n.weight = w; touch('weight'); rerender(); } }, w === 0 ? 'None' : '★'.repeat(w))))),
    field('Note', note),
    h('div', { class: 'grid g2' }, field('Owner', inp(n.owner, (v) => { n.owner = v; commit('tag'); })), field('Audience', inp(n.audience, (v) => { n.audience = v; commit('tag'); }))),
    h('div', { class: 'grid g2' }, field('Priority', sel([['', 'Not set'], ['high', 'High'], ['medium', 'Medium'], ['low', 'Low']], n.priority, (v) => { n.priority = v; commit('tag'); })), field('Status', sel([['draft', 'Draft'], ['review', 'In review'], ['approved', 'Approved']], n.status, (v) => { n.status = v; touch('status'); rerender(); }))),
    (n.src || []).length ? h('div', {}, h('h4', {}, 'Sources'), h('div', { class: 'row' }, n.src.map((s) => chip(s, 'acc')))) : (n.kind === 'evidence' ? h('div', { class: 'notice warn small' }, 'Evidence with no source. Attach one before presenting it as fact.') : null),
    h('label', { class: 'row' }, h('input', { type: 'checkbox', checked: n.locked, onchange: (e) => { n.locked = e.target.checked; touch('lock'); rerender(); } }), h('span', {}, h('b', {}, 'Lock this section'), h('span', { class: 'muted small' }, ' Approved content cannot be edited, moved, or deleted, and slides built from it are kept on regenerate.'))),
    h('div', { class: 'row' },
      h('button', { class: 'btn sm', onclick: () => { addChild(n.id); rerender(); } }, 'Add child'), n.parent ? h('button', { class: 'btn sm', onclick: () => { addSibling(n.id); rerender(); } }, 'Add sibling') : null,
      n.parent ? h('button', { class: 'btn sm', onclick: async () => { const t = await promptBox('Split into separate points (separate with a semicolon or new line)', n.text.replace(/[,.]\s+(and|but)\s+/i, ';\n'), true); if (t) { const parts = t.split(/[;\n]+/).map((x) => x.trim()).filter(Boolean); if (parts.length > 1) { splitNode(n.id, parts); touch('split'); rerender(); } } } }, 'Split') : null,
      h('button', { class: 'btn sm', onclick: () => expand(n) }, 'Suggest sub-points'),
      n.parent ? h('button', { class: 'btn sm danger', onclick: async () => { if (await confirmBox(`Delete "${trunc(n.text, 40)}" and everything under it?`, 'Delete', true) && deleteNode(n.id)) { ui.sel = []; touch('delete'); rerender(); } } }, 'Delete') : null)));
  // relations
  const others = nodes().filter((x) => x.id !== n.id);
  const relSel = h('select', {}, h('option', { value: '' }, 'Link to another point…'), others.map((o) => h('option', { value: o.id }, trunc(o.text, 40)))), relLabel = h('input', { type: 'text', placeholder: 'Relationship (depends on, contradicts…)' });
  el.append(h('div', { class: 'card stack' }, h('h3', { style: { margin: 0 } }, 'Relationships'),
    (n.rel || []).map((r) => h('div', { class: 'row small' }, chip(r.label || 'related'), h('span', {}, trunc((byId(r.to) || {}).text || '?', 40)), h('button', { class: 'btn sm ghost', onclick: () => { n.rel = n.rel.filter((x) => x !== r); touch('rel'); rerender(); } }, 'Remove'))),
    relSel, relLabel, h('button', { class: 'btn sm', onclick: () => { if (!relSel.value) return; n.rel = [...(n.rel || []), { id: nid(), to: relSel.value, label: relLabel.value.slice(0, 60) }]; touch('rel'); rerender(); } }, 'Add link')));
  // comments
  const cIn = h('input', { type: 'text', placeholder: 'Add a comment or question', onkeydown: (e) => { if (e.key === 'Enter') add.click(); } });
  const add = h('button', { class: 'btn sm', onclick: () => { if (!cIn.value.trim()) return; n.comments.push({ id: nid(), by: 'Me', text: cIn.value.slice(0, 600), ts: Math.floor(Date.now() / 1000), resolved: false }); touch('comment'); rerender(); } }, 'Post');
  el.append(h('div', { class: 'card stack' }, h('h3', { style: { margin: 0 } }, `Discussion (${n.comments.filter((c) => !c.resolved).length} open)`),
    n.comments.map((c) => h('div', { class: 'small', style: { opacity: c.resolved ? .55 : 1 } }, h('b', {}, c.by + ': '), c.text, ' ', h('button', { class: 'btn sm ghost', onclick: () => { c.resolved = !c.resolved; touch('comment'); rerender(); } }, c.resolved ? 'Reopen' : 'Resolve'))),
    h('div', { class: 'row' }, cIn, add)));
}

function drawSuggestions(el) {
  if (!ui.sugg.length) return el.append(h('div', { class: 'empty' }, 'Run a health check to find duplicates, thin points, missing evidence, and gaps.'), h('div', { class: 'row', style: { justifyContent: 'center', marginTop: 10 } }, h('button', { class: 'btn primary', onclick: healthCheck }, 'Run health check')));
  for (const s of ui.sugg) {
    el.append(h('div', { class: 'card stack', style: { padding: 12 } }, h('div', { class: 'row' }, chip({ merge: 'Merge', remove: 'Remove', expand: 'Expand', validate: 'Validate', combine: 'Combine' }[s.type] || s.type, s.severity === 'warn' ? 'warn' : ''), h('span', { class: 'small' }, s.text)),
      h('div', { class: 'row' },
        s.type === 'merge' ? h('button', { class: 'btn sm', onclick: () => { const k = mergeNodes(s.nodes); if (k) { touch('merge'); drop(s); } } }, 'Merge them') : null,
        s.type === 'remove' ? h('button', { class: 'btn sm', onclick: () => { if (deleteNode(s.nodes[0])) { touch('delete'); drop(s); } } }, 'Remove') : null,
        s.type === 'expand' && byId(s.nodes[0]) ? h('button', { class: 'btn sm', onclick: () => expand(byId(s.nodes[0])) }, 'Suggest points') : null,
        h('button', { class: 'btn sm', onclick: () => { ui.sel = [s.nodes[0]]; ui.tab = 'inspector'; rerender(); } }, 'Show'), h('button', { class: 'btn sm ghost', onclick: () => drop(s) }, 'Dismiss'))));
  }
}
const drop = (s) => { ui.sugg = ui.sugg.filter((x) => x !== s); rerender(); };

async function healthCheck() { const r = await api('POST', `/api/projects/${S.project.id}/map/suggestions`, {}); ui.sugg = r.suggestions; ui.tab = 'suggestions'; toast(r.suggestions.length ? `${r.suggestions.length} suggestion(s). Nothing changes until you act.` : 'No issues found.'); rerender(); }
function acceptAll() { nodes().forEach((n) => { n.ai = false; }); touch('accept'); rerender(); }

// ------------------------------------------------------------------ AI proposals (always reviewed before they enter the map)
async function proposeFromSources() {
  if (!await ensureScope()) return;
  const p = S.project;
  const btn = document.activeElement;
  try { toast('Reading your sources…'); const r = await api('POST', `/api/projects/${p.id}/map/propose`, {}); reviewProposal(r.branches, r, 'Suggested branches from your sources'); }
  catch (e) { toast(e.message, 'bad'); }
}
async function expand(n) {
  if (!await ensureScope()) return;
  try { const r = await api('POST', `/api/projects/${S.project.id}/map/expand`, { text: n.text, siblings: kids(n.id).map((k) => k.text) }); reviewProposal(r.children, { engine: r.engine, notes: [], gaps: [] }, `Suggested sub-points for "${trunc(n.text, 40)}"`, n.id); }
  catch (e) { toast(e.message, 'bad'); }
}
export function reviewProposal(branches, info, title, parentId) {
  if (!branches.length) return toast('Nothing to suggest from the current sources.');
  const picked = new Set(branches.map((b) => b.id));
  modal((box, close) => {
    const tree = (b, d = 0) => h('div', { style: { marginLeft: d * 18 } }, h('div', { class: 'row small kcolor-' + (b.kind || 'theme') }, d === 0 ? h('input', { type: 'checkbox', checked: true, onchange: (e) => { e.target.checked ? picked.add(b.id) : picked.delete(b.id); } }) : null, h('i', { class: 'dot' }), h('span', { style: { fontWeight: d === 0 ? 600 : 400 } }, b.text), chip(KINDS[b.kind || 'theme']), (b.src || []).map((s) => chip(s, 'acc')), b.weight ? chip('★'.repeat(b.weight)) : null), (b.children || []).map((c) => tree(c, d + 1)));
    box.append(h('h2', {}, title), h('div', { class: 'row' }, chip(info.engine === 'model' ? 'Written by an AI model' : 'Built with local rules', 'dashed'), chip('Suggestions only', 'warn')),
      h('p', { class: 'muted' }, 'Tick what you want to add. Added points are dashed until you accept them, and they cite the source they came from.'), (info.notes || []).map((x) => h('div', { class: 'notice small' }, x)),
      h('div', { class: 'stack' }, branches.map((b) => tree(b))), (info.gaps || []).length ? h('div', { class: 'notice warn' }, h('b', {}, 'Gaps the AI noticed: '), info.gaps.join(' · ')) : null,
      h('div', { class: 'row', style: { justifyContent: 'flex-end', marginTop: 12 } }, h('button', { class: 'btn', onclick: () => close() }, 'Discard'), h('button', { class: 'btn primary', onclick: () => {
        const rt = ensureRoot(); const sel = branches.filter((b) => picked.has(b.id)); const added = addProposal(sel, parentId || rt.id, true); ui.fit = true; commit('propose'); close(); toast(`Added ${added} point(s) as suggestions.`); rerender(); } }, 'Add selected to the map')));
  });
}

async function compare() {
  const { versions } = await api('GET', `/api/projects/${S.project.id}/versions`);
  modal((box, close) => {
    const out = h('div', { class: 'grid g2' });
    const outline = (list) => { const k = (id) => list.filter((n) => n.parent === id); const lines = []; const w = (id, d) => k(id).forEach((n) => { lines.push(h('div', { style: { marginLeft: d * 16 }, class: 'small' }, (d ? '– ' : '') + n.text)); w(n.id, d + 1); }); const r = list.find((n) => !n.parent); if (r) { lines.push(h('div', { class: 'small' }, h('b', {}, r.text))); w(r.id, 1); } return lines; };
    const sel = h('select', {}, h('option', { value: '' }, 'Choose a saved version…'), versions.map((v) => h('option', { value: v.id }, `${v.label} · ${v.nodes} nodes`)));
    sel.addEventListener('change', async () => { clear(out); if (!sel.value) return; const v = await api('GET', `/api/projects/${S.project.id}/versions/${sel.value}`); out.append(h('div', { class: 'card' }, h('h3', {}, 'Saved version'), outline(v.map.nodes)), h('div', { class: 'card' }, h('h3', {}, 'Current map'), outline(nodes()))); });
    box.append(h('h2', {}, 'Compare alternative structures'), h('p', { class: 'muted' }, 'Save a named snapshot from History before trying a different structure, then compare here. To switch, restore the snapshot from History.'), sel, out,
      h('div', { class: 'row', style: { justifyContent: 'flex-end', marginTop: 12 } }, h('button', { class: 'btn', onclick: () => close() }, 'Close')));
  });
}
