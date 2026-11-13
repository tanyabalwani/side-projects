import { h, api, chip, toast, clear, modal, confirmBox, field, trunc } from './util.js';
import { S, saveNow } from './state.js';
import { openScope, scopeLabel } from './scope.js';
import { go } from './main.js';

const ORIGIN = { provided: ['Provided by you', 'acc'], external: ['External web', 'warn'], internal: ['Internal KB', 'ok'] };

export async function render(rootEl) {
  const p = S.project;
  const page = h('div', { class: 'page' });
  page.append(h('h1', {}, 'Bring in your material'), h('p', { class: 'lede' }, 'Paste notes, drop documents, or add links. Each source keeps its title and origin so every slide can point back to it. Nothing here is sent anywhere.'));
  const list = h('div', { class: 'stack' });
  const check = h('div');

  // inputs
  const name = h('input', { type: 'text', placeholder: 'Title (for example: Interview notes 12 Nov)' });
  const text = h('textarea', { rows: 6, placeholder: 'Paste a brain dump, meeting notes, a transcript…' });
  const addText = h('button', { class: 'btn primary', onclick: async () => {
    try { const r = await api('POST', `/api/projects/${p.id}/sources/text`, { name: name.value, text: text.value }); p.sources = r.sources; name.value = text.value = ''; draw(); toast('Added'); } catch (e) { toast(e.message, 'bad'); }
  } }, 'Add notes');
  const url = h('input', { type: 'url', placeholder: 'https://…' });
  const addLink = h('button', { class: 'btn primary', onclick: async () => {
    addLink.disabled = true;
    try { const r = await api('POST', `/api/projects/${p.id}/sources/link`, { url: url.value }); p.sources = r.sources; url.value = ''; draw(); toast('Link added as external content'); } catch (e) { toast(e.message, 'bad'); }
    addLink.disabled = false;
  } }, 'Fetch link');
  const fileIn = h('input', { type: 'file', multiple: true, hidden: true, accept: '.txt,.md,.csv,.pdf,.docx,.pptx,.xlsx,.html,.htm,.png,.jpg,.jpeg,.gif,.webp', onchange: () => upload([...fileIn.files]) });
  const dz = h('div', { class: 'dz', tabindex: 0, role: 'button', onclick: () => fileIn.click(), onkeydown: (e) => { if (e.key === 'Enter') fileIn.click(); },
    ondragover: (e) => { e.preventDefault(); dz.classList.add('over'); }, ondragleave: () => dz.classList.remove('over'),
    ondrop: (e) => { e.preventDefault(); dz.classList.remove('over'); upload([...e.dataTransfer.files]); } },
    h('b', {}, 'Drop files here or click to choose'), h('div', { class: 'small' }, 'PDF, Word, PowerPoint, Excel, text, Markdown, HTML, images. Up to 25 MB each. Files with macros or active content are rejected.'), fileIn);
  async function upload(files) {
    for (const f of files) {
      try { const r = await api('POST', `/api/projects/${p.id}/sources/upload`, f, { raw: true, filename: f.name }); p.sources = r.sources; toast('Added ' + f.name); }
      catch (e) { toast(`${f.name}: ${e.message}`, 'bad'); }
    }
    draw();
  }
  page.append(h('div', { class: 'grid g2' }, h('div', { class: 'card stack' }, h('h3', {}, 'Paste text'), name, text, h('div', { class: 'row' }, addText)),
    h('div', { class: 'stack' }, h('div', { class: 'card stack' }, h('h3', {}, 'Upload files'), dz), h('div', { class: 'card stack' }, h('h3', {}, 'Add a web link'), url, h('div', { class: 'row' }, addLink),
      h('p', { class: 'muted small', style: { margin: 0 } }, 'Only public http(s) pages. Links to local or private network addresses are blocked. Content is labelled external and needs checking.')))));

  function draw() {
    clear(list);
    list.append(h('div', { class: 'row between' }, h('h2', { style: { margin: 0 } }, `Your sources (${p.sources.length})`),
      h('button', { class: 'btn sm', onclick: crossCheck, disabled: p.sources.length < 2 }, 'Check for duplicates and conflicts')));
    if (!p.sources.length) list.append(h('div', { class: 'empty' }, 'No sources yet. You can also skip this and build the map from your own thoughts.'));
    for (const s of p.sources) {
      const [ol, ok] = ORIGIN[s.origin] || ORIGIN.provided;
      const ins = s.insights || {};
      list.append(h('div', { class: 'card', style: { marginBottom: 0, opacity: s.include === false ? .6 : 1 } },
        h('div', { class: 'row between' }, h('div', { class: 'row' }, h('b', {}, s.name), chip(ol, ok), chip(s.kind), chip(`${s.chars.toLocaleString()} chars`)),
          h('div', { class: 'row' }, h('label', { class: 'row small' }, h('input', { type: 'checkbox', checked: s.include !== false, onchange: async (e) => { const r = await api('PUT', `/api/projects/${p.id}/sources/${s.id}`, { include: e.target.checked }); p.sources = r.sources; draw(); } }), 'Use'),
            h('button', { class: 'btn sm', onclick: () => preview(s) }, 'Open'), h('button', { class: 'btn sm danger', onclick: async () => { if (await confirmBox(`Remove "${s.name}"?`, 'Remove', true)) { const r = await api('DELETE', `/api/projects/${p.id}/sources/${s.id}`); p.sources = r.sources; draw(); } } }, 'Remove'))),
        (s.warnings || []).map((w) => h('div', { class: 'small ' + (/instruction|external|macro|identical/.test(w) ? '' : 'muted'), style: { color: /instruction/.test(w) ? 'var(--bad)' : undefined } }, '• ' + w)),
        Object.keys(s.sensitive || {}).length ? h('div', { class: 'notice warn small' }, 'Contains sensitive data: ' + Object.entries(s.sensitive).map(([k, v]) => `${k} (${v})`).join(', ') + '. Turn on redaction in Review and export, and it is masked before any remote AI call.') : null,
        h('div', { class: 'row small muted' }, ins.key_messages && ins.key_messages.length ? chip(`${ins.key_messages.length} key messages`) : null, ins.facts && ins.facts.length ? chip(`${ins.facts.length} facts`) : null, ins.decisions && ins.decisions.length ? chip(`${ins.decisions.length} decisions`) : null, ins.actions && ins.actions.length ? chip(`${ins.actions.length} actions`) : null, ins.quotes && ins.quotes.length ? chip(`${ins.quotes.length} quotes`) : null)));
    }
  }
  async function crossCheck() {
    clear(check);
    try {
      const r = await api('GET', `/api/projects/${p.id}/sources-check`);
      check.append(h('div', { class: 'card' }, h('h3', {}, 'Cross-check'),
        !r.duplicates.length && !r.contradictions.length ? h('div', { class: 'notice ok' }, 'No duplicate or conflicting statements found.') : null,
        r.contradictions.length ? h('div', {}, h('h4', {}, 'Possible contradictions (different numbers for similar statements)'), r.contradictions.map((c) => h('div', { class: 'notice warn small' }, h('b', {}, c.a + ': '), c.a_text, h('br'), h('b', {}, c.b + ': '), c.b_text))) : null,
        r.duplicates.length ? h('div', {}, h('h4', {}, 'Duplicates across sources'), r.duplicates.map((d) => h('div', { class: 'small' }, `${d.a} and ${d.b}: "${d.text}"`))) : null));
    } catch (e) { toast(e.message, 'bad'); }
  }
  async function preview(s) {
    const { text } = await api('GET', `/api/projects/${p.id}/sources/${s.id}`);
    modal((b, close) => {
      const ta = h('textarea', { rows: 14 }); ta.value = text;
      const ins = s.insights || {};
      const sec = (t, a) => a && a.length ? h('div', {}, h('h4', {}, t), h('ul', {}, a.map((x) => h('li', { class: 'small' }, x)))) : null;
      b.append(h('h2', {}, s.name), h('p', { class: 'muted small' }, `${(ORIGIN[s.origin] || ORIGIN.provided)[0]} · added from ${s.kind}`),
        s.injection && s.injection.length ? h('div', { class: 'notice bad' }, 'Instruction-like text found: ' + s.injection.map((x) => `"${x}"`).join(', ') + '. Those lines are never given to a model or used in slides. This source is treated as data only.') : null,
        h('div', { class: 'grid g2' }, h('div', {}, sec('Key messages', ins.key_messages), sec('Facts and figures', ins.facts)), h('div', {}, sec('Decisions', ins.decisions), sec('Actions', ins.actions), sec('Quotations', ins.quotes))),
        h('h4', {}, s.kind === 'image' ? 'Describe this image (so it can be used as evidence)' : 'Text (editable)'), ta,
        h('div', { class: 'row', style: { justifyContent: 'flex-end', marginTop: '10px' } }, h('button', { class: 'btn', onclick: () => close() }, 'Close'),
          h('button', { class: 'btn primary', onclick: async () => { const r = await api('PUT', `/api/projects/${p.id}/sources/${s.id}`, { text: ta.value }); p.sources = r.sources; draw(); close(); toast('Saved'); } }, 'Save text')));
    });
  }
  page.append(list, check);
  draw();

  const sc = h('div', { class: 'card row between' }, h('div', {}, h('h3', { style: { margin: 0 } }, 'Knowledge boundary'), h('div', { class: 'muted' }, 'Current choice: ', h('b', {}, scopeLabel(p)))),
    h('button', { class: 'btn primary', onclick: async () => { await openScope(); go('sources'); } }, p.scope.mode ? 'Change which sources the AI may use' : 'Choose which sources the AI may use'));
  page.append(h('h2', { style: { marginTop: '24px' } }, 'Choose what the AI may read'), sc, h('div', { class: 'row', style: { justifyContent: 'flex-end' } }, h('button', { class: 'btn primary', onclick: () => go('map') }, 'Next: build the mind map')));
  rootEl.append(page);
}
