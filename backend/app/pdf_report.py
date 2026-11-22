"""Professional PDF fact-checking report (ReportLab).

The PDF is built only from the saved results (`report.Report`): it never calls Groq or Tavily.
All text that comes from the uploaded PDF or the web is untrusted, so it is stripped of control
characters, escaped before it reaches ReportLab's markup parser, and checked against the embedded
font so a missing glyph can never produce a crash or a blank box. Links are limited to http(s).
"""
import io
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Flowable,
    Frame,
    HRFlowable,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from .report_schemas import Report, ReportClaim
from .verify_schemas import VerdictSource

# ---------------------------------------------------------------- design tokens

NAVY = colors.HexColor("#0f1f4a")
NAVY_SOFT = colors.HexColor("#1f3a85")
SKY = colors.HexColor("#3b82f6")
SKY_LIGHT = colors.HexColor("#93c5fd")
INK = colors.HexColor("#1e293b")
MUTED = colors.HexColor("#64748b")
LINE = colors.HexColor("#e2e8f0")
PANEL = colors.HexColor("#f8fafc")
LINK = colors.HexColor("#1d4ed8")

# status -> (label, strong colour, tint)
STATUS = {
    "VERIFIED": ("Verified", colors.HexColor("#16a34a"), colors.HexColor("#dcfce7")),
    "INACCURATE": ("Inaccurate", colors.HexColor("#ea580c"), colors.HexColor("#ffedd5")),
    "FALSE": ("False", colors.HexColor("#dc2626"), colors.HexColor("#fee2e2")),
    "UNVERIFIED": ("Unverified", colors.HexColor("#64748b"), colors.HexColor("#f1f5f9")),
}
ORDER = ["VERIFIED", "INACCURATE", "FALSE", "UNVERIFIED"]

CATEGORY_LABELS = {
    "statistics": "Statistics",
    "financial": "Financial",
    "date_timeline": "Date / Timeline",
    "market": "Market",
    "scientific": "Scientific",
    "technical": "Technical",
    "company": "Company",
    "demographic": "Demographic",
    "other": "Other",
}

PAGE_W, PAGE_H = A4
MARGIN = 48
CONTENT_W = PAGE_W - 2 * MARGIN
MAX_TEXT = 8000  # safety cap so a pathological value can never exceed a page frame

DISCLAIMER = (
    "This report was generated using automated AI analysis and web-based evidence. Results may be incomplete "
    "or affected by source quality, publication dates, and changing information. Important decisions should be "
    "confirmed using authoritative primary sources."
)

# ---------------------------------------------------------------- fonts

_FONT_DIR = Path(__file__).parent / "assets" / "fonts"
_FONTS = {
    "NotoSans": "NotoSans-Regular.ttf",
    "NotoSans-Bold": "NotoSans-Bold.ttf",
    "NotoSans-Italic": "NotoSans-Italic.ttf",
    "NotoSans-BoldItalic": "NotoSans-BoldItalic.ttf",
}
_glyphs: set[int] = set()
_registered = False


def _register_fonts() -> None:
    """Register Noto Sans (SIL Open Font License, see assets/fonts/OFL.txt) once per process."""
    global _registered
    if _registered:
        return
    for name, file in _FONTS.items():
        pdfmetrics.registerFont(TTFont(name, str(_FONT_DIR / file)))
    pdfmetrics.registerFontFamily(
        "NotoSans", normal="NotoSans", bold="NotoSans-Bold", italic="NotoSans-Italic", boldItalic="NotoSans-BoldItalic"
    )
    _glyphs.update(pdfmetrics.getFont("NotoSans").face.charToGlyph.keys())
    _registered = True


# ---------------------------------------------------------------- safe text

_CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f  ​-‏‪-‮⁠-⁩﻿]")


# Common symbols the embedded font cannot draw, replaced by readable ASCII instead of a "?".
_FALLBACK = {
    "≈": "~", "≃": "~", "≠": "!=", "≤": "<=", "≥": ">=", "→": "->", "←": "<-",
    "↔": "<->", "⇒": "=>", "✓": "[yes]", "✔": "[yes]", "✗": "[no]", "✘": "[no]",
    "•": "-", "●": "*", "▪": "-", "−": "-", " ": " ", " ": " ", " ": " ",
    " ": " ", " ": " ", " ": " ", "™": "(TM)", "®": "(R)", "…": "...",
}


