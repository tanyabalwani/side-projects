import { h, api, chip, toast, clear, modal, field, trunc, confirmBox, debounce, uid, LAYOUT_NAMES } from './util.js';
import { S, commit, byId } from './state.js';
import { stage } from './stage.js';
import { ensureScope } from './scope.js';
import { go } from './main.js';

let sel = 0;
const MODES = [['concise', 'More concise'], ['executive', 'More executive'], ['persuasive', 'More persuasive'], ['factual', 'More factual'], ['conversational', 'More conversational'], ['visual', 'More visual'], ['action', 'More action-oriented'], ['simple', 'Simpler language'], ['structure', 'Keep my words, fix structure'], ['headline', 'Headline as a conclusion'], ['evidence', 'Find claims needing evidence']];
const AUD = [['audience:technical', 'Technical'], ['audience:customer', 'Customer'], ['audience:employee', 'Employee'], ['audience:investor', 'Investor'], ['audience:workshop', 'Workshop']];
const blankSlide = () => ({ id: uid('s'), kind: 'content', layout: 'bullets', title: 'New slide', purpose: '', bullets: [], quote: '', quote_by: '', takeaway: '', notes: '', visual: '', transition: '', facilitation: '', node_id: '', sources: [], gaps: [], approved: false, locked: false, override_layout: '' });
const originChip = (o) => ({ provided: ['Your source', 'acc'], internal: ['Internal KB', 'ok'], external: ['External web', 'warn'] }[o] || ['Source', '']);

