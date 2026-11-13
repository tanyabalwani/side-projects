import { h, api, chip, toast, clear, field, confirmBox, trunc } from './util.js';

export async function render(rootEl) {
  const page = h('div', { class: 'page' }); rootEl.append(page);
  const draw = async () => {
    const kb = await api('GET', '/api/kb'); clear(page);
    page.append(h('h1', {}, 'Knowledge base'), h('p', { class: 'lede' }, 'Approved messaging, research, past decks, and evidence the AI may draw on when you allow it. Only approved, in-date documents are used automatically. Everything else is flagged and left out until you include it on purpose.'));
    page.append(h('div', { class: 'row' }, chip(`${kb.count} documents`), chip(`${kb.eligible} eligible for automatic use`, 'ok'), chip(`${kb.count - kb.eligible} excluded`, kb.count - kb.eligible ? 'warn' : '')));
    // folders
    const path = h('input', { type: 'text', placeholder: '/path/to/team/knowledge-folder' });
    page.append(h('h2', { style: { marginTop: 18 } }, 'Folders'), h('div', { class: 'card stack' },
      h('div', { class: 'row' }, path, h('button', { class: 'btn primary', onclick: async () => { try { await api('POST', '/api/kb/folders', { path: path.value }); toast('Folder added'); draw(); } catch (e) { toast(e.message, 'bad'); } } }, 'Add folder')),
      h('p', { class: 'muted small', style: { margin: 0 } }, 'Folders are read in place, never copied or changed. Hidden files, credentials, keys, and symbolic links are skipped. The tool reads only what your account can already open.'),
      kb.folders.length ? h('table', {}, h('tbody', {}, kb.folders.map((f) => h('tr', {}, h('td', {}, h('b', {}, f.name), h('div', { class: 'muted tiny' }, f.path)), h('td', {}, h('label', { class: 'row small' }, h('input', { type: 'checkbox', checked: f.enabled, onchange: async (e) => { await api('PUT', '/api/kb/folders/' + f.id, { enabled: e.target.checked }); draw(); } }), 'Enabled')),
        h('td', {}, h('button', { class: 'btn sm danger', onclick: async () => { if (await confirmBox(`Stop using "${f.name}"? Files stay where they are.`, 'Remove', true)) { await api('DELETE', '/api/kb/folders/' + f.id); draw(); } } }, 'Remove')))))) : h('div', { class: 'muted small' }, 'No folders yet.')));
    // upload
    const fi = h('input', { type: 'file', multiple: true, hidden: true, accept: '.txt,.md,.pdf,.docx,.pptx,.xlsx,.html,.csv', onchange: async () => { for (const f of fi.files) { try { await api('POST', '/api/kb/upload', f, { raw: true, filename: f.name }); toast('Added ' + f.name); } catch (e) { toast(`${f.name}: ${e.message}`, 'bad'); } } draw(); } });
    page.append(h('div', { class: 'card row between' }, h('div', {}, h('b', {}, 'Library'), h('div', { class: 'muted small' }, 'Upload approved messaging, brand guidelines, previous decks. Re-uploading a file with the same name creates a new version and marks the old one superseded. Exact duplicates are refused.')), h('button', { class: 'btn', onclick: () => fi.click() }, 'Upload documents'), fi));
    // search
    const q = h('input', { type: 'search', placeholder: 'Search the knowledge base', 'aria-label': 'Search', onkeydown: (e) => { if (e.key === 'Enter') go.click(); } }), res = h('div', { class: 'stack' });
    const go = h('button', { class: 'btn', onclick: async () => { const r = await api('POST', '/api/kb/search', { q: q.value }); clear(res); if (!r.hits.length) res.append(h('div', { class: 'muted' }, 'No matches among eligible documents.')); r.hits.forEach((x) => res.append(h('div', { class: 'card', style: { marginBottom: 0 } }, h('b', {}, x.name), ' ', x.owner ? chip('Owner: ' + x.owner) : null, h('div', { class: 'small' }, x.snippet)))); } }, 'Search');
    page.append(h('h2', {}, 'Search'), h('div', { class: 'row' }, q, go), res);
    // documents
    const filt = h('input', { type: 'search', placeholder: 'Filter by name, tag, owner', 'aria-label': 'Filter', oninput: () => rows() }), st = h('select', { onchange: () => rows() }, [['', 'All statuses'], ['approved', 'Approved'], ['draft', 'Draft'], ['superseded', 'Superseded'], ['archived', 'Archived']].map(([v, l]) => h('option', { value: v }, l)));
    const tb = h('tbody');
    const upd = async (d, fields) => { await api('PUT', '/api/kb/docs/' + d.id, fields); Object.assign(d, fields); };
    const rows = () => { clear(tb); kb.docs.filter((d) => (!st.value || d.status === st.value) && (!filt.value || (d.name + d.tags.join(' ') + d.owner).toLowerCase().includes(filt.value.toLowerCase()))).forEach((d) => {
      tb.append(h('tr', {}, h('td', {}, h('b', {}, d.name), h('div', { class: 'tiny muted' }, d.origin === 'library' ? 'Library · v' + d.version : d.source + (d.path_rel ? ' / ' + trunc(d.path_rel, 40) : ''))),
        h('td', {}, d.origin === 'library' ? h('select', { onchange: (e) => upd(d, { status: e.target.value }).then(draw) }, ['approved', 'draft', 'superseded', 'archived'].map((s) => h('option', { value: s, selected: d.status === s }, s))) : chip(d.status), d.flags.length ? h('div', {}, d.flags.map((f) => chip(f, 'warn'))) : null),
        h('td', {}, h('input', { type: 'text', value: d.owner, placeholder: 'Owner', style: { width: 110 }, onchange: (e) => upd(d, { owner: e.target.value }) })), h('td', {}, h('input', { type: 'text', value: d.tags.join(', '), placeholder: 'tags', style: { width: 130 }, onchange: (e) => upd(d, { tags: e.target.value.split(',').map((x) => x.trim()).filter(Boolean) }) })),
        h('td', {}, h('input', { type: 'date', value: d.review_by, style: { width: 140 }, onchange: (e) => upd(d, { review_by: e.target.value }).then(draw) })), h('td', {}, h('select', { onchange: (e) => upd(d, { classification: e.target.value }) }, ['public', 'internal', 'confidential', 'restricted'].map((c) => h('option', { value: c, selected: d.classification === c }, c)))),
        h('td', {}, d.origin === 'library' ? h('button', { class: 'btn sm danger', onclick: async () => { if (await confirmBox(`Delete "${d.name}" from the library?`, 'Delete', true)) { await api('DELETE', '/api/kb/docs/' + d.id); draw(); } } }, 'Delete') : null))); }); };
    page.append(h('h2', {}, 'Documents'), h('div', { class: 'row' }, filt, st), h('div', { class: 'card', style: { overflow: 'auto' } }, h('table', {}, h('thead', {}, h('tr', {}, ['Document', 'Status', 'Owner', 'Tags', 'Review by', 'Class', ''].map((x) => h('th', {}, x)))), tb)));
    rows();
  };
  draw();
}
