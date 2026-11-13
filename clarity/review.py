"""Pre-export quality review. Issue ids are stable, so sign-offs (resolved/accepted/override) persist."""
import re, time, zlib
import frameworks, safety, style, retrieval, store
from analysis import jaccard, shingles

VERB = re.compile(r"\b(is|are|was|were|will|can|cuts?|reduces?|increases?|grows?|grew|saves?|needs?|must|should|requires?|drives?|enables?|delivers?|moves?|shows?|means?|lets?|makes?|has|have|costs?|brings?|raises?|lowers?|improves?|protects?|speeds?|keeps?|gives?|takes?|runs?|builds?|wins?|loses?|fails?|stops?|starts?|helps?|allows?|prevents?|ends?|fell|rose|doubled?|halved?|approve|decide|needed|choose|adopt|fund|launch|migrate|hire|cut|keep|pick|select|renew|reduce|expand|cancel|replace|invest|pause|ship|ships)\b", re.I)
SEV = {"blocker": 3, "major": 2, "minor": 1, "info": 0}


def words(s): return len(re.findall(r"\S+", s or ""))


def slide_text(s):
    return " ".join([s["title"], s["takeaway"]] + [b["text"] for b in s["bullets"]])


def review(p, fit_issues=None):
    iss = []
    def add(key, sev, check, msg, slide=None, fix=""):
        iss.append({"id": key, "severity": sev, "check": check, "message": msg, "slide_id": slide or "", "fix": fix})
    slides = p["slides"]
    main = [s for s in slides if s["kind"] in ("title", "summary", "content", "ask")]
    thesis = p["storyline"]["thesis"] or p["governing"] or p["brief"]["message"]
    if not slides:
        add("empty", "blocker", "Deck", "There are no slides yet.", fix="Generate the deck from the map."); return _finish(p, iss)
    # 1 main message
    if not thesis: add("thesis-missing", "blocker", "Main message", "No single main message is set.", fix="Write the one sentence the audience should remember.")
    elif words(thesis) > 28: add("thesis-long", "minor", "Main message", f"The main message is {words(thesis)} words. Aim for one sentence under 25 words.")
    # 2 opening leads with answer
    fw = frameworks.FW.get(p["storyline"]["structure"] or p["framework"], frameworks.FW["reverse_pyramid"])
    first = next((s for s in slides if s["kind"] not in ("title",)), None)
    if fw["answer_first"] and first and first["kind"] != "summary":
        add("opening-no-answer", "major", "Opening", "The opening does not lead with the answer.", first["id"], "Add or move the summary slide to position 2.")
    # 3 supports central argument
    nodes = {n["id"] for n in p["map"]["nodes"]}
    for s in slides:
        if s["kind"] in ("content", "ask") and not s["bullets"] and not s["takeaway"] and s["layout"] not in ("quote",): add("empty-" + s["id"], "major", "Relevance", "Slide has no supporting content.", s["id"])
        if s["node_id"] and s["node_id"] not in nodes: add("orphan-" + s["id"], "minor", "Relevance", "Slide points to a map node that no longer exists.", s["id"], "Link it to a branch or delete it.")
        if s["kind"] == "content" and not s["purpose"]: add("purpose-" + s["id"], "info", "Relevance", "No stated purpose for this slide.", s["id"])
    # 4 headlines
    for s in slides:
        if s["kind"] in ("content", "ask", "summary"):
            w = words(s["title"])
            if w < 5 or not VERB.search(s["title"]): add("headline-" + s["id"], "minor", "Headline", f"'{s['title'][:60]}' reads as a topic, not a conclusion.", s["id"], "Rewrite it as a sentence with a verb and a result.")
            elif w > 18: add("headline-long-" + s["id"], "minor", "Headline", "Headline is longer than 18 words.", s["id"])
            if style.is_title_case(s["title"]): add("titlecase-" + s["id"], "minor", "Headline", "Headline is in title case. Use sentence case.", s["id"])
    # 5 sequence
    kinds = [s["kind"] for s in slides]
    if "appendix" in kinds:
        i = kinds.index("appendix")
        if any(k in ("content", "ask") for k in kinds[i:]): add("appendix-mid", "major", "Sequence", "Appendix slides appear before the end of the main story.", fix="Move appendix slides to the end.")
    if "ask" in kinds and any(k in ("content",) for k in kinds[kinds.index("ask") + 1:]): add("ask-early", "minor", "Sequence", "The ask appears before the last content slide.")
    for i, s in enumerate(main):
        if i > 1 and s["kind"] == "content" and not s["transition"]: add("trans-" + s["id"], "info", "Transitions", "No transition to the previous slide.", s["id"])
    # repetition
    sh = [(s, shingles(s["title"], 2)) for s in main if s["kind"] == "content"]
    for i in range(len(sh)):
        for j in range(i + 1, len(sh)):
            if jaccard(sh[i][1], sh[j][1]) > 0.6: add(f"dup-{sh[i][0]['id']}-{sh[j][0]['id']}", "minor", "Repetition", f"'{sh[i][0]['title'][:40]}' and '{sh[j][0]['title'][:40]}' say nearly the same thing.", sh[j][0]["id"], "Merge or differentiate.")
    # 6 claim support, 7 citations, 8 currency
    names = {s["name"] for s in p["sources"]}
    kb = {d["name"]: d for d in retrieval.list_docs()}
    for s in slides:
        for b in s["bullets"]:
            if b["origin"] == "ai" and re.search(r"\d", b["text"]): add(f"num-{s['id']}-{zlib.crc32(b['text'].encode()) % 99999}", "major", "Evidence", f"Unsupported number in an AI suggestion: '{b['text'][:60]}'.", s["id"], "Attach a source or remove the figure.")
        ai_n = sum(1 for b in s["bullets"] if b["origin"] == "ai")
        if ai_n and s["kind"] == "content": add(f"aisug-{s['id']}", "minor", "Evidence", f"{ai_n} bullet(s) are AI suggestions with no source. They are labelled as suggestions in the editor.", s["id"], "Confirm them yourself or add evidence.")
        for g in s["gaps"]: add(f"gap-{s['id']}-{zlib.crc32(g.encode()) % 99999}", "major", "Evidence", f"Open gap: {g}", s["id"], "Provide the data or delete the claim.")
        for r in s["sources"]:
            if r["origin"] == "internal":
                d = next((x for x in kb.values() if x["id"] == r.get("doc")), None) or kb.get(r["name"])
                if not d: add(f"cite-{s['id']}-{r['name'][:20]}", "major", "Citations", f"Cited document '{r['name']}' is no longer accessible.", s["id"])
                elif not d["eligible"]: add(f"stale-{s['id']}-{r['name'][:20]}", "major", "Sources", f"'{r['name']}' is {', '.join(d['flags'])}.", s["id"], "Replace with a current approved source.")
                elif retrieval.CLASS_RANK[d["classification"]] > retrieval.CLASS_RANK[p["security"]["classification"]]:
                    add(f"class-{s['id']}-{r['name'][:20]}", "blocker", "Confidentiality", f"'{r['name']}' is {d['classification']}, above this deck's {p['security']['classification']} level.", s["id"])
            elif r["name"] not in names: add(f"cite-{s['id']}-{r['name'][:20]}", "major", "Citations", f"Cited source '{r['name']}' is not in the project.", s["id"])
    # 9 confidentiality
    for s in slides:
        found = safety.find_sensitive(slide_text(s) + " " + s["notes"])
        if found.get("api-key") or found.get("private-key") or found.get("credential"): add(f"secret-{s['id']}", "blocker", "Confidentiality", "A credential or key appears in slide text or notes.", s["id"], "Remove it.")
        elif found and not p["security"]["redact_export"]: add(f"pii-{s['id']}", "major", "Confidentiality", "Personal data found (" + ", ".join(f"{k}: {v}" for k, v in found.items()) + ").", s["id"], "Remove it or turn on redaction at export.")
    # 10 crowding
    for s in slides:
        if s["kind"] in ("appendix", "sources"): continue
        w = words(slide_text(s))
        if w > 90 or len(s["bullets"]) > 7: add(f"crowd-{s['id']}", "major", "Density", f"Slide has {w} words and {len(s['bullets'])} bullets. Split it or cut.", s["id"])
        elif any(words(b["text"]) > 22 for b in s["bullets"]): add(f"long-{s['id']}", "minor", "Density", "A bullet is longer than 22 words.", s["id"])
    # 11 charts
    for s in slides:
        if s["layout"] == "data":
            pairs = [b for b in s["bullets"] if re.search(r"[:=]\s*[$€£]?\d", b["text"])]
            if len(pairs) < 2: add(f"chart-{s['id']}", "major", "Charts", "Data layout needs at least two 'label: value' lines to draw a real chart.", s["id"])
            elif not s["sources"]: add(f"chartsrc-{s['id']}", "major", "Charts", "A chart has no source line.", s["id"])
            elif not any(re.search(r"%|[$€£]|\b(days|users|customers|hours|weeks|months|k|m)\b", b["text"], re.I) for b in pairs): add(f"chartunit-{s['id']}", "minor", "Charts", "Values have no unit.", s["id"])
    # 12 language
    for s in slides:
        hits = [h for h in style.lint(slide_text(s)) if h["severity"] == "warn"]
        if len(hits) >= 2: add(f"lang-{s['id']}", "minor", "Language", "Wording patterns to rewrite: " + ", ".join(sorted({h['match'] for h in hits})[:5]) + ".", s["id"], "Use 'Fix wording' on the slide.")
    # 13 template fit
    for f in fit_issues or []: add("fit-" + f["slide_id"], "major", "Template", f["message"], f["slide_id"], "Shorten the text or choose a roomier layout.")
    if not p["template"]: add("no-template", "info", "Template", "No template uploaded. The built-in clean theme will be used.")
    # 14 action
    if not (p["brief"]["decides"] or p["brief"]["does"]): add("ask-undefined", "major", "Action", "The brief does not say what decision or action you want.")
    if not any(s["kind"] == "ask" for s in slides): add("ask-missing", "major", "Action", "No slide states the decision or next step.", fix="Add an ask slide.")
    # 15 ending
    body = [s for s in slides if s["kind"] not in ("appendix", "sources")]
    if body and body[-1]["kind"] != "ask": add("ending", "minor", "Ending", "The last main slide is not the ask. End on the action or decision.", body[-1]["id"])
    # complexity vs time
    mains = len([s for s in slides if s["kind"] in ("summary", "content", "ask")])
    if mains > max(3, p["brief"]["minutes"]): add("too-long", "major", "Complexity", f"{mains} main slides for {p['brief']['minutes']} minutes is too many. About one per minute at most.")
    return _finish(p, iss)


def _finish(p, iss):
    res = {r["id"]: r for r in p["qc"]["resolutions"]}
    for i in iss:
        r = res.get(i["id"])
        i["state"] = r["state"] if r else "open"; i["reason"] = r["reason"] if r else ""
    iss.sort(key=lambda i: (-SEV[i["severity"]], i["check"]))
    gating = [i for i in iss if SEV[i["severity"]] >= 2 and i["state"] == "open"]
    score = max(0, 100 - sum({"blocker": 25, "major": 8, "minor": 2, "info": 0}[i["severity"]] for i in iss if i["state"] == "open"))
    return {"issues": iss, "score": score, "can_export": not gating, "open_gating": len(gating),
            "counts": {k: sum(1 for i in iss if i["severity"] == k and i["state"] == "open") for k in SEV}}
