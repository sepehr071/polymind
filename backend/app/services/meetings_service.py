"""
Meetings service — thin orchestrator helpers shared between routes and
the background pipeline.

This module intentionally stays small: heavy lifting lives in
``meetings_pipeline``, ``summary_service``, ``transcription_service``,
``meeting_glossary``, ``series_match``, and ``meeting_storage``. The
helpers here are the bits that don't fit cleanly into any of those.
"""
from __future__ import annotations

from typing import Iterable, Optional


# Model id used by the "Discuss this meeting" spawn-conversation route.
# Pinned to the same family as the summarizer for consistency — both flows
# operate on the same diarized prompt and expect the same Persian/English
# behavior, and reusing the model means cost attribution stays predictable.
MEETING_DISCUSSION_MODEL = 'google/gemini-3.6-flash'


def _format_action_item(item: dict) -> str:
    """Render one action_item as a markdown bullet with owner + due_date."""
    text = (item.get('text') or '').strip()
    owner = (item.get('owner') or '').strip()
    due = (item.get('due_date') or '').strip()
    parts = [text] if text else []
    meta_bits: list[str] = []
    if owner:
        meta_bits.append(f"@{owner}")
    if due:
        meta_bits.append(f"due {due}")
    if meta_bits:
        parts.append(f"_({', '.join(meta_bits)})_")
    return f"- {' '.join(parts)}".rstrip()


def _format_qa(items: Iterable[dict]) -> list[str]:
    out: list[str] = []
    for entry in items:
        q = (entry.get('question') or '').strip()
        a = (entry.get('answer') or '').strip()
        if not q:
            continue
        out.append(f"- **Q:** {q}")
        if a:
            out.append(f"  **A:** {a}")
    return out


def _format_open_questions(items: Iterable[dict]) -> list[str]:
    out: list[str] = []
    for entry in items:
        q = (entry.get('question') or '').strip()
        owner = (entry.get('owner') or '').strip()
        if not q:
            continue
        line = f"- {q}"
        if owner:
            line = f"{line} _({owner})_"
        out.append(line)
    return out


def _format_minutes(items: Iterable[dict], *, speaker_names: dict[str, str]) -> list[str]:
    out: list[str] = []
    for entry in items:
        speaker_id = (entry.get('speaker_id') or '').strip()
        text = (entry.get('text') or '').strip()
        start = entry.get('start_s')
        end = entry.get('end_s')
        if not text:
            continue
        display = speaker_names.get(speaker_id, speaker_id) or speaker_id or 'speaker_?'
        time_tag = ''
        if isinstance(start, (int, float)) and isinstance(end, (int, float)):
            time_tag = f" `[{float(start):.2f}-{float(end):.2f}]`"
        out.append(f"- **{display}**{time_tag}: {text}")
    return out


def _speaker_name_map(meeting: dict) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for sp in (meeting.get('speakers') or []):
        sid = sp.get('speaker_id')
        name = (sp.get('display_name') or '').strip()
        if sid and name:
            mapping[sid] = name
    return mapping


def build_seed_text(meeting: dict, transcript: Optional[dict], summary: Optional[dict]) -> str:
    """Assemble the system-seed markdown body for a spawn-conversation call.

    Used by the future ``POST /api/meetings/<id>/spawn-conversation`` route
    to seed a brand-new uni-chat conversation with the full meeting
    context. The text is plain markdown so the downstream chat experience
    can render headings + bullets cleanly without special handling.

    Either ``transcript`` or ``summary`` may be ``None`` (e.g. immediately
    after upload before pipeline runs) — sections corresponding to
    missing inputs are dropped, so partial seeds still produce a sensible
    starting context.
    """
    title = (meeting.get('title') or 'Untitled').strip() or 'Untitled'
    lines: list[str] = [f"# Meeting: {title}", ""]

    # Resolve speaker display names so transcript + minutes are easier to
    # read inside the spawned chat.
    speaker_names = _speaker_name_map(meeting)

    if transcript is not None:
        plain = (transcript.get('plain_text') or '').strip()
        if plain:
            lines.append("## Transcript")
            lines.append("")
            lines.append(plain)
            lines.append("")

    if summary is not None:
        exec_summary = (summary.get('exec_summary') or '').strip()
        if exec_summary:
            lines.append("## Summary")
            lines.append("")
            lines.append(exec_summary)
            lines.append("")

        action_items = summary.get('action_items') or summary.get('action_items_json') or []
        if action_items:
            lines.append("## Action Items")
            lines.append("")
            for item in action_items:
                lines.append(_format_action_item(item))
            lines.append("")

        decisions = summary.get('decisions') or summary.get('decisions_json') or []
        if decisions:
            lines.append("## Decisions")
            lines.append("")
            for entry in decisions:
                if isinstance(entry, str):
                    text = entry.strip()
                elif isinstance(entry, dict):
                    text = (entry.get('decision') or entry.get('text') or '').strip()
                else:
                    text = ''
                if text:
                    lines.append(f"- {text}")
            lines.append("")

        minutes = summary.get('minutes') or summary.get('minutes_json') or []
        if minutes:
            lines.append("## Minutes")
            lines.append("")
            lines.extend(_format_minutes(minutes, speaker_names=speaker_names))
            lines.append("")

        qa = summary.get('qa') or summary.get('qa_json') or []
        if qa:
            lines.append("## Q&A")
            lines.append("")
            lines.extend(_format_qa(qa))
            lines.append("")

        open_questions = (
            summary.get('open_questions') or summary.get('open_questions_json') or []
        )
        if open_questions:
            lines.append("## Open Questions")
            lines.append("")
            lines.extend(_format_open_questions(open_questions))
            lines.append("")

        email_subject = (summary.get('email_subject') or '').strip()
        email_body = (summary.get('email_draft') or '').strip()
        if email_subject or email_body:
            lines.append("## Follow-up Email")
            lines.append("")
            if email_subject:
                lines.append(f"**Subject:** {email_subject}")
                lines.append("")
            if email_body:
                lines.append(email_body)
                lines.append("")

    # Trim trailing whitespace, collapse any accidental triple-newlines.
    text = '\n'.join(lines).rstrip() + '\n'
    return text
