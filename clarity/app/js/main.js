import { h, $, clear, api, setCsrf, toast, modal, confirmBox, promptBox, chip, ago } from './util.js';
import { S, on, emit, openProject, closeProject, undo, redo, commit, saveNow } from './state.js';
import { scopeLabel, openScope } from './scope.js';

const STEPS = [
  ['brief', 'Brief', () => import('./brief.js')], ['sources', 'Sources and scope', () => import('./sources.js')],
  ['board', 'Story board', () => import('./board.js')], ['map', 'Mind map', () => import('./map.js')], ['story', 'Storyline', () => import('./story.js')],
  ['slides', 'Slides', () => import('./slides.js')], ['template', 'Template and brand', () => import('./template.js')],
  ['export', 'Review and export', () => import('./exportview.js')],
];
const TOOLS = [['facilitate', 'Facilitate', () => import('./facilitate.js')], ['kb', 'Knowledge base', () => import('./kb.js')], ['security', 'Security and audit', () => import('./security.js')]];
const done = (id) => { const p = S.project; if (!p) return false; return {
  brief: !!(p.brief.purpose && (p.brief.message || p.governing)), sources: !!(p.scope.mode && (p.sources.length || p.scope.mode === 'none')), map: p.map.nodes.length > 2,
  board: !!(p.board && p.board.items.length), story: p.slides.length > 0 && p.storyline.approved, slides: p.slides.length > 0 && p.slides.every((s) => s.approved), template: !!p.template, export: false }[id]; };

function drawNav() {
  const nav = clear($('#nav'));
  nav.append(h('div', { class: 'brand' }, h('i'), h('b', {}, 'Clarity')));
  nav.append(h('button', { 'aria-current': S.view === 'dashboard' ? 'page' : null, onclick: () => go('dashboard') }, h('span', { class: 'n' }, '⌂'), h('span', { class: 't' }, 'Projects')));
  if (S.project) {
    nav.append(h('div', { class: 'group' }, 'Journey'));
    STEPS.forEach(([id, label], i) => nav.append(h('button', { 'aria-current': S.view === id ? 'page' : null, onclick: () => go(id) },
      h('span', { class: 'n' + (done(id) ? ' done' : '') }, done(id) ? '✓' : String(i + 1)), h('span', { class: 't' }, label))));
    nav.append(h('div', { class: 'group' }, 'Workspace'));
    TOOLS.forEach(([id, label]) => nav.append(h('button', { 'aria-current': S.view === id ? 'page' : null, onclick: () => go(id) }, h('span', { class: 'n' }, '•'), h('span', { class: 't' }, label))));
  } else nav.append(h('div', { class: 'group' }, 'Workspace'), ...TOOLS.slice(1).map(([id, label]) => h('button', { 'aria-current': S.view === id ? 'page' : null, onclick: () => go(id) }, h('span', { class: 'n' }, '•'), h('span', { class: 't' }, label))));
}

function drawTop() {
  const top = clear($('#top')), p = S.project;
  if (!p) { top.append(h('div', { class: 'title' }, 'Clarity'), aiChip()); return; }
  const name = h('input', { type: 'text', value: p.name, 'aria-label': 'Project name', style: { fontWeight: 650, maxWidth: '320px', border: '1px solid transparent', background: 'transparent' }, oninput: (e) => { p.name = e.target.value; commit('name'); } });
  const st = { saved: ['Saved', 'ok'], saving: ['Saving…', ''], unsaved: ['Unsaved changes', 'warn'], error: ['Not saved', 'bad'] }[S.status];
  top.append(name, h('span', { class: 'sp' }), chip(st[0], st[1]),
    h('button', { class: 'btn sm', title: 'Undo', disabled: !S.undo.length, onclick: undo }, '↶ Undo'), h('button', { class: 'btn sm', title: 'Redo', disabled: !S.redo.length, onclick: redo }, '↷ Redo'),
    h('button', { class: 'btn sm', onclick: history }, 'History'),
    h('button', { class: 'chip ' + (p.scope.mode ? 'acc' : 'warn'), style: { cursor: 'pointer', border: 0 }, title: 'Which sources the AI may use', onclick: () => openScope() }, scopeLabel(p)),
    h('span', { class: 'chip' }, p.security.classification), aiChip());
}
function aiChip() {
  const a = S.ai || {};
  return h('button', { class: 'chip ' + (a.local === false ? 'warn' : 'ok'), style: { cursor: 'pointer', border: 0 }, title: a.note || '', onclick: () => go('security') }, a.name ? `${a.local ? 'Local' : 'Remote'} · ${a.name === 'offline' ? 'built-in rules' : a.model}` : 'AI');
}

