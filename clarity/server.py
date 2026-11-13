#!/usr/bin/env python3
"""Clarity: local-first presentation workspace. Binds to loopback only.
Run:  python3 server.py --open"""
import argparse, hashlib, hmac, json, mimetypes, os, re, secrets, shutil, sys, threading, time, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs, unquote, quote

import store, ingest, safety, sources, retrieval, ai, deck, decks, review, export, frameworks, style, analysis

APP = store.ROOT / "app"
TOKEN = os.environ.get("CLARITY_TOKEN") or secrets.token_urlsafe(32)
CSRF = hmac.new(TOKEN.encode(), b"csrf", hashlib.sha256).hexdigest()
COOKIE = "cd_session"
MAX_JSON, MAX_RAW = 4 * 1024 * 1024, ingest.MAX_UPLOAD
ROUTES, JOBS = [], {}
PORT = 0
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'; object-src 'none'")


class Raw:
    def __init__(self, data, ctype, filename=None): self.data, self.ctype, self.filename = data, ctype, filename


class HttpError(Exception):
    def __init__(self, code, msg, **extra): self.code, self.msg, self.extra = code, msg, extra


def route(method, pattern, raw=False):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn, raw)); return fn
    return deco


def P(m):  # load project from match
    return store.load_project(m.group("pid"))


def save(p, snapshot=False): store.save_project(p, snapshot)


# ---------------------------------------------------------------- session / meta
@route("GET", r"/api/session")
def session(r): return 200, {"csrf": CSRF, "ai": ai.status()}


@route("GET", r"/api/meta")
def meta(r):
    return 200, {"frameworks": frameworks.FRAMEWORKS, "layouts": store.LAYOUTS, "modes": ai.MODES, "fonts": store.FONTS, "classes": store.CLASSES,
                 "ai": ai.status(), "vault": store.VAULT.enabled, "version": "1.0"}


@route("GET", r"/api/security")
def security(r):
    pid = r.query.get("project")
    p = store.load_project(pid) if pid else None
    st = ai.status(p)
    return 200, {"ai": st, "allowed_providers": ai.ALLOWED, "encryption_at_rest": store.VAULT.enabled, "binding": f"127.0.0.1:{PORT} only (no network access)",
                 "data_dir": str(store.DATA), "antivirus": bool(shutil.which("clamscan") or shutil.which("clamdscan")), "kb_roots": os.environ.get("CLARITY_KB_ROOTS", "") or "any folder you add",
                 "access": "Only this operating-system user, through this browser session. There are no accounts, SSO, or shared access.",
                 "private_links": "blocked" if not ingest.ALLOW_PRIVATE else "allowed (administrator setting)"}


@route("GET", r"/api/audit")
def audit_log(r): return 200, store.read_audit(r.query.get("project"))


# ---------------------------------------------------------------- projects
@route("GET", r"/api/projects")
def plist(r): return 200, {"projects": store.list_projects()}


@route("POST", r"/api/projects")
def pcreate(r):
    p = store.create_project((r.body or {}).get("name", ""))
    store.audit("project_create", p["id"]); return 201, p


@route("GET", r"/api/projects/(?P<pid>[0-9a-f]{16})")
def pget(r):
    p = P(r.m); store.audit("project_open", p["id"]); return 200, p


@route("PUT", r"/api/projects/(?P<pid>[0-9a-f]{16})")
def pput(r):
    cur = P(r.m)
    new = store.sanitize_project(r.body, cur)
    new["scope_conf"] = cur.get("scope_conf", {})
    if new["scope"] != cur["scope"] and new["scope"]["mode"] in ("selected", "all") and sources.scope_hash(new["scope"]) != new["scope_conf"].get("hash"):
        store.audit("scope_changed_unconfirmed", cur["id"], mode=new["scope"]["mode"])
    changed = (len(new["slides"]), len(new["map"]["nodes"])) != (len(cur["slides"]), len(cur["map"]["nodes"]))
    save(new, snapshot=changed)
    if changed: store.audit("project_edit", cur["id"], slides=len(new["slides"]), nodes=len(new["map"]["nodes"]))
    return 200, {"ok": True, "updated": new["updated"], "sources": new["sources"], "template": new["template"], "scope_conf": new["scope_conf"]}


@route("DELETE", r"/api/projects/(?P<pid>[0-9a-f]{16})")
def pdel(r):
    store.delete_project(r.m.group("pid")); store.audit("project_delete", r.m.group("pid")); return 200, {"ok": True}


@route("POST", r"/api/projects/(?P<pid>[0-9a-f]{16})/recommend")
def recommend(r):
    p = P(r.m); b = r.body if isinstance(r.body, dict) else {}
    brief = store.clean(b.get("brief"), store.PROJECT[1]["brief"]) if b.get("brief") else p["brief"]
    recs = frameworks.recommend(brief)
    return 200, {"recommended": recs}


