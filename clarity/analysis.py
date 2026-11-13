"""Source analysis without a model: key messages, facts, decisions, actions, quotes,
duplicates and possible contradictions. Always available, so traceability does not depend on AI."""
import math, re
from collections import Counter

STOP = set("a an the and or of to in on for at by with from as is are was were be been being it its this that these those we our you your they their i he she not no yes but if then than so such can could may might will would should do does did has have had which who whom what when where how also into over under about more most less very just only".split())


def sentences(text):
    out = []
    for para in re.split(r"\n{1,}", text or ""):
        para = para.strip()
        if not para or para.startswith("#"): continue
        for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", para):
            s = s.strip(" -*•\t")
            if len(s) > 25: out.append(s)
    return out


def tokens(s): return [w for w in re.findall(r"[a-z][a-z0-9'-]+", s.lower()) if w not in STOP and len(w) > 2]
def trim(s, words=22):
    w = s.split()
    return s if len(w) <= words else " ".join(w[:words]).rstrip(",;:") + "…"


def rank_sentences(text, k=6):
    sents = sentences(text)
    if not sents: return []
    tf = Counter(t for s in sents for t in set(tokens(s)))
    scored = []
    for i, s in enumerate(sents):
        tk = tokens(s)
        if not tk: continue
        sc = sum(math.log(1 + tf[t]) for t in set(tk)) / (len(tk) ** 0.5)
        if re.search(r"\d", s): sc *= 1.15
        if i < 3: sc *= 1.1
        scored.append((sc, i, s))
    top = sorted(scored, reverse=True)[:k]
    return [s for _, _, s in sorted(top, key=lambda x: x[1])]


ACTION = re.compile(r"(?i)^(?:action(?: item)?s?:|todo:|next step:|\[ \]|-\s*\[ \])|\b(?:will|to) (?:send|prepare|deliver|review|schedule|confirm|draft|share|update|complete|follow up|own|finali[sz]e)\b.*\b(?:by|before|on)\b|\bowner:|\bdue (?:by|on)?\b")
DECISION = re.compile(r"(?i)\b(?:we (?:decided|agreed|approved|chose|will go with)|decision:|it was decided|approved|agreed (?:to|that)|resolved to)\b")
QUOTE = re.compile(r"[\"“]([^\"”]{35,260})[\"”]")
NUM = re.compile(r"(?<![\w.])\$?\d[\d,]*(?:\.\d+)?\s?(?:%|percent|k|m|bn|million|billion|x)?(?![\w])", re.I)


def analyze(text):
    sents = sentences(text)
    return {
        "key_messages": [trim(s, 28) for s in rank_sentences(text, 5)],
        "facts": [trim(s, 28) for s in sents if NUM.search(s)][:8],
        "decisions": [trim(s, 28) for s in sents if DECISION.search(s)][:6],
        "actions": [trim(s, 28) for s in (re.sub(r"^[-*•]\s*", "", x.strip()) for l in (text or "").splitlines() for x in re.split(r"(?<=[.!?])\s+", l)) if len(s) > 12 and ACTION.search(s)][:8],
        "quotes": [m.group(1).strip() for m in QUOTE.finditer(text or "")][:5],
    }


def shingles(s, n=3):
    t = tokens(s)
    return {" ".join(t[i:i + n]) for i in range(max(1, len(t) - n + 1))} if t else set()


def jaccard(a, b): return len(a & b) / len(a | b) if a and b else 0.0


def cross_checks(sources):
    """sources: [{id,name,text}] -> duplicates and possible contradictions across/within sources."""
    items = []
    for s in sources:
        for sent in sentences(s["text"])[:400]: items.append((s["id"], s["name"], sent))
    dups, contra = [], []
    sh = [(i, shingles(x[2])) for i, x in enumerate(items)]
    for a in range(len(items)):
        for b in range(a + 1, len(items)):
            if items[a][0] == items[b][0] and a + 1 == b: pass
            ja = jaccard(sh[a][1], sh[b][1])
            if ja < 0.45: continue
            na = {re.sub(r"[,\s]", "", n) for n in NUM.findall(items[a][2])}
            nb = {re.sub(r"[,\s]", "", n) for n in NUM.findall(items[b][2])}
            if ja >= 0.85 and na == nb and items[a][0] != items[b][0] and len(dups) < 30:
                dups.append({"a": items[a][1], "b": items[b][1], "text": trim(items[a][2], 24)})
            elif na and nb and na != nb and not (na & nb) and len(contra) < 20:
                    contra.append({"a": items[a][1], "b": items[b][1], "a_text": trim(items[a][2], 24), "b_text": trim(items[b][2], 24)})
        if a > 700: break
    return {"duplicates": dups, "contradictions": contra}
