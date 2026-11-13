"""Chunking, BM25 retrieval, and the knowledge base (folders + uploaded library) with
approval status, ownership, tags, review dates, versions, duplicates and eligibility rules."""
import datetime, hashlib, json, math, os, re, threading, time
from collections import Counter
from pathlib import Path
import store, ingest, safety
from analysis import tokens, shingles, jaccard

CLASS_RANK = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
KB_EXT = ingest.ALLOWED_EXT
SENSITIVE_NAME = re.compile(r"(?i)(id_rsa|id_ed25519|\.pem$|\.key$|\.p12$|\.pfx$|\.kdbx$|\.env|secret|credential|passw|token|\.npmrc|\.netrc)")
DENY_PARTS = {".ssh", ".aws", ".gnupg", ".config", ".kube", ".docker"}
DENY_ROOTS = {"/", "/etc", "/proc", "/sys", "/dev", "/var", "/usr", "/bin", "/sbin", "/boot", "/lib", "/root", "/run", "/home"}
MAX_FILES, MAX_FILE = 2000, 10 * 1024 * 1024


def chunk_text(text, size=900):
    paras, chunks, cur, head = [p.strip() for p in re.split(r"\n{2,}|\n(?=#)", text or "") if p.strip()], [], "", ""
    for p in paras:
        if p.startswith("#"): head = p.lstrip("# ").strip()[:80]
        if len(cur) + len(p) > size and cur:
            chunks.append(cur); cur = (head + ": " if head and not p.startswith("#") else "") + p
        else: cur = (cur + "\n" + p) if cur else p
        while len(cur) > size * 2: chunks.append(cur[:size * 2]); cur = cur[size * 2:]
    if cur: chunks.append(cur)
    return chunks


class Chunk:
    __slots__ = ("sid", "name", "origin", "text", "toks", "doc")
    def __init__(self, sid, name, origin, text, doc=""):
        self.sid, self.name, self.origin, self.text, self.doc = sid, name, origin, text, doc
        self.toks = tokens(text)


class BM25:
    def __init__(self, chunks, k1=1.4, b=0.75):
        self.chunks, self.k1, self.b = chunks, k1, b
        self.N = len(chunks) or 1
        self.avg = (sum(len(c.toks) for c in chunks) / self.N) or 1
        self.df = Counter(t for c in chunks for t in set(c.toks))
        self.tf = [Counter(c.toks) for c in chunks]

    def search(self, query, k=5):
        q = set(tokens(query))
        scores = []
        for i, c in enumerate(self.chunks):
            s, dl = 0.0, len(c.toks) or 1
            for t in q:
                f = self.tf[i].get(t, 0)
                if not f: continue
                idf = math.log(1 + (self.N - self.df[t] + 0.5) / (self.df[t] + 0.5))
                s += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avg))
            if s > 0: scores.append((s, i))
        return [self.chunks[i] for _, i in sorted(scores, reverse=True)[:k]]


# ------------------------------------------------------------------ knowledge base
KBLOCK = threading.RLock()
_cache = {}


def _cfg_path(): return store.DATA / "kb" / "config.json"


def kb_cfg():
    p = _cfg_path()
    if p.exists():
        try: return json.loads(store.read_file(p))
        except Exception: pass
    return {"folders": [], "meta": {}}


def kb_save(cfg): store.atomic_write(_cfg_path(), json.dumps(cfg).encode())


def _meta_defaults(): return {"status": "approved", "owner": "", "tags": [], "review_by": "", "classification": "internal", "version": 1, "note": ""}


def _today(): return datetime.date.today().isoformat()


def check_folder(path: str) -> Path:
    p = Path(os.path.expanduser(path or "")).resolve()
    if not p.is_dir(): raise ingest.IngestError("folder not found")
    if str(p) in DENY_ROOTS or p == Path.home(): raise ingest.IngestError("that folder is too broad; choose a specific knowledge folder")
    if DENY_PARTS & set(p.parts): raise ingest.IngestError("folders holding credentials or config are not allowed")
    roots = [Path(r).resolve() for r in os.environ.get("CLARITY_KB_ROOTS", "").split(os.pathsep) if r]
    if roots and not any(p == r or r in p.parents for r in roots): raise ingest.IngestError("folder is outside the roots your administrator approved")
    if not os.access(p, os.R_OK | os.X_OK): raise ingest.IngestError("no permission to read that folder")
    return p


def add_folder(path, name=""):
    p = check_folder(path)
    with KBLOCK:
        cfg = kb_cfg()
        if any(f["path"] == str(p) for f in cfg["folders"]): raise ingest.IngestError("folder already added")
        f = {"id": store.new_id(), "path": str(p), "name": (name or p.name)[:80], "enabled": True}
        cfg["folders"].append(f); kb_save(cfg)
        return f


def _walk(folder):
    root, n = Path(folder["path"]), 0
    if not root.is_dir(): return
    for dp, dns, fns in os.walk(root, followlinks=False):
        dns[:] = [d for d in dns if not d.startswith(".") and d not in DENY_PARTS and not os.path.islink(os.path.join(dp, d))]
        for fn in fns:
            fp = Path(dp) / fn
            if fn.startswith(".") or SENSITIVE_NAME.search(fn) or fp.suffix.lower() not in KB_EXT or fp.is_symlink(): continue
            try:
                rp = fp.resolve()
                if root not in rp.parents or rp.stat().st_size > MAX_FILE or not os.access(rp, os.R_OK): continue
            except OSError: continue
            n += 1
            if n > MAX_FILES: return
            yield rp


