"""Storyline + slide generation from the approved map, honouring scope and structure."""
import re, secrets
import ai, frameworks, store, style
from analysis import trim, jaccard, shingles

VISUAL = {
    "key_message": "One large statement with two or three supporting facts beside it.",
    "comparison": "Two columns side by side with a shared set of criteria.",
    "before_after": "Left column for today, right column for the future state.",
    "process": "Numbered chevrons left to right, one short phrase each.",
    "timeline": "Horizontal timeline with dated milestones.",
    "roadmap": "Phased roadmap, one column per phase.",
    "framework": "Cards in a grid, one idea per card with a bold lead word.",
    "data": "Bar chart with labelled values and a source line.",
    "decision": "Recommendation box on the left, rationale on the right.",
    "recommendation": "Recommendation in a highlighted box, three reasons below.",
    "case": "Three panels: situation, action, result.",
    "quote": "Large quotation with attribution.",
    "action_plan": "Table with action, owner, and due date.",
    "summary": "Cards, one per key argument, ordered by importance.",
    "appendix": "Compact text, small type is acceptable here.",
    "bullets": "Short text list. Use only when no visual form fits.",
}
STEP = re.compile(r"\b(step|phase|stage|first|second|third|then|next|finally|milestone)\b", re.I)
DATE = re.compile(r"\b(q[1-4]|20\d\d|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|week \d+|month \d+)\b", re.I)
NUMV = re.compile(r"\d")


def sid(): return "s" + secrets.token_hex(4)


def tree(p):
    nodes = p["map"]["nodes"]; kids = {}
    for n in nodes: kids.setdefault(n["parent"], []).append(n)
    root = next((n for n in nodes if not n["parent"]), None)
    return root, kids


def choose_layout(node, kids, grand, role):
    texts = " ".join([node["text"]] + [k["text"] for k in kids]).lower()
    if role == "ask" or node["kind"] == "action" or (len(kids) >= 2 and sum(k["kind"] == "action" for k in kids) >= 2): return "action_plan"
    if re.search(r"\b(before|today)\b", texts) and re.search(r"\b(after|future|tomorrow)\b", texts): return "before_after"
    if re.search(r"\b(vs\.?|versus|compared (?:to|with)|trade-?off)\b", texts): return "comparison"
    if len(kids) >= 3 and len({m.group(0).lower() for k in kids for m in [DATE.search(k["text"])] if m}) >= 2: return "timeline"
    if len(kids) >= 3 and sum(bool(STEP.search(k["text"])) for k in kids) >= 2: return "process"
    if sum(bool(NUMV.search(k["text"])) for k in kids) >= 2 and sum(k["kind"] == "evidence" or "%" in k["text"] for k in kids) >= 2: return "data"
    if re.search(r"\b(recommend|decision|should)\b", node["text"].lower()): return "recommendation"
    if role in ("options", "risks") or 3 <= len(kids) <= 5: return "framework"
    if len(kids) <= 2: return "key_message"
    return "bullets"


def branch_info(p):
    root, kids = tree(p)
    out = []
    for b in kids.get(root["id"], []) if root else []:
        out.append({"id": b["id"], "title": b["text"], "role": frameworks.classify_branch(b["text"], b["kind"]), "weight": b["weight"] * 10 + b["votes"], "node": b})
    return root, kids, out


def preview_structures(p):
    root, kids, br = branch_info(p)
    res = []
    rec = [r["id"] for r in frameworks.recommend(p["brief"])]
    ids = list(dict.fromkeys([p["framework"]] + rec + ["reverse_pyramid", "pyramid", "scqa", "psi"]))[:5]
    for sidf in ids:
        fw = frameworks.FW.get(sidf)
        if not fw: continue
        seq = frameworks.order_for(sidf, [{"id": b["id"], "title": b["title"], "role": b["role"], "weight": b["weight"]} for b in br])
        titles = {b["id"]: b["title"] for b in br}
        pos = next((i for i, s in enumerate(seq) if s["id"] == "__answer__"), 0) + 2 if not fw["answer_first"] else 2
        res.append({"id": sidf, "name": fw["name"], "answer_first": fw["answer_first"], "answer_slide": pos,
                    "sequence": [{"section": s["section"], "title": titles.get(s["id"], "The answer"), "id": s["id"]} for s in seq]})
    return res


