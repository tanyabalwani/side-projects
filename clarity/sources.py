"""Project sources: ingest, scan, analyse, and keep provenance."""
import hashlib, json, re, time
import store, ingest, safety, analysis, decks
from retrieval import Chunk, chunk_text, kb_chunks


def _dir(pid):
    d = store.pdir(pid) / "sources"; d.mkdir(exist_ok=True); return d


def get_text(pid, sid):
    if not store.ID_RE.match(sid or ""): raise store.NotFound("bad source")
    f = _dir(pid) / f"{sid}.txt"
    if not f.exists(): raise store.NotFound("source not found")
    return store.read_file(f).decode("utf-8", "replace")


def _register(p, name, kind, origin, text, warns, extra=None):
    sid = store.new_id()
    inj = safety.injection_flags(text)
    rec = {"id": sid, "name": name[:120], "kind": kind, "origin": origin, "chars": len(text), "added": int(time.time()), "include": True,
           "sha": hashlib.sha256(text.encode()).hexdigest()[:16], "warnings": warns + ([f"{len(inj)} instruction-like phrase(s) found; they are removed before any model sees this source"] if inj else []),
           "injection": [i["snippet"] for i in inj][:5], "insights": analysis.analyze(text), "sensitive": safety.find_sensitive(text), **(extra or {})}
    for o in p["sources"]:
        if o["sha"] == rec["sha"]: rec["warnings"].append(f"identical content to '{o['name']}'")
    store.atomic_write(_dir(p["id"]) / f"{sid}.txt", text.encode("utf-8"))
    p["sources"].append(rec)
    return rec


def add_text(p, name, text):
    text = (text or "").strip()
    if not text: raise ingest.IngestError("text is empty")
    return _register(p, name or "Pasted notes", "text", "provided", text[:ingest.MAX_TEXT], [])


def add_file(p, filename, data):
    name = ingest.safe_name(filename)
    warns = safety.scan_upload(name, data)
    ext = ingest.ext_of(name)
    if ext in safety.IMAGE_EXT:
        rec = _register(p, name, "image", "provided", f"[Image: {name}] Add a description in the source preview so it can be used as evidence.", warns + ["Images are stored but not read automatically. Add a description."])
        store.atomic_write(_dir(p["id"]) / f"{rec['id']}.img", data)
        return rec
    return _register(p, name, "file", "provided", ingest.extract_text(name, data), warns)


def add_deck(p, filename, data):
    """An existing deck (.pptx or .pdf): kept per slide for the story board, and registered as a source so scope and citations apply."""
    name = ingest.safe_name(filename); ext = ingest.ext_of(name)
    if ext not in (".pptx", ".pdf"): raise ingest.IngestError("decks must be .pptx or .pdf")
    if sum(1 for s in p["sources"] if s.get("kind") == "deck") >= decks.MAX_DECKS: raise ingest.IngestError(f"at most {decks.MAX_DECKS} decks per project")
    warns = safety.scan_upload(name, data)
    slides = decks.prepare(decks.extract_pptx(data) if ext == ".pptx" else decks.extract_pdf(data))
    title = name.rsplit(".", 1)[0]
    rec = _register(p, title, "deck", "provided", decks.deck_text(title, slides)[:ingest.MAX_TEXT], warns, {"slides": len(slides)})
    decks.save_deck(p["id"], rec["id"], title, slides)
    if any(s["confidential"] for s in slides): rec["warnings"].append("some slides are marked confidential in the original")
    if any("image" in s["flags"] for s in slides): rec["warnings"].append("pictures and diagrams are not carried over; text, tables and chart data are")
    return rec


def add_link(p, url):
    name, text = ingest.fetch_url(url)
    return _register(p, name, "link", "external", text, ["External web content. Verify before treating as fact."], {"url": url[:500]})


def remove(p, sid):
    p["sources"] = [s for s in p["sources"] if s["id"] != sid]
    decks.delete_deck_files(p["id"], sid)
    for ext in (".txt", ".img"):
        f = _dir(p["id"]) / f"{sid}{ext}"
        if store.ID_RE.match(sid) and f.exists(): f.unlink()


def set_text(p, sid, text):
    rec = next((s for s in p["sources"] if s["id"] == sid), None)
    if not rec: raise store.NotFound("source not found")
    text = text.strip()[:ingest.MAX_TEXT]
    store.atomic_write(_dir(p["id"]) / f"{sid}.txt", text.encode("utf-8"))
    rec.update(chars=len(text), insights=analysis.analyze(text), injection=[i["snippet"] for i in safety.injection_flags(text)][:5], sensitive=safety.find_sensitive(text))


def project_chunks(p):
    out = []
    for s in p["sources"]:
        if not s.get("include", True): continue
        try: t = get_text(p["id"], s["id"])
        except store.NotFound: continue
        origin = "external" if s["origin"] == "external" else "provided"
        for c in chunk_text(safety.neutralise(t))[:120]: out.append(Chunk(s["id"], s["name"], origin, c))
    return out


def scope_hash(sc): return hashlib.sha256(json.dumps([sc.get("mode"), sorted(sc.get("kb_docs", []))]).encode()).hexdigest()[:16]


def resolve(p):
    """Chunks the model may use for this project, per the user's confirmed scope. Returns (chunks, notes, summary)."""
    sc, mode = p["scope"], p["scope"].get("mode")
    if not mode: raise PermissionError("Choose which sources the AI may use before generating.")
    if mode == "none": return [], ["No retrieval: only your instructions and map are used."], {"mode": mode, "provided": 0, "internal": 0}
    chunks, notes = project_chunks(p), []
    internal = 0
    if mode in ("selected", "all"):
        if p.get("scope_conf", {}).get("hash") != scope_hash(sc): raise PermissionError("Confirm the expanded knowledge scope before generating.")
        ids = None if mode == "all" else {d for d in sc["kb_docs"] if d not in sc["excluded"]}
        kc, kn = kb_chunks(ids, p["security"]["classification"])
        if mode == "all": kc = [c for c in kc if c.doc not in sc["excluded"]]
        chunks += kc; notes += kn; internal = len({c.doc for c in kc})
    return chunks, notes, {"mode": mode, "provided": len({c.sid for c in chunks if c.origin != "internal"}), "internal": internal}
