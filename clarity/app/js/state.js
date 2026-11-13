import { api, toast, debounce, setPreflight } from './util.js';
export const S = { project: null, meta: null, view: 'dashboard', undo: [], redo: [], status: 'saved', lastSnap: '', lastLabel: '', lastT: 0, listeners: [], ai: null };
export const on = (fn) => S.listeners.push(fn);
export const emit = (kind) => S.listeners.forEach((f) => f(kind));
const KEYS = ['name', 'brief', 'framework', 'answers', 'governing', 'map', 'scope', 'storyline', 'slides', 'theme', 'security', 'qc', 'facilitation'];
const snap = () => JSON.stringify(Object.fromEntries(KEYS.map((k) => [k, S.project[k]])));
export async function openProject(id) {
  S.project = await api('GET', '/api/projects/' + id);
  S.undo = []; S.redo = []; S.lastSnap = snap(); S.status = 'saved';
  S.ai = (await api('GET', '/api/security?project=' + id)).ai;
  emit('project');
}
export const closeProject = () => { S.project = null; emit('project'); };
const flush = async () => {
  if (!S.project) return;
  S.status = 'saving'; emit('status');
  try {
    const r = await api('PUT', '/api/projects/' + S.project.id, S.project);
    S.project.sources = r.sources; S.project.template = r.template; S.project.scope_conf = r.scope_conf;
    S.status = 'saved';
  } catch (e) { S.status = 'error'; toast('Not saved: ' + e.message, 'bad'); }
  emit('status');
};
const schedule = debounce(flush, 600);
setPreflight(async () => { if (S.project && (S.status === 'unsaved' || S.status === 'error')) await flush(); });
export function commit(label = 'edit') {
  const now = Date.now();
  if (!(label === S.lastLabel && now - S.lastT < 1500)) { S.undo.push(S.lastSnap); if (S.undo.length > 60) S.undo.shift(); S.redo = []; }
  S.lastLabel = label; S.lastT = now; S.lastSnap = snap(); S.status = 'unsaved'; emit('status'); schedule();
}
export const saveNow = flush;
function restore(json) { const o = JSON.parse(json); for (const k of KEYS) S.project[k] = o[k]; S.lastSnap = json; S.status = 'unsaved'; schedule(); emit('rerender'); }
export function undo() { if (!S.undo.length) return; S.redo.push(S.lastSnap); restore(S.undo.pop()); }
export function redo() { if (!S.redo.length) return; S.undo.push(S.lastSnap); restore(S.redo.pop()); }
export const refreshAI = async () => { S.ai = (await api('GET', '/api/security?project=' + S.project.id)).ai; emit('status'); };
export const nodes = () => S.project.map.nodes;
export const root = () => nodes().find((n) => !n.parent);
export const kids = (id) => nodes().filter((n) => n.parent === id);
export const byId = (id) => nodes().find((n) => n.id === id);
