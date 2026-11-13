import { h, api, chip, toast, clear, field, uid, trunc, confirmBox } from './util.js';
import { S, commit } from './state.js';
import { reviewProposal } from './map.js';
import { go } from './main.js';

const ui = { tab: 'agenda', role: 'facilitator', silent: false, cur: -1, left: 0, running: false, iv: null, dots: +(sessionStorage.getItem('cd_dots') || 0) };
const ACT = ['Brainstorm', 'Group', 'Vote', 'Discuss', 'Decide', 'Break'];
const TABS = [['agenda', 'Agenda and timer'], ['ideas', 'Brainstorm'], ['affinity', 'Affinity map'], ['vote', 'Vote'], ['parking', 'Parking lot'], ['decisions', 'Decisions and actions'], ['qa', 'Questions'], ['summary', 'Summary']];

export async function render(rootEl) {
  const p = S.project, f = p.facilitation, vis = f.visibility, fac = () => ui.role === 'facilitator';
  const page = h('div', { class: 'page' }); rootEl.append(page);
  const again = () => { clear(page); build(); };
  const fmt = (s) => `${Math.floor(Math.max(0, s) / 60)}:${String(Math.floor(Math.max(0, s) % 60)).padStart(2, '0')}`;
  function build() {
    page.append(h('div', { class: 'row between' }, h('div', {}, h('h1', { style: { margin: 0 } }, 'Facilitation workspace'), h('p', { class: 'muted', style: { margin: 0 } }, 'Run a session on this screen: capture ideas silently, group, vote, decide, then turn the outcome into a storyline.')),
      h('div', { class: 'seg', role: 'group', 'aria-label': 'View' }, ['facilitator', 'participant'].map((r) => h('button', { 'aria-pressed': ui.role === r, onclick: () => { ui.role = r; if (r === 'participant' && !TABS.some(([t]) => t === ui.tab && t !== 'summary')) ui.tab = 'ideas'; again(); } }, r === 'facilitator' ? 'Facilitator view' : 'Participant view')))));
    if (!fac()) page.append(h('div', { class: 'notice small' }, 'Participant view hides facilitator controls and respects what the facilitator allows. Use it when sharing your screen.'));
    else page.append(h('div', { class: 'card row' }, h('b', {}, 'Participants can:'), [['allow_edit', 'add ideas'], ['allow_vote', 'vote'], ['allow_anon', 'post anonymously'], ['show_votes', 'see vote counts']].map(([k, l]) => h('label', { class: 'row small' }, h('input', { type: 'checkbox', checked: vis[k], onchange: (e) => { vis[k] = e.target.checked; commit('facilitation'); } }), l)),
      h('label', { class: 'row small' }, h('input', { type: 'checkbox', checked: ui.silent, onchange: (e) => { ui.silent = e.target.checked; again(); } }), 'Silent phase (hide ideas until revealed)')));
    page.append(h('div', { class: 'seg', style: { margin: '6px 0 14px', flexWrap: 'wrap' } }, TABS.filter(([t]) => fac() || !['summary'].includes(t)).map(([t, l]) => h('button', { 'aria-pressed': ui.tab === t, onclick: () => { ui.tab = t; again(); } }, l))));
    const body = h('div'); page.append(body); ({ agenda, ideas, affinity, vote, parking, decisions, qa, summary }[ui.tab] || agenda)(body);
  }
  // ---------- agenda
  function agenda(b) {
    const total = f.agenda.reduce((a, x) => a + x.minutes, 0);
    b.append(h('div', { class: 'card stack' }, h('div', { class: 'row between' }, h('h3', { style: { margin: 0 } }, 'Agenda'), h('span', { class: total > p.brief.minutes ? 'chip warn' : 'chip' }, `${total} of ${p.brief.minutes} minutes planned`)),
      f.agenda.length ? null : h('div', { class: 'muted' }, fac() ? 'Add timeboxed activities. A good session alternates silent capture, grouping, voting, and deciding.' : 'No agenda yet.')));
    const card = b.firstChild;
    f.agenda.forEach((a, i) => { const row = h('div', { class: 'row', style: { background: ui.cur === i ? 'var(--accent-soft)' : '', borderRadius: 8, padding: 4 } },
      h('input', { type: 'checkbox', checked: a.done, disabled: !fac(), 'aria-label': 'Done', onchange: (e) => { a.done = e.target.checked; commit('agenda'); again(); } }),
      fac() ? h('input', { type: 'text', value: a.title, style: { flex: 1, minWidth: 160 }, oninput: (e) => { a.title = e.target.value; commit('agenda'); } }) : h('span', { style: { flex: 1, textDecoration: a.done ? 'line-through' : '' } }, a.title),
      fac() ? h('select', { onchange: (e) => { a.activity = e.target.value; commit('agenda'); } }, ACT.map((x) => h('option', { value: x, selected: a.activity === x }, x))) : chip(a.activity || 'Activity'),
      fac() ? h('input', { type: 'number', min: 0, max: 480, value: a.minutes, style: { width: 70 }, oninput: (e) => { a.minutes = +e.target.value || 0; commit('agenda'); } }) : chip(a.minutes + ' min'),
      fac() ? h('button', { class: 'btn sm', onclick: () => start(i) }, ui.cur === i ? 'Restart' : 'Start') : null, fac() ? h('button', { class: 'btn sm ghost', onclick: () => { f.agenda.splice(i, 1); commit('agenda'); again(); } }, 'Remove') : null); card.append(row); });
    if (fac()) card.append(h('div', { class: 'row' }, h('button', { class: 'btn sm', onclick: () => { f.agenda.push({ id: uid('a'), title: 'New activity', minutes: 10, done: false, activity: 'Discuss' }); commit('agenda'); again(); } }, 'Add activity'),
      h('button', { class: 'btn sm', onclick: () => { f.agenda = [['Frame the objective', 5, 'Discuss'], ['Silent idea capture', 8, 'Brainstorm'], ['Group similar ideas', 10, 'Group'], ['Vote on priorities', 5, 'Vote'], ['Decide and assign owners', 10, 'Decide']].map(([t, m, a]) => ({ id: uid('a'), title: t, minutes: m, done: false, activity: a })); commit('agenda'); again(); } }, 'Use a standard workshop flow')));
    const t = ui.cur >= 0 && f.agenda[ui.cur];
    if (t) { const clock = h('div', { class: 'timer' }, fmt(ui.left)); const bar = h('div', { class: 'bar' }, h('i', { style: { width: '0%' } })); const upd = () => { clock.textContent = fmt(ui.left); bar.firstChild.style.width = (100 - 100 * ui.left / Math.max(1, t.minutes * 60)) + '%'; clock.style.color = ui.left < 60 ? 'var(--bad)' : ''; };
      b.append(h('div', { class: 'card stack' }, h('div', { class: 'row between' }, h('h3', { style: { margin: 0 } }, 'Now: ' + t.title), chip(t.activity || '')), clock, bar, fac() ? h('div', { class: 'row' }, h('button', { class: 'btn', onclick: () => { ui.running = !ui.running; again(); } }, ui.running ? 'Pause' : 'Resume'), h('button', { class: 'btn', onclick: () => { ui.left += 60; upd(); } }, '+1 min'),
        h('button', { class: 'btn primary', onclick: () => { t.done = true; commit('agenda'); const n = ui.cur + 1; if (f.agenda[n]) start(n); else { stop(); } again(); } }, 'Done, next')) : null));
      ui._upd = upd; upd(); }
  }
  function start(i) { stop(); ui.cur = i; ui.left = f.agenda[i].minutes * 60; ui.running = true; ui.iv = setInterval(() => { if (!ui.running) return; ui.left--; if (ui._upd && document.body.contains(page)) ui._upd(); if (ui.left <= 0) { toast('Time is up for: ' + f.agenda[ui.cur].title); ui.running = false; again(); } if (!document.body.contains(page)) stop(); }, 1000); again(); }
  function stop() { if (ui.iv) clearInterval(ui.iv); ui.iv = null; ui.running = false; }
  // ---------- ideas
  function ideas(b) {
    const hidden = ui.silent || (!fac() && false);
    const name = h('input', { type: 'text', placeholder: 'Your name (optional)', style: { maxWidth: 200 } }); const anon = h('input', { type: 'checkbox', disabled: !vis.allow_anon && !fac() });
    const inp = h('input', { type: 'text', placeholder: 'One idea, then Enter', 'aria-label': 'New idea', onkeydown: (e) => { if (e.key === 'Enter') add.click(); } });
    const add = h('button', { class: 'btn primary', onclick: () => { if (!inp.value.trim()) return; if (!fac() && !vis.allow_edit) return toast('The facilitator has paused idea entry.', 'bad'); f.ideas.push({ id: uid('i'), text: inp.value.trim().slice(0, 300), by: anon.checked ? '' : name.value.slice(0, 60), anon: anon.checked, group: '', votes: 0 }); inp.value = ''; commit('ideas'); again(); setTimeout(() => document.querySelector('[aria-label="New idea"]')?.focus(), 30); } }, 'Add');
    b.append(h('div', { class: 'card stack' }, h('div', { class: 'row' }, inp, add), h('div', { class: 'row' }, name, h('label', { class: 'row small' }, anon, 'Post anonymously'))));
    if (hidden && !(fac() && false)) b.append(h('div', { class: 'notice' }, `${f.ideas.length} idea(s) captured. Hidden during the silent phase.`, fac() ? h('button', { class: 'btn sm', style: { marginLeft: 8 }, onclick: () => { ui.silent = false; again(); } }, 'Reveal ideas') : null));
    else b.append(h('div', { class: 'grid g3' }, f.ideas.map((i) => h('div', { class: 'kcard' }, i.text, h('div', { class: 'row tiny muted' }, i.anon ? 'Anonymous' : (i.by || 'Facilitator'), fac() ? h('button', { class: 'btn sm ghost', onclick: () => { f.ideas = f.ideas.filter((x) => x !== i); commit('ideas'); again(); } }, 'Remove') : null)))), !f.ideas.length ? h('div', { class: 'empty' }, 'No ideas yet.') : null);
  }
  function affinity(b) {
    const gn = h('input', { type: 'text', placeholder: 'Name a group (theme)' });
    if (fac()) b.append(h('div', { class: 'card row' }, gn, h('button', { class: 'btn', onclick: () => { if (gn.value.trim()) { f.groups.push({ id: uid('g'), name: gn.value.trim().slice(0, 100) }); commit('groups'); again(); } } }, 'Add group')));
    const cols = h('div', { class: 'grid g3' });
    const col = (g) => { const c = h('div', { class: 'card stack', ondragover: (e) => e.preventDefault(), ondrop: (e) => { const i = f.ideas.find((x) => x.id === e.dataTransfer.getData('text/plain')); if (i && (fac() || vis.allow_edit)) { i.group = g ? g.id : ''; commit('ideas'); again(); } } }, h('div', { class: 'row between' }, h('h3', { style: { margin: 0 } }, g ? g.name : 'Ungrouped'), g && fac() ? h('button', { class: 'btn sm ghost', onclick: () => { f.groups = f.groups.filter((x) => x !== g); f.ideas.forEach((i) => { if (i.group === g.id) i.group = ''; }); commit('groups'); again(); } }, 'Remove') : null));
      f.ideas.filter((i) => (g ? i.group === g.id : !f.groups.some((x) => x.id === i.group))).forEach((i) => c.append(h('div', { class: 'kcard', draggable: true, ondragstart: (e) => e.dataTransfer.setData('text/plain', i.id) }, i.text,
        h('select', { 'aria-label': 'Group', style: { marginTop: 6 }, disabled: !fac() && !vis.allow_edit, onchange: (e) => { i.group = e.target.value; commit('ideas'); again(); } }, h('option', { value: '' }, 'Ungrouped'), f.groups.map((x) => h('option', { value: x.id, selected: i.group === x.id }, x.name)))))); return c; };
    cols.append(col(null), f.groups.map(col)); b.append(cols);
  }
  function vote(b) {
    const budget = f.vote_budget, left = budget - ui.dots;
    b.append(h('div', { class: 'card row between' }, h('div', {}, h('b', {}, `Dots left: ${left} of ${budget}`), h('span', { class: 'muted small' }, ' Spread them or stack them. Vote for what matters most.')), fac() ? h('div', { class: 'row' }, h('label', { class: 'row small' }, 'Dots per person', h('input', { type: 'number', min: 1, max: 20, value: budget, style: { width: 64 }, onchange: (e) => { f.vote_budget = +e.target.value || 3; commit('facilitation'); again(); } })),
      h('button', { class: 'btn sm', onclick: () => { ui.dots = 0; sessionStorage.setItem('cd_dots', 0); again(); } }, 'Reset my dots'), h('button', { class: 'btn sm danger', onclick: async () => { if (await confirmBox('Clear all votes?', 'Clear', true)) { f.ideas.forEach((i) => { i.votes = 0; }); ui.dots = 0; sessionStorage.setItem('cd_dots', 0); commit('votes'); again(); } } }, 'Clear votes')) : null));
    const sorted = [...f.ideas].sort((a, c) => (vis.show_votes || fac() ? c.votes - a.votes : 0));
    b.append(h('div', { class: 'stack' }, sorted.map((i) => h('div', { class: 'card row between', style: { marginBottom: 0 } }, h('span', {}, i.text, i.group ? chip((f.groups.find((g) => g.id === i.group) || {}).name || '', 'acc') : null),
      h('div', { class: 'row' }, vis.show_votes || fac() ? chip(`${i.votes} vote${i.votes === 1 ? '' : 's'}`, i.votes ? 'ok' : '') : null,
        h('button', { class: 'btn sm', disabled: left <= 0 || (!fac() && !vis.allow_vote), onclick: () => { i.votes++; ui.dots++; sessionStorage.setItem('cd_dots', ui.dots); commit('votes'); again(); } }, '+ Dot'), h('button', { class: 'btn sm', disabled: i.votes <= 0 || ui.dots <= 0, onclick: () => { i.votes--; ui.dots--; sessionStorage.setItem('cd_dots', ui.dots); commit('votes'); again(); } }, '− Dot')))), !f.ideas.length ? h('div', { class: 'empty' }, 'Capture ideas first.') : null));
  }
  function simpleList(b, arr, label, ph, key = 'text') {
    const inp = h('input', { type: 'text', placeholder: ph, onkeydown: (e) => { if (e.key === 'Enter') add.click(); } }); const add = h('button', { class: 'btn primary', onclick: () => { if (inp.value.trim()) { arr.push({ id: uid('p'), [key]: inp.value.trim().slice(0, 400), by: '' }); commit('facilitation'); again(); } } }, 'Add');
    b.append(h('div', { class: 'card row' }, inp, add), h('div', { class: 'stack' }, arr.map((x) => h('div', { class: 'card row between', style: { marginBottom: 0 } }, x[key], fac() ? h('div', { class: 'row' }, h('button', { class: 'btn sm', onclick: () => { const i = arr.indexOf(x); arr.splice(i, 1); f.ideas.push({ id: uid('i'), text: x[key], by: '', anon: false, group: '', votes: 0 }); commit('facilitation'); again(); } }, 'Move to ideas'), h('button', { class: 'btn sm ghost', onclick: () => { arr.splice(arr.indexOf(x), 1); commit('facilitation'); again(); } }, 'Remove')) : null)), !arr.length ? h('div', { class: 'empty' }, label) : null));
  }
  const parking = (b) => simpleList(b, f.parking, 'Nothing parked. Use this for good points that are off-topic right now.', 'Park a topic for later');
  function decisions(b) {
    const kind = h('select', {}, [['decision', 'Decision'], ['action', 'Action']].map(([v, l]) => h('option', { value: v }, l))), txt = h('input', { type: 'text', placeholder: 'What was decided, or what needs doing', style: { flex: 1, minWidth: 220 } }), own = h('input', { type: 'text', placeholder: 'Owner', style: { width: 120 } }), due = h('input', { type: 'date', style: { width: 150 } });
    b.append(h('div', { class: 'card row' }, kind, txt, own, due, h('button', { class: 'btn primary', onclick: () => { if (!txt.value.trim()) return; f.decisions.push({ id: uid('d'), text: txt.value.trim(), owner: own.value, due: due.value, kind: kind.value, done: false }); commit('decisions'); again(); } }, 'Log')));
    b.append(h('div', { class: 'card' }, h('table', {}, h('thead', {}, h('tr', {}, ['', 'Type', 'What', 'Owner', 'Due', ''].map((x) => h('th', {}, x)))), h('tbody', {}, f.decisions.map((d) => h('tr', {}, h('td', {}, h('input', { type: 'checkbox', checked: d.done, onchange: (e) => { d.done = e.target.checked; commit('decisions'); } })), h('td', {}, chip(d.kind === 'action' ? 'Action' : 'Decision', d.kind === 'action' ? 'acc' : 'ok')), h('td', {}, d.text), h('td', {}, d.owner || h('span', { class: 'muted' }, d.kind === 'action' ? 'Owner needed' : '')), h('td', {}, d.due || h('span', { class: 'muted' }, d.kind === 'action' ? 'Date needed' : '')), h('td', {}, h('button', { class: 'btn sm ghost', onclick: () => { f.decisions = f.decisions.filter((x) => x !== d); commit('decisions'); again(); } }, 'Remove'))))))));
  }
  function qa(b) {
    b.append(h('p', { class: 'muted' }, 'List the questions and objections you expect, with your best answer. Answered ones become an appendix slide.'));
    const q = h('input', { type: 'text', placeholder: 'A tough question you expect', style: { flex: 1 } });
    b.append(h('div', { class: 'card row' }, q, h('button', { class: 'btn primary', onclick: () => { if (q.value.trim()) { f.questions.push({ id: uid('q'), q: q.value.trim(), a: '' }); commit('qa'); again(); } } }, 'Add')));
    f.questions.forEach((x) => { const a = h('textarea', { rows: 2, placeholder: 'Your answer' }); a.value = x.a; a.addEventListener('input', () => { x.a = a.value; commit('qa'); }); b.append(h('div', { class: 'card stack' }, h('div', { class: 'row between' }, h('b', {}, x.q), h('button', { class: 'btn sm ghost', onclick: () => { f.questions = f.questions.filter((y) => y !== x); commit('qa'); again(); } }, 'Remove')), a)); });
  }
  function summary(b) {
    const ta = h('textarea', { rows: 14 }); ta.value = f.summary; ta.addEventListener('input', () => { f.summary = ta.value; commit('summary'); });
    b.append(h('div', { class: 'card stack' }, h('div', { class: 'row' }, h('button', { class: 'btn primary', onclick: async () => { const r = await api('POST', `/api/projects/${p.id}/facilitation/summary`, {}); f.summary = r.summary; commit('summary'); again(); } }, 'Generate session summary'),
      h('button', { class: 'btn', onclick: async () => { const r = await api('POST', `/api/projects/${p.id}/facilitation/to-map`, {}); if (!r.branches.length) return toast('Add and group some ideas first.', 'bad'); reviewProposal(r.branches, { engine: 'rules', notes: ['These come from your workshop. Votes set the importance stars.'], gaps: [] }, 'Add workshop output to the map'); } }, 'Turn ideas into map branches'), h('button', { class: 'btn', onclick: () => go('map') }, 'Open the map')), ta));
  }
  build();
}
