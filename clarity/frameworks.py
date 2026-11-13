"""Communication frameworks, the intake-based recommender, and storyline structures."""
import re


def st(key, label, hint, role, example=""): return {"key": key, "label": label, "hint": hint, "role": role, "example": example}


FRAMEWORKS = [
    {"id": "reverse_pyramid", "name": "Reverse pyramid", "answer_first": True,
     "best_for": "Executives and short slots. The answer comes first and detail follows by importance.",
     "steps": [st("answer", "The answer", "The recommendation, decision, or main message in one sentence.", "answer", "Move the Berlin team to the new platform by March."),
               st("arguments", "Strongest reasons, most important first", "One per line. Stop at five.", "arguments", "Cuts release time from 9 days to 2."),
               st("evidence", "Evidence and examples", "Numbers, cases, quotes. One per line.", "section"),
               st("background", "Background (goes to the appendix)", "What the audience may need only if they ask.", "appendix"),
               st("ask", "What you need from them", "Decision, approval, or next step.", "ask")]},
    {"id": "pyramid", "name": "Pyramid Principle", "answer_first": True,
     "best_for": "Persuading with a recommendation. One governing thought, three to five grouped arguments.",
     "steps": [st("answer", "Governing thought", "The single sentence you want remembered.", "answer"),
               st("arguments", "Key line: 3 to 5 arguments", "Each argument must stand alone and not overlap the others (MECE).", "arguments"),
               st("evidence", "Support under each argument", "Facts and examples.", "section"),
               st("ask", "Ask", "What happens next.", "ask")]},
    {"id": "scqa", "name": "Situation, Complication, Question, Answer", "answer_first": False,
     "best_for": "Aligning people who need the context before they accept the answer.",
     "steps": [st("situation", "Situation", "What everyone already agrees on.", "context"),
               st("complication", "Complication", "What changed or went wrong.", "context"),
               st("question", "Question", "What the audience now needs answered.", "context"),
               st("answer", "Answer", "Your answer in one sentence.", "answer"),
               st("arguments", "Supporting arguments", "One per line.", "arguments"),
               st("ask", "Ask", "Decision or next step.", "ask")]},
    {"id": "cia", "name": "Context, Insight, Implication, Action", "answer_first": True,
     "best_for": "Research readouts and analysis. Moves from what we found to what to do.",
     "steps": [st("answer", "Headline", "The most important finding with its consequence.", "answer"),
               st("context", "Context", "Why this was looked at.", "context"),
               st("arguments", "Insights", "What the data shows. One per line.", "arguments"),
               st("implication", "Implications", "What each insight means for the audience.", "section"),
               st("ask", "Actions", "What to do, who, by when.", "ask")]},
    {"id": "psi", "name": "Problem, Solution, Impact", "answer_first": False,
     "best_for": "Proposals and pitches where the problem must land first.",
     "steps": [st("problem", "Problem", "Who is hurt, how much, how often.", "section"),
               st("answer", "Solution", "What you propose, in one sentence.", "answer"),
               st("arguments", "Impact", "Measurable benefits. One per line.", "arguments"),
               st("ask", "Ask", "What you need to proceed.", "ask")]},
    {"id": "wswnw", "name": "What, So what, Now what", "answer_first": False,
     "best_for": "Updates, retrospectives and debriefs.",
     "steps": [st("what", "What happened", "Facts only.", "section"),
               st("answer", "Main takeaway", "The one thing to remember.", "answer"),
               st("arguments", "So what: why it matters", "One per line.", "arguments"),
               st("ask", "Now what: actions", "Next steps with owners.", "ask")]},
    {"id": "bab", "name": "Before, After, Bridge", "answer_first": False,
     "best_for": "Change and transformation stories.",
     "steps": [st("before", "Before: today's state", "What it costs or limits now.", "section"),
               st("answer", "After: the future state", "What is true once it works.", "answer"),
               st("arguments", "Bridge: how we get there", "Steps or enablers. One per line.", "arguments"),
               st("ask", "Ask", "First move.", "ask")]},
    {"id": "decision_brief", "name": "Executive decision brief", "answer_first": True,
     "best_for": "A single decision from senior people.",
     "steps": [st("answer", "Recommendation", "What you recommend, in one sentence.", "answer"),
               st("context", "Why now", "The trigger and the deadline.", "context"),
               st("arguments", "Why this option", "Reasons. One per line.", "arguments"),
               st("options", "Options considered", "Each option and why it ranks lower.", "section"),
               st("risks", "Risks and mitigations", "One per line: risk, then mitigation.", "section"),
               st("ask", "Decision needed", "The exact decision, owner, and date.", "ask")]},
    {"id": "three_act", "name": "Three-act narrative", "answer_first": False,
     "best_for": "Keynotes and stories where emotion carries the argument.",
     "steps": [st("setup", "Act 1: setup", "The world as it was, and the hero.", "context"),
               st("arguments", "Act 2: obstacles and turns", "Each obstacle, one per line.", "arguments"),
               st("answer", "Act 3: resolution", "What changed and what it proves.", "answer"),
               st("ask", "Call to action", "What the audience does next.", "ask")]},
    {"id": "workshop", "name": "Workshop or facilitation flow", "answer_first": True,
     "best_for": "Sessions where the group produces the outcome.",
     "steps": [st("answer", "Objective", "What the group will have decided or made by the end.", "answer"),
               st("rules", "Ground rules and context", "Scope, roles, constraints.", "context"),
               st("arguments", "Activities", "One per line, with a time box.", "arguments"),
               st("outputs", "Expected outputs", "What gets captured.", "section"),
               st("ask", "Follow-up", "Owners and dates.", "ask")]},
]
FW = {f["id"]: f for f in FRAMEWORKS}


