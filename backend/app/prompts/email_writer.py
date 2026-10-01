"""Email / letter writer prompts — Iran formal register, FA default."""

from app.utils.quick_models import LOCAL_MODEL_ID

# Runs on the free self-hosted local (Ollama) model. chat_completion routes this
# id to Ollama when configured, else silently falls back to a cloud model.
EMAIL_WRITER_MODEL = LOCAL_MODEL_ID
EMAIL_WRITER_FEATURE = "email_writer"

TEMPLATE_IDS = frozenset({
    "official_letter",
    "internal_email",
    "follow_up",
    "request",
    "complaint",
    "invitation",
    "resignation",
    "thank_you",
    "introduction",
    "reply",
})

TONES = frozenset({"formal", "semi_formal", "friendly"})
LANGS = frozenset({"fa", "en"})

_TEMPLATE_HINTS = {
    "official_letter": "Formal organizational letter: header, recipient, subject, body, closing, signature.",
    "internal_email": "Internal company email: Subject line + concise body.",
    "follow_up": "Polite follow-up on a prior request or meeting.",
    "request": "Request for approval, information, or resources.",
    "complaint": "Respectful formal complaint / protest — firm but polite.",
    "invitation": "Meeting or event invitation with time/place when provided.",
    "resignation": "Resignation letter with last day when provided.",
    "thank_you": "Formal thank-you note.",
    "introduction": "Self or organization introduction / معارفه.",
    "reply": "Reply to a prior letter/email; use prior_context.",
}


def build_system_prompt(*, lang: str, tone: str, template_id: str) -> str:
    lang = lang if lang in LANGS else "fa"
    tone = tone if tone in TONES else "formal"
    hint = _TEMPLATE_HINTS.get(template_id, "")
    lang_line = (
        "Write the entire draft in Persian (Farsi), formal administrative register (شما, اداری)."
        if lang == "fa"
        else "Write the entire draft in clear professional English."
    )
    tone_line = {
        "formal": "Tone: formal / administrative.",
        "semi_formal": "Tone: semi-formal professional.",
        "friendly": "Tone: warm but still professional.",
    }[tone]
    return f"""You are Polymind AI's letter and email drafting assistant for Iranian professional contexts.
{lang_line}
{tone_line}
Template: {template_id} — {hint}

Rules:
- Never invent dates, reference numbers, legal clauses, amounts, or facts not supplied by the user.
- If a structural field is empty but needed, use a clear placeholder like [شماره نامه] or [Date].
- Prefer markdown: optional heading for subject; body paragraphs; closing + signature block.
- No HTML. No bidi control characters. Logical text only.
- For email-like templates, include a clear Subject line. Do not dump From:/To: headers.
- Keep concise; avoid fluff. Match Iranian formal letter conventions when lang=fa.
- Output only the draft — no meta commentary.
"""


def build_user_message(*, template_id: str, lang: str, tone: str, fields: dict) -> str:
    lines = [
        f"template: {template_id}",
        f"tone: {tone}",
        f"lang: {lang}",
    ]
    for key in (
        "recipient", "sender_name", "sender_title", "org", "subject", "points",
        "prior_context", "ref_number", "date_shamsi", "event_time", "event_place",
        "deadline", "last_day", "extra",
    ):
        val = (fields or {}).get(key)
        if val is None:
            continue
        s = str(val).strip()
        if s:
            lines.append(f"{key}: {s}")
    return "\n".join(lines)
