"""PDF/A-2U archive of a polymind.chat.export/v1 document.

fpdf2 owns conformance (embedded font, output intent, XMP pdfaid). Persian
shaping stays on so glyphs connect and the line runs right to left. Payslip
rendering stays on reportlab; this path is chat export only.
"""
from __future__ import annotations

import os

import arabic_reshaper
from bidi.algorithm import get_display
from fpdf import FPDF
from fpdf.enums import DocumentCompliance, WrapMode

from app.services.chat_export import content_text, iter_text_and_urls, prettify_urls

_FONT_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "fonts")
_REGULAR = os.path.join(_FONT_DIR, "Vazirmatn-Regular.ttf")
_BOLD = os.path.join(_FONT_DIR, "Vazirmatn-Bold.ttf")
_ROLE = {"user": "کاربر", "assistant": "دستیار"}


class _ChatPdf(FPDF):
    def __init__(self, header_text: str):
        super().__init__(format="A4", enforce_compliance=DocumentCompliance.PDFA_2U)
        self._header_text = header_text or "Polymind AI"
        self.set_auto_page_break(auto=True, margin=18)
        self.set_margins(15, 18, 15)

    def header(self):
        self.set_font("Vazirmatn", "B", 10)
        self.set_text_color(15, 23, 42)
        self.multi_cell(
            w=0, h=6, text=self._header_text, align="R",
            new_x="LMARGIN", new_y="NEXT",
        )
        self.ln(2)

    def footer(self):
        self.set_y(-12)
        self.set_font("Vazirmatn", "", 8)
        self.set_text_color(71, 85, 105)
        self.cell(w=0, h=8, text=str(self.page_no()), align="C")


def _leading(size: int) -> float:
    return size * 1.45


def _is_rtl_char(ch: str) -> bool:
    o = ord(ch)
    return (
        0x0600 <= o <= 0x06FF
        or 0x0750 <= o <= 0x077F
        or 0x08A0 <= o <= 0x08FF
        or 0xFB50 <= o <= 0xFDFF
        or 0xFE70 <= o <= 0xFEFF
    )


def _visual_url(shown: str) -> str:
    """Keep the https://host/ structure left to right.

    A Persian slug is one right-to-left run. Drawn left to right it would
    read backwards, so reshape and reorder only that run. Shaping stays off
    when the line is painted, or fpdf would reorder it a second time.
    """
    parts = []
    for i, part in enumerate(shown.split("/")):
        if i:
            parts.append("/")
        if any(_is_rtl_char(ch) for ch in part):
            parts.append(get_display(arabic_reshaper.reshape(part)))
        else:
            parts.append(part)
    return "".join(parts)


def _drop_url_parens(pieces: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """A source written as (https://...) must not leave a lone parenthesis."""
    cleaned = []
    for i, (kind, value) in enumerate(pieces):
        if kind == "text":
            if i + 1 < len(pieces) and pieces[i + 1][0] == "url":
                trimmed = value.rstrip()
                if trimmed.endswith("("):
                    value = trimmed[:-1].rstrip()
            if i > 0 and pieces[i - 1][0] == "url":
                trimmed = value.lstrip()
                if trimmed.startswith(")"):
                    value = trimmed[1:].lstrip()
        if kind == "text" and not value.strip():
            continue
        cleaned.append((kind, value))
    return cleaned


def _write_prose(pdf: _ChatPdf, text: str, size: int, *, bold: bool = False) -> None:
    body = prettify_urls((text or "").strip())
    if not body:
        return
    pdf.set_text_shaping(True)
    pdf.set_font("Vazirmatn", "B" if bold else "", size)
    pdf.set_text_color(15, 23, 42)
    pdf.multi_cell(
        w=0, h=_leading(size), text=body, align="R",
        new_x="LMARGIN", new_y="NEXT", wrapmode=WrapMode.WORD,
    )


def _write_url(pdf: _ChatPdf, url: str, size: int) -> None:
    shown = _visual_url(prettify_urls(url).strip())
    if not shown:
        return
    pdf.set_text_shaping(False)
    pdf.set_font("Vazirmatn", "", max(size - 1, 9))
    pdf.set_text_color(30, 64, 175)
    try:
        pdf.multi_cell(
            w=0, h=_leading(size), text=shown, align="L", link=url,
            new_x="LMARGIN", new_y="NEXT", wrapmode=WrapMode.CHAR,
        )
    except Exception:
        pdf.multi_cell(
            w=0, h=_leading(size), text=shown, align="L",
            new_x="LMARGIN", new_y="NEXT", wrapmode=WrapMode.CHAR,
        )
    pdf.set_text_shaping(True)
    pdf.set_text_color(15, 23, 42)


def _write(pdf: _ChatPdf, text: str, size: int, *, bold: bool = False) -> None:
    body = (text or "").strip()
    if not body:
        return
    if bold:
        _write_prose(pdf, body, size, bold=True)
        return
    for line in body.split("\n"):
        pieces = _drop_url_parens(list(iter_text_and_urls(line)))
        if not pieces:
            continue
        only_url = len(pieces) == 1 and pieces[0][0] == "url"
        if only_url:
            _write_url(pdf, pieces[0][1], size)
            continue
        buf = []
        for kind, value in pieces:
            if kind == "url":
                if buf:
                    _write_prose(pdf, "".join(buf), size)
                    buf = []
                _write_url(pdf, value, size)
            else:
                buf.append(value)
        if buf and "".join(buf).strip():
            _write_prose(pdf, "".join(buf), size)


def render_chat_pdf(doc: dict, title: str) -> bytes:
    header = " — ".join(
        part for part in (
            (doc.get("workspace") or {}).get("title"),
            (doc.get("assistant") or {}).get("name"),
        ) if part
    )
    pdf = _ChatPdf(header)
    pdf.set_title((title or "Polymind chat")[:200])
    pdf.set_lang("fa")
    pdf.set_author("Polymind AI")
    pdf.set_creator("Polymind AI")
    pdf.add_font("Vazirmatn", "", _REGULAR)
    pdf.add_font("Vazirmatn", "B", _BOLD)
    pdf.set_text_shaping(True)
    pdf.add_page()
    _write(pdf, title or "چت", 16, bold=True)
    assistant = (doc.get("assistant") or {}).get("name") or ""
    workspace = (doc.get("workspace") or {}).get("title") or ""
    model = (doc.get("model") or {})
    model_label = model.get("label") or model.get("id") or ""
    _write(pdf, f"دستیار: {assistant}", 11)
    _write(pdf, f"فضا: {workspace}", 11)
    _write(pdf, f"تاریخ: {doc.get('exported_at') or ''}", 11)
    if model_label:
        _write(pdf, f"مدل: {model_label}", 11)
    pdf.ln(2)
    systems = [m for m in doc.get("messages") or [] if m.get("role") == "system"]
    if systems:
        _write(pdf, "تنظیمات دستیار", 13, bold=True)
        for msg in systems:
            _write(pdf, content_text(msg.get("content")), 11)
        pdf.ln(2)
    _write(pdf, "گفتگو", 13, bold=True)
    for msg in doc.get("messages") or []:
        label = _ROLE.get(msg.get("role"))
        if not label:
            continue
        _write(pdf, label, 12, bold=True)
        _write(pdf, content_text(msg.get("content")), 11)
        pdf.ln(1)
    return bytes(pdf.output())
