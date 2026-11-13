"""Storage layer: schema-driven sanitising of everything the browser sends,
atomic writes, optional encryption at rest (Fernet + scrypt), version snapshots,
and a hash-chained audit log."""
import base64, hashlib, hmac, json, os, re, secrets, shutil, tempfile, threading, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("CLARITY_DATA", ROOT / "data")).resolve()
LOCK = threading.RLock()
ID_RE = re.compile(r"^[0-9a-f]{16}$")
NID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
FONTS = ["Calibri", "Arial", "Georgia", "Verdana", "Trebuchet MS", "Segoe UI", "Helvetica"]
LAYOUTS = ["bullets", "key_message", "comparison", "process", "timeline", "framework", "data", "decision", "recommendation",
           "case", "quote", "before_after", "roadmap", "action_plan", "summary", "appendix"]
KINDS = ["title", "summary", "content", "ask", "appendix", "sources"]
CLASSES = ["internal", "public", "confidential", "restricted"]


class NotFound(Exception): pass
class Invalid(Exception): pass


# ------------------------------------------------------------- vault (encryption at rest)
class Vault:
    """Enabled when CLARITY_PASSPHRASE is set. All project, source and KB files are encrypted with
    Fernet; the key comes from scrypt(passphrase, per-install salt)."""
    def __init__(self): self.f = None

    def setup(self):
        pw = os.environ.get("CLARITY_PASSPHRASE")
        if not pw: return
        from cryptography.fernet import Fernet
        salt_p = DATA / "vault.salt"
        if not salt_p.exists():
            salt_p.write_bytes(secrets.token_bytes(16)); os.chmod(salt_p, 0o600)
        key = hashlib.scrypt(pw.encode(), salt=salt_p.read_bytes(), n=2 ** 15, r=8, p=1, dklen=32, maxmem=2 ** 27)
        self.f = Fernet(base64.urlsafe_b64encode(key))
        chk = DATA / "vault.check"
        if chk.exists():
            try: self.f.decrypt(chk.read_bytes())
            except Exception: raise SystemExit("CLARITY_PASSPHRASE does not match this data folder.")
        else:
            chk.write_bytes(self.f.encrypt(b"ok")); os.chmod(chk, 0o600)

    @property
    def enabled(self): return self.f is not None
    def enc(self, b: bytes) -> bytes: return self.f.encrypt(b) if self.f else b
    def dec(self, b: bytes) -> bytes: return self.f.decrypt(b) if self.f else b


VAULT = Vault()


def init_dirs():
    for p in (DATA, DATA / "projects", DATA / "kb" / "uploads"):
        p.mkdir(parents=True, exist_ok=True)
        try: os.chmod(p, 0o700)
        except OSError: pass
    VAULT.setup()


def new_id(): return secrets.token_hex(8)
def valid_id(x): return isinstance(x, str) and bool(ID_RE.match(x))


def pdir(pid) -> Path:
    if not valid_id(pid): raise NotFound("bad project id")
    p = DATA / "projects" / pid
    if not p.is_dir(): raise NotFound("project not found")
    return p