async function history() {
  const { versions } = await api('GET', `/api/projects/${S.project.id}/versions`);
  modal((b, close) => {
    b.append(h('h2', {}, 'Version history'), h('p', { class: 'muted' }, 'Snapshots are taken when slides or map size change, and when you save one by name. Restoring keeps your current state as a snapshot first.'),
      h('div', { class: 'row' }, h('button', { class: 'btn primary', onclick: async () => { const l = await promptBox('Name this snapshot', 'Alternative: '); if (l) { await saveNow(); await api('POST', `/api/projects/${S.project.id}/versions`, { label: l }); toast('Snapshot saved'); close(); } } }, 'Save a named snapshot')),
      h('table', {}, h('thead', {}, h('tr', {}, h('th', {}, 'When'), h('th', {}, 'Label'), h('th', {}, 'Map nodes'), h('th', {}, 'Slides'), h('th', {}))),
        h('tbody', {}, versions.map((v) => h('tr', {}, h('td', {}, ago(v.ts)), h('td', {}, v.label), h('td', {}, v.nodes), h('td', {}, v.slides), h('td', {}, h('button', { class: 'btn sm', onclick: async () => {
          if (!await confirmBox('Restore this version? Your current state is saved as a snapshot first.', 'Restore')) return;
          S.project = await api('POST', `/api/projects/${S.project.id}/versions/${v.id}/restore`, {}); await openProject(S.project.id); close(); go(S.view); toast('Version restored'); } }, 'Restore')))))),
      h('div', { class: 'row', style: { justifyContent: 'flex-end', marginTop: '10px' } }, h('button', { class: 'btn', onclick: () => close() }, 'Close')));
  });
}

let token = 0;
export async function go(view) {
  if (!S.project && !['dashboard', 'kb', 'security'].includes(view)) view = 'dashboard';
  S.view = view; const my = ++token;
  drawNav(); drawTop();
  const root = clear($('#view')); root.scrollTop = 0;
  try {
    let mod;
    if (view === 'dashboard') mod = { render: dashboard };
    else mod = await ([...STEPS, ...TOOLS].find((x) => x[0] === view)[2]());
    if (my !== token) return;
    await (mod.render || mod.default)(root);
  } catch (e) { console.error(e); root.append(h('div', { class: 'notice bad' }, 'This screen failed to load: ' + e.message)); }
}

async function dashboard(root) {
  const { projects } = await api('GET', '/api/projects');
  const page = h('div', { class: 'page' });
  page.append(h('h1', {}, 'Projects'), h('p', { class: 'lede' }, 'Clarity helps you think first, then build. Each project moves from a brief to a mind map, a storyline, and an editable presentation. Everything stays on this computer.'));
  const nameIn = h('input', { type: 'text', placeholder: 'Name your presentation', 'aria-label': 'New project name', onkeydown: (e) => { if (e.key === 'Enter') create.click(); } });
  const create = h('button', { class: 'btn primary', onclick: async () => { const p = await api('POST', '/api/projects', { name: nameIn.value || 'Untitled presentation' }); await openProject(p.id); go('brief'); } }, 'Start a project');
  page.append(h('div', { class: 'card row' }, h('div', { style: { flex: 1, minWidth: '220px' } }, nameIn), create));
  if (!projects.length) page.append(h('div', { class: 'empty' }, 'No projects yet. Start with the brief: who you are talking to and what you need from them.'));
  const grid = h('div', { class: 'grid g3' });
  for (const p of projects) grid.append(h('div', { class: 'card proj', tabindex: 0, role: 'button', onclick: async () => { await openProject(p.id); go('brief'); }, onkeydown: async (e) => { if (e.key === 'Enter') { await openProject(p.id); go('brief'); } } },
    h('h3', {}, p.name), h('div', { class: 'row' }, chip(p.classification), chip(`${p.nodes} map nodes`), chip(`${p.slides} slides`)), h('div', { class: 'muted small', style: { marginTop: '6px' } }, 'Edited ' + ago(p.updated)),
    h('div', { class: 'row', style: { justifyContent: 'flex-end' } }, h('button', { class: 'btn sm danger', onclick: async (e) => { e.stopPropagation(); if (await confirmBox(`Delete "${p.name}" and its sources permanently?`, 'Delete', true)) { await api('DELETE', '/api/projects/' + p.id); go('dashboard'); } } }, 'Delete'))));
  page.append(grid);
  root.append(page);
}

async function boot() {
  const s = await api('GET', '/api/session'); setCsrf(s.csrf); S.ai = s.ai; S.meta = await api('GET', '/api/meta');
  on((k) => { if (k === 'status') { drawTop(); drawNav(); } else if (k === 'project') { drawNav(); drawTop(); } else if (k === 'rerender') go(S.view); });
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) { e.preventDefault(); e.shiftKey ? redo() : undo(); }
  });
  window.addEventListener('beforeunload', (e) => { if (S.status === 'unsaved' || S.status === 'saving') { e.preventDefault(); e.returnValue = ''; } });
  go('dashboard');
}
boot().catch((e) => { $('#view').append(h('div', { class: 'notice bad' }, 'Could not start: ' + e.message + '. Open the full link printed in the terminal.')); });