export async function render(rootEl) {
  const p = S.project; const page = h('div', { class: 'page wide' }); rootEl.append(page);
  const pre = sessionStorage.getItem('cd_sel'); if (pre != null) { sel = +pre || 0; sessionStorage.removeItem('cd_sel'); }
  const again = () => { clear(page); build(); };
  function build() {
    if (!p.slides.length) {
      page.append(h('h1', {}, 'Slides'), h('div', { class: 'empty' }, 'No slides yet. Generate them from the storyline, or add one by hand.', h('div', { class: 'row', style: { justifyContent: 'center', marginTop: 10 } }, h('button', { class: 'btn primary', onclick: () => go('story') }, 'Go to the storyline'), h('button', { class: 'btn', onclick: () => { p.slides.push(blankSlide()); commit('slide'); again(); } }, 'Add a slide'))));
      return;
    }
    sel = Math.min(sel, p.slides.length - 1); const s = p.slides[sel];
    page.append(h('div', { class: 'row between' }, h('h1', { style: { margin: 0 } }, 'Edit slides'), h('div', { class: 'row' }, h('button', { class: 'btn', onclick: () => present(sel) }, 'Present and rehearse'), h('button', { class: 'btn primary', onclick: () => go('template') }, 'Next: template'))));
    const grid = h('div', { class: 'slides', style: { marginTop: 12 } });
    // rail
    const rail = h('div', { class: 'rail' }); let dragI = null;
    p.slides.forEach((x, i) => rail.append(h('div', { class: 'thumb' + (i === sel ? ' sel' : ''), draggable: true, tabindex: 0, onclick: () => { sel = i; again(); }, onkeydown: (e) => { if (e.key === 'Enter') { sel = i; again(); } },
      ondragstart: () => { dragI = i; }, ondragover: (e) => { e.preventDefault(); e.currentTarget.classList.add('drop'); }, ondragleave: (e) => e.currentTarget.classList.remove('drop'),
      ondrop: (e) => { e.preventDefault(); if (dragI == null || dragI === i) return; const [m] = p.slides.splice(dragI, 1); p.slides.splice(i, 0, m); sel = i; commit('reorder'); again(); } },
      h('div', { class: 'row', style: { gap: 4, justifyContent: 'space-between' } }, h('span', { class: 'muted tiny' }, String(i + 1) + ' · ' + (LAYOUT_NAMES[x.layout] || x.layout)), h('span', {}, x.approved ? chip('✓', 'ok') : null, x.locked ? chip('lock') : null, x.gaps.length ? chip('gap', 'warn') : null)), h('b', {}, x.title || 'Untitled'))));
    rail.append(h('button', { class: 'btn sm', onclick: () => { p.slides.splice(sel + 1, 0, blankSlide()); sel++; commit('slide'); again(); } }, '+ Add slide'));
    // preview
    const mid = h('div', { class: 'stack' });
    const prev = h('div'); const drawPrev = () => { clear(prev); prev.append(stage(s, p)); };
    drawPrev();
    mid.append(prev, h('div', { class: 'card stack' }, h('div', { class: 'small' }, h('b', {}, 'Recommended visual: '), s.visual || LAYOUT_NAMES[s.layout]), s.purpose ? h('div', { class: 'small' }, h('b', {}, 'Purpose: '), s.purpose) : null,
      sel > 0 && s.transition ? h('div', { class: 'small' }, h('b', {}, 'Link from previous: '), s.transition) : null,
      h('div', { class: 'row' }, h('button', { class: 'btn sm', disabled: sel === 0, onclick: () => { const [m] = p.slides.splice(sel, 1); p.slides.splice(sel - 1, 0, m); sel--; commit('reorder'); again(); } }, 'Move earlier'), h('button', { class: 'btn sm', disabled: sel === p.slides.length - 1, onclick: () => { const [m] = p.slides.splice(sel, 1); p.slides.splice(sel + 1, 0, m); sel++; commit('reorder'); again(); } }, 'Move later'),
        h('button', { class: 'btn sm', onclick: () => { const c = JSON.parse(JSON.stringify(s)); c.id = uid('s'); c.approved = false; p.slides.splice(sel + 1, 0, c); sel++; commit('slide'); again(); } }, 'Duplicate'),
        s.node_id && byId(s.node_id) ? h('button', { class: 'btn sm', disabled: s.locked, onclick: () => regen(s) }, 'Regenerate from map') : null,
        h('button', { class: 'btn sm danger', onclick: async () => { if (await confirmBox('Delete this slide?', 'Delete', true)) { p.slides.splice(sel, 1); commit('slide'); again(); } } }, 'Delete'))));
    // evidence & provenance
    const ev = h('div', { class: 'card stack' }, h('h3', { style: { margin: 0 } }, 'Evidence and sources'));
    s.bullets.forEach((b) => ev.append(h('div', { class: 'bul' + (b.origin === 'ai' ? ' ai' : '') }, b.origin === 'ai' ? chip('AI suggestion, not sourced', 'dashed') : b.origin === 'sourced' ? chip('Sourced', 'ok') : chip('Yours'), h('span', {}, b.text), (b.cite || []).map((c) => chip(c, 'acc')))));
    if (s.ref) ev.append(h('div', { class: 'small' }, chip('Imported', 'acc'), ' ', s.ref, ' · text carried over, pictures are not'));
    if (s.sources.length) ev.append(h('h4', {}, 'Source references'), s.sources.map((r) => { const [l, k] = originChip(r.origin); return h('div', { class: 'small', style: { margin: '4px 0' } }, chip(l, k), ' ', h('b', {}, r.name), h('div', { class: 'muted tiny' }, r.snippet)); }));
    if (s.gaps.length) ev.append(s.gaps.map((g) => h('div', { class: 'notice warn small' }, g, ' ', h('button', { class: 'btn sm ghost', onclick: () => { s.gaps = s.gaps.filter((x) => x !== g); commit('gap'); again(); } }, 'Dismiss'))));
    if (!s.bullets.length && !s.sources.length) ev.append(h('div', { class: 'muted small' }, 'No content or sources on this slide yet.'));
    mid.append(ev);
    // editor
    const ed = h('div', { class: 'stack' });
    const upd = (k, v, label = 'slide') => { s[k] = v; commit(label); drawPrev(); lint(); };
    const title = h('textarea', { rows: 2, disabled: s.locked }); title.value = s.title; title.addEventListener('input', () => { upd('title', title.value.slice(0, 200)); rail.querySelectorAll('.thumb b')[sel].textContent = title.value; });
    const bul = h('textarea', { rows: 8, disabled: s.locked, placeholder: 'One point per line. Start a line with two spaces or "- " for a sub-point.' });
    bul.value = s.bullets.map((b) => (b.level ? '  ' : '') + b.text).join('\n');
    bul.addEventListener('input', () => {
      const old = new Map(s.bullets.map((b) => [b.text, b]));
      s.bullets = bul.value.split('\n').filter((l) => l.trim()).slice(0, 14).map((l) => { const lvl = /^(\s{2,}|\s*[-–•]\s+)/.test(l) ? 1 : 0; const t = l.replace(/^\s*[-–•]\s+/, '').trim().slice(0, 300); const o = old.get(t); return { text: t, level: lvl, origin: o ? o.origin : 'user', cite: o ? o.cite : [] }; });
      commit('bullets'); drawPrev(); lint();
    });
    const sel2 = (opts, val, fn, dis) => { const x = h('select', { disabled: dis }, opts.map(([v, l]) => h('option', { value: v }, l))); x.value = val; x.addEventListener('change', () => fn(x.value)); return x; };
    const ta = (k, rows, ph) => { const x = h('textarea', { rows, placeholder: ph, disabled: s.locked && k !== 'notes' }); x.value = s[k]; x.addEventListener('input', () => upd(k, x.value, k)); return x; };
    ed.append(h('div', { class: 'card stack' },
      h('div', { class: 'grid g2' }, field('Slide type', sel2([['title', 'Title'], ['summary', 'Executive summary'], ['content', 'Content'], ['ask', 'Decision or next step'], ['appendix', 'Appendix'], ['sources', 'Sources']], s.kind, (v) => { upd('kind', v); again(); }, s.locked)),
        field('Layout', sel2(Object.entries(LAYOUT_NAMES), s.layout, (v) => { upd('layout', v); again(); }, s.locked))),
      p.template ? field('Template layout for this slide', sel2([['', 'Default for this type'], ...p.template.approved.map((n) => [n, n])], s.override_layout, (v) => upd('override_layout', v))) : null,
      field('Headline (write it as a conclusion)', title), field('Points', bul, s.layout === 'data' ? 'For a chart write "Label: value%" on each line.' : s.layout === 'action_plan' ? 'One action per line: "Do the thing | Owner | Date".' : s.layout === 'process' || s.layout === 'timeline' ? 'Start lines with "Q1:" or "Step 1:" for labels.' : ''),
      field(s.kind === 'title' ? 'Subtitle' : 'So what (takeaway)', ta('takeaway', 2, s.kind === 'title' ? 'Audience and date' : 'The consequence for the audience')), s.layout === 'quote' ? h('div', { class: 'grid g2' }, field('Quote', ta('quote', 2, '')), field('Said by', ta('quote_by', 1, ''))) : null,
      field('Speaker notes', ta('notes', 4, 'What you will say')), field('Link to the previous slide', ta('transition', 2, '')), field('Facilitation instructions (optional)', ta('facilitation', 2, 'Ask the room…')),
      h('div', { class: 'row' }, h('label', { class: 'row' }, h('input', { type: 'checkbox', checked: s.approved, onchange: (e) => { s.approved = e.target.checked; commit('approve'); again(); } }), 'Approved'), h('label', { class: 'row' }, h('input', { type: 'checkbox', checked: s.locked, onchange: (e) => { s.locked = e.target.checked; commit('lock'); again(); } }), 'Lock (kept on regenerate)'))));
    // wording
    const lintBox = h('div', { class: 'card stack' });
    const doLint = async () => {
      const text = [s.title, s.takeaway, ...s.bullets.map((b) => b.text)].join('\n');
      try { const r = await api('POST', '/api/lint', { text }); clear(lintBox); const warn = r.hits.filter((x) => x.severity === 'warn');
        lintBox.append(h('div', { class: 'row between' }, h('h3', { style: { margin: 0 } }, 'Plain-writing check'), h('button', { class: 'btn sm', disabled: !r.hits.length, onclick: () => { applyFix(s); commit('fix'); again(); toast('Mechanical clean-up applied. Review the wording.'); } }, 'Fix punctuation and filler')),
          !r.hits.length ? h('div', { class: 'small muted' }, 'No stock phrasing found.') : h('div', { class: 'stack' }, r.hits.slice(0, 10).map((x) => h('div', { class: 'small' }, chip(x.match, x.severity === 'warn' ? 'warn' : ''), ' ', x.msg)), warn.length > 0 ? h('div', { class: 'muted tiny' }, 'These patterns read as generic. Replace them with a specific fact, number, or name. Use an editing mode for a rewrite.') : null)); } catch (e) { /* ignore */ }
    };
    const lint = debounce(doLint, 600);
    const applyFix = async (sl) => { /* local mechanical clean-up mirrors server autofix */ const f = (t) => t.replace(/[“”]/g, '"').replace(/[‘’]/g, "'").replace(/\s*—\s*/g, ', ').replace(/\s+-\s+/g, ', ').replace(/\*\*/g, '').replace(/^(Additionally|Moreover|Furthermore|Notably|Importantly),\s*(\w)/, (m, a, c) => c.toUpperCase()); sl.title = f(sl.title); sl.takeaway = f(sl.takeaway); sl.bullets.forEach((b) => { b.text = f(b.text); }); };
    doLint();
    // editing modes
    const modes = h('div', { class: 'card stack' }, h('h3', { style: { margin: 0 } }, 'Refine with AI'), h('p', { class: 'muted small', style: { margin: 0 } }, 'You always see the changes before anything is applied.'),
      h('div', { class: 'row' }, MODES.map(([m, l]) => h('button', { class: 'btn sm', disabled: s.locked, onclick: () => refine(s, m, l) }, l))), h('div', { class: 'row' }, h('span', { class: 'small muted' }, 'Rewrite for:'), AUD.map(([m, l]) => h('button', { class: 'btn sm', disabled: s.locked, onclick: () => refine(s, m, l) }, l))));
    ed.append(modes, lintBox);
    grid.append(rail, mid, ed); page.append(grid);
    async function refine(sl, mode, label) {
      try { const r = await api('POST', `/api/projects/${p.id}/refine`, { slide: sl, mode });
        modal((box, close) => {
          const col = (t, x) => h('div', {}, h('h4', {}, t), h('div', { class: 'small' }, h('b', {}, x.title)), x.bullets.map((b) => h('div', { class: 'small', style: { marginLeft: b.level ? 14 : 0 } }, '• ' + b.text)), x.takeaway ? h('div', { class: 'small' }, h('i', {}, 'So what: ' + x.takeaway)) : null, x.layout !== sl.layout ? h('div', { class: 'small' }, 'Layout: ' + LAYOUT_NAMES[x.layout]) : null);
          box.append(h('h2', {}, `Review changes: ${label}`), h('div', { class: 'row' }, chip(r.engine === 'model' ? 'Written by an AI model' : 'Built-in rules', 'dashed')), (r.changes || []).length ? h('ul', { class: 'small' }, r.changes.map((c) => h('li', {}, c))) : null,
            h('div', { class: 'diff' }, col('Before', r.before), col('After', r.after)), (r.after.gaps || []).length ? h('div', { class: 'notice warn small' }, r.after.gaps.join(' · ')) : null,
            h('div', { class: 'row', style: { justifyContent: 'flex-end', marginTop: 12 } }, h('button', { class: 'btn', onclick: () => close() }, 'Reject'), h('button', { class: 'btn primary', onclick: () => { Object.assign(sl, { title: r.after.title, bullets: r.after.bullets, takeaway: r.after.takeaway, notes: r.after.notes, layout: r.after.layout, gaps: r.after.gaps }); sl.approved = false; commit('refine'); close(); again(); } }, 'Accept changes')));
        }); } catch (e) { toast(e.message, 'bad'); }
    }
    async function regen(sl) {
      if (!await ensureScope()) return;
      try { const r = await api('POST', `/api/projects/${p.id}/slides/regenerate`, { node_id: sl.node_id }); const n = r.slide; n.id = sl.id; n.kind = sl.kind; p.slides[sel] = n; commit('regen'); again(); toast('Slide regenerated from the map.'); } catch (e) { toast(e.message, 'bad'); }
    }
  }
  build();
}

