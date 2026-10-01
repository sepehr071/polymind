"""Render ONE Persian (RTL) salary-slip PDF (فیش حقوقی) from a parsed payslip
record.

Pure rendering: no DB, no FastAPI. The record shape is the ``PayslipRecord``
contract produced by :func:`app.services.payroll_service.parse_payroll`.

Persian *labels* are reshaped + bidi-reordered through ``_fa`` so the bundled
Vazirmatn font draws connected, right-to-left glyphs. *Numbers* are drawn
verbatim as Latin digits with comma grouping (``171,797,355``) to match the
reference slip — they are never passed through ``_fa``.
"""
from __future__ import annotations

import io
import os

import arabic_reshaper
from bidi import get_display  # python-bidi 0.6 API
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_FONT_REGULAR = "Vazirmatn"
_FONT_BOLD = "Vazirmatn-Bold"

_FONT_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "fonts")

# Reference palette.
_LAVENDER = colors.HexColor("#ECECF8")
_VALUE_BLUE = colors.HexColor("#2B2BCB")
_LABEL_INK = colors.HexColor("#1A1A1A")
_BORDER_GRAY = colors.HexColor("#99AAAA")
_HEADER_INK = colors.HexColor("#111111")


def _fa(text: object) -> str:
    """Reshape + bidi-reorder Persian text for correct RTL glyph drawing.

    reportlab's ``wordWrap='RTL'`` does NOT bidi-reorder in this stack, so
    python-bidi must do it here. bidi returns *visual* order, which reportlab
    cannot re-wrap without scrambling word order — so callers pre-wrap into
    logical-order lines (``\\n`` via :func:`_wrap_label`) and we bidi each line
    independently, joining with ``<br/>``. Every Persian paragraph style keeps
    wordWrap at its default (NEVER 'RTL').
    """
    lines = str(text).split("\n")
    return "<br/>".join(get_display(arabic_reshaper.reshape(ln)) for ln in lines)


def _wrap_label(text: object, max_chars: int = 18) -> str:
    """Greedy word-wrap a logical-order Persian label into ``\\n`` lines so each
    line fits its cell. MUST run before :func:`_fa` (i.e. in logical order)."""
    words = str(text).split()
    if not words:
        return str(text)
    lines: list[str] = []
    cur = ""
    for w in words:
        cand = f"{cur} {w}".strip()
        if cur and len(cand) > max_chars:
            lines.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return "\n".join(lines)


def _register_fonts() -> None:
    """Register Vazirmatn regular + bold exactly once (idempotent)."""
    registered = set(pdfmetrics.getRegisteredFontNames())
    if _FONT_REGULAR not in registered:
        pdfmetrics.registerFont(
            TTFont(_FONT_REGULAR, os.path.join(_FONT_DIR, "Vazirmatn-Regular.ttf"))
        )
    if _FONT_BOLD not in registered:
        pdfmetrics.registerFont(
            TTFont(_FONT_BOLD, os.path.join(_FONT_DIR, "Vazirmatn-Bold.ttf"))
        )


def _money(value: object) -> str:
    """Latin digits, comma thousands grouping; blank for falsy/None."""
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return ""
    return f"{n:,}"