@route("POST", r"/api/projects/(?P<pid>[0-9a-f]{16})/coach")
def coach(r):
    q, eng = ai.coach(P(r.m)); return 200, {"questions": q, "engine": eng}


# ---------------------------------------------------------------- sources
def _src_public(p): return p["sources"]


@route("POST", r"/api/projects/(?P<pid>[0-9a-f]{16})/sources/text")
def s_text(r):
    p = P(r.m); b = r.body or {}
    rec = sources.add_text(p, str(b.get("name", ""))[:120], b.get("text", ""))
    save(p); store.audit("source_add", p["id"], kind="text", name=rec["name"]); return 201, {"source": rec, "sources": p["sources"]}


@route("POST", r"/api/projects/(?P<pid>[0-9a-f]{16})/decks", raw=True)
def deck_add(r):
    p = P(r.m); name = unquote(r.h.headers.get("X-Filename", "deck.pptx"))
    rec = sources.add_deck(p, name, r.body); save(p)
    store.audit("deck_import", p["id"], name=rec["name"], slides=rec.get("slides", 0)); return 201, {"source": rec, "sources": p["sources"]}


@route("GET", r"/api/projects/(?P<pid>[0-9a-f]{16})/decks")
def deck_list(r): return 200, decks.library(P(r.m))


STORY_FLOW = store.D(mode=store.E("framework", "reference", "custom"), framework=store.S(24), ref_deck=store.S(40), intent=store.S(500))


@route("POST", r"/api/projects/(?P<pid>[0-9a-f]{16})/story/suggest")
def story_suggest(r):
    p = P(r.m); b = r.body or {}
    items = store.clean(b.get("items"), store.L(150, store.SLIDE)); flow = store.clean(b.get("flow"), STORY_FLOW)
    out = decks.suggest(p, items, flow)
    out["notes"], out["engine"] = ai.story_notes(p, items, out["target"])
    store.audit("story_suggest", p["id"], items=len(items), target=out["target"], engine=out["engine"])
    return 200, out


@route("POST", r"/api/projects/(?P<pid>[0-9a-f]{16})/story/draft")
def story_draft(r):
    p = P(r.m); b = r.body or {}; kind = "ask" if b.get("kind") == "ask" else "answer"
    return 200, {"slide": store.clean(decks.draft(p, kind, store.clean(b.get("items"), store.L(150, store.SLIDE))), store.SLIDE)}


@route("POST", r"/api/projects/(?P<pid>[0-9a-f]{16})/sources/link")
def s_link(r):
    p = P(r.m); url = str((r.body or {}).get("url", ""))[:2000]
    rec = sources.add_link(p, url); save(p)
    store.audit("source_add", p["id"], kind="link", host=ingest.urlsplit(url).hostname); return 201, {"source": rec, "sources": p["sources"]}


@route("POST", r"/api/projects/(?P<pid>[0-9a-f]{16})/sources/upload", raw=True)
def s_upload(r):
    p = P(r.m); name = unquote(r.h.headers.get("X-Filename", "file"))
    rec = sources.add_file(p, name, r.body); save(p)
    store.audit("source_add", p["id"], kind="file", name=rec["name"], warnings=len(rec["warnings"])); return 201, {"source": rec, "sources": p["sources"]}


@route("GET", r"/api/projects/(?P<pid>[0-9a-f]{16})/sources/(?P<sid>[0-9a-f]{16})")
def s_get(r):
    p = P(r.m); return 200, {"text": sources.get_text(p["id"], r.m.group("sid"))[:60000]}


@route("PUT", r"/api/projects/(?P<pid>[0-9a-f]{16})/sources/(?P<sid>[0-9a-f]{16})")
def s_put(r):
    p = P(r.m); b = r.body or {}; sid = r.m.group("sid")
    rec = next((s for s in p["sources"] if s["id"] == sid), None)
    if not rec: raise store.NotFound("source not found")
    if "include" in b: rec["include"] = bool(b["include"])
    if isinstance(b.get("text"), str): sources.set_text(p, sid, b["text"])
    save(p); return 200, {"sources": p["sources"]}


@route("DELETE", r"/api/projects/(?P<pid>[0-9a-f]{16})/sources/(?P<sid>[0-9a-f]{16})")
def s_del(r):
    p = P(r.m); sources.remove(p, r.m.group("sid")); save(p); store.audit("source_remove", p["id"]); return 200, {"sources": p["sources"]}


@route("GET", r"/api/projects/(?P<pid>[0-9a-f]{16})/sources-check")
def s_check(r):
    p = P(r.m)
    items = [{"id": s["id"], "name": s["name"], "text": sources.get_text(p["id"], s["id"])} for s in p["sources"] if s.get("include", True)]
    return 200, analysis.cross_checks(items)


