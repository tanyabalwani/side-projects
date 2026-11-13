import { h, api, chip, toast, clear, field, download, modal, promptBox, trunc } from './util.js';
import { S, commit, saveNow } from './state.js';
import { present } from './slides.js';
import { go } from './main.js';

const SEV = { blocker: 'Blocker', major: 'Major', minor: 'Minor', info: 'Note' };
export async function render(rootEl) {
  const p = S.project, page = h('div', { class: 'page' }); rootEl.append(page);
  const draw = async () => {
    await saveNow(); clear(page);
    page.append(h('h1', {}, 'Review and export'), h('p', { class: 'lede' }, 'A last check against the argument, the evidence, the sources, and the template. Blockers and major issues must be resolved, accepted, or overridden with a reason before export.'));
    if (!p.slides.length) { page.append(h('div', { class: 'empty' }, 'There are no slides to review yet.')); return; }
    let rv, mf;
    try { [rv, mf] = await Promise.all([api('GET', `/api/projects/${p.id}/review`), api('GET', `/api/projects/${p.id}/export-manifest`)]); } catch (e) { page.append(h('div', { class: 'notice bad' }, e.message)); return; }
    const c = rv.counts;
    page.append(h('div', { class: 'card row' }, h('div', { class: 'score', style: { '--c': rv.score > 80 ? 'var(--ok)' : rv.score > 55 ? 'var(--warn)' : 'var(--bad)' } }, String(rv.score)),
      h('div', {}, h('h2', { style: { margin: 0 } }, rv.can_export ? 'Ready to export' : `${rv.open_gating} issue(s) block export`), h('div', { class: 'row' }, Object.keys(SEV).map((k) => chip(`${c[k]} ${SEV[k].toLowerCase()}`, k === 'blocker' && c[k] ? 'bad' : k === 'major' && c[k] ? 'warn' : ''))))));
    // issues
    const list = h('div', {});
    if (!rv.issues.length) list.append(h('div', { class: 'notice ok' }, 'Every check passed.'));
    for (const i of rv.issues) {
      const closed = i.state !== 'open';
      list.append(h('div', { class: 'issue sev-' + i.severity, style: { opacity: closed ? .65 : 1 } },
        h('div', { class: 'row between' }, h('div', { class: 'row' }, chip(SEV[i.severity], i.severity === 'blocker' ? 'bad' : i.severity === 'major' ? 'warn' : ''), chip(i.check), closed ? chip({ resolved: 'Resolved', accepted: 'Accepted', override: 'Overridden' }[i.state], 'ok') : null), h('div', { class: 'row' },
          i.slide_id ? h('button', { class: 'btn sm', onclick: () => { const ix = p.slides.findIndex((s) => s.id === i.slide_id); if (ix >= 0) { import('./slides.js').then(() => { sessionStorage.setItem('cd_sel', ix); go('slides'); }); } } }, 'Go to slide') : null,
          !closed ? h('span', { class: 'row' }, h('button', { class: 'btn sm', onclick: () => resolve(i, 'resolved') }, 'Mark resolved'), h('button', { class: 'btn sm', onclick: () => resolve(i, 'accepted') }, 'Accept'), h('button', { class: 'btn sm', onclick: async () => { const r = await promptBox('Why override this issue? The reason is recorded in the audit log.'); if (r) resolve(i, 'override', r); } }, 'Override'))
            : h('button', { class: 'btn sm ghost', onclick: () => resolve(i, 'open') }, 'Reopen'))),
        h('div', {}, i.message), i.fix ? h('div', { class: 'muted small' }, 'How to fix: ' + i.fix) : null, i.reason ? h('div', { class: 'small' }, 'Reason: ' + i.reason) : null));
    }
    page.append(h('h2', {}, 'Quality checks'), list);
    async function resolve(i, state, reason = '') { try { await api('POST', `/api/projects/${p.id}/review/resolve`, { id: i.id, state, reason }); p.qc.resolutions = p.qc.resolutions.filter((x) => x.id !== i.id); if (state !== 'open') p.qc.resolutions.push({ id: i.id, state, reason, ts: Date.now() / 1000 | 0 }); draw(); } catch (e) { toast(e.message, 'bad'); } }
    // export controls
    const sec = p.security;
    const sel = h('select', { onchange: (e) => { sec.classification = e.target.value; commit('security'); draw(); } }, S.meta.classes.map((k) => h('option', { value: k }, k))); sel.value = sec.classification;
    const wm = h('input', { type: 'text', value: sec.watermark, placeholder: 'DRAFT, CONFIDENTIAL…', oninput: (e) => { sec.watermark = e.target.value; commit('security'); } });
    const lg = h('input', { type: 'text', value: sec.legal, placeholder: 'Confidentiality or legal line for every footer', oninput: (e) => { sec.legal = e.target.value; commit('security'); } });
    page.append(h('h2', {}, 'Export controls'), h('div', { class: 'card stack' }, h('div', { class: 'grid g3' }, field('Information classification', sel), field('Watermark', wm), field('Footer legal line', lg)),
      h('label', { class: 'row' }, h('input', { type: 'checkbox', checked: sec.redact_export, onchange: (e) => { sec.redact_export = e.target.checked; commit('security'); draw(); } }), h('span', {}, h('b', {}, 'Redact personal data and secrets in the exported file'), h('span', { class: 'muted small' }, ' (emails, phone numbers, card and ID numbers, keys)')))));
    // manifest
    const sc = Object.entries(mf.sensitive_found);
    page.append(h('h2', {}, 'What will be in the file'), h('div', { class: 'card stack' },
      h('div', { class: 'row' }, chip(`${mf.slides} slides`), chip(`${mf.notes_included} with speaker notes (included in PPTX and DOCX)`), chip('Template: ' + mf.template), chip('Marking: ' + (mf.marking || 'none'), 'acc'), mf.watermark ? chip('Watermark: ' + mf.watermark) : null),
      sc.length ? h('div', { class: 'notice ' + (mf.redact_export ? 'ok' : 'warn') }, 'Sensitive data found: ' + sc.map(([k, v]) => `${k} (${v})`).join(', ') + (mf.redact_export ? '. It will be masked in the export.' : '. Redaction is off.')) : h('div', { class: 'small muted' }, 'No sensitive patterns detected.'),
      mf.ai_unsourced_bullets ? h('div', { class: 'notice warn small' }, `${mf.ai_unsourced_bullets} bullet(s) are AI suggestions without a source. They are marked in speaker notes.`) : null,
      mf.sources.length ? h('div', {}, h('h4', {}, 'Sources cited'), h('div', { class: 'row' }, mf.sources.map((x) => chip(x.name, x.origin === 'internal' ? 'ok' : x.origin === 'external' ? 'warn' : 'acc', x.origin)))) : h('div', { class: 'small muted' }, 'No sources are cited on slides.')));
    // buttons
    const dl = (fmt, label, primary) => { const b = h('button', { class: 'btn' + (primary ? ' primary' : ''), disabled: !rv.can_export && fmt !== 'json', title: rv.can_export || fmt === 'json' ? '' : 'Resolve blocking issues first', onclick: async () => { b.disabled = true; try { const n = await download(`/api/projects/${p.id}/export/${fmt}`); toast('Saved ' + n); } catch (e) { toast(e.message, 'bad'); } b.disabled = !rv.can_export && fmt !== 'json'; } }, label); return b; };
    page.append(h('div', { class: 'card stack' }, h('div', { class: 'row' }, dl('pptx', 'Editable PowerPoint (.pptx)', true), dl('docx', 'Briefing document (.docx)'), dl('md', 'Markdown outline'), dl('html', 'Standalone web deck'), dl('json', 'Project backup (.json)'), h('button', { class: 'btn', onclick: () => present(0) }, 'Present and rehearse')),
      h('p', { class: 'muted small', style: { margin: 0 } }, 'The PowerPoint file is editable: real text boxes, native charts and tables, speaker notes, and your template layouts. Exports are recorded in the audit log.')));
  };
  draw();
}
