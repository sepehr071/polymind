"""Meeting action pack — second-pass polish from transcript + summary."""

ACTION_PACK_MODEL = "google/gemini-3.5-flash-lite"
ACTION_PACK_FEATURE = "meeting_action_pack"


def build_system_prompt(*, lang: str) -> str:
    lang = "en" if lang == "en" else "fa"
    out = "Persian (Farsi), formal business" if lang == "fa" else "clear professional English"
    return f"""You are Polymind AI's meeting action-pack generator for Iranian companies.
Write all free text in {out}.

Return ONLY JSON (no fences):
{{
  "action_items": [{{"task":"...","owner":"...","due":null,"priority":"normal|high|low"}}],
  "decisions": [{{"decision":"...","context":"..."}}],
  "email": {{"subject":"...","body":"...","tone":"formal"}},
  "memo": "short internal memo"
}}

Rules:
- Ground in the provided transcript/summary only; do not invent attendees or decisions.
- Email: formal Persian when lang=fa (subject + body).
- Memo: concise internal note for managers.
- Empty lists OK if nothing clear; still produce email + memo best-effort.
"""


def build_user_message(*, seed_text: str) -> str:
    return (
        "Generate an action pack from this meeting material:\n\n"
        + (seed_text or "")[:120000]
    )
