"""Deliverables: editable PPTX (template-aware, native charts/tables), DOCX brief, Markdown, HTML deck.
Text that does not fit is reported, never silently shrunk below a readable size."""
import copy, io, math, re, zipfile, html as _html
from lxml import etree
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION
from pptx.enum.dml import MSO_THEME_COLOR
from pptx.enum.shapes import MSO_SHAPE, PP_PLACEHOLDER
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt, Emu
import safety, style, store

EMU = 914400
PH = PP_PLACEHOLDER


# ------------------------------------------------------------------ helpers shared by all formats
def redacted(p):
    """Copy of the project with sensitive strings masked. Used when security.redact_export is on."""
    q = copy.deepcopy(p)
    r = lambda t: safety.redact(t)[0]
    for s in q["slides"]:
        s["title"], s["takeaway"], s["notes"], s["quote"] = r(s["title"]), r(s["takeaway"]), r(s["notes"]), r(s["quote"])
        for b in s["bullets"]: b["text"] = r(b["text"])
    q["storyline"]["exec_summary"] = r(q["storyline"]["exec_summary"])
    return q


def marking(p):
    sec = p["security"]
    parts = [sec["classification"].upper()] + ([sec["legal"]] if sec["legal"] else [])
    return " · ".join(parts)


def derive_columns(s):
    groups, cur = [], None
    for b in s["bullets"]:
        if b["level"] == 0: cur = {"head": b["text"], "items": []}; groups.append(cur)
        elif cur is not None: cur["items"].append(b["text"])
    if len(groups) >= 2 and any(g["items"] for g in groups): return groups[:3]
    flat = [b["text"] for b in s["bullets"]]
    if s["layout"] == "before_after": h = ["Before", "After"]
    else: h = ["Option A", "Option B"]
    half = math.ceil(len(flat) / 2)
    return [{"head": h[0], "items": flat[:half]}, {"head": h[1], "items": flat[half:]}]


def derive_steps(s):
    out = []
    for b in s["bullets"]:
        if b["level"] != 0: continue
        m = re.match(r"^((?:Q[1-4]\s*)?(?:19|20)\d\d|Q[1-4]|Phase \d+|Step \d+|Month \d+|Week \d+)\s*[:\-]\s*(.+)$", b["text"], re.I)
        out.append({"head": m.group(1) if m else f"Step {len(out) + 1}", "text": m.group(2) if m else b["text"]})
    return out[:6]


def derive_cards(s):
    out = []
    for b in s["bullets"]:
        if b["level"] != 0: continue
        m = re.match(r"^([^:]{2,40}):\s*(.+)$", b["text"])
        out.append({"lead": m.group(1) if m else "", "text": m.group(2) if m else b["text"]})
    return out[:6]


def chart_pairs(s):
    out = []
    for b in s["bullets"]:
        m = re.match(r"^(.{2,40}?)\s*[:=]\s*([$€£]?)(-?\d[\d,]*(?:\.\d+)?)\s*(%|[A-Za-z]{0,12})?\s*$", b["text"].strip())
        if m: out.append((m.group(1).strip(), float(m.group(3).replace(",", "")), (m.group(2) + (m.group(4) or "")).strip()))
    return out


def derive_actions(s):
    rows = []
    for b in s["bullets"]:
        if b["level"] != 0: continue
        t, owner, due = b["text"], "", ""
        if "|" in t:
            parts = [x.strip() for x in t.split("|")]; t = parts[0]; owner = parts[1] if len(parts) > 1 else ""; due = parts[2] if len(parts) > 2 else ""
        else:
            m = re.search(r"\(([^)]{2,40})\)", t)
            if m: owner = m.group(1); t = t.replace(m.group(0), "").strip()
            m = re.search(r",?\s*(?:by|due)\s+(.+)$", t, re.I)
            if m: due = m.group(1); t = t[:m.start()].strip()
        rows.append((t, owner, due))
    return rows[:8]


def src_line(s):
    names = []
    for r in s["sources"]:
        if r["name"] not in names: names.append(r["name"])
    return ("Sources: " + "; ".join(names[:4])) if names else ""


def notes_text(s):
    parts = [s["notes"]]
    if s["transition"]: parts.append("Transition: " + s["transition"])
    if s["facilitation"]: parts.append("Facilitation: " + s["facilitation"])
    if s["sources"]: parts.append(src_line(s))
    ai_n = [b["text"] for b in s["bullets"] if b["origin"] == "ai"]
    if ai_n: parts.append("AI-suggested, not sourced: " + " | ".join(ai_n))
    return "\n\n".join(x for x in parts if x)