def _glyph_or_fallback(c: str) -> str:
    if c == "\n" or c == "\t" or ord(c) in _glyphs:
        return c
    if c in _FALLBACK:
        return _FALLBACK[c]
    decomposed = unicodedata.normalize("NFKD", c)  # ligatures, full-width forms, circled digits...
    if decomposed != c and decomposed and all(ord(d) in _glyphs for d in decomposed):
        return decomposed
    return "?"


def clean(value: object, limit: int = MAX_TEXT) -> str:
    """Untrusted text -> printable text the embedded font can draw. Common symbols the font lacks get an ASCII
    stand-in (for example '~' for the approximately sign); anything else unsupported becomes '?'."""
    text = unicodedata.normalize("NFC", str(value if value is not None else ""))
    text = _CONTROL.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return "".join(_glyph_or_fallback(c) for c in text)


def markup(value: object, limit: int = MAX_TEXT) -> str:
    """Escaped text for a Paragraph (newlines become line breaks)."""
    return escape(clean(value, limit)).replace("\t", " ").replace("\n", "<br/>")


def safe_url(url: object) -> str | None:
    """Only http(s) URLs with a host may become links."""
    u = re.sub(r"[\s\x00-\x1f\x7f]", "", str(url or ""))
    p = urlparse(u)
    return u if p.scheme in ("http", "https") and p.netloc and len(u) <= 2000 else None


def link(url: str, text: str) -> str:
    """<link> markup. `url` must come from safe_url(); `text` is already escaped markup."""
    return f'<link href="{escape(url, {chr(34): "&quot;"})}" color="#1d4ed8">{text}</link>'


def _has_long_token(text: str, n: int = 28) -> bool:
    return any(len(t) > n for t in clean(text).split())


def category_label(c: str) -> str:
    return CATEGORY_LABELS.get(c, c.replace("_", " ").title())


# ---------------------------------------------------------------- statistics