def atomic_write(path: Path, data: bytes, encrypt=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    if encrypt: data = VAULT.enc(data)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f: f.write(data)
        os.chmod(tmp, 0o600); os.replace(tmp, path)
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise


def read_file(path: Path) -> bytes:
    return VAULT.dec(path.read_bytes())


# ------------------------------------------------------------- schema-driven sanitiser
def S(n=200): return ("str", n)
def I(lo=0, hi=10 ** 6): return ("int", lo, hi)
def E(*vals): return ("enum", list(vals))
def L(cap, item): return ("list", cap, item)
def D(**fields): return ("dict", fields)
B = ("bool",); HEX = ("hex",); ID = ("id",)


def clean(v, spec, default=None):
    t = spec[0]
    if t == "raw": return v
    if t == "str": return v.strip()[:spec[1]] if isinstance(v, str) else ""
    if t == "bool": return bool(v)
    if t == "int":
        if isinstance(v, bool) or not isinstance(v, (int, float)): return spec[1]
        return min(spec[2], max(spec[1], int(v)))
    if t == "enum": return v if v in spec[1] else spec[1][0]
    if t == "hex": return v if isinstance(v, str) and HEX_RE.match(v) else ""
    if t == "id": return v if isinstance(v, str) and NID_RE.match(v) else ""
    if t == "list":
        out = []
        for x in (v if isinstance(v, list) else [])[:spec[1]]:
            c = clean(x, spec[2])
            if isinstance(c, dict) and "id" in spec[2][1] and not c.get("id"): continue
            if isinstance(x, str) and spec[2][0] == "str" and not c: continue
            out.append(c)
        return out
    if t == "dict":
        v = v if isinstance(v, dict) else {}
        return {k: clean(v.get(k), s) for k, s in spec[1].items()}
    raise Invalid("bad spec")


BULLET = D(text=S(300), level=I(0, 1), origin=E("user", "sourced", "ai"), cite=L(4, S(120)))
SRC_REF = D(name=S(160), origin=E("provided", "internal", "external"), snippet=S(400), doc=S(40))
NODE = D(id=ID, parent=S(40), text=S(300), note=S(2000), kind=E("", "theme", "evidence", "insight", "implication", "action", "risk", "question"),
         weight=I(0, 3), votes=I(0, 99), color=HEX, collapsed=B, ai=B, locked=B,
         owner=S(60), priority=E("", "high", "medium", "low"), status=E("draft", "review", "approved"), audience=S(60),
         src=L(4, S(120)), flags=L(4, S(80)),
         comments=L(30, D(id=ID, by=S(60), text=S(600), ts=I(0, 4 * 10 ** 9), resolved=B)),
         rel=L(8, D(id=ID, to=ID, label=S(60))))
SLIDE = D(id=ID, kind=E(*KINDS), layout=E(*LAYOUTS), title=S(200), purpose=S(200), bullets=L(14, BULLET),
          quote=S(400), quote_by=S(120), takeaway=S(300), notes=S(3000), visual=S(240), transition=S(240), facilitation=S(400),
          node_id=S(40), sources=L(12, SRC_REF), gaps=L(8, S(200)), approved=B, locked=B,
          override_layout=S(80), role=S(20), ref=S(200))
PROJECT = D(
    name=S(120),
    brief=D(purpose=S(1000), who=S(600), knows=S(600), feels=S(300), believes=S(300), decides=S(400), does=S(400),
            minutes=I(1, 480), intent=E("persuade", "inform", "align", "facilitate", "teach", "decide"),
            message=S(500), mandatory=S(1500), constraints=S(1000), sensitivities=S(1000), tone=S(120),
            outputs=L(6, E("presentation", "briefing", "workshop", "summary", "notes"))),
    framework=S(24), answers=("raw",), governing=S(500),
    map=("raw",),
    scope=D(mode=E("", "provided", "selected", "all", "none"), kb_docs=L(300, S(40)), excluded=L(200, S(40)),
            confirmed=B, ts=I(0, 4 * 10 ** 9)),
    storyline=D(structure=S(30), thesis=S(400), exec_summary=S(2000), openings=L(4, S(300)), closings=L(4, S(300)),
                appendix=L(10, S(200)), approved=B,
                alternatives=L(6, D(id=ID, name=S(60), order=L(60, S(40)), structure=S(30)))),
    slides=L(150, SLIDE),
    board=D(flow=D(mode=E("framework", "reference", "custom"), framework=S(24), ref_deck=S(40), intent=S(500)), items=L(150, SLIDE)),
    theme=D(accent=HEX, font=E(*FONTS)),
    security=D(classification=E(*CLASSES), watermark=S(60), redact_export=B, legal=S(300), confirm_remote=B),
    qc=D(resolutions=L(300, D(id=S(60), state=E("open", "resolved", "accepted", "override"), reason=S(300), ts=I(0, 4 * 10 ** 9)))),
    facilitation=D(
        agenda=L(40, D(id=ID, title=S(160), minutes=I(0, 480), done=B, activity=S(60))),
        parking=L(100, D(id=ID, text=S(400), by=S(60))),
        ideas=L(300, D(id=ID, text=S(300), by=S(60), anon=B, group=S(40), votes=I(0, 99))),
        groups=L(40, D(id=ID, name=S(100))),
        decisions=L(100, D(id=ID, text=S(400), owner=S(80), due=S(40), kind=E("decision", "action"), done=B)),
        questions=L(60, D(id=ID, q=S(300), a=S(1000))),
        vote_budget=I(1, 20), summary=S(3000),
        visibility=D(show_votes=B, allow_edit=B, allow_vote=B, allow_anon=B)),
)


def blank_project(name="Untitled presentation"):
    p = clean({}, PROJECT)
    p.update({"id": new_id(), "name": (name or "").strip()[:120] or "Untitled presentation", "created": int(time.time()), "updated": int(time.time()),
              "framework": "scqa", "answers": {}, "map": {"nodes": []}, "sources": [], "template": None})
    p["brief"].update({"minutes": 15, "tone": "Direct and confident", "outputs": ["presentation"]})
    p["theme"] = {"accent": "#1F4E79", "font": "Calibri"}
    p["facilitation"].update({"vote_budget": 3, "visibility": {"show_votes": True, "allow_edit": True, "allow_vote": True, "allow_anon": True}})
    return p


def sanitize_map(m):
    out, ids = [], set()
    for n in ((m or {}).get("nodes") if isinstance(m, dict) else [])[:600] if isinstance(m, dict) else []:
        if not isinstance(n, dict) or not NID_RE.match(str(n.get("id", ""))): raise Invalid("bad node id")
        c = clean(n, NODE)
        if c["id"] in ids: raise Invalid("duplicate node id")
        ids.add(c["id"]); c["parent"] = c["parent"] or None
        out.append(c)
    if out:
        byid = {n["id"]: n for n in out}
        if len([n for n in out if not n["parent"]]) != 1: raise Invalid("map needs exactly one root")
        for n in out:
            if n["parent"] and n["parent"] not in byid: raise Invalid("node parent missing")
            seen, cur = set(), n
            while cur["parent"]:
                if cur["id"] in seen: raise Invalid("cycle in map")
                seen.add(cur["id"]); cur = byid[cur["parent"]]
        for n in out: n["rel"] = [r for r in n["rel"] if r["to"] in byid]
    return {"nodes": out}


def sanitize_project(doc, cur):
    if not isinstance(doc, dict): raise Invalid("body must be an object")
    p = clean(doc, PROJECT)
    p["id"], p["created"], p["updated"] = cur["id"], cur["created"], int(time.time())
    p["sources"], p["template"] = cur.get("sources", []), cur.get("template")
    p["name"] = p["name"] or cur["name"]
    p["framework"] = re.sub(r"[^a-z0-9_]", "", p["framework"]) or "scqa"
    ans = doc.get("answers") if isinstance(doc.get("answers"), dict) else {}
    p["answers"] = {re.sub(r"[^a-z0-9_]", "", str(k))[:40]: (v.strip()[:4000] if isinstance(v, str) else "") for k, v in list(ans.items())[:40]}
    p["map"] = sanitize_map(doc.get("map"))
    p["scope"]["mode"] = p["scope"]["mode"] or None
    for s in p["slides"]:
        s["node_id"] = s["node_id"] if NID_RE.match(s["node_id"] or "x") else ""
    return p


# ------------------------------------------------------------- persistence
def load_project(pid):
    with LOCK:
        d = pdir(pid)
        p = json.loads(read_file(d / "project.json").decode("utf-8"))
    if "board" not in p: p["board"] = clean({}, PROJECT[1]["board"])      # projects made before the story board existed
    for sl in p.get("slides", []) + p["board"]["items"]: sl.setdefault("role", ""); sl.setdefault("ref", "")
    return p


def save_project(p, snapshot=False):
    with LOCK:
        d = pdir(p["id"])
        atomic_write(d / "project.json", json.dumps(p, ensure_ascii=False, indent=1).encode("utf-8"))
        if snapshot: take_snapshot(p, "autosave")


def take_snapshot(p, label="manual"):
    with LOCK:
        d = pdir(p["id"]) / "versions"
        d.mkdir(exist_ok=True)
        snaps = sorted(d.glob("*.json"))
        if label == "autosave" and snaps and time.time() - snaps[-1].stat().st_mtime < 90: return None
        vid = f"{int(time.time() * 1000)}-{secrets.token_hex(2)}"
        meta = {"label": re.sub(r"[^\w .-]", "", label)[:60] or "snapshot", "ts": int(time.time())}
        atomic_write(d / f"{vid}.json", json.dumps({"meta": meta, "project": p}, ensure_ascii=False).encode())
        for old in sorted(d.glob("*.json"))[:-40]: old.unlink()
        return vid


def list_snapshots(pid):
    d = pdir(pid) / "versions"
    out = []
    for f in sorted(d.glob("*.json"), reverse=True)[:40] if d.exists() else []:
        try:
            j = json.loads(read_file(f)); out.append({"id": f.stem, **j["meta"], "slides": len(j["project"].get("slides", [])),
                                                       "nodes": len(j["project"]["map"]["nodes"])})
        except Exception: pass
    return out


def load_snapshot(pid, vid):
    if not re.match(r"^\d{10,14}-[0-9a-f]{4}$", vid or ""): raise NotFound("bad version")
    f = pdir(pid) / "versions" / f"{vid}.json"
    if not f.exists(): raise NotFound("version not found")
    return json.loads(read_file(f))["project"]


def create_project(name):
    with LOCK:
        p = blank_project(name)
        (DATA / "projects" / p["id"]).mkdir(parents=True, mode=0o700)
        save_project(p)
        return p


def list_projects():
    out, base = [], DATA / "projects"
    for d in sorted(base.iterdir()) if base.exists() else []:
        if valid_id(d.name) and (d / "project.json").exists():
            try:
                p = json.loads(read_file(d / "project.json"))
                out.append({"id": p["id"], "name": p["name"], "updated": p["updated"], "slides": len(p.get("slides", [])),
                            "nodes": len(p["map"]["nodes"]), "classification": p.get("security", {}).get("classification", "internal")})
            except Exception: pass
    return sorted(out, key=lambda x: -x["updated"])


def delete_project(pid):
    with LOCK: shutil.rmtree(pdir(pid))


# ------------------------------------------------------------- audit trail (hash chained, append only)
AUDIT_LOCK = threading.Lock()


def audit(event: str, project=None, **detail):
    rec = {"ts": int(time.time()), "event": event, "project": project, "detail": {k: (str(v)[:200]) for k, v in detail.items()}}
    with AUDIT_LOCK:
        f = DATA / "audit.log"
        prev = "0" * 64
        if f.exists():
            try:
                with open(f, "rb") as fh:
                    fh.seek(max(0, f.stat().st_size - 2048)); last = fh.read().splitlines()[-1]
                prev = json.loads(last)["hash"]
            except Exception: pass
        rec["prev"] = prev
        rec["hash"] = hashlib.sha256((prev + json.dumps(rec, sort_keys=True)).encode()).hexdigest()
        with open(f, "ab") as fh: fh.write((json.dumps(rec) + "\n").encode())
        try: os.chmod(f, 0o600)
        except OSError: pass


def read_audit(project=None, limit=200):
    f = DATA / "audit.log"
    if not f.exists(): return {"events": [], "chain_ok": True}
    rows, prev, ok = [], "0" * 64, True
    for line in f.read_text("utf-8").splitlines():
        try:
            r = json.loads(line); h = r.pop("hash"); p = r.get("prev")
            calc = hashlib.sha256((p + json.dumps(r, sort_keys=True)).encode()).hexdigest()
            if p != prev or not hmac.compare_digest(calc, h): ok = False
            prev = h; r["hash"] = h
            if project is None or r.get("project") == project: rows.append(r)
        except Exception: ok = False
    return {"events": rows[-limit:][::-1], "chain_ok": ok}