# ------------------------------------------------------------------ template analysis
def normalize_template(data: bytes) -> bytes:
    """Accepts .pptx/.potx bytes; returns a .pptx python-pptx can open."""
    zin = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for it in zin.infolist():
            b = zin.read(it.filename)
            if it.filename == "[Content_Types].xml":
                b = b.replace(b"presentationml.template.main+xml", b"presentationml.presentation.main+xml")
            zout.writestr(it, b)
    prs = Presentation(io.BytesIO(out.getvalue()))
    if not len(prs.slide_layouts): raise ValueError("template has no layouts")
    return out.getvalue()


def _theme(prs):
    try:
        m = prs.slide_masters[0]
        for rel in m.part.rels.values():
            if rel.reltype.endswith("/theme"):
                x = etree.fromstring(rel.target_part.blob)
                ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
                cols = {}
                for name in ("dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6"):
                    el = x.find(f".//a:clrScheme/a:{name}", ns)
                    if el is not None and len(el):
                        c = el[0]; cols[name] = "#" + (c.get("val") if c.tag.endswith("srgbClr") else c.get("lastClr", "000000"))
                fonts = {k: (x.find(f".//a:fontScheme/a:{k}Font/a:latin", ns).get("typeface")) for k in ("major", "minor") if x.find(f".//a:fontScheme/a:{k}Font/a:latin", ns) is not None}
                return cols, fonts
    except Exception: pass
    return {}, {}


def analyze_template(data: bytes):
    prs = Presentation(io.BytesIO(data))
    cols, fonts = _theme(prs)
    layouts, logos, legal = [], 0, []
    for sh in prs.slide_masters[0].shapes:
        if sh.shape_type == 13: logos += 1
        if sh.has_text_frame and re.search(r"(?i)confidential|©|copyright|all rights reserved|proprietary", sh.text_frame.text): legal.append(sh.text_frame.text.strip()[:140])
    for i, lo in enumerate(prs.slide_layouts):
        types = [ph.placeholder_format.type for ph in lo.placeholders]
        has = lambda *t: any(x in types for x in t)
        n = lo.name or f"Layout {i + 1}"
        pics = sum(1 for sh in lo.shapes if sh.shape_type == 13); logos += pics
        for sh in lo.shapes:
            if sh.has_text_frame and not sh.is_placeholder and re.search(r"(?i)confidential|©|copyright|all rights reserved", sh.text_frame.text): legal.append(sh.text_frame.text.strip()[:140])
        if has(PH.CENTER_TITLE) or (has(PH.SUBTITLE) and has(PH.TITLE) and not has(PH.BODY, PH.OBJECT)): kind = "title"
        elif re.search(r"(?i)section|divider", n): kind = "section"
        elif has(PH.TITLE) and has(PH.BODY, PH.OBJECT): kind = "content"
        elif not has(PH.TITLE) and not has(PH.BODY, PH.OBJECT): kind = "blank"
        else: kind = "other"
        layouts.append({"index": i, "name": n, "kind": kind, "has_footer": has(PH.FOOTER), "has_number": has(PH.SLIDE_NUMBER), "placeholders": len(types)})
    pick = lambda kind, pat: next((l["name"] for l in layouts if l["kind"] == kind and re.search(pat, l["name"], re.I)), next((l["name"] for l in layouts if l["kind"] == kind), ""))
    return {"size": [round(prs.slide_width / EMU, 2), round(prs.slide_height / EMU, 2)], "colors": cols, "fonts": fonts, "layouts": layouts[:40],
            "logos": logos, "legal_found": list(dict.fromkeys(legal))[:3],
            "defaults": {"title_layout": pick("title", r"title slide"), "content_layout": pick("content", r"title and content")}}


# ------------------------------------------------------------------ PPTX
def rgb(h): return RGBColor(int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16))
def blend(h, f):
    r, g, b = (int(h[i:i + 2], 16) for i in (1, 3, 5)); return "#%02X%02X%02X" % tuple(int(c + (255 - c) * f) for c in (r, g, b))


class Ctx:
    def __init__(self, p, prs, template):
        self.p, self.prs, self.t, self.issues = p, prs, template, []
        self.W, self.H = prs.slide_width / EMU, prs.slide_height / EMU
        self.accent = p["theme"]["accent"]; self.font = None if template else p["theme"]["font"]
        self.cur = ""

    def flag(self, what):
        self.issues.append({"slide_id": self.cur, "message": f"{what} does not fit this layout at a readable size."})

    def fit(self, text, w, h, mx, mn, what, cpl_factor=0.52):
        pt = mx
        while pt >= mn:
            cpl = max(4, int(w * 72 / (pt * cpl_factor)))
            lines = sum(max(1, math.ceil(len(l) / cpl)) for l in (text.split("\n") if text else [""]))
            if lines * pt * 1.25 / 72 <= h: return pt
            pt -= 1
        self.flag(what); return mn

    def color(self, c, kind):
        if self.t:
            if kind == "accent": c.theme_color = MSO_THEME_COLOR.ACCENT_1
            elif kind == "white": c.theme_color = MSO_THEME_COLOR.BACKGROUND_1
            elif kind == "muted": c.theme_color = MSO_THEME_COLOR.TEXT_1; c.brightness = 0.4
            elif kind == "tint": c.theme_color = MSO_THEME_COLOR.ACCENT_1; c.brightness = 0.85
            elif kind == "light": c.theme_color = MSO_THEME_COLOR.BACKGROUND_1; c.brightness = -0.06
            else: c.theme_color = MSO_THEME_COLOR.TEXT_1
        else:
            c.rgb = rgb({"accent": self.accent, "white": "#FFFFFF", "muted": "#6B7280", "tint": blend(self.accent, 0.88), "light": "#F3F4F6"}.get(kind, "#1F2937"))


