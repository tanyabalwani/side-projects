// Knowledge boundary: which sources may the AI use? Asked before any generation.
import { h, api, modal, toast, chip, clear } from './util.js';
import { S, emit, saveNow, refreshAI } from './state.js';

const OPTIONS = [
  ['provided', 'Only the files, text, and links I provide', 'Nothing from the organisation knowledge base is read.'],
  ['selected', 'My provided sources plus selected organisational knowledge', 'You pick the documents. Only approved, current ones are listed by default.'],
  ['all', 'My provided sources plus all organisational knowledge I am authorised to access', 'Every approved, current, in-date document your folders expose. You can still exclude individual ones.'],
  ['none', 'No knowledge retrieval; use only my instructions', 'The AI sees your brief and your map text, no source documents.'],
];
export const scopeLabel = (p) => ({ provided: 'Only my sources', selected: 'My sources + selected KB', all: 'My sources + all KB', none: 'No retrieval' }[p.scope.mode] || 'Sources: not chosen');

export async function ensureScope() {
  const p = S.project;
  const confirmed = !!(p.scope_conf && p.scope_conf.hash);
  if (p.scope.mode && (p.scope.mode === 'provided' || p.scope.mode === 'none' || confirmed)) return true;
  return openScope();
}

export function openScope() {
  return new Promise((resolve) => {
    const p = S.project;
    api('GET', `/api/projects/${p.id}/scope`).then((info) => {
      let mode = p.scope.mode || 'provided', picked = new Set(p.scope.kb_docs), excluded = new Set(p.scope.excluded);
      let confirm = false, done = false;
      const ai = info.ai;
      modal((box, close) => {
        const body = h('div', { class: 'stack' });
        const draw = () => {
          clear(body);
          body.append(h('h2', {}, 'Which sources should the AI use for this project?'),
            h('p', { class: 'muted' }, 'This applies to every generate action. You can change it later; widening it asks you to confirm again.'));
          for (const [v, t, d] of OPTIONS) {
            body.append(h('label', { class: 'choice' + (mode === v ? ' on' : '') },
              h('input', { type: 'radio', name: 'scope', checked: mode === v, onchange: () => { mode = v; confirm = false; draw(); } }), h('span', {}, h('b', {}, t), h('span', { class: 'muted small' }, d))));
          }
          const eligible = info.docs.filter((d) => d.eligible);
          const blocked = info.docs.filter((d) => !d.eligible);
          if (mode === 'selected' || mode === 'all') {
            body.append(h('h4', {}, mode === 'selected' ? 'Choose documents' : 'Documents that will be available (untick to exclude)'));
            if (!info.docs.length) body.append(h('div', { class: 'notice warn' }, 'The knowledge base is empty. Add folders or documents in Knowledge base first.'));
            const list = h('div', { class: 'card', style: { maxHeight: '240px', overflow: 'auto', margin: 0 } });
            for (const d of eligible) {
              const checked = mode === 'selected' ? picked.has(d.id) : !excluded.has(d.id);
              list.append(h('label', { class: 'row', style: { padding: '3px 0' } }, h('input', { type: 'checkbox', checked, onchange: (e) => {
                if (mode === 'selected') e.target.checked ? picked.add(d.id) : picked.delete(d.id); else e.target.checked ? excluded.delete(d.id) : excluded.add(d.id); } }),
                h('span', {}, d.name), chip(d.origin === 'library' ? 'Library' : d.source, 'acc'), d.owner ? h('span', { class: 'muted small' }, 'Owner: ' + d.owner) : null, chip(d.classification)));
            }
            if (blocked.length) list.append(h('div', { class: 'muted small', style: { marginTop: '8px' } }, `${blocked.length} document(s) are excluded by default: draft, expired, superseded, or archived. (${blocked.slice(0, 4).map((d) => d.name + ' – ' + d.flags.join('/')).join('; ')}${blocked.length > 4 ? '…' : ''})`));
            body.append(list);
            body.append(h('div', { class: 'notice warn' }, 'Your existing file permissions apply. Documents you cannot read are never listed. Content from the knowledge base is labelled as internal on every slide that uses it.'));
            body.append(h('label', { class: 'row' }, h('input', { type: 'checkbox', checked: confirm, onchange: (e) => { confirm = e.target.checked; save.disabled = !confirm; } }), h('b', {}, 'I confirm this expands what the AI may read.')));
          }
          body.append(h('div', { class: 'notice' + (ai.local ? '' : ' warn') }, h('b', {}, 'Where processing happens: '), `${ai.name} (${ai.model}). ${ai.note}`));
          if (!ai.local) {
            const sec = p.security;
            body.append(h('label', { class: 'row' }, h('input', { type: 'checkbox', checked: sec.confirm_remote, disabled: sec.classification === 'restricted', onchange: (e) => { sec.confirm_remote = e.target.checked; } }),
              h('span', {}, 'Allow sending selected text to the remote model (secrets and personal data are redacted first).', sec.classification === 'restricted' ? ' Not available for restricted projects.' : '')));
          }
        };
        const save = h('button', { class: 'btn primary', onclick: async () => {
          try {
            const r = await api('POST', `/api/projects/${p.id}/scope`, { mode, kb_docs: mode === 'selected' ? [...picked] : [], excluded: [...excluded], confirm });
            p.scope = r.scope; await saveNow();
            const info2 = await api('GET', `/api/projects/${p.id}/scope`); p.scope_conf = info2.confirmed ? { hash: 'ok' } : {};
            await refreshAI(); emit('status'); done = true; close(true);
          } catch (e) { toast(e.message, 'bad'); }
        } }, 'Apply');
        draw(); save.disabled = (mode === 'selected' || mode === 'all') && !confirm;
        box.append(body, h('div', { class: 'row', style: { justifyContent: 'flex-end', marginTop: '14px' } }, h('button', { class: 'btn', onclick: () => close(false) }, 'Cancel'), save));
        body.addEventListener('change', () => { save.disabled = (mode === 'selected' || mode === 'all') && !confirm; });
      }, { onClose: (v) => resolve(!!(v && done)) });
    }).catch((e) => { toast(e.message, 'bad'); resolve(false); });
  });
}