export function present(start = 0) {
  const p = S.project; let i = start, t0 = Date.now(); const main = p.slides.filter((s) => ['summary', 'content', 'ask'].includes(s.kind)).length || 1;
  const per = (p.brief.minutes * 60) / main;
  const ov = h('div', { class: 'present', role: 'dialog', 'aria-label': 'Presenter view' }); document.body.append(ov);
  const left = h('div', { style: { display: 'grid', alignContent: 'center' } }), right = h('div', { class: 'stack', style: { overflow: 'auto' } });
  ov.append(left, right);
  const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
  const timer = h('div', { class: 'timer' }), budget = h('div', { class: 'small' }), bar = h('div', { class: 'bar' }, h('i', { style: { width: '0%' } }));
  const draw = () => { clear(left); clear(right); const s = p.slides[i]; left.append(stage(s, p));
    right.append(h('div', { class: 'row between' }, h('b', {}, `Slide ${i + 1} of ${p.slides.length}`), h('button', { class: 'btn sm', onclick: close }, 'Exit (Esc)')), timer, bar, budget, h('h4', {}, 'Speaker notes'), h('div', { style: { whiteSpace: 'pre-wrap', fontSize: '1.05rem' } }, s.notes || 'No notes.'),
      s.facilitation ? h('div', { class: 'notice' }, 'Facilitate: ' + s.facilitation) : null, p.slides[i + 1] ? h('div', { class: 'small', style: { color: '#98a2b3' } }, 'Next: ' + p.slides[i + 1].title) : null); tick(); };
  const tick = () => { const e = (Date.now() - t0) / 1000, total = p.brief.minutes * 60; timer.textContent = fmt(e) + ' / ' + fmt(total); bar.firstChild.style.width = Math.min(100, 100 * e / total) + '%'; const expected = per * (p.slides.slice(0, i + 1).filter((s) => ['summary', 'content', 'ask'].includes(s.kind)).length); budget.textContent = e > expected + 20 ? `Behind plan by ${fmt(e - expected)}` : e < expected - 40 ? `Ahead of plan by ${fmt(expected - e)}` : 'On pace'; };
  const iv = setInterval(tick, 1000);
  const key = (e) => { if (e.key === 'ArrowRight' || e.key === ' ' || e.key === 'PageDown') { i = Math.min(p.slides.length - 1, i + 1); draw(); } else if (e.key === 'ArrowLeft' || e.key === 'PageUp') { i = Math.max(0, i - 1); draw(); } else if (e.key === 'Escape') close(); };
  function close() { clearInterval(iv); document.removeEventListener('keydown', key); ov.remove(); }
  document.addEventListener('keydown', key); draw();
}
