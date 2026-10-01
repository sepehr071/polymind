"""Studio-tool DLP text assembly — must match ``POST /dlp/scan`` join rules.

``/dlp/scan`` builds::

    attachment_text = "\\n\\n".join(owner extracts for each upload_id in order)
    scan_text = f"{text}\\n\\n{attachment_text}" if attachment_text else text

Studio handlers MUST gate the same ``scan_text`` the pre-flight scan used.
"""
from __future__ import annotations

from typing import Any, Iterable, List, Optional, Sequence


def attachment_extracts(user_id: Any, upload_ids: Sequence[str]) -> List[str]:
    """Owner-scoped extracted_text parts (empty extracts skipped)."""
    from app.models.upload import UploadModel

    parts: List[str] = []
    for uid in upload_ids or []:
        if not uid:
            continue
        try:
            meta = UploadModel.get_extracted_text_for_user(str(uid), user_id)
            t = (meta or {}).get("extracted_text") or ""
        except Exception:  # noqa: BLE001
            t = ""
        if t:
            parts.append(str(t))
    return parts


def combine_message_attachments(message: str, attachment_parts: Iterable[str]) -> str:
    """Same formula as ``dlp.py`` scan + chat gate."""
    att = "\n\n".join(p for p in attachment_parts if p)
    msg = message if message is not None else ""
    if att:
        return f"{msg}\n\n{att}"
    return msg


def gate_text(
    message: str,
    user_id: Any,
    upload_ids: Optional[Sequence[str]] = None,
    *,
    empty_sentinel: str = "[studio attachments]",
) -> str:
    """Full text for ``dlp_gate.gate`` (message + owner extracts)."""
    parts = attachment_extracts(user_id, upload_ids or [])
    text = combine_message_attachments(message, parts)
    if not str(text).strip():
        return empty_sentinel
    return text


def email_writer_scan_text(template_id: str, fields: Optional[dict]) -> str:
    """Message-only scan text for email writer (no uploads)."""
    parts = [f"template:{template_id}"]
    for _k, v in (fields or {}).items():
        if v is None:
            continue
        s = str(v).strip()
        if s:
            parts.append(s)
    return "\n\n".join(parts)


def cv_message_text(focus: str = "", jd_text: str = "") -> str:
    parts = []
    for s in (focus, jd_text):
        if (s or "").strip():
            parts.append(s.strip())
    return "\n\n".join(parts)


def research_message_text(query: str = "", focus: str = "") -> str:
    parts = []
    for s in (query, focus):
        if (s or "").strip():
            parts.append(s.strip())
    return "\n\n".join(parts)


def shop_message_text(
    need: str = "",
    qty: Any = 1,
    max_budget_toman: Any = None,
    notes: str = "",
) -> str:
    """Stable DLP body for shop assistant (FE must match byte-for-byte)."""
    parts = []
    if (need or "").strip():
        parts.append(need.strip())
    parts.append(f"qty:{qty}")
    if max_budget_toman is not None and str(max_budget_toman).strip() != "":
        parts.append(f"budget_toman:{max_budget_toman}")
    if (notes or "").strip():
        parts.append(notes.strip())
    return "\n\n".join(parts)


def meeting_action_pack_scan_text(
    meeting: Optional[dict],
    transcript: Optional[dict],
    summary: Optional[dict],
    *,
    max_chars: int = 200_000,
) -> str:
    """Stable DLP body for action-pack (FE+BE must match).

    Uses title + transcript plain + exec_summary only — not full seed —
    so FE can rebuild without speaker-map / minutes formatting drift.
    """
    title = ((meeting or {}).get("title") or "Untitled").strip() or "Untitled"
    lines = [f"# Meeting: {title}", ""]
    if transcript is not None:
        plain = ((transcript or {}).get("plain_text") or "").strip()
        if plain:
            lines.extend(["## Transcript", "", plain, ""])
    if summary is not None:
        exec_summary = ((summary or {}).get("exec_summary") or "").strip()
        if exec_summary:
            lines.extend(["## Summary", "", exec_summary, ""])
    text = "\n".join(lines).rstrip() + "\n"
    if len(text) > max_chars:
        text = text[:max_chars]
    return text if text.strip() else "[meeting action pack]"

