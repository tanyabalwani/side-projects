"""Turn uploaded files / pasted text / links into plain text — defensively.
Allow-listed extensions, size caps, zip-bomb checks, and an SSRF-safe URL fetcher
(public IPs only, DNS pinned, redirects re-validated, size/time capped)."""
import html, http.client, io, ipaddress, os, re, socket, ssl, zipfile
from urllib.parse import urlsplit, urljoin

MAX_UPLOAD = 25 * 1024 * 1024
MAX_TEXT = 400_000
TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".tsv", ".log", ".rst"}
ALLOWED_EXT = TEXT_EXT | {".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm"}
MAX_FETCH = 5 * 1024 * 1024
ALLOW_PRIVATE = os.environ.get("CLARITY_ALLOW_PRIVATE_LINKS") == "1"


class IngestError(Exception): pass


def safe_name(name: str) -> str:
    name = os.path.basename(str(name or "").replace("\\", "/"))
    name = re.sub(r"[^\w.\- ()]", "_", name, flags=re.UNICODE).strip(" .")[:120]
    return name or "file"


def ext_of(name): return os.path.splitext(name.lower())[1]


def _zip_guard(data: bytes):
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise IngestError("not a valid Office file") from e
    total = 0
    infos = z.infolist()
    if len(infos) > 5000: raise IngestError("archive has too many entries")
    for i in infos:
        total += i.file_size
        if i.filename.startswith("/") or ".." in i.filename.split("/"): raise IngestError("unsafe archive path")
        if i.compress_size and i.file_size / max(i.compress_size, 1) > 200 and i.file_size > 1_000_000:
            raise IngestError("suspicious compression ratio")
    if total > 200 * 1024 * 1024: raise IngestError("archive expands too large")
    return z


def _decode(b: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "latin-1"):
        try: return b.decode(enc)
        except UnicodeError: continue
    return b.decode("utf-8", "replace")


def _html_to_text(raw: str):
    title = ""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(raw, "lxml") if _has_lxml() else BeautifulSoup(raw, "html.parser")
        title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
        for t in soup(["script", "style", "noscript", "nav", "footer", "header", "form", "svg", "iframe"]): t.decompose()
        lines = []
        for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "td", "th", "pre", "blockquote"]):
            t = " ".join(el.get_text(" ", strip=True).split())
            if not t: continue
            lines.append(("#" * min(int(el.name[1]), 4) + " " + t) if el.name[0] == "h" and len(el.name) == 2 else t)
        return title, "\n".join(lines)
    except ImportError:
        m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
        title = html.unescape(m.group(1)).strip() if m else ""
        raw = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", raw)
        raw = re.sub(r"(?s)<[^>]+>", "\n", raw)
        return title, "\n".join(l.strip() for l in html.unescape(raw).splitlines() if l.strip())


def _has_lxml():
    try:
        import lxml  # noqa
        return True
    except ImportError:
        return False


