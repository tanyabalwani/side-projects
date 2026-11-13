// DOM helpers. Nothing here uses innerHTML: all text goes through text nodes.
const SVGNS = 'http://www.w3.org/2000/svg';
// Native append() would print "null" and "[object HTMLDivElement]" for empty or array children. Make it safe everywhere.
const nativeAppend = Element.prototype.append;
Element.prototype.append = function (...kids) { return nativeAppend.apply(this, kids.flat(Infinity).filter((k) => k != null && k !== false)); };
function append(el, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k == null || k === false) continue;
    el.append(k.nodeType ? k : document.createTextNode(String(k)));
  }
}
export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (let [k, v] of Object.entries(attrs || {})) {
    if (typeof v === 'boolean' && k.startsWith('aria-')) v = String(v);
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k === 'for') el.htmlFor = v;
    else if (k in el && k !== 'list' && k !== 'form') el[k] = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  append(el, kids);
  return el;
}
export function sv(tag, attrs, ...kids) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  append(el, kids);
  return el;
}
export const $ = (sel, root = document) => root.querySelector(sel);
export const clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); return el; };
export const uid = (p = 'n') => p + Math.random().toString(16).slice(2, 10);
export const debounce = (fn, ms = 400) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
export const trunc = (s, n) => (s || '').length > n ? s.slice(0, n - 1) + '…' : (s || '');
export const ago = (ts) => { const d = Date.now() / 1000 - ts; return d < 90 ? 'just now' : d < 3600 ? Math.round(d / 60) + ' min ago' : d < 86400 ? Math.round(d / 3600) + ' h ago' : Math.round(d / 86400) + ' d ago'; };

let CSRF = '';
// Actions that read the server's copy of the project must see the user's latest edits, so unsaved changes are flushed first.
let preflight = null;
export const setPreflight = (f) => { preflight = f; };
const NEEDS_FRESH = /^\/api\/projects\/[0-9a-f]{16}\/(map|generate|slides|refine|coach|facilitation|recommend|export|export-manifest|review|structures|scope|versions|sources-check)/;
export const setCsrf = (v) => { CSRF = v; };
export async function api(method, path, body, opts = {}) {
  if (preflight && NEEDS_FRESH.test(path)) await preflight();
  const headers = { 'X-CSRF': CSRF };
  let payload;
  if (opts.raw) { payload = body; headers['X-Filename'] = encodeURIComponent(opts.filename || 'file'); }
  else if (body !== undefined) { payload = JSON.stringify(body); headers['Content-Type'] = 'application/json'; }
  const r = await fetch(path, { method, headers, body: payload, credentials: 'same-origin' });
  const data = (r.headers.get('content-type') || '').includes('json') ? await r.json() : await r.blob();
  if (!r.ok) { const e = new Error((data && data.error) || 'Request failed'); e.status = r.status; e.data = data; throw e; }
  return data;
}
export async function download(path) {
  const r = await fetch(path, { credentials: 'same-origin' });
  if (!r.ok) { const d = await r.json().catch(() => ({})); const e = new Error(d.error || 'Download failed'); e.status = r.status; e.data = d; throw e; }
  const cd = r.headers.get('content-disposition') || '';
  const m = /filename\*=UTF-8''([^;]+)/.exec(cd);
  const name = m ? decodeURIComponent(m[1]) : 'download';
  const url = URL.createObjectURL(await r.blob());
  const a = h('a', { href: url, download: name }); document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
  return name;
}
export function toast(msg, kind = '') {
  const t = h('div', { class: 'toast ' + kind }, msg);
  $('#toasts').append(t); setTimeout(() => t.remove(), kind === 'bad' ? 7000 : 3500);
}
const stack = [];
export function modal(build, { small = false, onClose } = {}) {
  const ov = $('#overlay');
  const box = h('div', { class: 'modal' + (small ? ' sm' : ''), role: 'dialog', 'aria-modal': 'true' });
  const close = (v) => { box.remove(); stack.pop(); if (!stack.length) ov.hidden = true; if (onClose) onClose(v); document.removeEventListener('keydown', esc); };
  const esc = (e) => { if (e.key === 'Escape' && stack[stack.length - 1] === close) close(); };
  document.addEventListener('keydown', esc);
  stack.push(close);
  build(box, close);
  ov.append(box); ov.hidden = false;
  const f = box.querySelector('input,textarea,select,button'); if (f) f.focus();
  return close;
}
export const confirmBox = (msg, ok = 'Confirm', danger = false) => new Promise((res) => modal((b, close) => {
  b.append(h('p', {}, msg), h('div', { class: 'row', style: { justifyContent: 'flex-end' } },
    h('button', { class: 'btn', onclick: () => close(false) }, 'Cancel'), h('button', { class: 'btn ' + (danger ? 'danger' : 'primary'), onclick: () => close(true) }, ok)));
}, { small: true, onClose: (v) => res(!!v) }));
export const promptBox = (label, value = '', multiline = false) => new Promise((res) => modal((b, close) => {
  const inp = multiline ? h('textarea', { rows: 4 }, value) : h('input', { type: 'text', value });
  inp.value = value;
  inp.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !multiline) close(inp.value); });
  b.append(h('label', { class: 'f' }, h('span', {}, label), inp), h('div', { class: 'row', style: { justifyContent: 'flex-end', marginTop: '12px' } },
    h('button', { class: 'btn', onclick: () => close(null) }, 'Cancel'), h('button', { class: 'btn primary', onclick: () => close(inp.value) }, 'OK')));
}, { small: true, onClose: (v) => res(v == null ? null : v) }));
export function field(label, input, hint) { return h('label', { class: 'f' }, h('span', {}, label), input, hint ? h('small', {}, hint) : null); }
export const chip = (text, kind = '', title = '') => h('span', { class: 'chip ' + kind, title }, text);
export function spin(btn, fn) {
  return async (...a) => { const t = btn.textContent; btn.disabled = true; btn.textContent = 'Working…'; try { return await fn(...a); } finally { btn.disabled = false; btn.textContent = t; } };
}
export async function pollJob(id, onProg) {
  for (;;) {
    const j = await api('GET', '/api/jobs/' + id);
    if (onProg) onProg(j);
    if (j.state !== 'running') { if (j.state === 'error') { const e = new Error(j.error); e.data = j; throw e; } return j.result; }
    await new Promise((r) => setTimeout(r, 400));
  }
}
export const KINDS = { theme: 'Theme', evidence: 'Evidence', insight: 'Insight', implication: 'Implication', action: 'Action', risk: 'Risk', question: 'Open question' };
export const LAYOUT_NAMES = { bullets: 'Text list', key_message: 'Key message', comparison: 'Comparison', process: 'Process', timeline: 'Timeline', framework: 'Cards', data: 'Data chart', decision: 'Decision', recommendation: 'Recommendation', case: 'Case study', quote: 'Quote', before_after: 'Before and after', roadmap: 'Roadmap', action_plan: 'Action plan', summary: 'Summary', appendix: 'Appendix' };