def run(ctx, r, size, bold=False, color="text", italic=False):
    f = r.font; f.size = Pt(size); f.bold = bold; f.italic = italic
    if ctx.font: f.name = ctx.font
    ctx.color(f.color, color)


def box(ctx, sl, x, y, w, h, kind="tint", shape=MSO_SHAPE.RECTANGLE):
    sh = sl.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    sh.fill.solid(); ctx.color(sh.fill.fore_color, kind); sh.line.fill.background(); sh.shadow.inherit = False
    return sh


def text(ctx, sl, x, y, w, h, t, size, bold=False, color="text", align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, italic=False, shape=None, what="Text", mn=12):
    sh = shape or sl.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if shape is not None: w, h = shape.width / EMU, shape.height / EMU
    tf = sh.text_frame; tf.word_wrap = True; tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(0.08); tf.margin_top = tf.margin_bottom = Inches(0.04)
    pt = ctx.fit(t, w - 0.16, h - 0.08, size, min(mn, size), what)
    p = tf.paragraphs[0]; p.alignment = align
    r = p.add_run(); r.text = t; run(ctx, r, pt, bold, color, italic)
    return sh


def bullets_tf(ctx, tf, items, w, h, mx=24, mn=14, color="text", placeholder=False):
    flat = "\n".join(("   " if b["level"] else "") + b["text"] for b in items)
    pt = ctx.fit(flat, w - 0.4, h - 0.1, mx, mn, "Body text", 0.55)
    tf.word_wrap = True
    first = True
    for b in items:
        p = tf.paragraphs[0] if first else tf.add_paragraph(); first = False
        p.level = b["level"]
        if not placeholder: p.alignment = PP_ALIGN.LEFT
        if placeholder:
            r = p.add_run(); r.text = b["text"]; r.font.size = Pt(pt - (2 if b["level"] else 0))
        else:
            r = p.add_run(); r.text = b["text"]; run(ctx, r, pt - (2 if b["level"] else 0), False, color)
            pPr = p._p.get_or_add_pPr(); ind = 0.28 + 0.3 * b["level"]
            pPr.set("marL", str(int(Inches(ind)))); pPr.set("indent", str(-int(Inches(0.25))))
            bu = etree.SubElement(pPr, qn("a:buChar")); bu.set("char", "•" if not b["level"] else "–")
            p.space_after = Pt(8)


def slide_number(ctx, sl, x, y, w):
    tb = sl.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(0.3))
    p = tb.text_frame.paragraphs[0]; p.alignment = PP_ALIGN.RIGHT
    fld = etree.SubElement(p._p, qn("a:fld")); fld.set("id", "{B6F15528-21DE-4FAA-801E-634DDDAF4B2B}"); fld.set("type", "slidenum")
    rpr = etree.SubElement(fld, qn("a:rPr")); rpr.set("lang", "en-US"); rpr.set("sz", "1000")
    etree.SubElement(fld, qn("a:t")).text = "‹#›"


def layout_by_name(prs, name):
    return next((l for l in prs.slide_layouts if l.name == name), None)


def clone_ph(sl, layout, types):
    for sh in layout.placeholders:
        if sh.placeholder_format.type in types:
            sl.shapes._spTree.append(copy.deepcopy(sh._element))


def remove_unused(sl, keep):
    for ph in list(sl.placeholders):
        if ph.placeholder_format.idx not in keep and ph.placeholder_format.type not in (PH.SLIDE_NUMBER, PH.FOOTER, PH.DATE):
            ph._element.getparent().remove(ph._element)