def extract_text(filename: str, data: bytes) -> str:
    ext = ext_of(filename)
    if ext not in ALLOWED_EXT: raise IngestError(f"file type {ext or '(none)'} is not supported")
    if len(data) > MAX_UPLOAD: raise IngestError("file too large")
    if ext in TEXT_EXT:
        text = _decode(data)
    elif ext in (".html", ".htm"):
        t, body = _html_to_text(_decode(data)); text = (f"# {t}\n" if t else "") + body
    elif ext == ".pdf":
        if not data.startswith(b"%PDF"): raise IngestError("not a PDF")
        from pypdf import PdfReader
        try:
            r = PdfReader(io.BytesIO(data))
            if r.is_encrypted: raise IngestError("encrypted PDFs are not supported")
            text = "\n\n".join((pg.extract_text() or "") for pg in r.pages[:300])
        except IngestError: raise
        except Exception as e: raise IngestError("could not read PDF") from e
    elif ext == ".docx":
        _zip_guard(data)
        import docx
        try:
            d = docx.Document(io.BytesIO(data))
        except Exception as e: raise IngestError("could not read DOCX") from e
        lines = []
        for p in d.paragraphs:
            t = p.text.strip()
            if not t: continue
            sn = (p.style.name or "") if p.style is not None else ""
            m = re.match(r"Heading (\d)", sn)
            lines.append(("#" * int(m.group(1)) + " " + t) if m else ("# " + t if sn == "Title" else t))
        for tb in d.tables:
            for row in tb.rows: lines.append(" | ".join(c.text.strip() for c in row.cells))
        text = "\n".join(lines)
    elif ext == ".pptx":
        _zip_guard(data)
        from pptx import Presentation
        try:
            prs = Presentation(io.BytesIO(data))
        except Exception as e: raise IngestError("could not read PPTX") from e
        parts = []
        for i, s in enumerate(prs.slides, 1):
            parts.append(f"## Slide {i}")
            for sh in s.shapes:
                if sh.has_text_frame and sh.text_frame.text.strip(): parts.append(sh.text_frame.text.strip())
            if s.has_notes_slide and s.notes_slide.notes_text_frame.text.strip():
                parts.append("Notes: " + s.notes_slide.notes_text_frame.text.strip())
        text = "\n".join(parts)
    elif ext == ".xlsx":
        _zip_guard(data)
        import openpyxl
        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as e: raise IngestError("could not read XLSX") from e
        parts = []
        for ws in wb.worksheets[:12]:
            parts.append(f"## Sheet {ws.title}")
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i >= 2000: break
                cells = ["" if c is None else str(c) for c in row]
                if any(cells): parts.append(" | ".join(cells))
        text = "\n".join(parts)
    else:
        raise IngestError("unsupported")
    text = re.sub(r"\x00", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text: raise IngestError("no readable text found")
    return text[:MAX_TEXT]


# ---------------- SSRF-safe link fetching ----------------
def _public_ips(host: str, port: int):
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise IngestError("could not resolve host") from e
    ips = []
    for fam, _, _, _, sa in infos:
        ip = ipaddress.ip_address(sa[0].split("%")[0])
        if not ALLOW_PRIVATE and (not ip.is_global or ip.is_multicast):
            raise IngestError("link points to a private or local address — blocked")
        ips.append((fam, sa[0]))
    if not ips: raise IngestError("could not resolve host")
    return ips


def check_url(url: str):
    u = urlsplit(url.strip())
    if u.scheme not in ("http", "https") or not u.hostname: raise IngestError("only http(s) links are allowed")
    if u.username or u.password: raise IngestError("links with embedded credentials are not allowed")
    port = u.port or (443 if u.scheme == "https" else 80)
    if port not in (80, 443, 8080, 8443) and not ALLOW_PRIVATE: raise IngestError("unusual port blocked")
    return u, port


def _connect_pinned(u, port):
    fam, ip = _public_ips(u.hostname, port)[0]
    sock = socket.socket(fam, socket.SOCK_STREAM); sock.settimeout(12)
    sock.connect((ip, port))
    if u.scheme == "https":
        ctx = ssl.create_default_context()
        sock = ctx.wrap_socket(sock, server_hostname=u.hostname)
    conn = http.client.HTTPConnection(u.hostname, port, timeout=12)
    conn.sock = sock
    return conn


def fetch_url(url: str):
    """Returns (display_name, text)."""
    for _ in range(4):
        u, port = check_url(url)
        conn = _connect_pinned(u, port)
        try:
            path = (u.path or "/") + (("?" + u.query) if u.query else "")
            conn.request("GET", path, headers={"Host": u.netloc.split("@")[-1], "User-Agent": "Clarity/1.0 (local)",
                                               "Accept": "text/html,text/plain,application/pdf;q=0.8", "Accept-Encoding": "identity"})
            r = conn.getresponse()
            if r.status in (301, 302, 303, 307, 308):
                loc = r.getheader("Location")
                if not loc: raise IngestError("bad redirect")
                url = urljoin(url, loc); continue
            if r.status != 200: raise IngestError(f"server returned {r.status}")
            ctype = (r.getheader("Content-Type") or "").split(";")[0].strip().lower()
            body = r.read(MAX_FETCH + 1)
            if len(body) > MAX_FETCH: raise IngestError("page too large")
        finally:
            conn.close()
        host = u.hostname
        if ctype == "application/pdf": return host, extract_text("x.pdf", body)
        if ctype in ("text/plain", "text/markdown", "text/csv"): return host, extract_text("x.txt", body)
        if ctype in ("text/html", "application/xhtml+xml", ""):
            t, text = _html_to_text(_decode(body))
            if not text.strip(): raise IngestError("no readable text on page")
            return (t or host)[:120], ((f"# {t}\n" if t else "") + text)[:MAX_TEXT]
        raise IngestError(f"unsupported content type {ctype}")
    raise IngestError("too many redirects")