def _percentages(counts: dict[str, int], total: int) -> dict[str, int]:
    """Whole-number shares that always add up to exactly 100 (largest-remainder method)."""
    if total == 0:
        return {k: 0 for k in counts}
    base = {k: counts[k] * 100 // total for k in counts}
    remainder = {k: counts[k] * 100 % total for k in counts}  # exact integers: no float rounding noise
    short = 100 - sum(base.values())
    for k in sorted(counts, key=lambda k: (remainder[k], counts[k]), reverse=True)[:short]:
        base[k] += 1
    return base


def compute_stats(report: Report) -> dict:
    """Everything the PDF reports, computed from the claim rows. Raises if the rows are inconsistent."""
    claims = report.claims
    counts = {s: sum(1 for c in claims if c.status == s) for s in ORDER}
    pending = sum(1 for c in claims if c.status == "PENDING")
    total = len(claims)
    if pending or sum(counts.values()) != total:
        raise ValueError("Report contains claims without a verdict.")
    by_cat: dict[str, dict[str, int]] = {}
    for c in claims:
        row = by_cat.setdefault(c.category, {"total": 0, **{s: 0 for s in ORDER}})
        row["total"] += 1
        row[c.status] += 1
    cats = sorted(by_cat.items(), key=lambda kv: (-kv[1]["total"], kv[0]))
    sources = sum(len(_source_rows(c)) for c in claims)
    return {
        "total": total,
        "counts": counts,
        "percent": _percentages(counts, total),
        "categories": cats,
        "sources": sources,
    }


# ---------------------------------------------------------------- styles

def _styles() -> dict[str, ParagraphStyle]:
    base = dict(fontName="NotoSans", fontSize=9.2, leading=13.2, textColor=INK)
    s = {
        "body": ParagraphStyle("body", **base),
        "small": ParagraphStyle("small", **{**base, "fontSize": 8, "leading": 11, "textColor": MUTED}),
        "tiny": ParagraphStyle("tiny", **{**base, "fontSize": 7.2, "leading": 9.5, "textColor": MUTED}),
        "h1": ParagraphStyle("h1", **{**base, "fontName": "NotoSans-Bold", "fontSize": 18, "leading": 22, "textColor": NAVY, "spaceAfter": 4}),
        "h2": ParagraphStyle("h2", **{**base, "fontName": "NotoSans-Bold", "fontSize": 11.5, "leading": 15, "textColor": NAVY, "spaceBefore": 10, "spaceAfter": 4}),
        "label": ParagraphStyle("label", **{**base, "fontName": "NotoSans-Bold", "fontSize": 7.2, "leading": 9.5, "textColor": MUTED, "spaceBefore": 6, "spaceAfter": 1.5, "keepWithNext": 1}),
        "claim": ParagraphStyle("claim", **{**base, "fontName": "NotoSans-Bold", "fontSize": 10.2, "leading": 14.5, "textColor": NAVY, "spaceBefore": 6}),
        "bullet": ParagraphStyle("bullet", **{**base, "leftIndent": 10, "bulletIndent": 0, "spaceAfter": 2.5}),
        "source": ParagraphStyle("source", **{**base, "leftIndent": 10, "bulletIndent": 0, "spaceAfter": 4}),
        "cell": ParagraphStyle("cell", **{**base, "fontSize": 8.2, "leading": 11}),
        "cell_b": ParagraphStyle("cell_b", **{**base, "fontName": "NotoSans-Bold", "fontSize": 8.2, "leading": 11}),
        "url": ParagraphStyle("url", **{**base, "fontSize": 7.2, "leading": 9.4, "wordWrap": "CJK"}),  # may break anywhere
        "note": ParagraphStyle("note", **{**base, "fontSize": 8.4, "leading": 12, "textColor": INK, "backColor": colors.HexColor("#fff7ed"), "borderPadding": (5, 6, 5, 6), "borderColor": colors.HexColor("#fed7aa"), "borderWidth": 0.6, "spaceBefore": 7, "spaceAfter": 5}),
        "quote": ParagraphStyle("quote", **{**base, "fontSize": 8.4, "leading": 12, "textColor": MUTED}),
    }
    return s


def P(text: object, style: ParagraphStyle, *, plain_limit: int = MAX_TEXT) -> Paragraph:
    """Paragraph from untrusted text. Long unbroken strings get character-level wrapping."""
    if _has_long_token(str(text)):
        style = ParagraphStyle(style.name + "_wrap", parent=style, wordWrap="CJK")
    return Paragraph(markup(text, plain_limit), style)


# ---------------------------------------------------------------- custom flowables

class Badge(Flowable):
    """A rounded status label."""

    def __init__(self, text: str, fg, bg, size: float = 8):
        super().__init__()
        self.text, self.fg, self.bg, self.size = text, fg, bg, size
        self.width = stringWidth(text, "NotoSans-Bold", size) + 14
        self.height = size + 7

    def wrap(self, *_):
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.setFillColor(self.bg)
        c.setStrokeColor(self.fg)
        c.setLineWidth(0.6)
        c.roundRect(0, 0, self.width, self.height, self.height / 2, stroke=1, fill=1)
        c.setFillColor(self.fg)
        c.setFont("NotoSans-Bold", self.size)
        c.drawCentredString(self.width / 2, (self.height - self.size) / 2 + self.size * 0.2, self.text)


class ShareBar(Flowable):
    """A thin bar showing a 0-100 value."""

    def __init__(self, pct: float, color, width: float = 110, height: float = 7):
        super().__init__()
        self.pct, self.color, self.width, self.height = max(0, min(100, pct)), color, width, height

    def wrap(self, *_):
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.setFillColor(LINE)
        c.roundRect(0, 0, self.width, self.height, self.height / 2, stroke=0, fill=1)
        if self.pct > 0:
            c.setFillColor(self.color)
            c.roundRect(0, 0, max(self.height, self.width * self.pct / 100), self.height, self.height / 2, stroke=0, fill=1)


class StackedBar(Flowable):
    """One bar for the whole document, split by verdict, with a 1.5pt gap between segments."""

    def __init__(self, counts: dict[str, int], width: float, height: float = 24):
        super().__init__()
        self.counts, self.width, self.height = counts, width, height

    def wrap(self, *_):
        return self.width, self.height

    def draw(self):
        c = self.canv
        total = sum(self.counts.values())
        if total == 0:
            c.setFillColor(LINE)
            c.roundRect(0, 0, self.width, self.height, 4, stroke=0, fill=1)
            return
        gap = 1.5
        active = [s for s in ORDER if self.counts[s] > 0]
        usable = self.width - gap * (len(active) - 1)
        x = 0.0
        for s in active:
            w = usable * self.counts[s] / total
            c.setFillColor(STATUS[s][1])
            c.rect(x, 0, w, self.height, stroke=0, fill=1)
            label = str(self.counts[s])
            if w >= stringWidth(label, "NotoSans-Bold", 9) + 8:
                c.setFillColor(colors.white)
                c.setFont("NotoSans-Bold", 9)
                c.drawCentredString(x + w / 2, self.height / 2 - 3.2, label)
            x += w + gap


def draw_logo(c, x: float, y: float, size: float, bg, fg) -> None:
    """The TruthLayer mark: a rounded square holding a shield with a check, drawn with paths."""
    c.saveState()
    c.setFillColor(bg)
    c.roundRect(x, y, size, size, size * 0.24, stroke=0, fill=1)
    k = size / 40.0
    p = c.beginPath()
    p.moveTo(x + 20 * k, y + 31 * k)
    p.lineTo(x + 30 * k, y + 27 * k)
    p.lineTo(x + 30 * k, y + 19 * k)
    p.curveTo(x + 30 * k, y + 12 * k, x + 25 * k, y + 9 * k, x + 20 * k, y + 8 * k)
    p.curveTo(x + 15 * k, y + 9 * k, x + 10 * k, y + 12 * k, x + 10 * k, y + 19 * k)
    p.lineTo(x + 10 * k, y + 27 * k)
    p.close()
    c.setFillColor(fg)
    c.drawPath(p, stroke=0, fill=1)
    c.setStrokeColor(bg)
    c.setLineWidth(2.2 * k)
    c.setLineCap(1)
    c.setLineJoin(1)
    c.lines([(x + 15 * k, y + 19 * k, x + 18.5 * k, y + 15.5 * k), (x + 18.5 * k, y + 15.5 * k, x + 25.5 * k, y + 23.5 * k)])
    c.restoreState()


# ---------------------------------------------------------------- page chrome (cover, header, footer)

class NumberedCanvas(rl_canvas.Canvas):
    """Canvas that knows the total page count, so the footer can say "Page 3 of 12"."""

    meta: dict = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved: list[dict] = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            n = self._pageNumber
            if n == 1:
                self._cover()
            else:
                self._chrome(n, total)
            super().showPage()
        super().save()

    def _cover(self):
        self.saveState()
        band = 262
        self.setFillColor(NAVY)
        self.rect(0, PAGE_H - band, PAGE_W, band, stroke=0, fill=1)
        self.setFillColor(NAVY_SOFT)
        self.circle(PAGE_W - 40, PAGE_H - 30, 120, stroke=0, fill=1)
        draw_logo(self, MARGIN, PAGE_H - 108, 46, colors.white, NAVY)
        self.setFillColor(colors.white)
        self.setFont("NotoSans-Bold", 24)
        self.drawString(MARGIN + 60, PAGE_H - 92, "TruthLayer ")
        w = stringWidth("TruthLayer ", "NotoSans-Bold", 24)
        self.setFillColor(SKY_LIGHT)
        self.drawString(MARGIN + 60 + w, PAGE_H - 92, "AI")
        self.setFillColor(SKY_LIGHT)
        self.setFont("NotoSans", 10)
        self.drawString(MARGIN + 60, PAGE_H - 108, "Don’t just publish. Verify.")
        self.setFillColor(colors.white)
        self.setFont("NotoSans-Bold", 34)
        self.drawString(MARGIN, PAGE_H - 190, "AI Fact-Checking Report")
        self.setFillColor(SKY_LIGHT)
        self.rect(MARGIN, PAGE_H - 206, 54, 3, stroke=0, fill=1)
        # footer note
        self.setFillColor(MUTED)
        self.setFont("NotoSans", 7.6)
        self.drawString(MARGIN, 34, "Generated by TruthLayer AI from saved verification results. Not legal, financial or professional advice.")
        self.restoreState()

    def _chrome(self, n: int, total: int):
        meta = self.meta
        self.saveState()
        draw_logo(self, MARGIN, PAGE_H - MARGIN + 6, 16, NAVY, colors.white)
        self.setFillColor(NAVY)
        self.setFont("NotoSans-Bold", 9)
        self.drawString(MARGIN + 22, PAGE_H - MARGIN + 11, "TruthLayer ")
        w = stringWidth("TruthLayer ", "NotoSans-Bold", 9)
        self.setFillColor(SKY)
        self.drawString(MARGIN + 22 + w, PAGE_H - MARGIN + 11, "AI")
        self.setFillColor(MUTED)
        self.setFont("NotoSans", 8)
        self.drawRightString(PAGE_W - MARGIN, PAGE_H - MARGIN + 11, meta.get("doc_short", ""))
        self.setStrokeColor(LINE)
        self.setLineWidth(0.7)
        self.line(MARGIN, PAGE_H - MARGIN + 2, PAGE_W - MARGIN, PAGE_H - MARGIN + 2)
        self.line(MARGIN, MARGIN - 16, PAGE_W - MARGIN, MARGIN - 16)
        self.setFillColor(MUTED)
        self.setFont("NotoSans", 7.6)
        self.drawString(MARGIN, MARGIN - 28, f"AI Fact-Checking Report · generated {meta.get('stamp', '')}")
        self.drawRightString(PAGE_W - MARGIN, MARGIN - 28, f"Page {n} of {total}")
        self.restoreState()


# ---------------------------------------------------------------- content builders

def _source_rows(claim: ReportClaim) -> list[tuple[str, VerdictSource | None, object]]:
    """(role, verdict_source, collected_source) rows for one claim, de-duplicated by URL.
    Only sources that exist in the saved results are listed."""
    rows: list[tuple[str, VerdictSource | None, object]] = []
    seen: set[str] = set()
    v = claim.verification
    if v:
        for role, items in (("Supports", v.supporting_sources), ("Contradicts", v.contradicting_sources)):
            for s in items:
                if s.url not in seen:
                    seen.add(s.url)
                    rows.append((role, s, None))
    for s in claim.collected_sources:
        if s.url not in seen:
            seen.add(s.url)
            rows.append(("Reviewed", None, s))
    return rows


def _fmt_date(d: str | None) -> str | None:
    return clean(d, 40) if d else None


def _source_line(title: str, url: str, domain: str, date: str | None) -> str:
    safe = safe_url(url)
    t = markup(clean(title).strip() or domain or url, 300)
    head = link(safe, t) if safe else t
    meta = markup(domain, 120) + (f" · {markup(date, 40)}" if date else "")
    return f"<b>{head}</b><br/><font size='7.6' color='#64748b'>{meta}</font>"


def _cover_story(report: Report, st: dict, stats: dict, stamp: str) -> list:
    S = st
    story: list = [Spacer(1, 262 - MARGIN + 30)]
    story.append(P("Automated, evidence-based verification of the factual claims in your document.", ParagraphStyle("sub", parent=S["body"], fontSize=12.5, leading=18, textColor=INK)))
    story.append(Spacer(1, 22))
    rows = [
        [Paragraph("DOCUMENT", S["label"]), P(report.document_name, ParagraphStyle("v", parent=S["body"], fontName="NotoSans-Bold", fontSize=11, leading=15, textColor=NAVY))],
        [Paragraph("GENERATED", S["label"]), P(stamp, S["body"])],
        [Paragraph("CLAIMS ANALYZED", S["label"]), P(str(stats["total"]), ParagraphStyle("v2", parent=S["body"], fontName="NotoSans-Bold", fontSize=11, textColor=NAVY))],
    ]
    t = Table(rows, colWidths=[110, CONTENT_W - 110])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("BOX", (0, 0), (-1, -1), 0.7, LINE),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    story += [t, Spacer(1, 22)]
    # verdict chips with counts
    cells = []
    for s in ORDER:
        label, fg, bg = STATUS[s]
        cells.append([Badge(f"{label}  {stats['counts'][s]}", fg, bg, 9.5)])
    chips = Table([[c[0] for c in cells]], colWidths=[CONTENT_W / 4] * 4, hAlign="LEFT")
    chips.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("ALIGN", (0, 0), (-1, -1), "LEFT")]))
    story += [chips, Spacer(1, 16), StackedBar(stats["counts"], CONTENT_W, 14), Spacer(1, 6)]
    if stats["total"]:
        story.append(P("Share of claims by verdict", S["tiny"]))
    story += [NextPageTemplate("body"), PageBreak()]
    return story


