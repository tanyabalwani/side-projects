import { h, api, chip, toast, clear, modal, confirmBox, field, trunc, uid, debounce } from './util.js';
import { S, commit } from './state.js';
import { stage } from './stage.js';
import { go } from './main.js';

const ROLES = ['title', 'agenda', 'context', 'problem', 'answer', 'evidence', 'case', 'options', 'plan', 'risks', 'ask', 'closing', 'appendix', 'content'];
const ROLE_LABEL = { title: 'Title', agenda: 'Agenda', context: 'Context', problem: 'Problem', answer: 'Answer', evidence: 'Evidence', case: 'Case study', options: 'Options', plan: 'Plan', risks: 'Risks', ask: 'Ask', closing: 'Closing', appendix: 'Appendix', content: 'Content' };
const RC = { answer: 'var(--accent)', evidence: 'var(--k-evidence)', case: 'var(--k-insight)', problem: 'var(--k-risk)', context: 'var(--k-theme)', options: 'var(--k-implication)', plan: 'var(--k-action)', risks: 'var(--k-risk)', ask: 'var(--ok)', title: 'var(--muted)', closing: 'var(--muted)', appendix: 'var(--muted)', agenda: 'var(--muted)', content: 'var(--k-question)' };
const SKIP = new Set(['title', 'closing', 'agenda']);
const ui = { by: 'theme', q: '', hidePicked: false, sugg: null, open: {} };
const roleChip = (r) => h('span', { class: 'rolechip', style: { '--rc': RC[r] || 'var(--muted)' }, title: ROLE_LABEL[r] }, ROLE_LABEL[r] || r);

