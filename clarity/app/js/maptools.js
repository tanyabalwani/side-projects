// Pure map operations on the project's flat node list. Locked sections are respected everywhere.
import { S, nodes, byId, kids, root } from './state.js';
import { toast } from './util.js';
export const nid = () => 'n' + Math.random().toString(16).slice(2, 10);
export const blank = (parent, text, extra = {}) => ({ id: nid(), parent, text, note: '', kind: '', weight: 0, votes: 0, color: '', collapsed: false, ai: false, locked: false, owner: '', priority: '', status: 'draft', audience: '', src: [], flags: [], comments: [], rel: [], ...extra });
export function ensureRoot(text) {
  if (!root()) nodes().push(blank(null, text || S.project.governing || 'Main message', { kind: 'theme' }));
  return root();
}
export function addProposal(branches, parentId, ai = true) {
  const add = (b, parent) => { const n = blank(parent, b.text, { kind: b.kind || '', weight: b.weight || 0, src: b.src || [], ai: b.ai !== undefined ? b.ai : ai }); nodes().push(n); (b.children || []).forEach((c) => add(c, n.id)); };
  const existing = new Set(kids(parentId).map((k) => k.text.toLowerCase()));
  let added = 0;
  for (const b of branches) { const k = b.text.toLowerCase(); if (existing.has(k)) continue; existing.add(k); add(b, parentId); added++; }
  return added;
}
export const descendants = (id) => { const out = []; const walk = (x) => kids(x).forEach((k) => { out.push(k); walk(k.id); }); walk(id); return out; };
export const isDesc = (id, anc) => { let c = byId(id); while (c && c.parent) { if (c.parent === anc) return true; c = byId(c.parent); } return false; };
export const isLocked = (id) => { let c = byId(id); while (c) { if (c.locked) return true; c = c.parent ? byId(c.parent) : null; } return false; };
export const depth = (id) => { let d = 0, c = byId(id); while (c && c.parent) { d++; c = byId(c.parent); } return d; };
export function moveNode(id, newParent, index = null) {
  const n = byId(id);
  if (!n || !n.parent) return false;
  if (isLocked(id) || (newParent && isLocked(newParent) && newParent !== n.parent)) { toast('That section is locked.', 'bad'); return false; }
  if (newParent === id || isDesc(newParent, id)) return false;
  const list = nodes(), sibs = kids(newParent).filter((k) => k.id !== id);
  list.splice(list.indexOf(n), 1);
  n.parent = newParent;
  const target = index != null && index < sibs.length ? sibs[index] : null;
  if (target) list.splice(list.indexOf(target), 0, n); else list.push(n);
  return true;
}
export function deleteNode(id) {
  const n = byId(id);
  if (!n || !n.parent) { toast('The central message cannot be deleted.', 'bad'); return false; }
  const gone = [n, ...descendants(id)];
  if (gone.some((x) => x.locked)) { toast('That section is locked.', 'bad'); return false; }
  const set = new Set(gone.map((x) => x.id));
  S.project.map.nodes = nodes().filter((x) => !set.has(x.id));
  S.project.map.nodes.forEach((x) => { x.rel = (x.rel || []).filter((r) => !set.has(r.to)); });
  return true;
}
export function mergeNodes(ids) {
  const list = ids.map(byId).filter((n) => n && n.parent && !isLocked(n.id));
  if (list.length < 2) return null;
  const keep = list[0];
  for (const o of list.slice(1)) {
    kids(o.id).forEach((k) => { k.parent = keep.id; });
    if (o.note) keep.note = (keep.note ? keep.note + '\n' : '') + o.note;
    keep.src = [...new Set([...(keep.src || []), ...(o.src || [])])];
    keep.votes += o.votes; keep.weight = Math.max(keep.weight, o.weight);
    keep.comments = [...keep.comments, ...o.comments];
    S.project.map.nodes = nodes().filter((x) => x.id !== o.id);
  }
  return keep;
}
export function splitNode(id, parts) {
  const n = byId(id); if (!n || !n.parent || isLocked(id) || parts.length < 2) return [];
  n.text = parts[0];
  const out = [];
  let at = nodes().indexOf(n) + 1;
  for (const t of parts.slice(1)) { const c = blank(n.parent, t, { kind: n.kind, src: n.src }); nodes().splice(at++, 0, c); out.push(c); }
  return out;
}
export const path = (id) => { const out = []; let c = byId(id); while (c) { out.unshift(c.text); c = c.parent ? byId(c.parent) : null; } return out; };
