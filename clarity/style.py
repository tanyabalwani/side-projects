"""Plain-writing linter + generation rules.
Built from the patterns catalogued in Wikipedia's "Signs of AI writing" page
(vocabulary, significance puffery, copula avoidance, vague attribution, negative
parallelism, rule of three, trailing -ing clauses, section summaries, em dashes,
title case, emoji, curly quotes). A hit is a prompt to rewrite, never proof of
anything, and every rule is advisory."""
import re

RULES = [
    ("ai-vocabulary", r"\b(delve[sd]?|delving|tapestry|testament|pivotal|vibrant|intricacies|intricate|interplay|meticulous(?:ly)?|"
                      r"multifaceted|garner(?:s|ed)?|bolster(?:s|ed)?|underscor(?:e|es|ed|ing)|showcas(?:e|es|ed|ing)|"
                      r"foster(?:s|ed|ing)?|cultivat(?:e|es|ed|ing)|leverag(?:e|es|ed|ing)|deep dive|enduring|valuable insights?)\b",
     "Overused 'AI vocabulary'. Use a plainer word or state the fact."),
    ("significance-puffery", r"\b(stands as|serves as|is a testament|a testament to|plays? an? (?:crucial|pivotal|vital|key|significant) role|"
                             r"marks an? (?:shift|turning point|milestone)|key turning point|setting the stage|evolving landscape|"
                             r"digital landscape|broader (?:trend|movement|context)|indelible mark|deeply rooted|focal point|"
                             r"reflects broader|underscores? (?:its|the) (?:importance|significance))\b",
     "Puffs up importance without a fact. Say what happened and by how much."),
    ("copula-avoidance", r"\b(serves as|stands as|functions as|operates as|boasts|refers to|represents an?)\b",
     "Prefer plain 'is', 'are', or 'has'."),
    ("promotional", r"\b(groundbreaking|breathtaking|renowned|nestled|world-class|cutting-edge|game-?changer|seamless(?:ly)?|robust|"
                    r"unlock(?:s|ed|ing)? (?:the )?(?:power|potential|value)|rich (?:tapestry|heritage|history)|diverse array|commitment to)\b",
     "Promotional wording. Replace with a measurable claim."),
    ("vague-attribution", r"\b(experts (?:say|argue|agree|believe)|industry (?:reports|experts|observers)|observers (?:have )?(?:noted|cited)|"
                          r"some critics|several (?:sources|studies|publications)|studies (?:show|suggest)|research (?:shows|suggests)|"
                          r"many (?:believe|argue))\b",
     "Vague attribution. Name the source or remove the claim."),
    ("vague-connection", r"\b(associated with|in connection with|connected (?:with|to))\b",
     "State the actual relationship directly."),
    ("negative-parallelism", r"(\bnot (?:only|just|merely) [^.;:]{1,80}?,? (?:but|it'?s|it is)\b|\b(?:it'?s|it is|this is) not [^.;]{1,60}, (?:it'?s|it is)\b|\b(?:doesn'?t|does not|isn'?t) just\b)",
     "'Not just X but Y' framing. State Y."),
    ("trailing-ing-clause", r",\s+(?:highlighting|underscoring|emphasi[sz]ing|ensuring|reflecting|symboli[sz]ing|contributing|fostering|"
                            r"cultivating|showcasing|enhancing|demonstrating|encompassing)\b",
     "Trailing '-ing' comment that adds no fact. Cut it or make it a sentence with a number."),
    ("challenges-formula", r"\b(despite (?:its|these|the) [^.]{0,60}challenges|faces (?:several|many|a number of) challenges|future outlook|challenges and opportunities)\b",
     "Formula wording. Name the specific risk and the mitigation."),
    ("section-summary", r"(?:^|[.!?]\s+)(In summary|In conclusion|Overall|To summari[sz]e|To sum up),?",
     "Restating summary. End on the action or the next fact."),
    ("transition-opener", r"(?:^|[.!?]\s+)(Additionally|Moreover|Furthermore|Notably|Importantly),",
     "Filler transition. Join ideas with logic, not connectives."),
    ("chatbot-leftover", r"(?i)\b(as an ai(?: language model)?|i hope this helps|let me know if|certainly!|here is (?:a|the)|great question|\[insert[^\]]*\]|lorem ipsum|TODO)\b",
     "Assistant phrasing or a placeholder left in the text."),
    ("hedge-filler", r"\b(it(?:'s| is) (?:important|worth) (?:to note|noting)|it should be noted)\b",
     "Filler lead-in. State the point."),
    ("em-dash", "—", "Em dash. Use a comma, colon, period, or parentheses."),
    ("spaced-hyphen", r"\s-\s", "Spaced hyphen used as a dash. Use a comma or colon."),
    ("curly-quotes", "[“”‘’]", "Curly quotes. Use straight quotes for consistency."),
    ("emoji", "[\U0001F300-\U0001FAFF☀-➿⭐✅]", "Emoji in business copy."),
    ("markdown-bold", r"\*\*[^*]+\*\*", "Literal Markdown bold markers in slide text."),
]
_COMPILED = [(n, re.compile(p, re.I if n not in ("section-summary", "transition-opener", "chatbot-leftover") else 0), m) for n, p, m in RULES]
_SPECIAL = {"em-dash", "spaced-hyphen", "curly-quotes", "emoji", "markdown-bold"}