def _count(value: object) -> str:
    """Day/hour counts: keep fractional parts (e.g. ``31.04``, ``1.11``) — these
    are NOT money, so don't round them like :func:`_money` does."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return ""
    if f == int(f):
        return f"{int(f):,}"
    return f"{f:,.2f}".rstrip("0").rstrip(".")


# ---------------------------------------------------------------------------
# Paragraph styles (built lazily after fonts are registered).
# ---------------------------------------------------------------------------
def _styles() -> dict[str, ParagraphStyle]:
    return {
        "title": ParagraphStyle(
            "ps_title", fontName=_FONT_BOLD, fontSize=15, leading=20,
            alignment=2, textColor=_HEADER_INK,
        ),
        "hdr_label": ParagraphStyle(
            "ps_hdr_label", fontName=_FONT_REGULAR, fontSize=9, leading=13,
            alignment=2, textColor=_LABEL_INK,
        ),
        "hdr_value": ParagraphStyle(
            "ps_hdr_value", fontName=_FONT_BOLD, fontSize=9.5, leading=13,
            alignment=2, textColor=_VALUE_BLUE,
        ),
        "cat_title": ParagraphStyle(
            "ps_cat_title", fontName=_FONT_BOLD, fontSize=10, leading=14,
            alignment=1, textColor=_HEADER_INK,
        ),
        "row_label": ParagraphStyle(
            "ps_row_label", fontName=_FONT_REGULAR, fontSize=8.5, leading=12,
            alignment=2, textColor=_LABEL_INK,
        ),
        "row_value": ParagraphStyle(
            "ps_row_value", fontName=_FONT_BOLD, fontSize=8.5, leading=12,
            alignment=0, textColor=_VALUE_BLUE,
        ),
        "subtotal_label": ParagraphStyle(
            "ps_sub_label", fontName=_FONT_BOLD, fontSize=8.8, leading=12,
            alignment=2, textColor=_HEADER_INK,
        ),
        "subtotal_value": ParagraphStyle(
            "ps_sub_value", fontName=_FONT_BOLD, fontSize=8.8, leading=12,
            alignment=0, textColor=_VALUE_BLUE,
        ),
        "net_label": ParagraphStyle(
            "ps_net_label", fontName=_FONT_BOLD, fontSize=13, leading=18,
            alignment=2, textColor=_HEADER_INK,
        ),
        "net_value": ParagraphStyle(
            "ps_net_value", fontName=_FONT_BOLD, fontSize=16, leading=20,
            alignment=0, textColor=_VALUE_BLUE,
        ),
    }


def _line_row(label: str, value: object, st: dict, *, bold: bool = False, fmt=None) -> Table:
    """A two-cell row: Persian label (start/right) + Latin number (end/left).

    Built as its own 2-col table so the label and value keep independent
    alignment and the label can wrap without dragging the number. ``fmt`` picks
    the value formatter (defaults to :func:`_money`; pass :func:`_count` for
    day/hour columns that must keep decimals).
    """
    label_style = st["subtotal_label"] if bold else st["row_label"]
    value_style = st["subtotal_value"] if bold else st["row_value"]
    money = (fmt or _money)(value)
    # Size the value cell to the number itself so the label gets the rest of the
    # category column. (A flexible 50/50 split squeezed long labels into a wrap.)
    value_w = (pdfmetrics.stringWidth(money, value_style.fontName, value_style.fontSize) + 6) if money else 6
    # Visual order under RTL: value cell physically LEFT, label cell physically
    # RIGHT. Table cells are laid out LTR, so put value first, label second.
    inner = Table(
        [[Paragraph(money, value_style), Paragraph(_fa(_wrap_label(label)), label_style)]],
        colWidths=[value_w, None],
    )
    style = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]
    if bold:
        style.append(("BACKGROUND", (0, 0), (-1, -1), _LAVENDER))
    inner.setStyle(TableStyle(style))
    return inner


def _category_block(title: str, rows: list[Table], st: dict) -> Table:
    """A category column: a lavender title cell stacked over its line rows."""
    cells = [[Paragraph(_fa(title), st["cat_title"])]]
    cells.extend([[r] for r in rows])
    block = Table(cells, colWidths=[None])
    block.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), _LAVENDER),
        ("BOX", (0, 0), (-1, -1), 0.6, _BORDER_GRAY),
        ("LINEBELOW", (0, 0), (0, 0), 0.6, _BORDER_GRAY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return block


def render_payslip(record: dict, *, employer: str, month: str) -> bytes:
    """Render a single payslip record to PDF bytes (``b'%PDF...'``)."""
    _register_fonts()
    st = _styles()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=10 * mm, bottomMargin=10 * mm,
        title=f"payslip-{record.get('code', '')}",
    )
    flow: list = []

    # --- Title -------------------------------------------------------------
    flow.append(Paragraph(_fa(f"فیش حقوقی {month}"), st["title"]))
    flow.append(Spacer(1, 4 * mm))

    # --- Header (3 fields, RTL: code | name | employer) --------------------
    def _hdr_field(label: str, value: str) -> Table:
        t = Table(
            [[Paragraph(_fa(f"{label} :"), st["hdr_label"])],
             [Paragraph(_fa(_wrap_label(value, 24)), st["hdr_value"])]],
            colWidths=[None],
        )
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ]))
        return t

    # Visual order RTL → physically: employer (left), name (mid), code (right).
    header = Table(
        [[
            _hdr_field("محل خدمت", str(employer)),
            _hdr_field("نام و نام خانوادگی", str(record.get("name", ""))),
            _hdr_field("کد", str(record.get("code", ""))),
        ]],
        colWidths=["50%", "30%", "20%"],
    )
    header.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, _BORDER_GRAY),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, _BORDER_GRAY),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    flow.append(header)
    flow.append(Spacer(1, 4 * mm))

    # --- Main grid: 5 category columns -------------------------------------
    # Visual left→right: مساعده | اقساط | کسورات | مزایا | کارکرد
    earnings = record.get("earnings") or []
    deductions = record.get("deductions") or []

    earn_rows = [_line_row(e["label"], e["amount"], st) for e in earnings]
    earn_rows.append(_line_row("جمع مزایا", record.get("earnings_total", 0), st, bold=True))

    ded_rows = [_line_row(d["label"], d["amount"], st) for d in deductions]
    ded_rows.append(_line_row("جمع کسورات", record.get("deductions_total", 0), st, bold=True))

    work_rows = [
        _line_row("کارکرد روزانه", record.get("work_days", 0), st, fmt=_count),
        _line_row("کارکرد اضافه کاری", record.get("overtime_hours", 0), st, fmt=_count),
    ]

    advance = record.get("advance", 0) or 0
    installment = record.get("installment", 0) or 0
    advance_rows = [_line_row("مساعده", advance if advance else "", st)]
    instal_rows = [_line_row("اقساط", installment if installment else "", st)]

    grid = Table(
        [[
            _category_block("مساعده", advance_rows, st),
            _category_block("اقساط", instal_rows, st),
            _category_block("کسورات", ded_rows, st),
            _category_block("مزایا", earn_rows, st),
            _category_block("کارکرد", work_rows, st),
        ]],
        colWidths=["12%", "14%", "25%", "28%", "21%"],
    )
    grid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    flow.append(grid)
    flow.append(Spacer(1, 5 * mm))

    # --- Footer: net pay band ---------------------------------------------
    footer = Table(
        [[
            Paragraph(_money(record.get("net", 0)), st["net_value"]),
            Paragraph(_fa("خالص"), st["net_label"]),
        ]],
        colWidths=["60%", "40%"],
    )
    footer.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _LAVENDER),
        ("BOX", (0, 0), (-1, -1), 0.8, _BORDER_GRAY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    flow.append(footer)

    doc.build(flow)
    return buf.getvalue()


__all__ = ["render_payslip", "_fa", "_register_fonts"]