def recommend(brief: dict):
    """Returns ranked [{id, score, why}]; deterministic and explainable."""
    intent, mins = brief.get("intent", "persuade"), brief.get("minutes", 15) or 15
    text = " ".join(str(brief.get(k, "")) for k in ("purpose", "who", "decides", "does", "message")).lower()
    outs = brief.get("outputs") or []
    sc, why = {f["id"]: 0 for f in FRAMEWORKS}, {f["id"]: [] for f in FRAMEWORKS}
    def add(i, n, w): sc[i] += n; why[i].append(w)
    exec_aud = re.search(r"\b(executive|board|leadership|ceo|cfo|vp|director|steering|c-suite|senior)\b", text)
    base = {"persuade": [("pyramid", 3, "You are making an argument, so one governing thought with grouped support fits"), ("psi", 2, "Problem and impact framing helps persuasion")],
            "inform": [("reverse_pyramid", 3, "Informing busy people works best answer-first"), ("cia", 2, "Insight and implication keeps findings actionable"), ("wswnw", 1, "Good for updates")],
            "align": [("scqa", 3, "Alignment needs shared context before the answer"), ("pyramid", 1, "Grouped arguments help settle disagreement")],
            "facilitate": [("workshop", 4, "The group produces the outcome")],
            "teach": [("three_act", 2, "A narrative arc helps people remember"), ("wswnw", 2, "Explains the point then the use"), ("bab", 1, "Shows progress from old to new")],
            "decide": [("decision_brief", 4, "A single decision needs recommendation, options, risk, and ask")]}
    for i, n, w in base.get(intent, base["persuade"]): add(i, n, w)
    if exec_aud or mins <= 10: add("reverse_pyramid", 3, "Senior audience or a short slot: lead with the answer"); add("decision_brief", 1, "Executives often want a clear decision")
    if re.search(r"\b(change|transform|migrat|move from|modernis|modernize)\b", text): add("bab", 3, "Describes a change from one state to another")
    if re.search(r"\b(problem|issue|pain|risk|gap)\b", text): add("psi", 1, "Names a problem")
    if re.search(r"\b(research|findings|survey|analysis|data)\b", text): add("cia", 2, "Presents findings")
    if "workshop" in outs: add("workshop", 3, "A workshop output was requested")
    if "summary" in outs and len(outs) == 1: add("reverse_pyramid", 1, "Summary output favors answer-first")
    ranked = sorted(sc, key=lambda k: -sc[k])
    return [{"id": i, "score": sc[i], "why": why[i]} for i in ranked[:4] if sc[i] > 0]


# Storyline structures reuse frameworks; matchers decide which map branch lands in which section.
SECTION_WORDS = {
    "appendix": r"background|appendix|glossary|reference|methodolog|supplement|detail|history",
    "ask": r"next step|ask|decision needed|action plan|follow[- ]?up|call to action|approval",
    "context": r"situation|context|current state|why now|trigger|setup",
    "risks": r"risk|mitigat|threat|concern|downside",
    "options": r"option|alternative|trade-?off",
    "implication": r"implication|so what|impact|consequence",
}


def classify_branch(text: str, kind: str = ""):
    t = (text or "").lower()
    if kind == "action": return "ask"
    if kind == "risk": return "risks"
    if kind == "implication": return "implication"
    for role in ("appendix", "ask", "context", "risks", "options", "implication"):
        if re.search(SECTION_WORDS[role], t): return role
    return "arguments"


def order_for(structure_id: str, branches):
    """branches: [{id,title,role,weight}] -> ordered [{id,section}], plus notes. Pure function for previews."""
    fw = FW.get(structure_id, FW["reverse_pyramid"])
    by_role = {}
    for b in branches: by_role.setdefault(b["role"], []).append(b)
    for r in by_role.values(): r.sort(key=lambda b: -b.get("weight", 0))
    seq, used = [], set()
    def put(role, label):
        for b in by_role.get(role, []):
            if b["id"] not in used: used.add(b["id"]); seq.append({"id": b["id"], "section": label})
    tail = [("arguments", "Key arguments"), ("implication", "Implications"), ("options", "Options"), ("risks", "Risks"), ("context", "Context"), ("ask", "Ask")]
    order = []
    for s in fw["steps"]:
        role = s["role"]
        if role == "section": role = {"problem": "arguments", "what": "arguments", "before": "context", "options": "options", "risks": "risks", "outputs": "arguments", "implication": "implication"}.get(s["key"], "arguments")
        if role == "answer": order.append(("__answer__", s["label"]) if not fw["answer_first"] else None)
        elif role != "appendix": order.append((role, s["label"]))
    order = [o for o in order if o] + tail + [("appendix", "Appendix")]
    for role, label in order:
        if role == "__answer__": seq.append({"id": "__answer__", "section": label}); continue
        put(role, label)
    for b in branches:
        if b["id"] not in used: seq.append({"id": b["id"], "section": "Other"})
    return seq