# ---------------------------------------------------------------- scope & knowledge boundaries
@route("GET", r"/api/projects/(?P<pid>[0-9a-f]{16})/scope")
def scope_get(r):
    p = P(r.m)
    docs = [{k: v for k, v in d.items() if k != "_text"} for d in retrieval.list_docs()]
    st = ai.status(p)
    return 200, {"scope": p["scope"], "confirmed": p.get("scope_conf", {}).get("hash") == sources.scope_hash(p["scope"]), "docs": docs,
                 "provided": [{"id": s["id"], "name": s["name"], "origin": s["origin"], "include": s.get("include", True), "chars": s["chars"]} for s in p["sources"]], "ai": st}


@route("POST", r"/api/projects/(?P<pid>[0-9a-f]{16})/scope")
def scope_set(r):
    p = P(r.m); b = r.body or {}
    sc = store.clean(b, store.PROJECT[1]["scope"]); sc["ts"] = int(time.time())
    if not sc["mode"]: raise store.Invalid("choose a scope")
    if sc["mode"] != "selected": sc["kb_docs"] = []
    sc["confirmed"] = False
    if sc["mode"] in ("selected", "all"):
        if not b.get("confirm"): raise HttpError(409, "Using organisational knowledge needs your confirmation.", need="confirm")
        p["scope_conf"] = {"hash": sources.scope_hash(sc), "ts": int(time.time())}; sc["confirmed"] = True
    else: p["scope_conf"] = {}
    p["scope"] = sc; save(p)
    store.audit("scope_set", p["id"], mode=sc["mode"], kb_docs=len(sc["kb_docs"]), excluded=len(sc["excluded"]))
    return 200, {"scope": sc}


# ---------------------------------------------------------------- map
def _scope_chunks(p):
    try: return sources.resolve(p)
    except PermissionError as e: raise HttpError(403, str(e), need="scope")


def _audit_kb(p, chunks):
    docs = sorted({c.name for c in chunks if c.origin == "internal"})
    if docs: store.audit("kb_use", p["id"], docs=",".join(docs)[:180], count=len(docs))


@route("POST", r"/api/projects/(?P<pid>[0-9a-f]{16})/map/propose")
def map_propose(r):
    p = P(r.m); chunks, notes, summ = _scope_chunks(p); _audit_kb(p, chunks)
    texts, seen = [], set()
    if summ["mode"] != "none":
        for s in p["sources"]:
            if s.get("include", True) and s["sha"] not in seen:
                seen.add(s["sha"]); texts.append((s["name"], safety.neutralise(sources.get_text(p["id"], s["id"]))))
    out = ai.propose_map(p, chunks, texts)
    out["notes"] = ([out["note"]] if out.get("note") else []) + notes; out["scope"] = summ
    return 200, out


@route("POST", r"/api/projects/(?P<pid>[0-9a-f]{16})/map/suggestions")
def map_sugg(r): return 200, {"suggestions": ai.map_suggestions(P(r.m))}


@route("POST", r"/api/projects/(?P<pid>[0-9a-f]{16})/map/expand")
def map_expand(r):
    p = P(r.m); b = r.body or {}
    chunks, notes, _ = _scope_chunks(p); _audit_kb(p, chunks)
    text = str(b.get("text", ""))[:300]
    kids, eng = ai.suggest_children(p, text, [str(x)[:100] for x in (b.get("siblings") or [])[:10]], ai.retrieve_for(chunks, text, 8))
    return 200, {"children": kids, "engine": eng}


@route("POST", r"/api/projects/(?P<pid>[0-9a-f]{16})/map/seed")
def map_seed(r):
    p = P(r.m); fw = frameworks.FW.get(p["framework"], frameworks.FW["reverse_pyramid"]); a = p["answers"]
    branches, ans_text = [], p["governing"]
    lines = lambda k: [l.strip(" -•*\t") for l in re.split(r"\n+", a.get(k, "")) if l.strip(" -•*\t")]
    for s in fw["steps"]:
        ls = lines(s["key"])
        if not ls: continue
        if s["role"] == "answer" and not ans_text: ans_text = ls[0]
        elif s["role"] == "arguments": branches += [ai._node(l, "", 0, [], [], False) for l in ls]
        elif s["role"] in ("section", "ask", "appendix", "context"):
            label = {"ask": "Next steps", "appendix": "Background", "context": s["label"]}.get(s["role"], s["label"])
            branches.append(ai._node(label, "action" if s["role"] == "ask" else "theme", 0, [], [ai._node(l, "", 0, [], [], False) for l in ls], False))
    return 200, {"root": ans_text, "branches": branches}