def build_pptx(p, template_bytes=None, watermark=True):
    """Returns (bytes, fit_issues)."""
    q = redacted(p) if p["security"]["redact_export"] else p
    template = bool(template_bytes)
    prs = Presentation(io.BytesIO(template_bytes)) if template else Presentation()
    if template:
        lst = prs.slides._sldIdLst
        for sid in list(lst): prs.part.drop_rel(sid.rId); lst.remove(sid)
        tcfg = p["template"] or {}
        approved = set(tcfg.get("approved") or [l.name for l in prs.slide_layouts])
        t_lo = layout_by_name(prs, tcfg.get("title_layout", "")) or prs.slide_layouts[0]
        c_lo = layout_by_name(prs, tcfg.get("content_layout", "")) or (prs.slide_layouts[1] if len(prs.slide_layouts) > 1 else prs.slide_layouts[0])
    else:
        prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
        blank = prs.slide_layouts[6]
    ctx = Ctx(q, prs, template)
    mark = marking(q); W, H = ctx.W, ctx.H
    for idx, s in enumerate(q["slides"], 1):
        ctx.cur = s["id"]
        lo = None
        if template:
            if s["kind"] == "title": lo = t_lo
            else:
                lo = layout_by_name(prs, s["override_layout"]) if s["override_layout"] in approved else None
                lo = lo or c_lo
        else: lo = blank
        sl = prs.slides.add_slide(lo)
        # ---------------- title slide
        if s["kind"] == "title":
            if template:
                if sl.shapes.title is not None: sl.shapes.title.text_frame.text = s["title"]
                sub = next((ph for ph in sl.placeholders if ph.placeholder_format.type == PH.SUBTITLE), None)
                keep = {0}
                if sub is not None and s["takeaway"]: sub.text_frame.text = s["takeaway"]; keep.add(sub.placeholder_format.idx)
                remove_unused(sl, keep | {ph.placeholder_format.idx for ph in sl.placeholders if ph.placeholder_format.type in (PH.CENTER_TITLE, PH.TITLE)})
            else:
                bg = box(ctx, sl, 0, 0, W, H, "accent")
                text(ctx, sl, 0.9, 2.3, W - 1.8, 1.8, s["title"], 44, True, "white", anchor=MSO_ANCHOR.BOTTOM, what="Title", mn=28)
                if s["takeaway"]: text(ctx, sl, 0.9, 4.25, W - 1.8, 0.8, s["takeaway"], 20, False, "white", what="Subtitle")
                text(ctx, sl, 0.9, H - 0.8, W - 1.8, 0.4, mark, 11, False, "white")
        else:
            # ---------------- content slide frame
            if template:
                ttl = sl.shapes.title
                if ttl is not None:
                    ttl.text_frame.text = s["title"]
                    pt = ctx.fit(s["title"], ttl.width / EMU - 0.2, ttl.height / EMU, 34, 22, "Headline", 0.5)
                    for r_ in ttl.text_frame.paragraphs[0].runs: r_.font.size = Pt(min(pt, r_.font.size.pt if r_.font.size else pt))
                body = next((ph for ph in sl.placeholders if ph.placeholder_format.type in (PH.BODY, PH.OBJECT) and ph.placeholder_format.idx != 0), None)
                if body is not None: fx, fy, fw, fh = body.left / EMU, body.top / EMU, body.width / EMU, body.height / EMU
                else:
                    tb = (ttl.top + ttl.height) / EMU if ttl is not None else 1.5
                    fx, fy, fw, fh = 0.7, tb + 0.2, W - 1.4, H - tb - 1.1
            else:
                box(ctx, sl, 0, 0.5, 0.14, 0.95, "accent")
                text(ctx, sl, 0.55, 0.4, W - 1.1, 1.2, s["title"], 30, True, "text", anchor=MSO_ANCHOR.MIDDLE, what="Headline", mn=22)
                fx, fy, fw, fh = 0.7, 1.8, W - 1.4, H - 1.8 - 0.95
                body = None
                text(ctx, sl, 0.7, H - 0.5, W - 3.0, 0.3, (q["name"] + "  ·  " + mark)[:120], 10, False, "muted", what="Footer", mn=9)
                slide_number(ctx, sl, W - 1.6, H - 0.5, 0.9)
            srcs = src_line(s)
            if srcs and s["kind"] not in ("sources",): fh -= 0.3
            kinds_with_bar = s["layout"] not in ("key_message", "recommendation", "decision", "quote", "appendix", "bullets") or (s["layout"] in ("bullets",) and False)
            bar = s["takeaway"] and s["layout"] not in ("key_message", "recommendation", "decision", "quote") and s["kind"] != "appendix" and not (s["layout"] == "data" and len(chart_pairs(s)) >= 2)
            if bar: fh -= 0.85
            lay = s["layout"]; vis = lay not in ("bullets", "appendix")
            # --------- renderers
            if not vis:
                small = s["kind"] in ("appendix", "sources")
                if body is not None:
                    body.left, body.top, body.width, body.height = Inches(fx), Inches(fy), Inches(fw), Inches(fh)
                    tf = body.text_frame; tf.clear(); bullets_tf(ctx, tf, s["bullets"], fw, fh, 16 if small else 24, 11 if small else 14, placeholder=True)
                else:
                    tb = sl.shapes.add_textbox(Inches(fx), Inches(fy), Inches(fw), Inches(fh)); bullets_tf(ctx, tb.text_frame, s["bullets"], fw, fh, 16 if small else 24, 11 if small else 14)
            else:
                if body is not None: body._element.getparent().remove(body._element)
                _visual(ctx, sl, s, fx, fy, fw, fh)
            if bar:
                box(ctx, sl, fx, fy + fh + 0.1, 0.08, 0.65, "accent")
                b = box(ctx, sl, fx + 0.08, fy + fh + 0.1, fw - 0.08, 0.65, "tint")
                text(ctx, sl, 0, 0, 0, 0, s["takeaway"], 18, True, "text", anchor=MSO_ANCHOR.MIDDLE, shape=b, what="Takeaway", mn=13)
            if srcs and s["kind"] != "sources":
                text(ctx, sl, fx, fy + fh + (0.8 if bar else 0.05), fw, 0.28, srcs, 10, False, "muted", what="Source line", mn=9)
            if template:
                remove_unused(sl, {0} | ({body.placeholder_format.idx} if (body is not None and not vis) else set()))
                clone_ph(sl, lo, {PH.SLIDE_NUMBER})
                if mark:
                    clone_ph(sl, lo, {PH.FOOTER})
                    for ph in sl.placeholders:
                        if ph.placeholder_format.type == PH.FOOTER: ph.text_frame.text = mark[:120]
        # ---------------- watermark + notes
        if watermark and q["security"]["watermark"]:
            wm = sl.shapes.add_textbox(Inches(W * 0.15), Inches(H * 0.38), Inches(W * 0.7), Inches(1.2))
            pp = wm.text_frame.paragraphs[0]; pp.alignment = PP_ALIGN.CENTER
            r_ = pp.add_run(); r_.text = q["security"]["watermark"]; r_.font.size = Pt(60); r_.font.bold = True; r_.font.color.rgb = RGBColor(0xD9, 0xD9, 0xD9)
            wm.rotation = -20
            sl.shapes._spTree.remove(wm._element); sl.shapes._spTree.insert(2, wm._element)
        n = notes_text(s)
        if n: sl.notes_slide.notes_text_frame.text = n
    bio = io.BytesIO(); prs.save(bio)
    return bio.getvalue(), ctx.issues


