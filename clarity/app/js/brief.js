import { h, api, field, chip, toast, clear, debounce } from './util.js';
import { S, commit, root } from './state.js';
import { ensureRoot, addProposal, blank } from './maptools.js';
import { go } from './main.js';

const INTENTS = [['persuade', 'Persuade'], ['inform', 'Inform'], ['align', 'Align'], ['decide', 'Support a decision'], ['facilitate', 'Facilitate'], ['teach', 'Teach']];
const OUTPUTS = [['presentation', 'Presentation'], ['briefing', 'Briefing document'], ['workshop', 'Workshop plan'], ['summary', 'Executive summary'], ['notes', 'Speaker notes']];

export async function render(rootEl) {
  const p = S.project, b = p.brief;
  const page = h('div', { class: 'page' });
  const bind = (key, rows = 0, ph = '') => {
    const el = rows ? h('textarea', { rows, placeholder: ph }) : h('input', { type: 'text', placeholder: ph });
    el.value = b[key] || '';
    el.addEventListener('input', () => { b[key] = el.value; commit('brief'); rec(); });
    return el;
  };
  page.append(h('h1', {}, 'Define the communication objective'),
    h('p', { class: 'lede' }, 'Answer these first. They steer the framework, the map, and every sentence the AI drafts. Short answers are fine; you can come back.'));

  const msg = h('textarea', { rows: 2, placeholder: 'If the audience remembers one sentence, what is it?' }); msg.value = p.governing || b.message || '';
  msg.addEventListener('input', () => { p.governing = msg.value; b.message = msg.value; commit('brief'); rec(); });
  const intent = h('div', { class: 'seg', role: 'group', 'aria-label': 'Intent' });
  const drawIntent = () => { clear(intent); INTENTS.forEach(([v, l]) => intent.append(h('button', { 'aria-pressed': b.intent === v, onclick: () => { b.intent = v; commit('brief'); drawIntent(); rec(); } }, l))); };
  drawIntent();
  const outs = h('div', { class: 'row' }, OUTPUTS.map(([v, l]) => h('label', { class: 'row' }, h('input', { type: 'checkbox', checked: b.outputs.includes(v), onchange: (e) => { b.outputs = e.target.checked ? [...new Set([...b.outputs, v])] : b.outputs.filter((x) => x !== v); commit('brief'); rec(); } }), l)));
  const mins = h('input', { type: 'number', min: 1, max: 480, value: b.minutes, oninput: (e) => { b.minutes = Math.max(1, +e.target.value || 15); commit('brief'); rec(); } });

  page.append(h('div', { class: 'card stack' },
    field('What is the purpose of this presentation?', bind('purpose', 2, 'For example: get approval to move the Berlin team to the new platform')),
    h('div', { class: 'stack' }, h('b', {}, 'What should it do for the audience?'), intent),
    field('Single most important message', msg, 'Write it as a conclusion, not a topic.'),
    h('div', { class: 'grid g2' }, field('Who is the audience?', bind('who', 2, 'Role, seniority, how many people')), field('What do they already know or believe?', bind('knows', 2))),
    h('div', { class: 'stack' }, h('b', {}, 'After this, the audience should…'),
      h('div', { class: 'grid g2' }, field('Know', bind('feels', 2, 'Facts they must leave with')), field('Believe', bind('believes', 2, 'The belief that makes the decision easy')),
        field('Decide', bind('decides', 2, 'The exact decision, if there is one')), field('Do', bind('does', 2, 'The action, owner, and date')))),
    h('div', { class: 'grid g2' }, field('Time available (minutes)', mins), field('Tone', bind('tone', 0, 'Direct, warm, technical…'))),
    h('div', { class: 'grid g2' }, field('Mandatory messages or evidence', bind('mandatory', 2, 'Things that must appear')), field('Constraints and sensitivities', bind('constraints', 2, 'Topics to avoid, legal limits, politics'))),
    h('div', { class: 'stack' }, h('b', {}, 'Output required'), outs)));

  // framework recommendation
  const recBox = h('div', { class: 'stack' });
  const rec = debounce(async () => {
    try {
      const r = await api('POST', `/api/projects/${p.id}/recommend`, { brief: b });
      clear(recBox);
      if (!r.recommended.length) return recBox.append(h('p', { class: 'muted' }, 'Answer the intent and audience questions to get a recommendation.'));
      r.recommended.slice(0, 3).forEach((x, i) => {
        const fw = S.meta.frameworks.find((f) => f.id === x.id);
        recBox.append(h('label', { class: 'choice' + (p.framework === x.id ? ' on' : '') }, h('input', { type: 'radio', name: 'fw', checked: p.framework === x.id, onchange: () => pick(x.id) }),
          h('span', {}, h('b', {}, fw.name, i === 0 ? chip('Recommended', 'ok') : null, fw.answer_first ? chip('Answer first', 'acc') : null), h('span', { class: 'muted small' }, fw.best_for), h('div', { class: 'small' }, x.why.join('. ') + '.'))));
      });
    } catch (e) { /* offline */ }
  }, 300);
  page.append(h('h2', {}, 'Choose a framework'), h('p', { class: 'muted' }, 'This is a recommendation based on your answers. You can pick any other framework below.'), h('div', { class: 'card' }, recBox));
  const all = h('div', { class: 'grid g3' });
  const drawAll = () => { clear(all); S.meta.frameworks.forEach((f) => all.append(h('label', { class: 'choice' + (p.framework === f.id ? ' on' : '') }, h('input', { type: 'radio', name: 'fw2', checked: p.framework === f.id, onchange: () => pick(f.id) }), h('span', {}, h('b', {}, f.name), h('span', { class: 'muted small' }, f.best_for))))); };
  drawAll();
  page.append(h('details', {}, h('summary', {}, 'All frameworks'), h('div', { style: { marginTop: '10px' } }, all)));
  const steps = h('div', { class: 'stack' });
  function pick(id) { p.framework = id; p.storyline.structure = ''; commit('framework'); drawAll(); rec(); drawSteps(); }

  function drawSteps() {
    clear(steps);
    const fw = S.meta.frameworks.find((f) => f.id === p.framework) || S.meta.frameworks[0];
    steps.append(h('div', { class: 'notice' }, h('b', {}, fw.name + ': '), fw.best_for, fw.answer_first ? ' The answer leads the deck (reverse pyramid).' : ' The story builds to the answer.'));
    fw.steps.forEach((st, i) => {
      const ta = h('textarea', { rows: st.role === 'answer' ? 2 : 4, placeholder: st.example ? 'For example: ' + st.example : '' }); ta.value = p.answers[st.key] || (st.role === 'answer' ? p.governing : '') || '';
      ta.addEventListener('input', () => { p.answers[st.key] = ta.value; if (st.role === 'answer' && !p.governing) { /* keep user's own wording */ } commit('answers'); });
      steps.append(h('div', { class: 'card', style: { marginBottom: 0 } }, field(`${i + 1}. ${st.label}`, ta, st.hint)));
    });
  }
  page.append(h('h2', {}, 'Capture your thinking'), h('p', { class: 'muted' }, 'Get the rough thoughts out, one idea per line. Do not polish yet.'), steps);
  drawSteps(); rec();

  const coachBox = h('div', { class: 'stack' });
  const coachBtn = h('button', { class: 'btn' }, 'Challenge my thinking');
  coachBtn.onclick = async () => { coachBtn.disabled = true; try { const r = await api('POST', `/api/projects/${p.id}/coach`, {}); clear(coachBox); coachBox.append(h('div', { class: 'row' }, h('b', {}, 'Questions to answer before you build'), chip(r.engine === 'model' ? 'AI-generated' : 'Rule-based', 'dashed')), h('ol', {}, r.questions.map((q) => h('li', {}, q)))); } catch (e) { toast(e.message, 'bad'); } coachBtn.disabled = false; };
  const seed = h('button', { class: 'btn primary', onclick: async () => {
    const r = await api('POST', `/api/projects/${p.id}/map/seed`, {});
    if (!r.root && !r.branches.length) return toast('Write some thoughts above first.', 'bad');
    const rt = ensureRoot(r.root || p.governing);
    if (r.root && !p.governing) p.governing = r.root;
    const added = addProposal(r.branches, rt.id, false);
    commit('seed'); toast(`Added ${added} branch(es) to the map from your own answers.`); go('map');
  } }, 'Build the map from my answers');
  page.append(h('div', { class: 'card stack' }, h('div', { class: 'row' }, coachBtn, seed, h('button', { class: 'btn', onclick: () => go('sources') }, 'Next: add sources')), coachBox));
  rootEl.append(page);
}