# ---------------------------------------------------------------- generation
def run_job(fn):
    jid = secrets.token_hex(8); JOBS[jid] = {"state": "running", "done": 0, "total": 0, "label": "", "result": None, "error": None, "t": time.time()}
    def work():
        def prog(d, t, l): JOBS[jid].update(done=d, total=t, label=l)
        try: JOBS[jid]["result"] = fn(prog); JOBS[jid]["state"] = "done"
        except PermissionError as e: JOBS[jid].update(state="error", error=str(e), need="scope")
        except (store.Invalid, store.NotFound) as e: JOBS[jid].update(state="error", error=str(e))
        except Exception as e:
            sys.stderr.write(f"job error: {type(e).__name__}\n"); JOBS[jid].update(state="error", error="Generation failed. See the server log.")
    threading.Thread(target=work, daemon=True).start()
    for k in [k for k, v in JOBS.items() if time.time() - v["t"] > 3600]: JOBS.pop(k, None)
    return jid


@route("POST", r"/api/projects/(?P<pid>[0-9a-f]{16})/generate")
def generate(r):
    pid = r.m.group("pid"); b = r.body or {}
    p = store.load_project(pid); _scope_chunks(p)  # fail fast with a clear 403
    structure = re.sub(r"[^a-z_]", "", str(b.get("structure", "")))[:24] or None
    keep = b.get("keep_locked", True)
    def job(prog):
        p = store.load_project(pid); chunks, notes, summ = sources.resolve(p); _audit_kb(p, chunks)
        slides, story = deck.build(p, chunks, structure, prog, keep)
        store.audit("deck_generate", pid, slides=len(slides), scope=summ["mode"], engine=story.get("engine"), provider=ai.provider()["name"])
        return {"slides": store.clean(slides, store.L(150, store.SLIDE)), "storyline": story, "notes": notes, "scope": summ, "ai": ai.status(p)}
    return 202, {"job": run_job(job)}


@route("GET", r"/api/jobs/(?P<jid>[0-9a-f]{16})")
def job_get(r):
    j = JOBS.get(r.m.group("jid"))
    if not j: raise store.NotFound("job not found")
    return 200, {k: v for k, v in j.items() if k != "t"}


@route("GET", r"/api/projects/(?P<pid>[0-9a-f]{16})/structures")
def structures(r): return 200, {"structures": deck.preview_structures(P(r.m))}


@route("POST", r"/api/projects/(?P<pid>[0-9a-f]{16})/slides/regenerate")
def regen(r):
    p = P(r.m); nid = str((r.body or {}).get("node_id", ""))
    node = next((n for n in p["map"]["nodes"] if n["id"] == nid), None)
    if not node: raise store.NotFound("map branch not found")
    chunks, notes, _ = _scope_chunks(p); _audit_kb(p, chunks)
    _, kids = deck.tree(p); ks = kids.get(nid, [])
    used = ai.retrieve_for(chunks, node["text"] + " " + " ".join(k["text"] for k in ks), 5)
    role = frameworks.classify_branch(node["text"], node["kind"]); layout = deck.choose_layout(node, ks, kids, role)
    try: c, used2 = ai.llm_slide(p, node, ks, kids, used, layout); used = used2 or used
    except (ai.AIBlocked, ai.AIError): c = ai.offline_slide(node, ks, kids, used, layout)
    s = dict(id=deck.sid(), kind="ask" if role == "ask" else "content", layout=layout, title=style.autofix(c["title"]), purpose="", bullets=c["bullets"], quote="", quote_by="", takeaway=c["takeaway"],
             notes=c["notes"], visual=deck.VISUAL[layout], transition="", facilitation="", node_id=nid, sources=ai.sources_of(used), gaps=c["gaps"], approved=False, locked=False, override_layout="")
    return 200, {"slide": store.clean(s, store.SLIDE), "notes": notes}


@route("POST", r"/api/projects/(?P<pid>[0-9a-f]{16})/refine")
def refine(r):
    p = P(r.m); b = r.body or {}
    slide = store.clean(b.get("slide"), store.SLIDE); mode = str(b.get("mode", ""))
    if mode not in ai.MODES: raise store.Invalid("unknown editing mode")
    try: chunks, _, _ = sources.resolve(p)
    except PermissionError: chunks = []
    out, changes, eng = ai.refine_slide(p, slide, mode, ai.retrieve_for(chunks, slide["title"] + " " + " ".join(x["text"] for x in slide["bullets"]), 4))
    return 200, {"before": slide, "after": store.clean(out, store.SLIDE), "changes": changes, "engine": eng}


@route("POST", r"/api/lint")
def lint(r):
    t = str((r.body or {}).get("text", ""))[:20000]
    return 200, {"hits": style.lint(t), "fixed": style.autofix(t)}


