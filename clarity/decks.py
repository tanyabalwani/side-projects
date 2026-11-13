"""Existing decks as raw material: import slides, organise them (theme, role, duplicates, currency),
and suggest a flow and edits against the author's intention or a reference flow.
Everything here is rule-based and local; suggestions only, nothing is applied for the user."""
import datetime, io, json, math, re, secrets
from collections import Counter
import store, ingest, safety, analysis, frameworks, style
from analysis import tokens, shingles, jaccard, trim

MAX_SLIDES, MAX_DECKS = 400, 12
ROLES = ["title", "agenda", "context", "problem", "answer", "evidence", "case", "options", "plan", "risks", "ask", "closing", "appendix", "content"]
ROLE_LABEL = {"title": "Title", "agenda": "Agenda", "context": "Context", "problem": "Problem", "answer": "Answer", "evidence": "Evidence", "case": "Case study", "options": "Options", "plan": "Plan", "risks": "Risks", "ask": "Ask", "closing": "Closing", "appendix": "Appendix", "content": "Content"}
KEY = [
    ("closing", r"\b(thank you|thanks|questions\??|q ?& ?a|contact us)\b"),
    ("appendix", r"\b(appendix|backup|reference|glossary|supplement|methodology|definitions?)\b"),
    ("agenda", r"\b(agenda|contents|outline|today'?s (?:session|discussion)|what we'?ll cover)\b"),
    ("ask", r"\b(next steps?|the ask|our ask|decision (?:needed|required)|approval|call to action|requested|what we need|asks?)\b"),
    ("answer", r"\b(recommend\w*|proposal|we propose|executive summary|key takeaways?|summary|our approach|the answer|bottom line|decision)\b"),
    ("risks", r"\b(risks?|mitigations?|dependenc\w+|assumptions?|concerns?|constraints?)\b"),
    ("options", r"\b(options?|alternatives?|trade-?offs?|comparison|versus|vs\.?)\b"),
    ("plan", r"\b(roadmap|timeline|plan|phases?|milestones?|rollout|schedule|workplan)\b"),
    ("case", r"\b(case stud(?:y|ies)|customer stor(?:y|ies)|testimonial|success stor(?:y|ies)|example)\b"),
    ("problem", r"\b(problems?|challenges?|pain points?|gaps?|issues?|why now|opportunity|burning platform)\b"),
    ("context", r"\b(background|context|situation|overview|about us|history|where we are|current state|introduction)\b"),
    ("evidence", r"\b(results?|data|metrics?|findings?|performance|analysis|market|insights?|research|survey|benchmarks?|kpis?|numbers)\b"),
]
FLOWS = {  # role order per structure; answer-first structures put the answer straight after the title
    "answer_first": ["title", "answer", "context", "problem", "evidence", "case", "options", "plan", "risks", "ask", "closing", "agenda", "content", "appendix"],
    "scqa": ["title", "agenda", "context", "problem", "answer", "evidence", "case", "options", "plan", "risks", "ask", "closing", "content", "appendix"],
    "psi": ["title", "agenda", "problem", "context", "answer", "evidence", "case", "plan", "risks", "ask", "closing", "content", "appendix"],
    "story": ["title", "agenda", "context", "problem", "case", "evidence", "answer", "plan", "ask", "closing", "content", "risks", "appendix"],
}
GENERIC = set("across team teams plan plans overview new year years month months quarter key based show shows using use used make makes group general slide slides deck item items list part parts summary introduction about more less each every per via within between including include includes also next first second third one two three four five".split())
CONFIDENTIAL = re.compile(r"(?i)\b(confidential|internal use only|do not distribute|proprietary|not for external)\b")


def flow_for(framework_id):
    fw = frameworks.FW.get(framework_id, frameworks.FW["reverse_pyramid"])
    if fw["answer_first"]: return FLOWS["answer_first"]
    return FLOWS["psi"] if framework_id == "psi" else FLOWS["story"] if framework_id in ("three_act", "bab", "wswnw") else FLOWS["scqa"]


# ------------------------------------------------------------------ import
def _clean(t): return re.sub(r"\s+", " ", (t or "").replace("\x0b", " ")).strip()[:300]


