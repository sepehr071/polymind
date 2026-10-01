"""Meeting action pack — generate + persist on latest summary."""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Dict, Optional

from app.extensions import db
from app.models.meeting import MeetingModel
from app.models.meeting_summary import MeetingSummary, MeetingSummaryModel
from app.models.meeting_transcript import MeetingTranscriptModel
from app.prompts.meeting_action_pack import (
    ACTION_PACK_FEATURE,
    ACTION_PACK_MODEL,
    build_system_prompt,
    build_user_message,
)
from app.services.meetings_service import build_seed_text
from app.services.openrouter_service import OpenRouterService
from app.services.ocr_service import _content_text

logger = logging.getLogger(__name__)


def _parse_json(raw: str) -> dict:
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end != -1:
        raw = raw[start : end + 1]
    return json.loads(raw)


def generate_and_persist(
    *,
    meeting_id: str,
    user_id: str,
    lang: str = "fa",
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    meeting = MeetingModel.find_owned(meeting_id, user_id)
    if not meeting:
        raise LookupError("meeting_not_found")
    if meeting.get("status") != "done":
        raise ValueError("meeting_not_ready")

    transcript = MeetingTranscriptModel.find_by_meeting(meeting_id)
    summary = MeetingSummaryModel.find_latest_for_meeting(meeting_id)
    seed = build_seed_text(meeting, transcript, summary)

    result = OpenRouterService.chat_completion(
        messages=[{"role": "user", "content": build_user_message(seed_text=seed)}],
        model=ACTION_PACK_MODEL,
        system_prompt=build_system_prompt(lang=lang),
        temperature=0.2,
        max_tokens=4000,
        stream=False,
        user_id=user_id,
        feature=ACTION_PACK_FEATURE,
        workspace_id=workspace_id,
        project_id=None,
        origin="web",
        timeout=90,
    )
    raw = _content_text(result)
    try:
        parsed = _parse_json(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("action pack parse failed: %s", exc)
        raise RuntimeError("action_pack_parse_failed") from exc

    action_items = parsed.get("action_items") or []
    decisions = parsed.get("decisions") or []
    email = parsed.get("email") or {}
    if not isinstance(email, dict):
        email = {}
    memo = (parsed.get("memo") or "").strip()
    email_body = (email.get("body") or "").strip()
    email_subject = (email.get("subject") or "").strip()
    tone = email.get("tone") if email.get("tone") in ("formal", "casual") else "formal"

    # Persist onto latest summary row (or create minimal row)
    if summary:
        sid = summary.get("_id") or summary.get("id")
        row = db.session.get(MeetingSummary, uuid.UUID(str(sid)))
        if row:
            row.action_items = list(action_items)
            row.decisions = list(decisions)
            row.email_draft = email_body or row.email_draft
            row.tone = tone
            row.memo = memo
            row.model_used = ACTION_PACK_MODEL
            # stash subject in speaker_names? No — prepend subject into email body if needed
            if email_subject and email_body and not email_body.startswith(email_subject):
                row.email_draft = f"Subject: {email_subject}\n\n{email_body}"
            db.session.commit()
    else:
        MeetingSummaryModel.create(
            meeting_id,
            {
                "exec_summary": "",
                "action_items": list(action_items),
                "decisions": list(decisions),
                "email_draft": (
                    f"Subject: {email_subject}\n\n{email_body}" if email_subject else email_body
                ),
                "email_tone": tone,
                "model": ACTION_PACK_MODEL,
                "memo": memo,
            },
        )

    return {
        "action_items": action_items,
        "decisions": decisions,
        "email": {"subject": email_subject, "body": email_body, "tone": tone},
        "memo": memo,
        "model": ACTION_PACK_MODEL,
        "lang": lang if lang in ("fa", "en") else "fa",
    }