# ---------------------------------------------------------------- review & template & export
def _tpl_path(p): return store.pdir(p["id"]) / "template.pptx"
def _tpl_bytes(p):
    f = _tpl_path(p); return store.read_file(f) if p.get("template") and f.exists() else None


@route("GET", r"/api/projects/(?P<pid>[0-9a-f]{16})/review")
def review_get(r):
    p = P(r.m)
    try: fit = export.build_pptx(p, _tpl_bytes(p), False)[1] if p["slides"] else []
    except Exception: fit = []
    return 200, review.review(p, fit)


@route("POST", r"/api/projects/(?P<pid>[0-9a-f]{16})/review/resolve")
def review_resolve(r):
    p = P(r.m); b = r.body or {}
    state = b.get("state"); iid = str(b.get("id", ""))[:60]
    if state not in ("open", "resolved", "accepted", "override") or not iid: raise store.Invalid("bad resolution")
    if state == "override" and not str(b.get("reason", "")).strip(): raise store.Invalid("an override needs a reason")
    res = [x for x in p["qc"]["resolutions"] if x["id"] != iid]
    if state != "open": res.append({"id": iid, "state": state, "reason": str(b.get("reason", ""))[:300], "ts": int(time.time())})
    p["qc"]["resolutions"] = res[-300:]; save(p)
    store.audit("qc_" + state, p["id"], issue=iid, reason=str(b.get("reason", ""))[:100]); return 200, {"ok": True}


@route("POST", r"/api/projects/(?P<pid>[0-9a-f]{16})/template", raw=True)
def tpl_upload(r):
    p = P(r.m); name = ingest.safe_name(unquote(r.h.headers.get("X-Filename", "template.pptx")))
    if ingest.ext_of(name) not in (".pptx", ".potx"): raise ingest.IngestError("templates must be .pptx or .potx")
    safety.scan_upload(name, r.body); ingest._zip_guard(r.body)
    try: data = export.normalize_template(r.body); info = export.analyze_template(data)
    except Exception as e: raise ingest.IngestError("could not read this template") from e
    store.atomic_write(_tpl_path(p), data)
    p["template"] = {"name": name, "title_layout": info["defaults"]["title_layout"], "content_layout": info["defaults"]["content_layout"], "approved": [l["name"] for l in info["layouts"] if l["kind"] in ("content", "title", "section", "other")], "info": info}
    save(p); store.audit("template_upload", p["id"], name=name); return 201, {"template": p["template"]}


@route("PUT", r"/api/projects/(?P<pid>[0-9a-f]{16})/template")
def tpl_cfg(r):
    p = P(r.m); b = r.body or {}
    if not p["template"]: raise store.NotFound("no template")
    names = {l["name"] for l in p["template"]["info"]["layouts"]}
    for k in ("title_layout", "content_layout"):
        if b.get(k) in names: p["template"][k] = b[k]
    if isinstance(b.get("approved"), list): p["template"]["approved"] = [n for n in b["approved"] if n in names]
    save(p); return 200, {"template": p["template"]}


@route("DELETE", r"/api/projects/(?P<pid>[0-9a-f]{16})/template")
def tpl_del(r):
    p = P(r.m); p["template"] = None
    if _tpl_path(p).exists(): _tpl_path(p).unlink()
    save(p); return 200, {"ok": True}


@route("GET", r"/api/projects/(?P<pid>[0-9a-f]{16})/export-manifest")
def manifest(r):
    p = P(r.m); srcs = {}
    for s in p["slides"]:
        for x in s["sources"]: srcs.setdefault(x["name"], x["origin"])
    red = {}
    for s in p["slides"]:
        for k, v in safety.find_sensitive(" ".join([s["title"], s["takeaway"], s["notes"]] + [b["text"] for b in s["bullets"]])).items(): red[k] = red.get(k, 0) + v
    return 200, {"slides": len(p["slides"]), "notes_included": sum(1 for s in p["slides"] if s["notes"]), "classification": p["security"]["classification"], "marking": export.marking(p),
                 "watermark": p["security"]["watermark"], "redact_export": p["security"]["redact_export"], "sensitive_found": red, "sources": [{"name": k, "origin": v} for k, v in srcs.items()],
                 "ai_unsourced_bullets": sum(1 for s in p["slides"] for b in s["bullets"] if b["origin"] == "ai"), "template": (p["template"] or {}).get("name", "built-in theme")}


FORMATS = {"pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", "pptx"),
           "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
           "md": ("text/markdown; charset=utf-8", "md"), "html": ("text/html; charset=utf-8", "html"), "json": ("application/json", "json")}