def _shapes(shapes):
    for sh in sorted(shapes, key=lambda s: ((s.top or 0) // 300000, s.left or 0)):
        if sh.shape_type == 6:
            try: yield from _shapes(sh.shapes)
            except Exception: pass
        else: yield sh


def _num(v):
    try: return str(int(v)) if float(v).is_integer() else str(round(float(v), 2))
    except (TypeError, ValueError): return str(v)


def extract_pptx(data):
    ingest._zip_guard(data)
    from pptx import Presentation
    try: prs = Presentation(io.BytesIO(data))
    except Exception as e: raise ingest.IngestError("could not read this PowerPoint file") from e
    out = []
    for i, sl in enumerate(prs.slides, 1):
        if i > MAX_SLIDES: break
        title, bullets, flags = "", [], set()
        ts = sl.shapes.title
        if ts is not None and ts.has_text_frame: title = _clean(ts.text_frame.text)
        for sh in _shapes(sl.shapes):
            if ts is not None and sh.shape_id == ts.shape_id: continue
            try:
                if sh.shape_type == 13: flags.add("image")
                if getattr(sh, "has_chart", False) and sh.has_chart:
                    flags.add("chart"); ch = sh.chart
                    try:
                        cats = [str(c) for c in ch.plots[0].categories]; ser = list(ch.plots[0].series)
                        for s_ in ser[:3]:
                            for c, v in list(zip(cats, s_.values))[:12]:
                                if v is not None: bullets.append({"text": f"{c}{' (' + s_.name + ')' if len(ser) > 1 else ''}: {_num(v)}", "level": 0})
                    except Exception: pass
                if getattr(sh, "has_table", False) and sh.has_table:
                    flags.add("table")
                    for r in list(sh.table.rows)[:12]:
                        cells = [_clean(c.text) for c in r.cells]
                        if any(cells): bullets.append({"text": " | ".join(cells)[:300], "level": 0})
                if sh.has_text_frame:
                    for p in sh.text_frame.paragraphs:
                        t = _clean("".join(r.text for r in p.runs))
                        if t: bullets.append({"text": t, "level": 1 if p.level else 0})
            except Exception: continue
        if not title and bullets and len(bullets[0]["text"].split()) <= 16: title = bullets.pop(0)["text"]
        notes = ""
        try:
            if sl.has_notes_slide: notes = _clean(sl.notes_slide.notes_text_frame.text)[:1500]
        except Exception: pass
        out.append({"n": i, "title": title, "bullets": bullets[:40], "notes": notes, "layout_name": (sl.slide_layout.name or "")[:60], "flags": sorted(flags)})
    if not out: raise ingest.IngestError("no slides found")
    return out


def extract_pdf(data):
    if not data.startswith(b"%PDF"): raise ingest.IngestError("not a PDF")
    from pypdf import PdfReader
    try: r = PdfReader(io.BytesIO(data))
    except Exception as e: raise ingest.IngestError("could not read PDF") from e
    if r.is_encrypted: raise ingest.IngestError("encrypted PDFs are not supported")
    out = []
    for i, pg in enumerate(r.pages[:MAX_SLIDES], 1):
        lines = [_clean(l) for l in (pg.extract_text() or "").splitlines() if _clean(l)]
        if not lines: out.append({"n": i, "title": f"Page {i}", "bullets": [], "notes": "", "layout_name": "", "flags": ["image"]}); continue
        out.append({"n": i, "title": lines[0], "bullets": [{"text": l, "level": 0} for l in lines[1:30]], "notes": "", "layout_name": "", "flags": []})
    return out


def role_of(s, total):
    title = (s["title"] or "").lower(); body = " ".join(b["text"] for b in s["bullets"]).lower(); n = s["n"]
    words = len(title.split()) + sum(len(b["text"].split()) for b in s["bullets"])
    if re.search(r"title slide|^cover", s["layout_name"].lower()) or (n == 1 and words <= 25): return "title"
    for role, rx in KEY:
        if re.search(rx, title): return role
    if "chart" in s["flags"] or len(re.findall(r"\d", body)) >= 6: return "evidence"
    if n == total and words <= 20: return "closing"
    for role, rx in KEY:
        if role in ("appendix", "closing", "agenda"): continue
        if len(re.findall(rx, body)) >= 2: return role
    return "content"


def layout_guess(s):
    pairs = [b for b in s["bullets"] if re.search(r"^.{2,40}?\s*[:=]\s*[$€£]?-?\d[\d,.]*\s*%?\s*$", b["text"])]
    if "chart" in s["flags"] and len(pairs) >= 2: return "data"
    top = [b for b in s["bullets"] if b["level"] == 0]
    if 3 <= len(top) <= 5 and sum(": " in b["text"] for b in top) >= 3: return "framework"
    return "bullets"


def prepare(raw):
    total = len(raw); out = []
    for s in raw:
        s["role"] = role_of(s, total); s["layout"] = layout_guess(s)
        body = " ".join([s["title"]] + [b["text"] for b in s["bullets"]])
        s["words"] = len(body.split()); s["years"] = sorted({int(y) for y in re.findall(r"\b(20[0-3]\d)\b", body)})
        s["confidential"] = bool(CONFIDENTIAL.search(body))
        out.append(s)
    return out


def deck_text(name, slides):
    parts = [f"# {name}"]
    for s in slides:
        parts.append(f"## Slide {s['n']}: {s['title']}")
        parts += [("  " if b["level"] else "") + b["text"] for b in s["bullets"]]
        if s["notes"]: parts.append("Notes: " + s["notes"])
    return "\n".join(parts)


def _ddir(pid):
    d = store.pdir(pid) / "decks"; d.mkdir(exist_ok=True); return d


def save_deck(pid, did, name, slides):
    store.atomic_write(_ddir(pid) / f"{did}.json", json.dumps({"id": did, "name": name, "slides": slides}, ensure_ascii=False).encode())


def load_deck(pid, did):
    if not store.ID_RE.match(did or ""): raise store.NotFound("bad deck")
    f = _ddir(pid) / f"{did}.json"
    if not f.exists(): raise store.NotFound("deck not found")
    return json.loads(store.read_file(f))


def delete_deck_files(pid, did):
    f = _ddir(pid) / f"{did}.json"
    if store.ID_RE.match(did or "") and f.exists(): f.unlink()


# ------------------------------------------------------------------ organise
def themes(decks, k=7):
    items = [(d["id"], s) for d in decks for s in d["slides"] if s["role"] not in ("title", "closing", "agenda")]
    if len(items) < 4: return [{"name": "All content", "keys": [f"{d}:{s['n']}" for d, s in items]}]
    docs = {f"{d}:{s['n']}": Counter(tokens(s["title"]) * 3 + tokens(" ".join(b["text"] for b in s["bullets"]))) for d, s in items}
    df = Counter(t for c in docs.values() for t in c); N = len(docs)
    cand = [t for t, c in df.items() if 2 <= c <= max(3, int(0.5 * N)) and t not in GENERIC]
    where = {t: {key for key, c in docs.items() if t in c} for t in cand}
    score = {t: df[t] * math.log(N / df[t] + 1) for t in cand}
    chosen = []
    for t in sorted(cand, key=lambda t: -score[t]):
        if len(chosen) >= k: break
        if all(jaccard(where[t], where[c]) < 0.5 for c in chosen): chosen.append(t)
    groups = {t: [] for t in chosen}; other = []
    for key, c in docs.items():
        best = max(chosen, key=lambda t: c.get(t, 0) * math.log(N / df[t] + 1), default=None)
        (groups[best] if best and c.get(best, 0) else other).append(key)
    res = []
    for t, v in groups.items():
        if len(v) < 2: other += v; continue
        # name the theme by its two most characteristic words, not only the seed word
        cnt = Counter(w for key in v for w in docs[key] if w not in GENERIC and df[w] <= 0.6 * N)
        words = [t] + [w for w, _ in cnt.most_common(6) if w != t][:1]
        res.append({"name": " & ".join(w.capitalize() for w in words), "keys": v})
    if other: res.append({"name": "Other", "keys": other})
    return res


def _tn(title): return {re.sub(r"[,\s]", "", x) for x in analysis.NUM.findall(title)}


def cross(decks):
    """Near-duplicates and conflicting figures between slides of different decks."""
    flat = [(d["id"], d["name"], s) for d in decks for s in d["slides"] if s["role"] not in ("title", "closing", "agenda")]
    sh = [shingles(s["title"] + " " + " ".join(b["text"] for b in s["bullets"]), 2) for _, _, s in flat]
    dups, conflicts = [], []
    for i in range(len(flat)):
        for j in range(i + 1, len(flat)):
            if flat[i][0] == flat[j][0]: continue
            jac = jaccard(sh[i], sh[j])
            if jac < 0.3: continue
            na = {re.sub(r"[,\s]", "", x) for x in analysis.NUM.findall(" ".join(b["text"] for b in flat[i][2]["bullets"] + [{"text": flat[i][2]["title"]}]))}
            nb = {re.sub(r"[,\s]", "", x) for x in analysis.NUM.findall(" ".join(b["text"] for b in flat[j][2]["bullets"] + [{"text": flat[j][2]["title"]}]))}
            ka, kb = f"{flat[i][0]}:{flat[i][2]['n']}", f"{flat[j][0]}:{flat[j][2]['n']}"
            if jac >= 0.6 and na == nb: dups.append({"a": ka, "b": kb, "score": round(jac, 2)})
            elif ((na and nb and not (na & nb)) or (_tn(flat[i][2]["title"]) and _tn(flat[j][2]["title"]) and not (_tn(flat[i][2]["title"]) & _tn(flat[j][2]["title"])))) \
                    and set(tokens(flat[i][2]["title"])) & set(tokens(flat[j][2]["title"])) and len(conflicts) < 15:
                conflicts.append({"a": ka, "b": kb, "text": f"'{trim(flat[i][2]['title'], 8)}' and '{trim(flat[j][2]['title'], 8)}' give different figures"})
        if len(dups) > 60: break
    return dups[:60], conflicts


def library(p):
    decks = []
    for src in p["sources"]:
        if src.get("kind") != "deck": continue
        try: d = load_deck(p["id"], src["id"])
        except store.NotFound: continue
        d["include"] = src.get("include", True); decks.append(d)
    inc = [d for d in decks if d["include"]]
    th = themes(inc); dups, conflicts = cross(inc)
    year = datetime.date.today().year
    theme_of = {k: t["name"] for t in th for k in t["keys"]}
    dup_keys = {}
    for x in dups: dup_keys.setdefault(x["a"], []).append(x["b"]); dup_keys.setdefault(x["b"], []).append(x["a"])
    out = []
    for d in decks:
        slides = []
        for s in d["slides"]:
            key = f"{d['id']}:{s['n']}"
            slides.append({**s, "key": key, "theme": theme_of.get(key, "Framing" if s["role"] in ("title", "closing", "agenda") else "Other"), "dups": dup_keys.get(key, []),
                           "stale": bool(s["years"]) and max(s["years"]) <= year - 2, "slide": to_slide(d, s)})
        out.append({"id": d["id"], "name": d["name"], "include": d["include"], "count": len(slides), "slides": slides,
                    "roles": list(dict.fromkeys(s["role"] for s in d["slides"]))})
    return {"decks": out, "themes": [t["name"] for t in th], "duplicates": dups, "conflicts": conflicts}


def to_slide(deck, s):
    """A Clarity slide made from an imported one. Content is marked sourced and cites the deck."""
    snippet = trim(f"Slide {s['n']}: {s['title']}", 14)
    kind = "title" if s["role"] == "title" else "ask" if s["role"] == "ask" else "appendix" if s["role"] in ("appendix",) else "content"
    return {"id": "x" + secrets.token_hex(4), "kind": kind, "layout": s["layout"], "title": s["title"][:200], "purpose": f"From {deck['name']}, slide {s['n']}", "bullets": [{"text": b["text"], "level": b["level"], "origin": "sourced", "cite": [deck["name"]]} for b in s["bullets"][:14]],
            "quote": "", "quote_by": "", "takeaway": "", "notes": s["notes"], "visual": "", "transition": "", "facilitation": "", "node_id": "", "role": s["role"], "ref": f"{deck['name']} · slide {s['n']}"[:200],
            "sources": [{"name": deck["name"], "origin": "provided", "snippet": snippet, "doc": ""}], "gaps": [], "approved": False, "locked": False, "override_layout": ""}


# ------------------------------------------------------------------ flow suggestions
def _role(s): return s.get("role") or "content"


def target_order(p, flow):
    mode = flow.get("mode")
    if mode == "reference" and flow.get("ref_deck"):
        try:
            d = load_deck(p["id"], flow["ref_deck"]); seq = list(dict.fromkeys(s["role"] for s in d["slides"]))
            base = flow_for(p["framework"])
            rest = [r for r in base if r not in seq]
            # roles the reference lacks slot in beside their nearest default neighbour
            order = list(seq)
            for r in rest:
                prev = next((x for x in reversed(base[:base.index(r)]) if x in order), None)
                order.insert(order.index(prev) + 1 if prev else 0, r)
            return order, f"the flow of '{d['name']}'"
        except store.NotFound: pass
    fid = flow.get("framework") or p["framework"]
    return flow_for(fid), frameworks.FW.get(fid, frameworks.FW["reverse_pyramid"])["name"]


def suggest(p, items, flow):
    """items: list of slide dicts (with role/ref). Returns order, moves, gaps, mods, shape."""
    order, label = target_order(p, flow)
    rank = {r: i for i, r in enumerate(order)}
    pos = {s["id"]: i for i, s in enumerate(items)}
    def key(s):
        r = _role(s)
        return (rank.get(r, rank.get("content", 99)), pos[s["id"]])
    new = sorted(items, key=key)
    moves = []
    for i, s in enumerate(new):
        j = pos[s["id"]]
        if abs(i - j) >= 2 and len(moves) < 10:
            r = _role(s)
            why = {"answer": "lead with the answer", "evidence": "evidence follows the claim it supports", "ask": "end on the decision", "appendix": "background belongs at the end", "context": "set context before the argument", "problem": "name the problem before the fix", "plan": "the plan follows the case for it", "risks": "address objections after the case", "closing": "close last", "title": "open with the title"}.get(r, "matches the target flow")
            moves.append({"id": s["id"], "title": s["title"], "from": j + 1, "to": i + 1, "reason": f"Move from {j + 1} to {i + 1}: {why} ({ROLE_LABEL.get(r, r)}, per {label})."})
    roles = [_role(s) for s in items]; have = set(roles)
    af = frameworks.FW.get(flow.get("framework") or p["framework"], {}).get("answer_first", True) if flow.get("mode") != "reference" else ("answer" in order[:3])
    gaps = []
    b = p["brief"]
    if "answer" not in have: gaps.append({"role": "answer", "text": "No slide gives the answer. " + ("Your flow leads with it." if af else "Your flow needs it after the problem."), "action": "draft_answer"})
    if "evidence" not in have and "case" not in have: gaps.append({"role": "evidence", "text": "No slide gives evidence (data, a case, or a finding). The argument will read as assertion.", "action": None})
    if "ask" not in have and (b["decides"] or b["does"] or True): gaps.append({"role": "ask", "text": "No slide states the decision or next step" + (f" ({trim(b['decides'] or b['does'], 8)})." if (b["decides"] or b["does"]) else "."), "action": "draft_ask"})
    if not af and "problem" not in have and "context" not in have: gaps.append({"role": "problem", "text": "This flow builds to the answer but no slide sets up the problem or context.", "action": None})
    # per-slide modifications
    mods = []
    def mod(s, kind, text, **extra): mods.append({"id": s["id"], "title": s["title"], "type": kind, "text": text, **extra})
    year = datetime.date.today().year
    intent = " ".join([flow.get("intent", ""), b["message"], b["purpose"], p["governing"]]); itok = set(tokens(intent))
    for s in items:
        r = _role(s); tl = s["title"].strip()
        strong = next((x["text"] for x in s["bullets"] if x["level"] == 0 and len(x["text"].split()) >= 6), None)
        if r in ("content", "evidence", "context", "problem", "options", "plan", "risks", "case", "answer") and (len(tl.split()) <= 3 or (len(tl.split()) <= 5 and not _has_verb(tl))) and strong:
            mod(s, "headline", f"The headline '{trim(tl, 6)}' is a label. Lead with the conclusion.", apply={"title": trim(strong, 16).rstrip("…. "), "bullets_drop_first": True})
        words = len(" ".join([tl] + [x["text"] for x in s["bullets"]]).split())
        if words > 95 and r not in ("appendix",): mod(s, "dense", f"{words} words. Split it or move detail to the appendix.")
        yrs = re.findall(r"\b(20[0-3]\d)\b", " ".join([tl] + [x["text"] for x in s["bullets"]]))
        if yrs and max(int(y) for y in yrs) <= year - 2: mod(s, "stale", f"Latest year mentioned is {max(yrs)}. Check the figures are current.")
        if CONFIDENTIAL.search(" ".join([tl] + [x["text"] for x in s["bullets"]])): mod(s, "confidential", "Text in this slide is marked confidential in its source. Check the audience may see it.")
        if "image" in (s.get("flags") or []): mod(s, "visual", "The source slide had an image or diagram. Pictures are not carried over; re-add the visual.")
        if itok and r not in ("title", "closing", "appendix", "agenda") and not (set(tokens(tl + " " + " ".join(x["text"] for x in s["bullets"]))) & itok):
            mod(s, "weak_fit", "Shares no words with your intention. Cut it unless it supports a point you have not stated.", apply={"remove": True})
    # duplicates inside the story
    sh = {s["id"]: shingles(s["title"] + " " + " ".join(x["text"] for x in s["bullets"]), 2) for s in items}
    for i, a in enumerate(items):
        for c in items[i + 1:]:
            if jaccard(sh[a["id"]], sh[c["id"]]) >= 0.6: mod(c, "duplicate", f"Nearly the same as '{trim(a['title'], 8)}'. Keep one.", apply={"remove": True})
    mains = [s for s in items if _role(s) not in ("title", "closing", "appendix", "agenda")]
    if len(mains) > max(3, p["brief"]["minutes"]):
        n = len(mains) - p["brief"]["minutes"]; mods.append({"id": "", "title": "", "type": "length", "text": f"{len(mains)} main slides for {p['brief']['minutes']} minutes. Cut about {n} or raise the time."})
    for ct in analysis.cross_checks([{"id": s["id"], "name": s["ref"] or s["title"], "text": " ".join(x["text"] for x in s["bullets"])} for s in items])["contradictions"][:5]:
        mods.append({"id": "", "title": "", "type": "conflict", "text": f"Different figures: {ct['a']} says '{ct['a_text']}' while {ct['b']} says '{ct['b_text']}'."})
    return {"order": [s["id"] for s in new], "moves": moves, "gaps": gaps, "mods": mods, "target": label, "target_roles": [r for r in order if r in set(roles) | {"answer", "ask"}],
            "shape": {"current": roles, "suggested": [_role(s) for s in new]}}


VERBS = re.compile(r"\b(is|are|was|were|will|can|grew|grow|fell|rose|cuts?|reduces?|increases?|saves?|needs?|must|should|drives?|enables?|delivers?|shows?|means?|has|have|costs?|brings?|improves?|protects?|speeds?|keeps?|gives?|takes?|runs?|builds?|wins?|loses?|fails?|stops?|starts?|helps?|allows?|prevents?|ends?|doubled?|halved?|approve|decide|launch|migrate|hire|reach\w*|exceed\w*|move|moves|switch|adopt|choose|replace|invest|fund|cut|stop)\b", re.I)
def _has_verb(t): return bool(VERBS.search(t))


def draft(p, kind, items):
    """A starter slide for a missing answer or ask, written from the user's own brief and picks."""
    b = p["brief"]
    from deck import sid
    base = {"id": sid(), "layout": "key_message", "quote": "", "quote_by": "", "notes": "", "visual": "", "transition": "", "facilitation": "", "node_id": "", "sources": [], "gaps": [], "approved": False, "locked": False, "override_layout": "", "ref": "", "purpose": "Drafted from your brief"}
    if kind == "answer":
        msg = p["governing"] or b["message"] or ""
        heads = [s["title"] for s in items if _role(s) in ("evidence", "case", "problem", "plan", "options", "content")][:4]
        gaps = [] if msg else ["[needs data: the one-sentence answer. Write it in the Brief.]"]
        return {**base, "kind": "summary", "layout": "summary", "role": "answer", "title": msg or "State the answer here", "bullets": [{"text": trim(h, 16), "level": 0, "origin": "user", "cite": []} for h in heads], "takeaway": (b["decides"] or b["does"])[:300], "gaps": gaps}
    ask = b["decides"] or b["does"]
    acts = [d for d in p["facilitation"]["decisions"] if d["kind"] == "action"]
    return {**base, "kind": "ask", "layout": "action_plan" if acts else "key_message", "role": "ask", "title": f"Decision needed: {trim(ask[:1].lower() + ask[1:], 14)}" if ask else "State the decision or next step",
            "bullets": [{"text": a["text"] + (f" ({a['owner']})" if a["owner"] else "") + (f", by {a['due']}" if a["due"] else ""), "level": 0, "origin": "user", "cite": []} for a in acts[:6]], "takeaway": ask[:300],
            "gaps": [] if ask else ["[needs data: what you need from the audience. Write it in the Brief.]"]}