def lint(text: str):
    out = []
    for name, rx, msg in _COMPILED:
        for m in rx.finditer(text or ""):
            out.append({"rule": name, "match": (m.group(0) or "").strip()[:60], "pos": m.start(), "msg": msg,
                        "severity": "info" if name in _SPECIAL else "warn"})
    # rule of three: "a, b, and c" short list inside one sentence
    for m in re.finditer(r"\b\w[\w-]*(?: \w[\w-]*)?, \w[\w-]*(?: \w[\w-]*)?,? and \w[\w-]*(?: \w[\w-]*)?\b", text or ""):
        if len(m.group(0)) < 70:
            out.append({"rule": "rule-of-three", "match": m.group(0), "pos": m.start(), "severity": "info",
                        "msg": "Three-item list. Keep it only if there really are three things."})
    return sorted(out, key=lambda x: x["pos"])


def is_title_case(s: str) -> bool:
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", s)
    if len(words) < 4: return False
    minor = {"a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "at", "by", "vs", "with", "from", "as", "but", "nor"}
    major = [w for w in words[1:] if w.lower() not in minor and not w.isupper()]
    return len(major) >= 2 and all(w[0].isupper() for w in major)


SWAPS = [(r"\bin order to\b", "to"), (r"\bdue to the fact that\b", "because"), (r"\butili[sz]e[sd]?\b", "use"),
         (r"\bleverag(?:e|es|ed|ing)\b", "use"), (r"\bserves as\b", "is"), (r"\bstands as\b", "is"), (r"\bboasts\b", "has"),
         (r"\bnumerous\b", "many"), (r"\bapproximately\b", "about"), (r"\bfacilitate[sd]?\b", "help"),
         (r"\bendeavou?r\b", "try"), (r"\bcommence\b", "start"), (r"\bat this point in time\b", "now")]


def autofix(text: str) -> str:
    """Mechanical clean-up only: quotes, dashes, emoji, filler openers, a few plain-word swaps."""
    t = text or ""
    t = t.translate({0x201c: '"', 0x201d: '"', 0x2018: "'", 0x2019: "'"})
    t = re.sub(r"\s*—\s*", ", ", t)
    t = re.sub(r"\s+-\s+", ", ", t)
    t = re.sub("[\U0001F300-\U0001FAFF☀-➿⭐✅]️?\\s*", "", t)
    t = t.replace("**", "")
    t = re.sub(r"^(Additionally|Moreover|Furthermore|Notably|Importantly),\s*(\w)", lambda m: m.group(2).upper(), t)
    t = re.sub(r"^(In summary|In conclusion|Overall|To summarize|To sum up),?\s*(\w)", lambda m: m.group(2).upper(), t)
    for pat, rep in SWAPS: t = re.sub(pat, rep, t, flags=re.I)
    return re.sub(r"\s{2,}", " ", t).strip()


PROMPT_RULES = """Writing rules (apply to every string you output):
- Plain, specific, human. Say what happened, how much, by when, who owns it. Prefer 'is', 'has', 'use' over 'serves as', 'boasts', 'utilize'.
- Banned vocabulary: delve, tapestry, testament, pivotal, crucial, vibrant, landscape (abstract), underscore, showcase, foster, cultivate, leverage, robust, seamless, groundbreaking, multifaceted, intricate, interplay, enduring, deep dive, valuable insights.
- No significance padding ('plays a key role', 'marks a shift', 'broader trend') unless the context states the fact behind it.
- No 'not just X but Y' or 'it is not X, it is Y' constructions. State Y.
- No trailing '-ing' comment clauses ('..., highlighting the importance of ...').
- No vague attribution ('experts say', 'industry reports'). Cite a provided source by name or leave the claim out.
- No 'In summary', 'Overall', 'Additionally', 'Moreover', 'Notably'. No 'Despite these challenges'.
- Do not force lists into threes. Use the number of items that exist.
- No em dashes, no emoji, no markdown bold, no title-case headings. Use sentence case and straight quotes.
- Keep the user's own terminology and voice. Do not add praise, hedging, or greetings."""
