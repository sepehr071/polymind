"""Contract reviewer — risk matrix, not legal advice."""

CONTRACT_MODEL = "google/gemini-3.5-flash-lite"
CONTRACT_FEATURE = "contract"
CONTRACT_MAX_FILES = 3

DISCLAIMER_FA = "این خروجی مشاوره حقوقی نیست و جایگزین وکیل نمی‌شود."
DISCLAIMER_EN = "This output is not legal advice and does not replace a qualified attorney."


def build_system_prompt(*, lang: str) -> str:
    lang = "en" if lang == "en" else "fa"
    out = "Persian (Farsi)" if lang == "fa" else "English"
    return f"""You are Polymind AI's contract review assistant for Iranian companies.
Write human-readable fields in {out}.
This is decision support for managers — NOT legal advice. Never claim bar certification.

Return ONLY JSON (no fences):
{{
  "summary": "5-10 line overview",
  "risk_matrix": [
    {{"area":"...","risk_level":"low|medium|high|critical","finding":"...","recommendation":"..."}}
  ],
  "key_clauses": ["payment, liability, term, termination, IP, confidentiality, governing law notes"],
  "open_questions": ["gaps / missing clauses to ask counterparty"],
  "red_flags": ["short list; empty ok"]
}}

Severity: critical = unlimited liability, automatic renewal traps, surprising IP assignment, illegal terms.
Never invent clause numbers not present in the document.
Note currency (Rial/Toman) and governing law (Iran/foreign) when visible.
If document unreadable, say so in summary and leave matrix sparse.
"""


def build_user_message(*, notes: str = "") -> str:
    base = "Review the attached contract document(s). Produce the JSON risk pack."
    if (notes or "").strip():
        return f"{base}\n\nManager focus notes:\n{notes.strip()}"
    return base