export async function render(rootEl) {
  const p = S.project; if (!p.board) p.board = { flow: { mode: 'framework', framework: '', ref_deck: '', intent: '' }, items: [] };
  const B = p.board, page = h('div', { class: 'page wide' }); rootEl.append(page);
  let lib = { decks: [], themes: [], duplicates: [], conflicts: [] };
  const load = async () => { lib = await api('GET', `/api/projects/${p.id}/decks`); };
  const again = () => { clear(page); build(); };
  const picked = () => new Set(B.items.map((i) => i.ref));
  const touch = (l = 'board') => { commit(l); };

  const fileIn = h('input', { type: 'file', multiple: true, hidden: true, accept: '.pptx,.pdf', onchange: async () => {
    for (const f of fileIn.files) { try { const r = await api('POST', `/api/projects/${p.id}/decks`, f, { raw: true, filename: f.name }); p.sources = r.sources; toast(`Imported ${f.name}: ${r.source.slides} slides`); (r.source.warnings || []).filter((w) => /confidential|pictures/.test(w)).forEach((w) => toast(w)); } catch (e) { toast(`${f.name}: ${e.message}`, 'bad'); } }
    await load(); again();
  } });

  function build() {
    page.append(h('div', { class: 'row between' }, h('div', {}, h('h1', { style: { marginBottom: 2 } }, 'Story board'), h('p', { class: 'muted', style: { margin: 0, maxWidth: '78ch' } }, 'Bring in existing decks, browse their slides, and pick the pieces for a new story. Clarity organises them, then suggests a flow and edits against your intention. You decide what changes.')),
      h('div', { class: 'row' }, h('button', { class: 'btn primary', onclick: () => fileIn.click() }, 'Add decks (.pptx, .pdf)'), fileIn)));
    const cols = h('div', { class: 'board', style: { marginTop: 12 } });
    cols.append(libraryCol(), storyCol(), suggestCol()); page.append(cols);
  }

  // ----------------------------------------------------------------- library
  function libraryCol() {
    const c = h('div', { class: 'bcol' }); c.append(h('h3', {}, 'Your decks'));
    const q = h('input', { type: 'search', placeholder: 'Search slides', value: ui.q, 'aria-label': 'Search slides', oninput: debounce((e) => { ui.q = e.target.value; again(); setTimeout(() => document.querySelector('.bcol input[type=search]')?.focus(), 0); }, 250) });
    c.append(h('div', { class: 'row', style: { margin: '6px 0' } }, h('div', { class: 'seg' }, [['theme', 'By theme'], ['role', 'By role'], ['deck', 'By deck']].map(([v, l]) => h('button', { 'aria-pressed': ui.by === v, onclick: () => { ui.by = v; again(); } }, l))), q,
      h('label', { class: 'row small' }, h('input', { type: 'checkbox', checked: ui.hidePicked, onchange: (e) => { ui.hidePicked = e.target.checked; again(); } }), 'Hide picked')));
    if (!lib.decks.length) return c.append(h('div', { class: 'empty' }, 'No decks yet. Add PowerPoint or PDF decks from different sources. Text, tables and chart data come across as editable content.')), c;
    c.append(h('div', { class: 'stack', style: { marginBottom: 8 } }, lib.decks.map((d) => h('div', { class: 'row small', style: { gap: 6 } }, h('input', { type: 'checkbox', checked: d.include, 'aria-label': 'Include ' + d.name, onchange: async (e) => { const r = await api('PUT', `/api/projects/${p.id}/sources/${d.id}`, { include: e.target.checked }); p.sources = r.sources; await load(); again(); } }),
      h('b', {}, d.name), chip(`${d.count} slides`), h('span', { class: 'sp' }), h('button', { class: 'btn sm ghost', onclick: async () => { if (await confirmBox(`Remove "${d.name}" from this project? Slides already in your story stay.`, 'Remove', true)) { const r = await api('DELETE', `/api/projects/${p.id}/sources/${d.id}`); p.sources = r.sources; if (B.flow.ref_deck === d.id) B.flow.ref_deck = ''; await load(); again(); } } }, 'Remove')))));
    if (lib.duplicates.length || lib.conflicts.length) c.append(h('details', { class: 'notice warn small', open: ui.open.cross, ontoggle: (e) => { ui.open.cross = e.target.open; } }, h('summary', {}, `${lib.duplicates.length} near-duplicate slide(s), ${lib.conflicts.length} conflicting figure(s) across decks`),
      lib.conflicts.map((x) => h('div', {}, '• ' + x.text)), lib.duplicates.slice(0, 6).map((x) => h('div', {}, `• ${name(x.a)} repeats ${name(x.b)}`))));
    const all = lib.decks.filter((d) => d.include).flatMap((d) => d.slides.map((s) => ({ ...s, deckName: d.name, deckId: d.id })));
    const ps = picked(), term = ui.q.trim().toLowerCase();
    const shown = all.filter((s) => (!ui.hidePicked || !ps.has(s.slide.ref)) && (!term || (s.title + ' ' + s.bullets.map((b) => b.text).join(' ')).toLowerCase().includes(term)));
    let groups = [];
    if (ui.by === 'role') groups = ROLES.map((r) => [ROLE_LABEL[r], shown.filter((s) => s.role === r)]);
    else if (ui.by === 'deck') groups = lib.decks.filter((d) => d.include).map((d) => [d.name, shown.filter((s) => s.deckId === d.id)]);
    else groups = [...lib.themes, 'Framing', 'Other'].map((t) => [t, shown.filter((s) => s.theme === t)]);
    for (const [name_, list] of groups) { if (!list.length) continue;
      c.append(h('h4', { style: { margin: '14px 0 6px' } }, `${name_} · ${list.length}`), h('div', { class: 'mgrid' }, list.map((s) => miniCard(s, ps)))); }
    if (!shown.length) c.append(h('div', { class: 'muted' }, 'No slides match.'));
    return c;
  }
  const name = (key) => { const [d, n] = key.split(':'); const dk = lib.decks.find((x) => x.id === d); return `${dk ? dk.name : 'deck'} slide ${n}`; };
  const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { const el = e.target; io.unobserve(el); el.replaceWith(stage({ ...el._slide, layout: el._slide.layout }, p)); } }), { rootMargin: '300px' });
  function miniCard(s, ps) {
    const inStory = ps.has(s.slide.ref), ph = h('div', { class: 'ph' }); ph._slide = s.slide; io.observe(ph);
    return h('div', { class: 'mini' + (inStory ? ' in' : '') + (SKIP.has(s.role) ? ' skip' : ''), draggable: true, title: s.title, ondragstart: (e) => { e.dataTransfer.setData('text/plain', 'lib:' + s.key); e.dataTransfer.effectAllowed = 'copy'; } },
      ph, h('div', { class: 'tt' }, s.title || 'Untitled'),
      h('div', { class: 'meta' }, roleChip(s.role), ui.by !== 'deck' ? h('span', { class: 'tiny muted' }, trunc(s.deckName, 14) + ' ' + s.n) : h('span', { class: 'tiny muted' }, '#' + s.n),
        s.flags.includes('chart') ? chip('chart', 'acc') : null, s.flags.includes('table') ? chip('table', 'acc') : null, s.flags.includes('image') ? chip('image', 'warn', 'Pictures are not carried over') : null, s.stale ? chip('dated', 'warn', 'Mentions ' + Math.max(...s.years)) : null, s.dups.length ? chip('repeat', 'warn', 'Near-duplicate in another deck') : null, s.confidential ? chip('confidential', 'bad') : null),
      h('div', { class: 'row', style: { justifyContent: 'space-between' } }, h('button', { class: 'btn sm ghost', onclick: () => preview(s) }, 'Preview'), h('button', { class: 'btn sm' + (inStory ? '' : ' primary'), disabled: inStory, onclick: () => add(s) }, inStory ? 'In story' : '+ Add')));
  }
  function preview(s) { modal((box, close) => { box.append(h('div', { class: 'row between' }, h('h2', {}, s.title), roleChip(s.role)), stage(s.slide, p), s.notes ? h('div', { class: 'card small', style: { marginTop: 10 } }, h('b', {}, 'Speaker notes: '), s.notes) : null,
    h('div', { class: 'row', style: { justifyContent: 'flex-end', marginTop: 10 } }, h('button', { class: 'btn', onclick: () => close() }, 'Close'), h('button', { class: 'btn primary', onclick: () => { add(s); close(); } }, 'Add to story'))); }); }
  function add(s, at = null) { const it = JSON.parse(JSON.stringify(s.slide)); it.id = uid('s'); if (at == null) B.items.push(it); else B.items.splice(at, 0, it); touch('board add'); ui.sugg = null; again(); }

  // ----------------------------------------------------------------- story
  function storyCol() {
    const c = h('div', { class: 'bcol' }); c.append(h('h3', {}, `Your story (${B.items.length})`));
    const f = B.flow, fws = S.meta.frameworks;
    const intent = h('textarea', { rows: 2, placeholder: p.brief.message || p.governing || 'What should this story make the audience do or believe?' }); intent.value = f.intent; intent.addEventListener('input', () => { f.intent = intent.value; commit('board'); });
    const fwSel = h('select', { 'aria-label': 'Framework', onchange: (e) => { f.framework = e.target.value; commit('board'); ui.sugg = null; again(); } }, h('option', { value: '' }, `Use the project's (${(fws.find((x) => x.id === p.framework) || {}).name || p.framework})`), fws.map((x) => h('option', { value: x.id }, x.name))); fwSel.value = f.framework;
    const refSel = h('select', { 'aria-label': 'Reference deck', onchange: (e) => { f.ref_deck = e.target.value; commit('board'); ui.sugg = null; again(); } }, h('option', { value: '' }, 'Choose a deck whose flow you like…'), lib.decks.map((d) => h('option', { value: d.id }, d.name))); refSel.value = f.ref_deck;
    c.append(h('div', { class: 'card stack', style: { padding: 12, margin: '6px 0 10px' } }, field('Your intention for this story', intent),
      h('div', { class: 'stack' }, h('span', { class: 'small' }, h('b', {}, 'Flow to follow')), h('div', { class: 'seg' }, [['framework', 'A framework'], ['reference', 'A reference deck']].map(([v, l]) => h('button', { 'aria-pressed': f.mode === v, onclick: () => { f.mode = v; commit('board'); ui.sugg = null; again(); } }, l))), f.mode === 'reference' ? refSel : fwSel),
      h('div', { class: 'row' }, h('button', { class: 'btn primary', disabled: !B.items.length || (f.mode === 'reference' && !f.ref_deck), onclick: suggest }, 'Suggest flow and edits'), h('button', { class: 'btn', disabled: !B.items.length, onclick: send }, 'Send to Slides'))));
    const zone = h('div', {}, null);
    const mark = (e) => { const kids = [...zone.querySelectorAll('.sitem')]; let at = kids.length; for (let i = 0; i < kids.length; i++) { const r = kids[i].getBoundingClientRect(); if (e.clientY < r.top + r.height / 2) { at = i; break; } } return at; };
    zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.querySelectorAll('.drop').forEach((x) => x.classList.remove('drop')); const at = mark(e); const k = zone.querySelectorAll('.sitem')[at]; if (k) k.classList.add('drop'); });
    zone.addEventListener('dragleave', () => zone.querySelectorAll('.drop').forEach((x) => x.classList.remove('drop')));
    zone.addEventListener('drop', (e) => { e.preventDefault(); const at = mark(e); const d = e.dataTransfer.getData('text/plain');
      if (d.startsWith('lib:')) { const s = lib.decks.flatMap((x) => x.slides).find((x) => x.key === d.slice(4)); if (s && !picked().has(s.slide.ref)) add(s, at); }
      else if (d.startsWith('story:')) { const i = B.items.findIndex((x) => x.id === d.slice(6)); if (i >= 0) { const [m] = B.items.splice(i, 1); B.items.splice(at > i ? at - 1 : at, 0, m); touch('board'); ui.sugg = null; again(); } } });
    if (!B.items.length) zone.append(h('div', { class: 'dropzone' }, 'Drag slides here or press "+ Add". Order them as you would tell the story.'));
    B.items.forEach((it, i) => zone.append(storyItem(it, i)));
    c.append(zone); return c;
  }
  function storyItem(it, i) {
    const role = it.role || 'content';
    const sel = h('select', { 'aria-label': 'Role', style: { width: 'auto', padding: '2px 4px', fontSize: '.75rem' }, onchange: (e) => { it.role = e.target.value; touch('board'); ui.sugg = null; again(); } }, ROLES.map((r) => h('option', { value: r }, ROLE_LABEL[r]))); sel.value = role;
    return h('div', { class: 'sitem', draggable: true, style: { '--rc': RC[role] }, ondragstart: (e) => { e.dataTransfer.setData('text/plain', 'story:' + it.id); } },
      h('span', { class: 'num' }, String(i + 1)), h('div', { style: { flex: 1, minWidth: 0 } }, h('div', { style: { fontWeight: 600, fontSize: '.9rem' } }, it.title || 'Untitled'), h('div', { class: 'row small', style: { gap: 4, marginTop: 3 } }, sel, it.ref ? chip(trunc(it.ref, 30), 'acc', it.ref) : chip('Drafted by you'), it.gaps.length ? chip('gap', 'warn', it.gaps.join(' ')) : null)),
      h('div', { class: 'row', style: { gap: 2, flexWrap: 'nowrap' } }, h('button', { class: 'btn sm ghost', 'aria-label': 'Edit', onclick: () => edit(it) }, 'Edit'), h('button', { class: 'btn sm ghost', 'aria-label': 'Move up', disabled: i === 0, onclick: () => mv(i, -1) }, '↑'), h('button', { class: 'btn sm ghost', 'aria-label': 'Move down', disabled: i === B.items.length - 1, onclick: () => mv(i, 1) }, '↓'),
        h('button', { class: 'btn sm ghost', 'aria-label': 'Remove', onclick: () => { B.items.splice(i, 1); touch('board'); ui.sugg = null; again(); } }, '✕')));
  }
  const mv = (i, d) => { const [m] = B.items.splice(i, 1); B.items.splice(i + d, 0, m); commit('board'); ui.sugg = null; again(); };
  function edit(it) {
    modal((box, close) => {
      const t = h('textarea', { rows: 2 }); t.value = it.title; const b = h('textarea', { rows: 8 }); b.value = it.bullets.map((x) => (x.level ? '  ' : '') + x.text).join('\n'); const tk = h('textarea', { rows: 2 }); tk.value = it.takeaway;
      box.append(h('h2', {}, 'Edit this slide'), h('p', { class: 'muted small' }, it.ref ? 'Imported from ' + it.ref + '. Edited text is labelled as yours.' : ''), field('Headline', t), field('Points (one per line, two spaces for a sub-point)', b), field('So what', tk),
        h('div', { class: 'row', style: { justifyContent: 'flex-end', marginTop: 10 } }, h('button', { class: 'btn', onclick: () => close() }, 'Cancel'), h('button', { class: 'btn primary', onclick: () => {
          const old = new Map(it.bullets.map((x) => [x.text, x])); it.title = t.value.slice(0, 200); it.takeaway = tk.value.slice(0, 300);
          it.bullets = b.value.split('\n').filter((l) => l.trim()).slice(0, 14).map((l) => { const x = l.trim(); const o = old.get(x); return { text: x.slice(0, 300), level: /^\s{2,}/.test(l) ? 1 : 0, origin: o ? o.origin : 'user', cite: o ? o.cite : [] }; });
          touch('board'); close(); ui.sugg = null; again(); } }, 'Save')));
    });
  }

  // ----------------------------------------------------------------- suggestions
  async function suggest() {
    try { ui.sugg = await api('POST', `/api/projects/${p.id}/story/suggest`, { items: B.items, flow: B.flow }); again(); } catch (e) { toast(e.message, 'bad'); }
  }
  function suggestCol() {
    const c = h('div', { class: 'bcol' }); c.append(h('h3', {}, 'Flow and edits'));
    const r = ui.sugg;
    if (!r) return c.append(h('div', { class: 'empty', style: { marginTop: 8 } }, 'Pick slides, state your intention, then ask for a suggested flow. Suggestions never change your story until you apply them.')), c;
    const same = r.order.every((id, i) => B.items[i] && B.items[i].id === id);
    c.append(h('div', { class: 'card stack', style: { padding: 12, margin: '6px 0 10px' } }, h('div', { class: 'row between' }, h('b', {}, 'Target: ' + r.target), chip(r.engine === 'model' ? 'Rules + AI notes' : 'Rules', 'dashed')),
      h('div', { class: 'small muted' }, 'Current order'), h('div', { class: 'shape' }, r.shape.current.map((x) => h('i', { style: { '--rc': RC[x] }, title: ROLE_LABEL[x] }))),
      h('div', { class: 'small muted' }, 'Suggested order'), h('div', { class: 'shape' }, r.shape.suggested.map((x) => h('i', { style: { '--rc': RC[x] }, title: ROLE_LABEL[x] }))),
      h('div', { class: 'row', style: { gap: 4 } }, [...new Set(r.shape.suggested)].map(roleChip)),
      same ? h('div', { class: 'notice ok small' }, 'Your order already matches this flow.') : h('button', { class: 'btn primary', onclick: () => { const m = new Map(B.items.map((x) => [x.id, x])); B.items = r.order.map((id) => m.get(id)); touch('board'); toast('Order applied. Undo is available.'); suggest(); } }, 'Apply suggested order')));
    if (r.moves.length) c.append(h('h4', {}, 'Why the order changes'), h('ul', { class: 'small', style: { paddingLeft: 18 } }, r.moves.map((m) => h('li', {}, m.reason))));
    if (r.gaps.length) { c.append(h('h4', {}, 'Missing pieces')); r.gaps.forEach((g) => c.append(h('div', { class: 'notice warn small' }, g.text, ' ', g.action ? h('button', { class: 'btn sm', onclick: () => draft(g) }, g.action === 'draft_answer' ? 'Draft the answer slide' : 'Draft the ask slide') : null))); }
    if (r.mods.length) { c.append(h('h4', {}, 'Suggested edits')); r.mods.forEach((m) => c.append(h('div', { class: 'card stack', style: { padding: 10, marginBottom: 8 } }, h('div', { class: 'row' }, chip({ headline: 'Headline', dense: 'Dense', stale: 'Dated', confidential: 'Confidential', visual: 'Visual', weak_fit: 'Weak fit', duplicate: 'Duplicate', length: 'Length', conflict: 'Conflict' }[m.type] || m.type, ['stale', 'confidential', 'conflict', 'weak_fit', 'duplicate'].includes(m.type) ? 'warn' : ''), m.title ? h('b', { class: 'small' }, trunc(m.title, 40)) : null),
      h('div', { class: 'small' }, m.text), m.apply ? h('div', { class: 'row' }, m.apply.title ? h('div', { class: 'small muted' }, 'New headline: ' + m.apply.title) : null, h('button', { class: 'btn sm', onclick: () => applyMod(m) }, m.apply.remove ? 'Remove from story' : 'Apply')) : null))); }
    if (r.notes && r.notes.length) c.append(h('h4', {}, 'AI notes'), r.notes.map((n) => h('div', { class: 'small', style: { marginBottom: 4 } }, chip('AI', 'dashed'), ' ', n.note)));
    if (!r.moves.length && !r.gaps.length && !r.mods.length) c.append(h('div', { class: 'notice ok' }, 'Nothing to change. The story fits the flow and your intention.'));
    return c;
  }
  function applyMod(m) {
    const it = B.items.find((x) => x.id === m.id); if (!it) return;
    if (m.apply.remove) B.items = B.items.filter((x) => x.id !== m.id);
    else { if (m.apply.title) { it.title = m.apply.title; if (m.apply.bullets_drop_first) { const i = it.bullets.findIndex((b) => b.level === 0); if (i >= 0) it.bullets.splice(i, 1); } } }
    touch('board'); suggest();
  }
  async function draft(g) {
    const r = await api('POST', `/api/projects/${p.id}/story/draft`, { kind: g.action === 'draft_ask' ? 'ask' : 'answer', items: B.items });
    const s = r.slide; s.id = uid('s');
    const first = B.items.findIndex((x) => x.role !== 'title'); const lastMain = B.items.map((x) => x.role).findLastIndex((x) => !['closing', 'appendix'].includes(x));
    if (g.action === 'draft_ask') B.items.splice(lastMain + 1, 0, s); else B.items.splice(first < 0 ? B.items.length : first, 0, s);
    touch('board'); toast('Drafted from your brief. Edit it to say what you mean.'); suggest();
  }
  async function send() {
    const go2 = (replace) => {
      const items = B.items.map((x) => { const c = JSON.parse(JSON.stringify(x)); c.id = uid('s'); c.approved = false; if (c.kind === 'title') { c.takeaway = c.takeaway || (c.bullets[0] ? c.bullets[0].text : ''); c.bullets = []; } return c; });
      if (!items.some((x) => x.kind === 'title') && !(!replace && p.slides.some((x) => x.kind === 'title'))) items.unshift({ id: uid('s'), kind: 'title', layout: 'key_message', title: p.name, purpose: 'Opening', bullets: [], quote: '', quote_by: '', takeaway: p.brief.who.slice(0, 120), notes: '', visual: 'Title slide', transition: '', facilitation: '', node_id: '', role: 'title', ref: '', sources: [], gaps: [], approved: false, locked: false, override_layout: '' });
      p.slides = replace ? items : [...p.slides, ...items]; p.storyline.approved = false; if (!p.storyline.thesis) p.storyline.thesis = B.flow.intent || p.governing;
      commit('story to slides'); toast(`${items.length} slides sent to the editor.`); go('slides');
    };
    if (!p.slides.length) return go2(true);
    modal((box, close) => box.append(h('h2', {}, 'Send to Slides'), h('p', {}, `You already have ${p.slides.length} slide(s). Replace them with this story, or add the story after them?`), h('div', { class: 'row', style: { justifyContent: 'flex-end' } },
      h('button', { class: 'btn', onclick: () => close() }, 'Cancel'), h('button', { class: 'btn', onclick: () => { close(); go2(false); } }, 'Add after'), h('button', { class: 'btn primary', onclick: () => { close(); go2(true); } }, 'Replace'))), { small: true });
  }

  await load(); build();
}