def _did(key): return hashlib.sha1(key.encode()).hexdigest()[:16]


def _text_for(path: Path):
    st = path.stat(); k = (str(path), st.st_mtime_ns, st.st_size)
    if k in _cache: return _cache[k]
    try: t = ingest.extract_text(path.name, path.read_bytes())
    except Exception: t = ""
    _cache[k] = t
    if len(_cache) > 3000: _cache.clear()
    return t


def list_docs(include_text=False):
    """All documents with metadata + eligibility flags."""
    cfg = kb_cfg(); docs = []
    def add(did, name, origin, src, text_fn, extra):
        m = {**_meta_defaults(), **cfg["meta"].get(did, {})}
        reasons = []
        if m["status"] != "approved": reasons.append(m["status"])
        if m["review_by"] and m["review_by"] < _today(): reasons.append("expired")
        d = {"id": did, "name": name, "origin": origin, "source": src, **m, "eligible": not reasons, "flags": reasons, **extra}
        if include_text: d["_text"] = text_fn()
        docs.append(d)
    up = store.DATA / "kb" / "uploads"
    for f in sorted(up.glob("*.json")) if up.exists() else []:
        try: j = json.loads(store.read_file(f))
        except Exception: continue
        add(j["id"], j["name"], "library", "uploaded", lambda f=f: store.read_file(f.with_suffix(".txt")).decode("utf-8", "replace"),
            {"chars": j.get("chars", 0), "sha": j.get("sha", ""), "folder": "library"})
    for fo in cfg["folders"]:
        if not fo.get("enabled"): continue
        for rp in _walk(fo):
            did = _did(str(rp))
            add(did, rp.name, "folder", fo["name"], lambda rp=rp: _text_for(rp), {"path_rel": str(rp.relative_to(fo["path"])), "folder": fo["id"], "chars": rp.stat().st_size})
    return docs


def add_library_doc(name, data, meta=None):
    text = ingest.extract_text(name, data)
    sha = hashlib.sha256(text.encode()).hexdigest()
    cfg = kb_cfg(); up = store.DATA / "kb" / "uploads"
    version, prev = 1, None
    for d in list_docs():
        if d["origin"] == "library" and d["name"] == name and d["status"] == "approved": prev = d; version = d["version"] + 1
        if d["origin"] == "library" and d["sha"] == sha: raise ingest.IngestError(f"duplicate of existing document '{d['name']}'")
    did = store.new_id()
    store.atomic_write(up / f"{did}.txt", text.encode("utf-8"))
    store.atomic_write(up / f"{did}.json", json.dumps({"id": did, "name": name, "chars": len(text), "sha": sha, "added": int(time.time())}).encode())
    m = {**_meta_defaults(), "version": version, **{k: v for k, v in (meta or {}).items() if k in _meta_defaults()}}
    with KBLOCK:
        cfg = kb_cfg()
        if prev:
            cfg["meta"].setdefault(prev["id"], {})["status"] = "superseded"
        cfg["meta"][did] = m; kb_save(cfg)
    return did


def update_doc_meta(did, fields):
    if not re.match(r"^[0-9a-f]{16}$", did or ""): raise store.NotFound("bad id")
    with KBLOCK:
        cfg = kb_cfg(); m = cfg["meta"].setdefault(did, {})
        if fields.get("status") in ("approved", "draft", "superseded", "archived"): m["status"] = fields["status"]
        for k, n in (("owner", 80), ("note", 400)):
            if isinstance(fields.get(k), str): m[k] = fields[k][:n]
        if isinstance(fields.get("tags"), list): m["tags"] = [str(t)[:30] for t in fields["tags"]][:12]
        if isinstance(fields.get("review_by"), str) and re.match(r"^(\d{4}-\d{2}-\d{2})?$", fields["review_by"]): m["review_by"] = fields["review_by"]
        if fields.get("classification") in CLASS_RANK: m["classification"] = fields["classification"]
        kb_save(cfg)


def remove_doc(did):
    up = store.DATA / "kb" / "uploads"
    for ext in (".json", ".txt"):
        f = up / f"{did}{ext}"
        if re.match(r"^[0-9a-f]{16}$", did) and f.exists(): f.unlink()


def duplicates(docs):
    out, sh = [], []
    for d in docs:
        t = d.get("_text") or ""
        sh.append((d, shingles(t[:4000])))
    for i in range(len(sh)):
        for j in range(i + 1, len(sh)):
            if sh[i][1] and jaccard(sh[i][1], sh[j][1]) > 0.8: out.append([sh[i][0]["name"], sh[j][0]["name"]])
    return out[:20]


def kb_chunks(doc_ids=None, project_class="internal", allow_ineligible=()):
    """Chunks from eligible docs (or an explicit id list; explicitly chosen ineligible docs are included but flagged)."""
    out, notes = [], []
    for d in list_docs(include_text=True):
        if doc_ids is not None and d["id"] not in doc_ids: continue
        if doc_ids is None and not d["eligible"]: continue
        if CLASS_RANK.get(d["classification"], 1) > CLASS_RANK.get(project_class, 1):
            notes.append(f"'{d['name']}' skipped: classified {d['classification']}, above this project's level"); continue
        if not d["eligible"]: notes.append(f"'{d['name']}' used by explicit choice although {', '.join(d['flags'])}")
        for c in chunk_text(safety.neutralise(d.get("_text", "")))[:60]: out.append(Chunk(d["id"], d["name"], "internal", c, d["id"]))
    return out, notes