def build(p, chunks, structure=None, progress=None, keep_locked=True):
    """Returns (slides, storyline). Does not mutate p."""
    structure = structure or p["storyline"]["structure"] or p["framework"] or "reverse_pyramid"
    fw = frameworks.FW.get(structure, frameworks.FW["reverse_pyramid"])
    root, kids, br = branch_info(p)
    if not root: raise store.Invalid("The map is empty. Build the map first.")
    grand = kids
    seq = frameworks.order_for(structure, [{"id": b["id"], "title": b["title"], "role": b["role"], "weight": b["weight"]} for b in br])
    by = {b["id"]: b for b in br}
    old = {s["node_id"]: s for s in p["slides"] if s["node_id"] and (s["locked"] or s["approved"]) and keep_locked}
    main_titles = [by[s["id"]]["title"] for s in seq if s["id"] in by and by[s["id"]]["role"] not in ("appendix",)]
    thesis = p["governing"] or p["brief"]["message"] or root["text"]
    story, how = ai.storyline_text(p, main_titles, chunks)
    story["thesis"] = story["thesis"] or thesis
    slides, prev_title = [], ""
    name = p["name"]
    sub = " · ".join(x for x in [p["brief"]["who"][:60], ] if x)
    slides.append(dict(id=sid(), kind="title", layout="key_message", title=name, purpose="Opening", bullets=[], quote="", quote_by="", takeaway=sub, notes="", visual="Title slide", transition="",
                       facilitation="", node_id="", sources=[], gaps=[], approved=False, locked=False, override_layout=""))
    summary_made = False
    def make_summary():
        titles = []
        slides.append(dict(id=sid(), kind="summary", layout="summary", title=(story["thesis"] or thesis)[:200], purpose="Give the answer before any detail",
                           bullets=[{"text": trim(t, 16), "level": 0, "origin": "user", "cite": []} for t in titles], quote="", quote_by="",
                           takeaway=(p["brief"]["decides"] or p["brief"]["does"])[:300], notes=story["exec_summary"], visual=VISUAL["summary"], transition="",
                           facilitation="", node_id="", sources=[], gaps=[], approved=False, locked=False, override_layout=""))
    if fw["answer_first"]: make_summary(); summary_made = True
    work = [s for s in seq if s["id"] == "__answer__" or (s["id"] in by and by[s["id"]]["role"] != "appendix")]
    appendix = [by[s["id"]] for s in seq if s["id"] in by and by[s["id"]]["role"] == "appendix"]
    total = len(work) + len(appendix)
    done = 0
    for item in work:
        if item["id"] == "__answer__":
            if not summary_made: make_summary(); summary_made = True
            continue
        b = by[item["id"]]; node = b["node"]
        if node["id"] in old:
            slides.append(old[node["id"]]); prev_title = old[node["id"]]["title"]; continue
        ks = kids.get(node["id"], [])
        used = ai.retrieve_for(chunks, node["text"] + " " + " ".join(k["text"] for k in ks) + " " + thesis, 5)
        layout = choose_layout(node, ks, grand, b["role"])
        try:
            content, used2 = ai.llm_slide(p, node, ks, grand, used, layout)
            used = used2 if used2 else used
        except (ai.AIBlocked, ai.AIError):
            content = ai.offline_slide(node, ks, grand, used, layout)
        title = style.autofix(content["title"])
        slides.append(dict(id=sid(), kind="ask" if b["role"] == "ask" else "content", layout=layout, title=title, purpose=f"Supports the answer: {trim(thesis, 14)}" if thesis else "",
                           bullets=[{**bb, "text": style.autofix(bb["text"])} for bb in content["bullets"]], quote="", quote_by="", takeaway=style.autofix(content["takeaway"]),
                           notes=content["notes"], visual=VISUAL[layout], transition=(f"Having covered '{trim(prev_title, 8)}', now: {trim(title, 10)}" if prev_title else ""),
                           facilitation="", node_id=node["id"], sources=ai.sources_of(used if any(bb["origin"] == "sourced" for bb in content["bullets"]) else []),
                           gaps=content["gaps"], approved=False, locked=False, override_layout=""))
        prev_title = title; done += 1
        if progress: progress(done, total, title)
    # the summary lists the real slide headlines of the key arguments, not raw map labels
    for sm in slides:
        if sm["kind"] == "summary":
            heads = [s["title"] for s, r in zip([x for x in slides if x["node_id"] and x["kind"] == "content"], [by[x["node_id"]]["role"] if x["node_id"] in by else "" for x in slides if x["node_id"] and x["kind"] == "content"]) if r in ("arguments", "implication")][:5]
            sm["bullets"] = [{"text": trim(t, 16), "level": 0, "origin": "user", "cite": []} for t in heads]
    # ask slide from brief when none exists
    if not any(s["kind"] == "ask" for s in slides) and (p["brief"]["decides"] or p["brief"]["does"]):
        ask_t = p["brief"]["decides"] or p["brief"]["does"]
        acts = [d for d in p["facilitation"]["decisions"] if d["kind"] == "action"]
        slides.append(dict(id=sid(), kind="ask", layout="action_plan" if acts else "key_message", title=f"Decision needed: {trim(ask_t[:1].lower() + ask_t[1:], 14)}", purpose="State the decision or action requested",
                           bullets=[{"text": f"{a['text']}" + (f" ({a['owner']})" if a["owner"] else "") + (f", by {a['due']}" if a["due"] else ""), "level": 0, "origin": "user", "cite": []} for a in acts[:6]],
                           quote="", quote_by="", takeaway=ask_t[:300], notes="", visual=VISUAL["action_plan" if acts else "key_message"], transition="", facilitation="", node_id="", sources=[], gaps=[], approved=False, locked=False, override_layout=""))
    for b in appendix:
        node = b["node"]; ks = kids.get(node["id"], [])
        used = ai.retrieve_for(chunks, node["text"], 3)
        c = ai.offline_slide(node, ks, grand, used, "appendix")
        slides.append(dict(id=sid(), kind="appendix", layout="appendix", title=style.autofix(c["title"]), purpose="Reference detail for questions", bullets=c["bullets"], quote="", quote_by="", takeaway="",
                           notes=c["notes"], visual=VISUAL["appendix"], transition="", facilitation="", node_id=node["id"], sources=ai.sources_of(used), gaps=c["gaps"], approved=False, locked=False, override_layout=""))
    qa = [q for q in p["facilitation"]["questions"] if q["q"]]
    if qa:
        bl = []
        for q in qa[:6]:
            bl.append({"text": q["q"], "level": 0, "origin": "user", "cite": []})
            if q["a"]: bl.append({"text": q["a"], "level": 1, "origin": "user", "cite": []})
        slides.append(dict(id=sid(), kind="appendix", layout="appendix", title="Questions we expect, and our answers", purpose="Prepare for objections", bullets=bl, quote="", quote_by="", takeaway="", notes="",
                           visual=VISUAL["appendix"], transition="", facilitation="", node_id="", sources=[], gaps=[], approved=False, locked=False, override_layout=""))
    used_src = {}
    for s in slides:
        for r in s["sources"]: used_src.setdefault(r["name"], r)
    if used_src:
        slides.append(dict(id=sid(), kind="sources", layout="appendix", title="Sources used in this deck", purpose="Traceability", quote="", quote_by="", takeaway="", notes="", visual=VISUAL["appendix"],
                           bullets=[{"text": f"{r['name']} ({ {'provided':'provided by you','internal':'internal knowledge base','external':'external web'}[r['origin']] })", "level": 0, "origin": "user", "cite": []} for r in used_src.values()][:12],
                           transition="", facilitation="", node_id="", sources=[], gaps=[], approved=False, locked=False, override_layout=""))
    story.update(structure=structure, approved=p["storyline"]["approved"], alternatives=p["storyline"]["alternatives"])
    story["engine"] = how
    return slides, story
