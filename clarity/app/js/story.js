import { h, api, chip, toast, clear, field, trunc, pollJob, confirmBox } from './util.js';
import { S, commit, nodes } from './state.js';
import { ensureScope } from './scope.js';
import { go } from './main.js';

export async function render(rootEl) {
  const p = S.project, st = p.storyline;
  const page = h('div', { class: 'page' });
  page.append(h('h1', {}, 'Build the storyline'), h('p', { class: 'lede' }, 'Lead with the answer, then the strongest reasons, then evidence. Background goes to the appendix. Pick the structure, generate the draft, then approve the story before polishing slides.'));
  if (nodes().length < 2) { page.append(h('div', { class: 'empty' }, 'Build the mind map first. The storyline is made from its branches.', h('div', {}, h('button', { class: 'btn primary', style: { marginTop: 10 }, onclick: () => go('map') }, 'Open the map')))); rootEl.append(page); return; }

  // structures
  const structBox = h('div', { class: 'grid g3' });
  page.append(h('h2', {}, 'Choose the structure'), h('p', { class: 'muted' }, 'Each option reorders your branches. The line under each name shows where the answer arrives.'), structBox);
  try {
    const { structures } = await api('GET', `/api/projects/${p.id}/structures`);
    const cur = st.structure || p.framework || 'reverse_pyramid';
    const draw = () => { clear(structBox); structures.forEach((s) => structBox.append(h('div', { class: 'choice' + (cur === s.id ? ' on' : ''), style: { flexDirection: 'column', cursor: 'default' } },
      h('div', { class: 'row between', style: { width: '100%' } }, h('b', {}, s.name), s.answer_first ? chip('Answer first', 'ok') : chip(`Answer at slide ${s.answer_slide}`, 'warn')),
      h('ol', { class: 'small', style: { margin: '4px 0', paddingLeft: 18 } }, s.sequence.slice(0, 8).map((q) => h('li', {}, h('span', { class: 'muted' }, q.section + ': '), trunc(q.title, 38)))),
      h('button', { class: 'btn sm', onclick: () => { st.structure = s.id; commit('structure'); go('story'); } }, cur === s.id ? 'Selected' : 'Use this structure')))); };
    draw();
  } catch (e) { structBox.append(h('div', { class: 'notice warn' }, e.message)); }

  // generate
  const keep = h('input', { type: 'checkbox', checked: true });
  const prog = h('div', { class: 'bar', hidden: true }, h('i', { style: { width: '0%' } })), label = h('span', { class: 'muted small' });
  const gen = h('button', { class: 'btn primary', onclick: async () => {
    if (!await ensureScope()) return;
    if (p.slides.length && !await confirmBox('Regenerate the slides? Slides you locked or approved are kept. Others are replaced. You can undo.', 'Regenerate')) return;
    gen.disabled = true; prog.hidden = false;
    try {
      const { job } = await api('POST', `/api/projects/${p.id}/generate`, { structure: st.structure || p.framework, keep_locked: keep.checked });
      const r = await pollJob(job, (j) => { prog.firstChild.style.width = j.total ? (100 * j.done / j.total) + '%' : '10%'; label.textContent = j.label ? 'Drafting: ' + trunc(j.label, 60) : 'Starting…'; });
      p.slides = r.slides; Object.assign(st, { thesis: r.storyline.thesis, exec_summary: r.storyline.exec_summary, openings: r.storyline.openings, closings: r.storyline.closings, appendix: r.storyline.appendix, structure: r.storyline.structure, approved: false });
      commit('generate'); toast(`Draft ready: ${r.slides.length} slides, drafted by ${r.storyline.engine === 'model' ? 'an AI model' : 'local rules'}.`);
      (r.notes || []).forEach((n) => toast(n)); go('story');
    } catch (e) { toast(e.message, 'bad'); if (e.data && e.data.need === 'scope') ensureScope(); }
    gen.disabled = false;
  } }, p.slides.length ? 'Regenerate storyline and slides' : 'Generate storyline and slides');
  page.append(h('div', { class: 'card stack' }, h('div', { class: 'row' }, gen, h('label', { class: 'row small' }, keep, 'Keep locked and approved slides')), prog, label,
    h('p', { class: 'muted small', style: { margin: 0 } }, 'Uses only the sources you allowed. Every bullet is labelled sourced, your own, or an AI suggestion.')));

  // thesis & summary
  const th = h('textarea', { rows: 2 }); th.value = st.thesis || p.governing || ''; th.addEventListener('input', () => { st.thesis = th.value; commit('story'); });
  const ex = h('textarea', { rows: 4 }); ex.value = st.exec_summary || ''; ex.addEventListener('input', () => { st.exec_summary = ex.value; commit('story'); });
  page.append(h('div', { class: 'card stack' }, field('One-sentence thesis', th, 'The answer, in a sentence a busy person can repeat.'), field('Executive summary', ex, 'Three to five sentences, answer first. It becomes the speaker notes on slide 2.')));

  // pyramid + outline
  const main = p.slides.filter((s) => ['summary', 'content', 'ask'].includes(s.kind));
  if (p.slides.length) {
    const layers = [['The answer', p.slides.filter((s) => s.kind === 'summary').length, 'var(--accent)', 100], ['Key arguments', p.slides.filter((s) => s.kind === 'content').length, 'var(--k-insight)', 82], ['Evidence and detail', p.slides.reduce((a, s) => a + s.bullets.length, 0), 'var(--k-evidence)', 64], ['Appendix', p.slides.filter((s) => ['appendix', 'sources'].includes(s.kind)).length, 'var(--k-theme)', 46]];
    page.append(h('h2', {}, 'The story at a glance'), h('div', { class: 'grid g2' }, h('div', { class: 'card' }, h('div', { class: 'pyr' }, layers.map(([l, n, c, w]) => h('div', { style: { background: c, width: w + '%' } }, `${l}: ${n}`)))),
      h('div', { class: 'card' }, h('h3', {}, 'Message hierarchy'), h('ol', { class: 'stack small', style: { margin: 0, paddingLeft: 18 } }, p.slides.filter((s) => s.kind !== 'title').map((s) => h('li', {}, h('b', {}, trunc(s.title, 80)), s.transition ? h('div', { class: 'muted tiny' }, 'Transition: ' + s.transition) : null))))));
    const opt = (label, arr) => arr && arr.length ? h('div', { class: 'card' }, h('h3', {}, label), arr.map((o) => h('div', { class: 'row small', style: { marginBottom: 4 } }, h('span', { style: { flex: 1 } }, o), h('button', { class: 'btn sm', onclick: () => { const sl = label.startsWith('Open') ? p.slides[0] : p.slides.filter((s) => s.kind !== 'appendix' && s.kind !== 'sources').pop(); if (sl) { sl.notes = (sl.notes ? sl.notes + '\n\n' : '') + o; commit('notes'); toast('Added to speaker notes'); } } }, 'Add to notes')))) : null;
    page.append(h('div', { class: 'grid g2' }, opt('Opening options', st.openings), opt('Closing options', st.closings)));
    if ((st.appendix || []).length) page.append(h('div', { class: 'card' }, h('h3', {}, 'Suggested appendix material'), h('ul', {}, st.appendix.map((a) => h('li', {}, a)))));
  }
  page.append(h('div', { class: 'card row between' }, h('label', { class: 'row' }, h('input', { type: 'checkbox', checked: st.approved, disabled: !p.slides.length, onchange: (e) => { st.approved = e.target.checked; commit('approve'); } }), h('b', {}, 'I approve this storyline'), h('span', { class: 'muted small' }, 'You can reopen it any time.')),
    h('button', { class: 'btn primary', disabled: !p.slides.length, onclick: () => go('slides') }, 'Next: edit slides')));
  rootEl.append(page);
}