def _summary_story(report: Report, st: dict, stats: dict) -> list:
    S, total = st, stats["total"]
    story: list = [Paragraph("Executive summary", S["h1"]), HRFlowable(width="100%", thickness=0.8, color=LINE, spaceAfter=10)]

    # stat cards
    def card(label: str, count: int, pct: int | None, color, tint):
        return [
            Paragraph(f"<font size='7.4' color='#64748b'><b>{markup(label.upper())}</b></font>", S["small"]),
            Paragraph(f"<font size='25' color='{color.hexval().replace('0x', '#')}'><b>{count}</b></font>", ParagraphStyle("n", parent=S["body"], leading=30)),
            Paragraph(f"<font size='8' color='#64748b'>{'' if pct is None else str(pct) + '% of claims'}</font>", S["small"]),
        ]

    cols = [card("Total claims analyzed", total, None, NAVY, PANEL)]
    for s in ORDER:
        label, fg, tint = STATUS[s]
        cols.append(card(label, stats["counts"][s], stats["percent"][s] if total else None, fg, tint))
    w = CONTENT_W / 5
    t = Table([cols], colWidths=[w] * 5)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.7, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.7, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LINEABOVE", (0, 0), (0, 0), 3, NAVY),
    ]
    for i, s in enumerate(ORDER, start=1):
        style.append(("LINEABOVE", (i, 0), (i, 0), 3, STATUS[s][1]))
    t.setStyle(TableStyle(style))
    story += [t, Spacer(1, 6)]
    if total:
        pct = stats["percent"]
        story.append(P(
            "Distribution: " + ", ".join(f"{STATUS[s][0]} {pct[s]}%" for s in ORDER) + ". "
            "Percentages are rounded to whole numbers that add up to 100%.",
            S["small"],
        ))

    story.append(Paragraph("Summary", S["h2"]))
    story.append(P(report.summary.text, S["body"]))
    if report.summary.narrative:
        story.append(Paragraph("AI-WRITTEN SUMMARY", S["label"]))
        story.append(P(report.summary.narrative, S["body"]))
        story.append(P("Written by AI from the results in this report; it adds no new findings.", S["tiny"]))

    items = report.summary.needs_investigation
    story.append(Paragraph(f"Needs further investigation ({len(items)})", S["h2"]))
    if not items:
        story.append(P("No claims are flagged for follow-up.", S["body"]))
    for i in items[:15]:
        story.append(Paragraph(
            f"<b>{markup(i.claim_id, 40)}</b> — {markup(i.claim_text, 220)}<br/>"
            f"<font size='8' color='#64748b'>{markup(i.reason, 200)}</font>",
            ParagraphStyle("inv", parent=S["bullet"], wordWrap="CJK" if _has_long_token(i.claim_text) else "LTR"),
            bulletText="•",
        ))
    if len(items) > 15:
        story.append(P(f"…and {len(items) - 15} more.", S["small"]))
    story.append(Spacer(1, 14))
    return story