@route("GET", r"/api/projects/(?P<pid>[0-9a-f]{16})/export/(?P<fmt>pptx|docx|md|html|json)")
def do_export(r):
    p = P(r.m); fmt = r.m.group("fmt")
    if fmt != "json":
        try: fit = export.build_pptx(p, _tpl_bytes(p), False)[1]
        except Exception: fit = []
        rv = review.review(p, fit)
        if not rv["can_export"]: raise HttpError(409, f"{rv['open_gating']} blocking quality issue(s) are still open. Resolve, accept, or override them first.", need="review")
    if fmt == "pptx": data = export.build_pptx(p, _tpl_bytes(p))[0]
    elif fmt == "docx": data = export.build_docx(p)
    elif fmt == "md": data = export.build_md(p).encode()
    elif fmt == "html": data = export.build_html(p).encode()
    else:
        q = json.loads(json.dumps(p)); q.pop("template", None); data = json.dumps(q, indent=1, ensure_ascii=False).encode()
    store.audit("export", p["id"], format=fmt, classification=p["security"]["classification"], redacted=p["security"]["redact_export"], slides=len(p["slides"]))
    base = re.sub(r"[^\w\- ]", "", p["name"]).strip().replace(" ", "-")[:60] or "presentation"
    return 200, Raw(data, FORMATS[fmt][0], f"{base}.{FORMATS[fmt][1]}")


# ---------------------------------------------------------------- versions
@route("GET", r"/api/projects/(?P<pid>[0-9a-f]{16})/versions")
def v_list(r): return 200, {"versions": store.list_snapshots(r.m.group("pid"))}


@route("GET", r"/api/projects/(?P<pid>[0-9a-f]{16})/versions/(?P<vid>[0-9a-z-]{10,24})")
def v_get(r):
    old = store.load_snapshot(r.m.group("pid"), r.m.group("vid")); return 200, {"map": old["map"], "slides": len(old["slides"]), "governing": old["governing"]}


@route("POST", r"/api/projects/(?P<pid>[0-9a-f]{16})/versions")
def v_make(r):
    p = P(r.m); vid = store.take_snapshot(p, str((r.body or {}).get("label", "manual"))); return 201, {"id": vid}


@route("POST", r"/api/projects/(?P<pid>[0-9a-f]{16})/versions/(?P<vid>[0-9a-z-]{10,24})/restore")
def v_restore(r):
    p = P(r.m); old = store.load_snapshot(p["id"], r.m.group("vid"))
    store.take_snapshot(p, "before restore")
    old["sources"], old["template"], old["scope_conf"] = p["sources"], p["template"], p.get("scope_conf", {})
    old["id"], old["updated"] = p["id"], int(time.time())
    save(old); store.audit("version_restore", p["id"], version=r.m.group("vid")); return 200, old


# ---------------------------------------------------------------- facilitation
@route("POST", r"/api/projects/(?P<pid>[0-9a-f]{16})/facilitation/to-map")
def fac_to_map(r):
    p = P(r.m); f = p["facilitation"]; groups = {g["id"]: g for g in f["groups"]}; by = {}
    for i in f["ideas"]: by.setdefault(i["group"], []).append(i)
    top = max([i["votes"] for i in f["ideas"]] + [1])
    wt = lambda v: 3 if v >= top * 0.67 and v else (2 if v >= top * 0.34 and v else (1 if v else 0))
    branches = []
    for gid, ideas in by.items():
        if gid in groups:
            branches.append(ai._node(groups[gid]["name"], "theme", wt(sum(i["votes"] for i in ideas)), ["Workshop"], [ai._node(i["text"], "", wt(i["votes"]), ["Workshop"], [], False) for i in ideas], False))
        else:
            for i in ideas: branches.append(ai._node(i["text"], "", wt(i["votes"]), ["Workshop"], [], False))
    return 200, {"branches": branches}


@route("POST", r"/api/projects/(?P<pid>[0-9a-f]{16})/facilitation/summary")
def fac_summary(r):
    p = P(r.m); f = p["facilitation"]; L = ["Session summary", ""]
    ideas = sorted(f["ideas"], key=lambda i: -i["votes"])[:5]
    if ideas: L += ["Top ideas by votes:"] + [f"- {i['text']} ({i['votes']})" for i in ideas] + [""]
    dec = [d for d in f["decisions"] if d["kind"] == "decision"]; act = [d for d in f["decisions"] if d["kind"] == "action"]
    if dec: L += ["Decisions:"] + [f"- {d['text']}" for d in dec] + [""]
    if act: L += ["Actions:"] + [f"- {d['text']}" + (f", owner {d['owner']}" if d["owner"] else ", owner needed") + (f", due {d['due']}" if d["due"] else ", date needed") + (" (done)" if d["done"] else "") for d in act] + [""]
    if f["parking"]: L += ["Parked for later:"] + [f"- {x['text']}" for x in f["parking"]] + [""]
    if f["questions"]: L += ["Open questions:"] + [f"- {x['q']}" for x in f["questions"] if not x["a"]] + [""]
    return 200, {"summary": "\n".join(L).strip()[:3000]}


