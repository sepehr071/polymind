"""Tender / RFQ assistant — مناقصه / استعلام, Rial/Toman."""

TENDER_MODEL = "google/gemini-3.5-flash-lite"
TENDER_FEATURE = "tender"
TENDER_MAX_FILES = 5
TENDER_MODES = frozenset({"tender", "rfq"})

DISCLAIMER_FA = "این خروجی مشاوره حقوقی نیست و جایگزین کارشناس حقوقی/مناقصه نمی‌شود."
DISCLAIMER_EN = "This output is not legal advice and does not replace a qualified tender specialist."


def build_system_prompt(*, lang: str, mode: str, currency_unit: str) -> str:
    lang = "en" if lang == "en" else "fa"
    mode = mode if mode in TENDER_MODES else "tender"
    unit = "rial" if currency_unit == "rial" else "toman"
    mode_label = "مناقصه (tender)" if mode == "tender" else "استعلام بها (RFQ)"
    out = "Persian" if lang == "fa" else "English"
    return f"""You are Polymind AI's tender/RFQ assistant for Iranian companies.
Mode: {mode_label}. Output language for narrative fields: {out}.
Always produce cover_letter_fa in formal Persian (اداری) even if lang=en.
Currency: prefer amounts as integer Rial in amount_rial; user display unit preference = {unit}.
1 Toman = 10 Rial. Never use USD/$ unless the document explicitly uses foreign currency (then note it).
Vocabulary: تضمین، پاکات، ارزیابی فنی/مالی، اسناد مناقصه، مهلت.

Return ONLY JSON (no fences):
{{
  "title": "...",
  "summary": "...",
  "deadlines": [{{"label":"...","date_text":"...","iso":null}}],
  "compliance_matrix": [
    {{
      "id": "R1",
      "requirement": "...",
      "status": "met|partial|gap|unknown",
      "response": "...",
      "evidence": "...",
      "amount_rial": null,
      "unit_uncertain": false,
      "priority": "must|should|nice"
    }}
  ],
  "cover_letter_fa": "formal Persian letter with {{{{COMPANY}}}} if name unknown",
  "cover_letter": "English body if lang=en else empty string",
  "questions": ["clarifying questions for buyer"],
  "risks": ["..."]
}}

Never fabricate registration numbers, licenses, or bid amounts.
Extract must/should requirements into the matrix (≥3 rows when document allows).
Not legal advice.
"""


def build_user_message(*, notes: str = "", mode: str = "tender") -> str:
    parts = [
        f"Analyze the attached {mode} documents and produce the JSON pack.",
    ]
    if (notes or "").strip():
        parts.append(f"Company notes / strengths / exclusions:\n{notes.strip()}")
    return "\n\n".join(parts)
