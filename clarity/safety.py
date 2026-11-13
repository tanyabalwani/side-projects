"""Upload scanning, prompt-injection flagging, redaction. All checks are local."""
import io, re, shutil, subprocess, tempfile, zipfile
from ingest import IngestError, ext_of

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
XLSX_EXT = {".xlsx"}
BAD_MAGIC = (b"MZ", b"\x7fELF", b"#!", b"\xca\xfe\xba\xbe", b"PK\x03\x04")  # PK allowed only for office ext, checked below


def scan_upload(name: str, data: bytes):
    """Returns a list of warnings; raises IngestError to reject."""
    ext, warns = ext_of(name), []
    head = data[:8]
    if head.startswith((b"MZ", b"\x7fELF", b"#!")): raise IngestError("executable content is not accepted")
    if ext in (".docx", ".pptx", ".xlsx", ".potx"):
        try: z = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as e: raise IngestError("not a valid Office file") from e
        names = [n.lower() for n in z.namelist()]
        if any("vbaproject" in n or n.endswith((".exe", ".dll", ".scr", ".js", ".vbs")) for n in names):
            raise IngestError("file contains macros or executable parts and was rejected")
        if any("activex" in n or "oleobject" in n for n in names): raise IngestError("file embeds OLE/ActiveX objects and was rejected")
        ct = z.read("[Content_Types].xml").decode("utf-8", "replace").lower() if "[Content_Types].xml" in z.namelist() else ""
        if "macroenabled" in ct: raise IngestError("macro-enabled file rejected")
        ext_rel = 0
        for n in z.namelist():
            if n.endswith(".rels") and z.getinfo(n).file_size < 2_000_000:
                ext_rel += len(re.findall(rb'TargetMode="External"', z.read(n)))
        if ext_rel: warns.append(f"{ext_rel} external link(s) inside the file were ignored, never followed")
    elif ext == ".pdf":
        low = data[:5_000_000]
        if re.search(rb"/(JavaScript|JS|Launch|RichMedia)\b", low): raise IngestError("PDF contains active content (JavaScript/Launch) and was rejected")
        if b"/EmbeddedFile" in low: warns.append("PDF has embedded files; they are not opened")
    elif ext in IMAGE_EXT:
        try:
            from PIL import Image
            Image.MAX_IMAGE_PIXELS = 50_000_000
            im = Image.open(io.BytesIO(data)); im.verify()
        except Exception as e: raise IngestError("image could not be verified") from e
    av = shutil.which("clamscan") or shutil.which("clamdscan")
    if av:
        with tempfile.NamedTemporaryFile(suffix=ext) as tf:
            tf.write(data); tf.flush()
            r = subprocess.run([av, "--no-summary", tf.name], capture_output=True, timeout=60)
            if r.returncode == 1: raise IngestError("antivirus flagged this file")
            if r.returncode == 0: warns.append("antivirus scan clean")
    else:
        warns.append("no antivirus installed; structural checks only")
    return warns


INJECTION = re.compile(
    r"(?i)(ignore (?:all |any |the )?(?:previous|prior|above|earlier) (?:instructions|prompts?|rules)|disregard (?:the |all |your )?(?:above|previous|instructions|rules)|"
    r"you are now\b|new instructions:|system prompt|\bact as (?:an? )?(?:admin|root|developer)|do not (?:tell|inform|mention to) the user|"
    r"reveal (?:your|the) (?:prompt|instructions|system)|<\s*/?system\s*>|\[\s*system\s*\]|begin system|override (?:the )?(?:safety|rules)|"
    r"(?:send|post|upload|email|exfiltrate) [^.\n]{0,60}(?:to|at) (?:https?://|\S+@\S+)|print (?:your|all) (?:secrets?|keys?|credentials))")


def injection_flags(text: str):
    return [{"snippet": m.group(0)[:100], "pos": m.start()} for m in INJECTION.finditer(text or "")][:20]


def neutralise(text: str) -> str:
    """Drops every line holding instruction-like text. Applied when sources are chunked, so neither a model
    prompt nor the rule-based drafting can ever carry it into a slide. The stored original stays viewable."""
    return "\n".join(l for l in (text or "").splitlines() if not INJECTION.search(l))


# --------------------------------------------------------------- redaction
def _luhn(num: str):
    d = [int(c) for c in num if c.isdigit()]
    if not 13 <= len(d) <= 19: return False
    s = 0
    for i, x in enumerate(reversed(d)):
        if i % 2: x = x * 2 - 9 if x * 2 > 9 else x * 2
        s += x
    return s % 10 == 0


PATTERNS = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")),
    ("api-key", re.compile(r"\b(?:sk-[A-Za-z0-9_\-]{16,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{30,}|xox[abprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_\-]{30,})\b")),
    ("credential", re.compile(r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|token)\s*[:=]\s*\S{6,}")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,4})?\b")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("phone", re.compile(r"(?<!\d)(?:\+\d{1,3}[ .-]?)?(?:\(\d{2,4}\)[ .-]?|\d{2,4}[ .-])\d{3,4}[ .-]\d{3,4}(?!\d)")),
]
CARD = re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)")


def redact(text: str, kinds=None):
    """Returns (redacted_text, counts). kinds=None means all."""
    counts, out = {}, text or ""
    def sub(name, rx, fn=None):
        nonlocal out
        def r(m):
            if fn and not fn(m.group(0)): return m.group(0)
            counts[name] = counts.get(name, 0) + 1
            return f"[REDACTED {name.upper()}]"
        out = rx.sub(r, out)
    if kinds is None or "card" in kinds: sub("card", CARD, _luhn)
    for name, rx in PATTERNS:
        if kinds is None or name in kinds: sub(name, rx)
    return out, counts


def find_sensitive(text: str):
    _, c = redact(text)
    return c
