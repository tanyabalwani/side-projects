import { h, api, chip, toast, clear, field, confirmBox } from './util.js';
import { S, commit, saveNow } from './state.js';
import { stage } from './stage.js';
import { go } from './main.js';

export async function render(rootEl) {
  const p = S.project, page = h('div', { class: 'page' }); rootEl.append(page);
  const draw = async () => {
    clear(page);
    page.append(h('h1', {}, 'Template and brand'), h('p', { class: 'lede' }, 'Upload your PowerPoint template or a reference deck. The exported file uses its slide masters, so fonts, colours, logos, footers, and page numbers stay exactly as your brand team set them.'));
    const fileIn = h('input', { type: 'file', accept: '.pptx,.potx', hidden: true, onchange: async () => { const f = fileIn.files[0]; if (!f) return; try { await saveNow(); const r = await api('POST', `/api/projects/${p.id}/template`, f, { raw: true, filename: f.name }); p.template = r.template; toast('Template loaded'); draw(); } catch (e) { toast(e.message, 'bad'); } } });
    const dz = h('div', { class: 'dz', tabindex: 0, role: 'button', onclick: () => fileIn.click(), onkeydown: (e) => { if (e.key === 'Enter') fileIn.click(); },
      ondragover: (e) => { e.preventDefault(); dz.classList.add('over'); }, ondragleave: () => dz.classList.remove('over'), ondrop: (e) => { e.preventDefault(); dz.classList.remove('over'); fileIn.files = e.dataTransfer.files; fileIn.onchange(); } },
      h('b', {}, p.template ? 'Replace the template' : 'Drop a .pptx or .potx here, or click to choose'), h('div', { class: 'small' }, 'Files with macros or embedded objects are rejected. The template is stored only on this computer.'), fileIn);
    page.append(h('div', { class: 'card stack' }, dz));
    if (p.template) {
      const t = p.template, info = t.info;
      const sel = (key, kinds) => { const s = h('select', {}, info.layouts.filter((l) => kinds.includes(l.kind)).map((l) => h('option', { value: l.name }, l.name))); s.value = t[key]; s.addEventListener('change', async () => { await api('PUT', `/api/projects/${p.id}/template`, { [key]: s.value }); t[key] = s.value; toast('Saved'); }); return s; };
      page.append(h('div', { class: 'card stack' }, h('div', { class: 'row between' }, h('h3', { style: { margin: 0 } }, t.name), h('button', { class: 'btn sm danger', onclick: async () => { if (await confirmBox('Remove this template and use the built-in theme?', 'Remove', true)) { await api('DELETE', `/api/projects/${p.id}/template`); p.template = null; draw(); } } }, 'Remove')),
        h('div', { class: 'row' }, chip(`${info.size[0]} × ${info.size[1]} in`), chip(`${info.layouts.length} layouts`), chip(`${info.logos} logo/picture(s) in master`), info.fonts.major ? chip('Fonts: ' + info.fonts.major + (info.fonts.minor && info.fonts.minor !== info.fonts.major ? ' / ' + info.fonts.minor : '')) : null),
        h('div', { class: 'row' }, ['accent1', 'accent2', 'accent3', 'accent4', 'accent5', 'accent6', 'dk2', 'lt2'].filter((k) => info.colors[k]).map((k) => h('span', { class: 'sw', title: k + ' ' + info.colors[k], style: { background: info.colors[k] } }))),
        info.legal_found.length ? h('div', { class: 'notice small' }, h('b', {}, 'Standard legal text found in the master: '), info.legal_found.join(' | '), '. It appears on every slide automatically.') : null,
        h('div', { class: 'notice small' }, 'Brand elements in the master (logos, footers, page numbers, legal lines) are locked: this tool never moves or restyles them.'),
        h('div', { class: 'grid g2' }, field('Layout for the title slide', sel('title_layout', ['title', 'section', 'other'])), field('Layout for content slides', sel('content_layout', ['content', 'other'])))));
      page.append(h('div', { class: 'card stack' }, h('h3', { style: { margin: 0 } }, 'Approved layouts'), h('p', { class: 'muted small', style: { margin: 0 } }, 'Only ticked layouts can be chosen for individual slides.'),
        h('div', { class: 'grid g3' }, info.layouts.map((l) => h('label', { class: 'row small' }, h('input', { type: 'checkbox', checked: t.approved.includes(l.name), onchange: async (e) => { const a = e.target.checked ? [...t.approved, l.name] : t.approved.filter((x) => x !== l.name); const r = await api('PUT', `/api/projects/${p.id}/template`, { approved: a }); t.approved = r.template.approved; } }), l.name, chip(l.kind), l.has_number ? chip('page no.', 'ok') : null)))));
    } else {
      const ac = h('input', { type: 'color', value: p.theme.accent, oninput: (e) => { p.theme.accent = e.target.value; commit('theme'); prev(); } });
      const ft = h('select', { onchange: (e) => { p.theme.font = e.target.value; commit('theme'); prev(); } }, S.meta.fonts.map((f) => h('option', { value: f }, f))); ft.value = p.theme.font;
      const pv = h('div'); const prev = () => { clear(pv); pv.append(stage({ kind: 'content', layout: 'framework', title: 'This is how a headline reads on the built-in theme', bullets: [{ text: 'Speed: releases ship in 2 days', level: 0 }, { text: 'Cost: saves 40k a year', level: 0 }, { text: 'Risk: low with a phased rollout', level: 0 }], takeaway: 'Approve the budget today', sources: [] }, p)); }; prev();
      page.append(h('div', { class: 'card stack' }, h('h3', { style: { margin: 0 } }, 'No template: built-in theme'), h('div', { class: 'row' }, field('Accent colour', ac), field('Font', ft)), pv));
    }
    page.append(h('div', { class: 'row', style: { justifyContent: 'flex-end' } }, h('button', { class: 'btn primary', onclick: () => go('export') }, 'Next: review and export')));
  };
  draw();
}