def _overview_story(st: dict, stats: dict) -> list:
    S, total = st, stats["total"]
    story: list = [CondPageBreak(330), Paragraph("Verification overview", S["h1"]), HRFlowable(width="100%", thickness=0.8, color=LINE, spaceAfter=10)]
    if total == 0:
        story.append(P("No factual claims were extracted from this document, so there is nothing to chart.", S["body"]))
        story.append(PageBreak())
        return story
    story += [StackedBar(stats["counts"], CONTENT_W), Spacer(1, 12)]

    rows = [[Paragraph("<b>Status</b>", S["cell"]), Paragraph("<b>Claims</b>", S["cell"]), Paragraph("<b>Share</b>", S["cell"]), ""]]
    for s in ORDER:
        label, fg, tint = STATUS[s]
        rows.append([
            Paragraph(f"<font color='{fg.hexval().replace('0x', '#')}'><b>•</b></font>&nbsp;&nbsp;{label}", S["cell"]),
            Paragraph(str(stats["counts"][s]), S["cell_b"]),
            Paragraph(f"{stats['percent'][s]}%", S["cell"]),
            ShareBar(stats["counts"][s] * 100 / total, fg, 170),
        ])
    rows.append([Paragraph("<b>Total</b>", S["cell_b"]), Paragraph(str(total), S["cell_b"]), Paragraph("100%", S["cell_b"]), ""])
    t = Table(rows, colWidths=[150, 70, 70, CONTENT_W - 290])
    st_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), PANEL),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, LINE),
        ("BOX", (0, 0), (-1, -1), 0.7, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("BACKGROUND", (0, -1), (-1, -1), PANEL),
    ]
    for i, s in enumerate(ORDER, start=1):
        st_cmds.append(("LINEBEFORE", (0, i), (0, i), 3, STATUS[s][1]))
    t.setStyle(TableStyle(st_cmds))
    story += [t, CondPageBreak(120), Paragraph("Claims by category", S["h2"])]

    head = ["Category", "Claims"] + [STATUS[s][0] for s in ORDER]
    crow = [[Paragraph(f"<b>{h}</b>", S["cell"]) for h in head]]
    for cat, row in stats["categories"]:
        crow.append([P(category_label(cat), S["cell"]), Paragraph(f"<b>{row['total']}</b>", S["cell"])] + [Paragraph(str(row[s]), S["cell"]) for s in ORDER])
    widths = [CONTENT_W - 5 * 62] + [62] * 5
    ct = Table(crow, colWidths=widths, repeatRows=1)
    ct.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PANEL),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE),
        ("BOX", (0, 0), (-1, -1), 0.7, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story += [ct, PageBreak()]
    return story


def _claim_story(c: ReportClaim, st: dict) -> list:
    S = st
    v = c.verification
    label, fg, tint = STATUS[c.status]
    hexfg = fg.hexval().replace("0x", "#")
    story: list = [CondPageBreak(190)]

    head = Table(
        [[Paragraph(
            f"<b>{markup(c.claim_id, 40)}</b>&nbsp;&nbsp;·&nbsp;&nbsp;PDF page {c.page_number}&nbsp;&nbsp;·&nbsp;&nbsp;{markup(category_label(c.category), 60)}",
            ParagraphStyle("hd", parent=S["body"], fontSize=8.8, textColor=NAVY),
        ), Badge(label, fg, tint, 8.5)]],
        colWidths=[CONTENT_W - 100, 100],
    )
    head.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("LINEBEFORE", (0, 0), (0, 0), 4, fg),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [head, P(f"“{clean(c.claim_text)}”", S["claim"])]

    facts = []
    if c.value or c.unit or c.time_period:
        bits = [x for x in (c.value, c.unit, c.time_period) if x]
        facts.append("Extracted: " + " · ".join(clean(b, 80) for b in bits))
    if facts:
        story.append(P(" ".join(facts), S["small"]))

    if v is None:  # cannot happen for a ready report; guard so a bad call never prints a made-up verdict
        story.append(P("No verification result is available for this claim.", S["body"]))
        return story

    # confidence
    if c.confidence_score is not None:
        conf = Table([[Paragraph(f"<font size='7.4' color='#64748b'><b>CONFIDENCE</b></font>&nbsp; <b>{c.confidence_score}/100</b> <font size='7.4' color='#64748b'>(AI-assessed evidence strength)</font>", S["cell"]), ShareBar(c.confidence_score, fg, 120)]], colWidths=[CONTENT_W - 130, 120])
        conf.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
        story.append(conf)

    notes = {
        "prediction": "This statement is a forecast, so it cannot be confirmed or refuted as a fact.",
        "hypothetical": "This statement looks like a hypothetical or illustrative example, not a confirmed real-world event.",
        "not_verifiable": "This statement is not objectively verifiable.",
    }
    if v.claim_type in notes:
        story.append(P(notes[v.claim_type], S["note"]))

    story += [Paragraph("AI EXPLANATION", S["label"]), P(v.explanation or "No explanation was provided.", S["body"])]
    if v.corrected_claim:
        story += [Paragraph("CORRECTED INFORMATION", S["label"]), P(v.corrected_claim, S["note"])]
    if v.evidence_summary:
        story += [Paragraph("EVIDENCE SUMMARY", S["label"]), P(v.evidence_summary, S["body"])]

    for title, items, color in (
        ("SUPPORTING SOURCES", v.supporting_sources, "#16a34a"),
        ("CONTRADICTING SOURCES", v.contradicting_sources, "#dc2626"),
    ):
        story.append(Paragraph(f"<font color='{color}'>{title} ({len(items)})</font>", S["label"]))
        if not items:
            story.append(P("None cited.", S["small"]))
        for s in items:
            line = _source_line(s.title, s.url, s.domain, _fmt_date(s.published_date))
            if s.relevance:
                line += f"<br/><i><font size='8' color='#475569'>{markup(s.relevance, 400)}</font></i>"
            story.append(Paragraph(line, S["source"], bulletText="•"))

    if v.adjustments:
        story.append(Paragraph("ANALYSIS NOTES", S["label"]))
        for a in v.adjustments:
            story.append(Paragraph(markup(a, 400), ParagraphStyle("adj", parent=S["small"], leftIndent=10), bulletText="•"))

    story += [Spacer(1, 8), HRFlowable(width="100%", thickness=0.5, color=LINE, spaceAfter=10)]
    return story


def _detail_story(report: Report, st: dict) -> list:
    story: list = [Paragraph("Detailed claim-by-claim analysis", st["h1"]), HRFlowable(width="100%", thickness=0.8, color=LINE, spaceAfter=6)]
    if not report.claims:
        story.append(P("No factual claims were extracted from this document.", st["body"]))
    else:
        story.append(P("Claims appear in extraction order. Each claim shows the original text as extracted from the PDF, the AI verdict, and the web sources behind it.", st["small"]))
        story.append(Spacer(1, 6))
    for c in report.claims:
        story += _claim_story(c, st)
    story.append(PageBreak())
    return story


def _sources_story(report: Report, st: dict) -> list:
    S = st
    story: list = [Paragraph("Sources and references", S["h1"]), HRFlowable(width="100%", thickness=0.8, color=LINE, spaceAfter=6)]
    rows = [[Paragraph("<b>Claim</b>", S["cell"]), Paragraph("<b>Role</b>", S["cell"]), Paragraph("<b>Source</b>", S["cell"]), Paragraph("<b>URL</b>", S["cell"])]]
    role_color = {"Supports": "#16a34a", "Contradicts": "#dc2626", "Reviewed": "#64748b"}
    for c in report.claims:
        for role, vs, cs in _source_rows(c):
            src = vs or cs
            url, title, domain, date = src.url, src.title, src.domain, src.published_date
            safe = safe_url(url)
            role_text = {"Supports": "Supports", "Contradicts": "Contradicts", "Reviewed": "Reviewed, not cited"}[role]
            rows.append([
                P(c.claim_id, S["cell"]),
                Paragraph(f"<font color='{role_color[role]}'><b>{role_text}</b></font>", S["cell"]),
                Paragraph(_source_line(title, url, domain, _fmt_date(date)), S["cell"]),
                Paragraph(link(safe, markup(url, 600)) if safe else markup(url, 600), S["url"]),
            ])
    if len(rows) == 1:
        story.append(P("No web sources were collected for this document.", S["body"]))
        story.append(Spacer(1, 18))
        return story
    story.append(P("Only sources that the web search returned for a claim are listed. “Supports” and “Contradicts” sources were cited in the verdict; “Reviewed, not cited” sources were returned by the search but not relied on. Links are clickable.", S["small"]))
    story.append(Spacer(1, 6))
    t = Table(rows, colWidths=[52, 66, 170, CONTENT_W - 288], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PANEL),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
        ("BOX", (0, 0), (-1, -1), 0.7, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [t, Spacer(1, 18)]
    return story


def _limits_story(st: dict, stamp: str) -> list:
    S = st
    box = Paragraph(markup(DISCLAIMER), ParagraphStyle("disc", parent=S["body"], fontSize=10, leading=15, backColor=PANEL, borderColor=NAVY_SOFT, borderWidth=0.8, borderPadding=(10, 12, 10, 12)))
    items = [
        "<b>Unverified does not mean false.</b> It means the collected evidence was missing, insufficient, conflicting or not objectively verifiable (for example, a forecast or an illustrative example).",
        "<b>Confidence scores</b> reflect the AI-assessed strength of the available evidence. They are not statistically calibrated probabilities.",
        "<b>Search results are not exhaustive.</b> The web search is not guaranteed to include every relevant source, and a few excerpts per claim cannot cover a whole topic.",
        f"<b>Verification reflects the evidence available at the time of analysis</b> (report generated {markup(stamp)}). Facts, figures and sources change over time.",
        "<b>Source excerpts are unverified web content.</b> Source quality varies; official, government, research and reputable news sources were given more weight than blogs and forums.",
        "<b>AI can make mistakes.</b> Review the cited sources before relying on any verdict, especially for decisions with legal, financial, medical or reputational consequences.",
    ]
    story: list = [CondPageBreak(330), Paragraph("Limitations and disclaimer", S["h1"]), HRFlowable(width="100%", thickness=0.8, color=LINE, spaceAfter=12), box, Spacer(1, 14)]
    for i in items:
        story.append(Paragraph(i, S["bullet"], bulletText="•"))
    return story


# ---------------------------------------------------------------- public API

def build_pdf(report: Report, now: datetime | None = None) -> bytes:
    """Render the report to PDF bytes. Raises ValueError if verification is incomplete."""
    _register_fonts()
    stats = compute_stats(report)
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%d %b %Y, %H:%M UTC")
    st = _styles()

    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN + 10,
        bottomMargin=MARGIN + 6,
        title="AI Fact-Checking Report",
        author="TruthLayer AI",
        subject=f"Fact-check of {clean(report.document_name, 120)}",
        creator="TruthLayer AI",
    )
    cover = Frame(MARGIN, 60, CONTENT_W, PAGE_H - 60 - 40, id="cover", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    body = Frame(MARGIN, MARGIN + 6, CONTENT_W, PAGE_H - 2 * MARGIN - 16, id="body", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="cover", frames=[cover]), PageTemplate(id="body", frames=[body])])

    story: list = []
    story += _cover_story(report, st, stats, stamp)
    story += _summary_story(report, st, stats)
    story += _overview_story(st, stats)
    story += _detail_story(report, st)
    story += _sources_story(report, st)
    story += _limits_story(st, stamp)

    meta = {"doc_short": clean(report.document_name, 60), "stamp": stamp}

    def canvasmaker(*a, **k):
        c = NumberedCanvas(*a, **k)
        c.meta = meta
        return c

    doc.build(story, canvasmaker=canvasmaker)
    return buf.getvalue()


def download_filename(document_name: str) -> str:
    """A safe ASCII filename for Content-Disposition."""
    stem = re.sub(r"\.pdf$", "", document_name.strip(), flags=re.I)
    stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._")[:60] or "document"
    return f"truthlayer-fact-check-{stem}.pdf"
