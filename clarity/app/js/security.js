import { h, api, chip, toast, clear, ago, field } from './util.js';
import { S, commit, refreshAI } from './state.js';

export async function render(rootEl) {
  const p = S.project, page = h('div', { class: 'page' }); rootEl.append(page);
  const sec = await api('GET', '/api/security' + (p ? '?project=' + p.id : ''));
  page.append(h('h1', {}, 'Security and audit'), h('p', { class: 'lede' }, 'What runs where, who can see it, and what has happened to your content.'));
  const row = (k, v, kind) => h('tr', {}, h('td', { style: { width: 220 } }, h('b', {}, k)), h('td', {}, v, kind ? ' ' : '', kind ? chip(kind[0], kind[1]) : null));
  page.append(h('div', { class: 'card' }, h('h3', {}, 'This installation'), h('table', {}, h('tbody', {},
    row('Network access', sec.binding, ['Local only', 'ok']), row('Who can open it', sec.access), row('AI model', `${sec.ai.name} (${sec.ai.model})`, sec.ai.local ? ['Processed locally', 'ok'] : ['Remote', 'warn']), row('Model policy', sec.ai.note),
    row('Approved providers', sec.allowed_providers.join(', ') + '. Set by CLARITY_ALLOWED_PROVIDERS.'), row('Encryption at rest', sec.encryption_at_rest ? 'On (Fernet, key derived from your passphrase)' : 'Off. Start with CLARITY_PASSPHRASE set to encrypt projects, sources, and the knowledge base.', sec.encryption_at_rest ? ['On', 'ok'] : ['Off', 'warn']),
    row('Malware scan', sec.antivirus ? 'ClamAV scans every upload, plus structural checks.' : 'Structural checks only (macros, embedded objects, PDF scripts). Install ClamAV to add antivirus.'),
    row('Links', 'Public http(s) only. Private, local, and metadata addresses are blocked. ' + (sec.private_links === 'blocked' ? '' : 'Administrator has allowed private links.')), row('Knowledge folders allowed', sec.kb_roots), row('Data folder', sec.data_dir)))));
  if (p) {
    const s = p.security, rem = sec.ai.local === false;
    const cls = h('select', { onchange: (e) => { s.classification = e.target.value; if (s.classification === 'restricted') s.confirm_remote = false; commit('security'); refreshAI(); } }, S.meta.classes.map((k) => h('option', { value: k }, k))); cls.value = s.classification;
    page.append(h('div', { class: 'card stack' }, h('h3', { style: { margin: 0 } }, 'This project'),
      h('div', { class: 'grid g2' }, field('Information classification', cls, 'Controls which knowledge documents may be used. Restricted projects never use a remote model.'), field('Sources the AI may read', h('div', {}, chip(({ provided: 'Only your provided sources', selected: 'Provided + selected knowledge', all: 'Provided + all knowledge', none: 'No retrieval' })[p.scope.mode] || 'Not chosen yet', 'acc')))),
      rem ? h('label', { class: 'row' }, h('input', { type: 'checkbox', checked: s.confirm_remote, disabled: s.classification === 'restricted', onchange: (e) => { s.confirm_remote = e.target.checked; commit('security'); refreshAI(); } }), h('span', {}, h('b', {}, 'Allow sending selected text to the remote model.'), ' Secrets and personal data are redacted first. Content is not used for training by the provider under API terms; check your own agreement.')) : h('div', { class: 'notice ok small' }, 'The active model runs on this machine. No project text leaves it.'),
      h('div', { class: 'small muted' }, 'Access: only this operating-system user. There are no shared accounts, single sign-on, or role-based permissions in this local edition; project and document permissions follow your file system permissions.')));
  }
  const a = await api('GET', '/api/audit' + (p ? '?project=' + p.id : ''));
  page.append(h('div', { class: 'row between' }, h('h2', {}, p ? 'Audit trail for this project' : 'Audit trail'), chip(a.chain_ok ? 'Chain verified' : 'Chain broken: log was altered', a.chain_ok ? 'ok' : 'bad')),
    h('div', { class: 'card', style: { maxHeight: 420, overflow: 'auto' } }, a.events.length ? h('table', {}, h('thead', {}, h('tr', {}, ['When', 'Event', 'Details'].map((x) => h('th', {}, x)))), h('tbody', {}, a.events.map((e) => h('tr', {}, h('td', { class: 'small' }, ago(e.ts)), h('td', {}, h('b', {}, e.event)), h('td', { class: 'small muted' }, Object.entries(e.detail).map(([k, v]) => `${k}: ${v}`).join(' · ')))))) : h('div', { class: 'muted' }, 'No events yet.')),
    h('p', { class: 'muted small' }, 'The log records opens, edits, source additions, scope changes, knowledge use, AI calls (provider, size, redactions), quality sign-offs, and exports. It never stores your slide text. Each entry is chained to the previous one, so edits to past entries are detected.'));
}