def _visual(ctx, sl, s, x, y, w, h):
    lay = s["layout"]
    if lay in ("key_message", "recommendation", "decision"):
        stmt = s["takeaway"] or (s["bullets"][0]["text"] if s["bullets"] else "")
        if stmt.strip().lower() == s["title"].strip().lower(): stmt = ""
        rest = [b for b in s["bullets"] if b["text"] != stmt][:4]
        if not stmt and not rest: return
        if lay == "key_message":
            box(ctx, sl, x, y, 0.1, h, "accent")
            text(ctx, sl, x + 0.2, y, w * 0.48, h, stmt, 32, True, "text", anchor=MSO_ANCHOR.MIDDLE, what="Key message", mn=20)
            ry = y; rh = h / max(1, len(rest)) - 0.12
            for b in rest:
                bx = box(ctx, sl, x + w * 0.54, ry, w * 0.46, rh, "tint")
                text(ctx, sl, 0, 0, 0, 0, b["text"], 18, False, "text", anchor=MSO_ANCHOR.MIDDLE, shape=bx, what="Supporting point", mn=12)
                ry += rh + 0.12
        else:
            top = box(ctx, sl, x, y, w, min(1.5, h * 0.38), "accent")
            text(ctx, sl, 0, 0, 0, 0, stmt, 26, True, "white", anchor=MSO_ANCHOR.MIDDLE, shape=top, what="Recommendation", mn=18)
            n = max(1, len(rest)); cw = (w - 0.2 * (n - 1)) / n; cy = y + min(1.5, h * 0.38) + 0.25
            for i, b in enumerate(rest):
                bx = box(ctx, sl, x + i * (cw + 0.2), cy, cw, h - (cy - y), "tint")
                text(ctx, sl, 0, 0, 0, 0, b["text"], 18, False, "text", anchor=MSO_ANCHOR.TOP, shape=bx, what="Rationale", mn=12)
    elif lay in ("comparison", "before_after", "case"):
        cols = derive_columns(s) if lay != "case" else [{"head": h_, "items": [b["text"]]} for h_, b in zip(["Situation", "Action", "Result"], s["bullets"][:3])]
        n = len(cols); cw = (w - 0.3 * (n - 1)) / n
        for i, c in enumerate(cols):
            cx = x + i * (cw + 0.3)
            hd = box(ctx, sl, cx, y, cw, 0.6, "accent"); text(ctx, sl, 0, 0, 0, 0, c["head"], 20, True, "white", anchor=MSO_ANCHOR.MIDDLE, shape=hd, what="Column heading", mn=14)
            bd = box(ctx, sl, cx, y + 0.6, cw, h - 0.6, "tint")
            tf = bd.text_frame; tf.vertical_anchor = MSO_ANCHOR.TOP; tf.margin_left = tf.margin_right = Inches(0.15); tf.margin_top = Inches(0.15)
            bullets_tf(ctx, tf, [{"text": t, "level": 0} for t in c["items"]], cw, h - 0.6, 20, 13)
    elif lay in ("process", "timeline", "roadmap"):
        st = derive_steps(s) or [{"head": "Step 1", "text": s["title"]}]
        n = len(st); cw = w / n
        if lay == "timeline":
            ln = box(ctx, sl, x, y + 0.55, w, 0.06, "accent")
        for i, c in enumerate(st):
            cx = x + i * cw
            if lay == "timeline":
                dot = box(ctx, sl, cx + cw / 2 - 0.15, y + 0.43, 0.3, 0.3, "accent", MSO_SHAPE.OVAL)
                text(ctx, sl, cx, y - 0.1, cw, 0.4, c["head"], 16, True, "accent", PP_ALIGN.CENTER, what="Date", mn=11)
                text(ctx, sl, cx + 0.05, y + 0.9, cw - 0.1, h - 0.9, c["text"], 18, False, "text", PP_ALIGN.CENTER, what="Milestone", mn=12)
            else:
                ch = box(ctx, sl, cx, y, cw - 0.05, 0.9, "accent", MSO_SHAPE.PENTAGON if i == 0 else MSO_SHAPE.CHEVRON)
                text(ctx, sl, 0, 0, 0, 0, c["head"], 16, True, "white", PP_ALIGN.CENTER, MSO_ANCHOR.MIDDLE, shape=ch, what="Step label", mn=11)
                text(ctx, sl, cx + 0.05, y + 1.1, cw - 0.2, h - 1.1, c["text"], 18, False, "text", what="Step text", mn=12)
    elif lay == "data" and len(chart_pairs(s)) >= 2:
        pairs = chart_pairs(s); unit = next((u for _, _, u in pairs if u), "")
        cd = CategoryChartData(); cd.categories = [a for a, _, _ in pairs]; cd.add_series(unit.lstrip("$€£") or "Value", [v for _, v, _ in pairs])
        gf = sl.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(x), Inches(y), Inches(w * 0.62), Inches(h), cd); ch = gf.chart
        ch.has_legend = False; ch.has_title = False
        pl = ch.plots[0]; pl.has_data_labels = True; pl.data_labels.font.size = Pt(14); pl.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
        pl.data_labels.number_format = '#,##0.##' + ('"%"' if unit == "%" else ""); pl.data_labels.number_format_is_linked = False
        pl.gap_width = 60
        ch.value_axis.has_major_gridlines = False; ch.value_axis.visible = False; ch.category_axis.tick_labels.font.size = Pt(14)
        ch.category_axis.reverse_order = True
        stmt = s["takeaway"] or s["title"]
        text(ctx, sl, x + w * 0.66, y, w * 0.34, h, stmt, 22, True, "text", anchor=MSO_ANCHOR.MIDDLE, what="Chart message", mn=14)
    elif lay == "action_plan":
        rows = derive_actions(s) or [(s["title"], "", "")]
        gf = sl.shapes.add_table(len(rows) + 1, 3, Inches(x), Inches(y), Inches(w), Inches(min(h, 0.6 + 0.6 * len(rows)))); tb = gf.table
        tb.columns[0].width = Inches(w * 0.58); tb.columns[1].width = Inches(w * 0.2); tb.columns[2].width = Inches(w * 0.22)
        for j, hd in enumerate(["Action", "Owner", "Due"]):
            c = tb.cell(0, j); c.text_frame.text = hd; r = c.text_frame.paragraphs[0].runs[0]; r.font.size = Pt(16); r.font.bold = True
        for i, row in enumerate(rows, 1):
            for j, v in enumerate(row):
                c = tb.cell(i, j); c.text_frame.text = v or ("Owner needed" if j == 1 else "Date needed" if j == 2 else "")
                for r in c.text_frame.paragraphs[0].runs: r.font.size = Pt(16 if len(v) < 60 else 14)
    elif lay == "quote":
        qt = s["quote"] or (s["bullets"][0]["text"] if s["bullets"] else s["title"])
        box(ctx, sl, x, y, 0.1, h, "accent")
        text(ctx, sl, x + 0.3, y, w - 0.4, h * 0.75, "“" + qt.strip('"“”') + "”", 32, False, "text", anchor=MSO_ANCHOR.MIDDLE, italic=True, what="Quote", mn=18)
        if s["quote_by"] or len(s["bullets"]) > 1: text(ctx, sl, x + 0.3, y + h * 0.78, w - 0.4, 0.5, (s["quote_by"] or s["bullets"][1]["text"]), 18, False, "muted", what="Attribution", mn=12)
    else:  # framework / summary / data without numbers
        cards = derive_cards(s) or [{"lead": "", "text": s["title"]}]
        n = len(cards); cols_ = n if n <= 3 else math.ceil(n / 2); rows_ = math.ceil(n / cols_)
        gap = 0.25; cw = (w - gap * (cols_ - 1)) / cols_; chh = min(3.4, (h - gap * (rows_ - 1)) / rows_)
        for i, c in enumerate(cards):
            cx = x + (i % cols_) * (cw + gap); cy = y + (i // cols_) * (chh + gap)
            box(ctx, sl, cx, cy, cw, chh, "tint"); box(ctx, sl, cx, cy, cw, 0.08, "accent")
            if lay == "summary":
                badge = box(ctx, sl, cx + 0.15, cy + 0.25, 0.5, 0.5, "accent", MSO_SHAPE.OVAL)
                text(ctx, sl, 0, 0, 0, 0, str(i + 1), 18, True, "white", PP_ALIGN.CENTER, MSO_ANCHOR.MIDDLE, shape=badge, what="Number", mn=12)
                text(ctx, sl, cx + 0.1, cy + 0.85, cw - 0.2, chh - 0.95, c["text"] if not c["lead"] else c["lead"] + ": " + c["text"], 20, True, "text", what="Key argument", mn=13)
            else:
                ty = cy + 0.2
                if c["lead"]:
                    text(ctx, sl, cx + 0.1, ty, cw - 0.2, 0.6, c["lead"], 20, True, "accent", what="Card lead", mn=13); ty += 0.65
                text(ctx, sl, cx + 0.1, ty, cw - 0.2, cy + chh - ty - 0.1, c["text"], 18, False, "text", what="Card text", mn=12)


def check_fit(p):
    tb = None
    return build_pptx(p, None, False)[1]


# ------------------------------------------------------------------ DOCX / Markdown / HTML
def build_docx(p):
    import docx
    from docx.shared import Pt as DPt
    q = redacted(p) if p["security"]["redact_export"] else p
    d = docx.Document()
    d.styles["Normal"].font.name = q["theme"]["font"]; d.styles["Normal"].font.size = DPt(11)
    sec = d.sections[0]
    hp = sec.header.paragraphs[0]; hp.text = marking(q) + (("   ·   " + q["security"]["watermark"]) if q["security"]["watermark"] else "")
    d.add_heading(q["name"], 0)
    thesis = q["storyline"]["thesis"] or q["governing"] or q["brief"]["message"]
    if thesis: d.add_paragraph().add_run(thesis).bold = True
    if q["storyline"]["exec_summary"]: d.add_heading("Executive summary", 1); d.add_paragraph(q["storyline"]["exec_summary"])
    d.add_heading("Key messages", 1)
    for s in q["slides"]:
        if s["kind"] not in ("content", "ask"): continue
        d.add_heading(s["title"], 2)
        for b in s["bullets"]:
            para = d.add_paragraph(style="List Bullet 2" if b["level"] else "List Bullet"); para.add_run(b["text"])
            if b["origin"] == "ai": para.add_run("  [AI suggestion, not sourced]").italic = True
            elif b["cite"]: para.add_run("  [" + ", ".join(b["cite"]) + "]").italic = True
        if s["takeaway"]: d.add_paragraph().add_run("So what: " + s["takeaway"]).bold = True
    if q["facilitation"]["questions"]:
        d.add_heading("Anticipated questions", 1)
        for x in q["facilitation"]["questions"]:
            d.add_paragraph().add_run(x["q"]).bold = True; d.add_paragraph(x["a"])
    d.add_heading("Speaker notes", 1)
    for i, s in enumerate(q["slides"], 1):
        n = notes_text(s)
        if n: d.add_paragraph().add_run(f"Slide {i}: {s['title']}").bold = True; d.add_paragraph(n)
    d.add_heading("Sources", 1)
    seen = {}
    for s in q["slides"]:
        for r in s["sources"]: seen.setdefault(r["name"], r["origin"])
    for n, o in seen.items(): d.add_paragraph(f"{n} ({ {'provided': 'provided by author', 'internal': 'internal knowledge base', 'external': 'external web'}[o] })", style="List Bullet")
    bio = io.BytesIO(); d.save(bio); return bio.getvalue()


def build_md(p):
    q = redacted(p) if p["security"]["redact_export"] else p
    L = [f"> {marking(q)}", "", f"# {q['name']}", ""]
    thesis = q["storyline"]["thesis"] or q["governing"]
    if thesis: L += [f"**{thesis}**", ""]
    if q["storyline"]["exec_summary"]: L += ["## Executive summary", "", q["storyline"]["exec_summary"], ""]
    for i, s in enumerate(q["slides"], 1):
        if s["kind"] == "title": continue
        L += [f"## {i}. {s['title']}", ""]
        for b in s["bullets"]:
            tag = " *(AI suggestion, not sourced)*" if b["origin"] == "ai" else (f" *[{', '.join(b['cite'])}]*" if b["cite"] else "")
            L.append(("  " if b["level"] else "") + "- " + b["text"] + tag)
        if s["takeaway"]: L += ["", f"**So what:** {s['takeaway']}"]
        if s["notes"]: L += ["", f"*Notes:* {s['notes']}"]
        L.append("")
    return "\n".join(L)


def build_html(p):
    q = redacted(p) if p["security"]["redact_export"] else p
    e = _html.escape
    secs = []
    for i, s in enumerate(q["slides"], 1):
        lay, body = s["layout"], ""
        if s["kind"] == "title": body = f"<p class='sub'>{e(s['takeaway'])}</p>"
        elif lay in ("comparison", "before_after"):
            body = "<div class='cols'>" + "".join(f"<div class='col'><h3>{e(c['head'])}</h3><ul>{''.join('<li>'+e(t)+'</li>' for t in c['items'])}</ul></div>" for c in derive_columns(s)) + "</div>"
        elif lay in ("process", "timeline", "roadmap"):
            body = "<div class='cols'>" + "".join(f"<div class='col step'><h3>{e(c['head'])}</h3><p>{e(c['text'])}</p></div>" for c in derive_steps(s)) + "</div>"
        elif lay in ("framework", "summary", "data"):
            body = "<div class='cols'>" + "".join(f"<div class='col'><h3>{e(c['lead'])}</h3><p>{e(c['text'])}</p></div>" for c in derive_cards(s)) + "</div>"
        elif lay == "action_plan":
            body = "<table><tr><th>Action</th><th>Owner</th><th>Due</th></tr>" + "".join(f"<tr><td>{e(a)}</td><td>{e(b)}</td><td>{e(c)}</td></tr>" for a, b, c in derive_actions(s)) + "</table>"
        else:
            body = "<ul>" + "".join(f"<li class='l{b['level']}'>{e(b['text'])}</li>" for b in s["bullets"]) + "</ul>"
        tk = f"<div class='take'>{e(s['takeaway'])}</div>" if s["takeaway"] and s["kind"] != "title" else ""
        secs.append(f"<section><h2>{e(s['title'])}</h2>{body}{tk}<footer>{e(src_line(s))}<span>{i}</span></footer><aside>{e(notes_text(s))}</aside></section>")
    wm = f"<div class='wm'>{e(q['security']['watermark'])}</div>" if q["security"]["watermark"] else ""
    css = ("body{margin:0;font-family:Calibri,Segoe UI,Arial,sans-serif;background:#111;color:#1f2937}section{box-sizing:border-box;width:min(100vw,177vh);aspect-ratio:16/9;margin:2vh auto;background:#fff;padding:5% 6%;position:relative;overflow:hidden}"
           f"h2{{font-size:2.4vw;border-left:.5vw solid {q['theme']['accent']};padding-left:1.2vw;margin:0 0 3vh}}ul{{font-size:1.9vw;line-height:1.4}}.l1{{margin-left:2vw;font-size:1.6vw}}.cols{{display:flex;gap:1.5vw}}.col{{flex:1;background:{blend(q['theme']['accent'], .88)};padding:1.2vw;font-size:1.5vw}}"
           f".col h3{{margin:0 0 1vh;color:{q['theme']['accent']}}}table{{width:100%;border-collapse:collapse;font-size:1.6vw}}th{{background:{q['theme']['accent']};color:#fff;text-align:left}}td,th{{padding:1vh 1vw;border-bottom:1px solid #ddd}}"
           f".take{{position:absolute;left:6%;right:6%;bottom:9%;background:{blend(q['theme']['accent'], .88)};border-left:.5vw solid {q['theme']['accent']};padding:1.2vh 1.5vw;font-weight:700;font-size:1.7vw}}"
           "footer{position:absolute;left:6%;right:6%;bottom:3%;font-size:.9vw;color:#6b7280;display:flex;justify-content:space-between}aside{display:none}.wm{position:fixed;inset:0;display:grid;place-items:center;font-size:12vw;font-weight:800;color:rgba(0,0,0,.07);transform:rotate(-20deg);pointer-events:none}"
           ".mark{position:fixed;top:0;left:0;right:0;background:#222;color:#ddd;font:12px sans-serif;padding:4px 10px;z-index:5}@media print{section{width:100%;margin:0;page-break-after:always}.mark{display:none}}")
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{e(q['name'])}</title><style>{css}</style></head>"
            f"<body><div class='mark'>{e(marking(q))}</div><div style='height:24px'></div>{wm}{''.join(secs)}</body></html>")