# ---------------------------------------------------------------- knowledge base
def _docs():
    return [{k: v for k, v in d.items() if k != "_text"} for d in retrieval.list_docs()]


@route("GET", r"/api/kb")
def kb_get(r):
    cfg = retrieval.kb_cfg(); docs = _docs()
    return 200, {"folders": cfg["folders"], "docs": docs, "count": len(docs), "eligible": sum(d["eligible"] for d in docs)}


@route("POST", r"/api/kb/folders")
def kb_addf(r):
    f = retrieval.add_folder(str((r.body or {}).get("path", ""))[:500], str((r.body or {}).get("name", ""))[:80])
    store.audit("kb_folder_add", None, name=f["name"]); return 201, f


@route("PUT", r"/api/kb/folders/(?P<fid>[0-9a-f]{16})")
def kb_foldr(r):
    with retrieval.KBLOCK:
        cfg = retrieval.kb_cfg(); f = next((x for x in cfg["folders"] if x["id"] == r.m.group("fid")), None)
        if not f: raise store.NotFound("folder not found")
        f["enabled"] = bool((r.body or {}).get("enabled")); retrieval.kb_save(cfg)
    return 200, f


@route("DELETE", r"/api/kb/folders/(?P<fid>[0-9a-f]{16})")
def kb_delf(r):
    with retrieval.KBLOCK:
        cfg = retrieval.kb_cfg(); cfg["folders"] = [x for x in cfg["folders"] if x["id"] != r.m.group("fid")]; retrieval.kb_save(cfg)
    return 200, {"ok": True}


@route("POST", r"/api/kb/upload", raw=True)
def kb_up(r):
    name = ingest.safe_name(unquote(r.h.headers.get("X-Filename", "file"))); safety.scan_upload(name, r.body)
    did = retrieval.add_library_doc(name, r.body); store.audit("kb_upload", None, name=name); return 201, {"id": did}


@route("PUT", r"/api/kb/docs/(?P<did>[0-9a-f]{16})")
def kb_meta(r): retrieval.update_doc_meta(r.m.group("did"), r.body or {}); store.audit("kb_meta", None, doc=r.m.group("did")); return 200, {"ok": True}


@route("DELETE", r"/api/kb/docs/(?P<did>[0-9a-f]{16})")
def kb_deld(r): retrieval.remove_doc(r.m.group("did")); store.audit("kb_delete", None, doc=r.m.group("did")); return 200, {"ok": True}


@route("POST", r"/api/kb/search")
def kb_search(r):
    b = r.body or {}; q = str(b.get("q", ""))[:200]
    docs = retrieval.list_docs(include_text=True); chunks = []
    for d in docs:
        if not b.get("all") and not d["eligible"]: continue
        for c in retrieval.chunk_text(d.get("_text", ""))[:60]: chunks.append(retrieval.Chunk(d["id"], d["name"], "internal", c, d["id"]))
    info = {d["id"]: d for d in docs}
    hits = [{"doc": c.doc, "name": c.name, "snippet": analysis.trim(c.text.replace("\n", " "), 45), "status": info[c.doc]["status"], "flags": info[c.doc]["flags"], "owner": info[c.doc]["owner"]}
            for c in retrieval.BM25(chunks).search(q, 10)] if q else []
    store.audit("kb_search", None, q=q[:60], hits=len(hits))
    return 200, {"hits": hits, "duplicates": retrieval.duplicates(docs) if b.get("dups") else []}


