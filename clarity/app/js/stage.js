// Slide preview renderer (mirrors export.py's derive_* logic). Text only through text nodes.
import { h } from './util.js';
export const derive = {
  columns(s) {
    const groups = []; let cur = null;
    for (const b of s.bullets) { if (b.level === 0) { cur = { head: b.text, items: [] }; groups.push(cur); } else if (cur) cur.items.push(b.text); }
    if (groups.length >= 2 && groups.some((g) => g.items.length)) return groups.slice(0, 3);
    const flat = s.bullets.map((b) => b.text), hd = s.layout === 'before_after' ? ['Before', 'After'] : ['Option A', 'Option B'], half = Math.ceil(flat.length / 2);
    return [{ head: hd[0], items: flat.slice(0, half) }, { head: hd[1], items: flat.slice(half) }];
  },
  steps(s) { return s.bullets.filter((b) => b.level === 0).slice(0, 6).map((b, i) => { const m = /^((?:Q[1-4]\s*)?(?:19|20)\d\d|Q[1-4]|Phase \d+|Step \d+|Month \d+|Week \d+)\s*[:\-]\s*(.+)$/i.exec(b.text); return { head: m ? m[1] : 'Step ' + (i + 1), text: m ? m[2] : b.text }; }); },
  cards(s) { return s.bullets.filter((b) => b.level === 0).slice(0, 6).map((b) => { const m = /^([^:]{2,40}):\s*(.+)$/.exec(b.text); return { lead: m ? m[1] : '', text: m ? m[2] : b.text }; }); },
  pairs(s) { const out = []; for (const b of s.bullets) { const m = /^(.{2,40}?)\s*[:=]\s*([$€£]?)(-?\d[\d,]*(?:\.\d+)?)\s*(%|[A-Za-z]{0,12})?\s*$/.exec(b.text.trim()); if (m) out.push([m[1].trim(), parseFloat(m[3].replace(/,/g, '')), (m[2] + (m[4] || '')).trim()]); } return out; },
  actions(s) { return s.bullets.filter((b) => b.level === 0).slice(0, 8).map((b) => { let t = b.text, owner = '', due = ''; if (t.includes('|')) { const p = t.split('|').map((x) => x.trim()); t = p[0]; owner = p[1] || ''; due = p[2] || ''; } else { let m = /\(([^)]{2,40})\)/.exec(t); if (m) { owner = m[1]; t = t.replace(m[0], '').trim(); } m = /,?\s*(?:by|due)\s+(.+)$/i.exec(t); if (m) { due = m[1]; t = t.slice(0, m.index).trim(); } } return [t, owner, due]; }); },
};
const ul = (bs) => h('ul', {}, bs.map((b) => h('li', { class: b.level ? 'l1' : '' }, b.text)));
export function stage(s, project) {
  const acc = project.theme.accent;
  const el = h('div', { class: 'stage' + (s.kind === 'title' ? ' title-slide' : ''), style: { fontFamily: project.theme.font + ',Segoe UI,sans-serif' } });
  el.style.setProperty('--ac', acc); el.style.setProperty('--ts', 'color-mix(in srgb,' + acc + ' 12%,white)');
  const inn = h('div', { class: 'in' }); el.append(inn);
  inn.append(h('h2', {}, s.title || 'Untitled slide'));
  if (s.kind === 'title') { inn.append(h('div', { style: { fontSize: '2.2cqw', marginTop: '1.5cqw' } }, s.takeaway)); return el; }
  const lay = s.layout; let body, bar = !!s.takeaway && !['key_message', 'recommendation', 'decision', 'quote', 'appendix', 'bullets'].includes(lay) && !(lay === 'data' && derive.pairs(s).length >= 2);
  if (['bullets', 'appendix'].includes(lay)) { body = ul(s.bullets); if (s.takeaway && lay === 'bullets') bar = true; }
  else if (['key_message', 'recommendation', 'decision'].includes(lay)) {
    let stmt = s.takeaway || (s.bullets[0] && s.bullets[0].text) || ''; if (stmt.trim().toLowerCase() === (s.title || '').trim().toLowerCase()) stmt = ''; const rest = s.bullets.filter((b) => b.text !== stmt).slice(0, 4);
    body = !stmt && !rest.length ? h('div', { class: 'muted', style: { color: '#9ca3af', fontSize: '2cqw' } }, 'No supporting content yet') : lay === 'key_message' ? h('div', { class: 'cols' }, stmt ? h('div', { class: 'big' }, stmt) : null, h('div', { style: { flex: 1, display: 'flex', flexDirection: 'column', gap: '1cqw' } }, rest.map((b) => h('div', { class: 'col' }, b.text))))
      : h('div', { style: { flex: 1, display: 'flex', flexDirection: 'column', gap: '1.6cqw' } }, h('div', { style: { background: 'var(--ac)', color: '#fff', padding: '2cqw', fontSize: '3cqw', fontWeight: 700 } }, stmt), h('div', { class: 'cols' }, rest.map((b) => h('div', { class: 'col' }, b.text))));
  } else if (['comparison', 'before_after', 'case'].includes(lay)) {
    const cols = lay === 'case' ? s.bullets.slice(0, 3).map((b, i) => ({ head: ['Situation', 'Action', 'Result'][i], items: [b.text] })) : derive.columns(s);
    body = h('div', { class: 'cols' }, cols.map((c) => h('div', { class: 'col hd' }, h('h4', {}, c.head), h('div', { class: 'b' }, ul(c.items.map((t) => ({ text: t, level: 0 })))))));
  } else if (['process', 'timeline', 'roadmap'].includes(lay)) {
    body = h('div', { class: 'cols' }, derive.steps(s).map((c) => h('div', { class: 'step' }, h('b', {}, c.head), h('div', { style: { fontSize: '1.9cqw', padding: '1cqw' } }, c.text))));
  } else if (lay === 'data' && derive.pairs(s).length >= 2) {
    const pr = derive.pairs(s), mx = Math.max(...pr.map((x) => x[1])) || 1;
    body = h('div', { class: 'cols' }, h('div', { style: { flex: 1.6 } }, pr.map(([l, v, u]) => h('div', { style: { display: 'flex', alignItems: 'center', gap: '1cqw', margin: '1.2cqw 0', fontSize: '1.9cqw' } }, h('span', { style: { width: '18cqw', textAlign: 'right' } }, l), h('span', { style: { height: '3cqw', width: (v / mx * 40) + 'cqw', background: 'var(--ac)' } }), h('b', {}, v + (u.includes('%') ? '%' : u ? ' ' + u : ''))))), h('div', { class: 'big', style: { fontSize: '2.6cqw' } }, s.takeaway || ''));
  } else if (lay === 'action_plan') {
    body = h('table', {}, h('thead', {}, h('tr', {}, ['Action', 'Owner', 'Due'].map((x) => h('th', {}, x)))), h('tbody', {}, derive.actions(s).map((r) => h('tr', {}, r.map((c, i) => h('td', {}, c || (i === 1 ? 'Owner needed' : i === 2 ? 'Date needed' : '')))))));
  } else if (lay === 'quote') { body = h('div', { class: 'quote' }, '“' + (s.quote || (s.bullets[0] || {}).text || '') + '”', h('div', { style: { fontSize: '2cqw', fontStyle: 'normal', color: '#6b7280' } }, s.quote_by || (s.bullets[1] || {}).text || '')); }
  else { const cs = derive.cards(s); body = h('div', { class: 'cols', style: { flexWrap: 'wrap' } }, cs.map((c, i) => h('div', { class: 'col', style: { minWidth: '22%' } }, lay === 'summary' ? h('div', { class: 'num' }, String(i + 1)) : null, c.lead ? h('h4', {}, c.lead) : null, h('div', { style: { fontWeight: lay === 'summary' ? 700 : 400 } }, c.text)))); }
  inn.append(body); if (bar) inn.append(h('div', { class: 'take' }, s.takeaway));
  const names = [...new Set(s.sources.map((r) => r.name))]; if (names.length) el.append(h('div', { class: 'src' }, 'Sources: ' + names.slice(0, 4).join('; ')));
  return el;
}