# ---------------------------------------------------------------- HTTP plumbing
class H(BaseHTTPRequestHandler):
    server_version = "Clarity"; sys_version = ""; protocol_version = "HTTP/1.1"
    timeout = 60

    def log_message(self, fmt, *a): pass

    def _hdrs(self, ctype, length, extra=None):
        self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(length)); self.send_header("Connection", "close"); self.close_connection = True
        for k, v in {"Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
                     "Cross-Origin-Resource-Policy": "same-origin", "Cross-Origin-Opener-Policy": "same-origin", "Cache-Control": "no-store",
                     "Permissions-Policy": "camera=(), microphone=(), geolocation=()"}.items(): self.send_header(k, v)
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers()

    def _send(self, code, payload, extra=None):
        if isinstance(payload, Raw):
            self.send_response(code)
            ex = dict(extra or {})
            if payload.filename:
                ascii_name = re.sub(r"[^A-Za-z0-9._-]", "_", payload.filename)
                ex["Content-Disposition"] = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(payload.filename)}"
            self._hdrs(payload.ctype, len(payload.data), ex); self.wfile.write(payload.data); return
        b = json.dumps(payload, ensure_ascii=False).encode(); self.send_response(code); self._hdrs("application/json; charset=utf-8", len(b), extra); self.wfile.write(b)

    def _authed(self):
        c = self.headers.get("Cookie", "")
        m = re.search(COOKIE + r"=([^;]+)", c)
        return bool(m) and hmac.compare_digest(m.group(1), TOKEN)

    def _host_ok(self):
        h = (self.headers.get("Host") or "").lower()
        return h in (f"127.0.0.1:{PORT}", f"localhost:{PORT}", f"[::1]:{PORT}")

    def _handle(self, method):
        try:
            if not self._host_ok(): return self._send(403, {"error": "bad host"})
            u = urlsplit(self.path); path = u.path; q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if method == "GET" and path == "/" and q.get("t") and hmac.compare_digest(q["t"], TOKEN):
                self.send_response(302); self.send_header("Set-Cookie", f"{COOKIE}={TOKEN}; HttpOnly; SameSite=Strict; Path=/")
                self.send_header("Location", "/"); self.send_header("Content-Length", "0"); self.send_header("Cache-Control", "no-store"); self.send_header("Connection", "close"); self.close_connection = True; self.end_headers(); return
            if not self._authed():
                b = b"<!doctype html><meta charset=utf-8><title>Clarity</title><p>Open the full link printed in the terminal where Clarity is running."
                self.send_response(401); self._hdrs("text/html; charset=utf-8", len(b)); self.wfile.write(b); return
            if method in ("POST", "PUT", "DELETE"):
                o = self.headers.get("Origin")
                if o and o not in (f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"): return self._send(403, {"error": "cross-origin request blocked"})
                if not hmac.compare_digest(self.headers.get("X-CSRF", ""), CSRF): return self._send(403, {"error": "missing CSRF token"})
            if not path.startswith("/api/"):
                if method != "GET": return self._send(405, {"error": "method not allowed"})
                return self._static(path)
            for mth, rx, fn, raw in ROUTES:
                if mth != method: continue
                m = rx.match(path)
                if not m: continue
                body = None
                if method in ("POST", "PUT"):
                    n = int(self.headers.get("Content-Length") or 0)
                    if n > (MAX_RAW if raw else MAX_JSON): return self._send(413, {"error": "request too large"})
                    data = self.rfile.read(n) if n else b""
                    if raw: body = data
                    elif data:
                        try: body = json.loads(data)
                        except ValueError: return self._send(400, {"error": "invalid JSON"})
                req = type("Req", (), {"m": m, "body": body, "query": q, "h": self})()
                code, payload = fn(req); return self._send(code, payload)
            self._send(404, {"error": "not found"})
        except HttpError as e: self._send(e.code, {"error": e.msg, **e.extra})
        except store.NotFound as e: self._send(404, {"error": str(e)})
        except (store.Invalid, ingest.IngestError) as e: self._send(400, {"error": str(e)})
        except Exception as e:
            sys.stderr.write(f"error {method} {self.path.split('?')[0]}: {type(e).__name__}: {e}\n")
            try: self._send(500, {"error": "Something went wrong. Details are in the server log."})
            except Exception: pass

    def _static(self, path):
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        f = STATIC.get(rel)
        if not f: return self._send(404, {"error": "not found"})
        b = f.read_bytes(); self.send_response(200)
        self._hdrs(mimetypes.guess_type(rel)[0] or "application/octet-stream", len(b))
        self.wfile.write(b)

    do_GET = lambda s: s._handle("GET")
    do_POST = lambda s: s._handle("POST")
    do_PUT = lambda s: s._handle("PUT")
    do_DELETE = lambda s: s._handle("DELETE")


STATIC = {}


def main():
    global PORT, STATIC
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, default=8765); ap.add_argument("--open", action="store_true"); a = ap.parse_args()
    store.init_dirs()
    STATIC = {str(f.relative_to(APP)): f for f in APP.rglob("*") if f.is_file() and f.suffix in (".html", ".js", ".css", ".svg", ".png", ".ico")}
    srv = None
    for port in range(a.port, a.port + 20):
        try: srv = ThreadingHTTPServer(("127.0.0.1", port), H); PORT = port; break
        except OSError: continue
    if not srv: sys.exit("No free port found.")
    url = f"http://127.0.0.1:{PORT}/?t={TOKEN}"
    st = ai.status()
    print(f"\n  Clarity is running (local only).\n  Open: {url}\n  AI: {st['name']} ({st['model']}), {'local' if st['local'] else 'REMOTE: needs per-project consent'}\n"
          f"  Encryption at rest: {'on' if store.VAULT.enabled else 'off (set CLARITY_PASSPHRASE to enable)'}\n  Data: {store.DATA}\n")
    if a.open: threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try: srv.serve_forever()
    except KeyboardInterrupt: print("\nStopped.")


if __name__ == "__main__": main()
