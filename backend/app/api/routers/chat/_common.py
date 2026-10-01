"""Shared chat router instance + cross-route helpers.

Route modules import ``router`` from here and register with ``@router.post(...)``.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.deps import flask_ctx
from app.models.upload import UploadModel
from app.services.chat_attachments import (
    DATA_FILE_EXTS as _DATA_FILE_EXTS,
    attachment_text_for_dlp as _attachment_text_for_dlp,
    filter_owned_attachments as _filter_owned_attachments,
    is_data_attachment as _is_data_attachment,
)
from app.services.chat_artifacts import (
    append_artifact_recaps as _append_artifact_recaps,
    format_tool_result_for_model as _format_tool_result_for_model,
    persist_file_artifacts as _persist_file_artifacts,
    prune_dead_file_artifacts as _prune_dead_file_artifacts,
    summarize_artifacts as _summarize_artifacts,
)
from app.services.dlp_gate import gate_redactable
from app.services.dlp_service import DLPDetector

# Per-user concurrent-stream cap (DB connection-pool exhaustion DoS guard). Each
# in-flight SSE pins a psycopg3 connection; this bounds how many a single user
# can hold at once (a point-read speed-bump — a tiny race is acceptable).
_MAX_CONCURRENT_STREAMS = 3

# Router-level dependency: every request runs inside the Flask app_context.
router = APIRouter(dependencies=[Depends(flask_ctx)])

_KEEPALIVE_INTERVAL = 15        # seconds between keepalive SSE comments
_MAX_WALLCLOCK_SECONDS = 1800   # 30-minute hard cap on a single stream

_logger = logging.getLogger("app.api.routers.chat")

# web_fetch auto-enables whenever the user's message text contains a URL — it is
# derived from the actual text on every turn (send/edit/regen), never a body flag
# and never persisted to metadata.
_URL_RE = re.compile(r'https?://', re.I)


def _text_has_url(text) -> bool:
    return bool(text and _URL_RE.search(str(text)))


async def _json_body(request: Request) -> dict:
    """Read the JSON body, tolerating empty/garbage like get_json(silent=True)."""
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def _sse_event(event_type: str, data: dict) -> str:
    """Format data as an SSE event frame."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"  # noqa: intentional SSE framing


def _resolve_user_lang(data: dict, user: dict) -> str:
    """Resolve the 2-char UI language for DLP smart-scan reason phrasing.

    Prefers the explicit request-body ``lang`` (i18next current language), then
    ``user.ai_preferences.user_info.language``, finally ``en``.
    """
    body_lang = (data.get("lang") or "").strip()
    return (
        body_lang
        or user.get("ai_preferences", {}).get("user_info", {}).get("language", "en")
        or "en"
    )[:2].lower()


def _gate_and_redact_chat_turn(
    *,
    user: dict,
    workspace_id,
    project_id,
    message_content: str,
    attachments: list,
    force_redact: bool,
    confirmed: bool,
    dlp_confirm_token,
    user_lang: str,
    source_ref: dict,
) -> dict:
    """Synchronous DLP chokepoint for a chat turn — run this in a worker thread.

    Runs ``gate_redactable`` over the message PLUS extractable attachment text
    (so block/warn covers attachment content too, and one ``dlp_event``
    is logged). In enforce mode it raises ``DLPBlockedError`` unchanged. In
    redact mode it scrubs the message body and each NON-PDF attachment's
    extracted text INDEPENDENTLY (placeholders numbered per field), returning the
    scrubbed values + a small badge dict for the UI.

    Returns ``{message_content, attachments, badge}`` where ``badge`` is
    ``{'count': int, 'labels': [str]} | None``.
    """
    from app.services.chat_attachments import load_attachment_extracted_text

    attachment_text = _attachment_text_for_dlp(attachments, user_id=user["_id"])
    dlp_text = (
        f"{message_content}\n\n{attachment_text}" if attachment_text else message_content
    )
    gate_res = gate_redactable(
        text=dlp_text,
        user_id=user["_id"],
        workspace_id=workspace_id,
        project_id=project_id,
        source="chat",
        source_ref=source_ref,
        force_redact=force_redact,
        confirmed=confirmed,
        dlp_confirm_token=dlp_confirm_token,
        user_lang=user_lang,
    )

    if not gate_res.get("redacted"):
        return {"message_content": message_content, "attachments": attachments, "badge": None}

    # Re-redact each field on its own so placeholders are numbered independently
    # of the combined scan above (which exists only for the event log).
    detector = DLPDetector.from_workspace(str(workspace_id))
    labels: list[str] = []
    count = 0

    msg_red, msg_redactions, _ = detector.redact(
        message_content, user_lang=user_lang, user_id=user["_id"],
    )
    for r in msg_redactions:
        count += 1
        labels.append(r["label"])

    redacted_attachments: list = []
    for att in attachments or []:
        if not isinstance(att, dict):
            redacted_attachments.append(att)
            continue
        att_copy = dict(att)
        # Load OWNER-SCOPED server extract (never client extracted_text).
        att_text = load_attachment_extracted_text(att_copy, user["_id"])
        # PDFs are OCR'd model-side (excluded v1) — leave them untouched.
        if not att_copy.get("is_pdf") and att_text:
            a_red, a_redactions, _ = detector.redact(
                str(att_text), user_lang=user_lang, user_id=user["_id"],
            )
            if a_redactions:
                # Server-only field preferred by OpenRouter formatter + DLP rejoin.
                att_copy["_dlp_extracted_text"] = a_red
                for r in a_redactions:
                    count += 1
                    labels.append(r["label"])
            else:
                att_copy["_dlp_extracted_text"] = att_text
        redacted_attachments.append(att_copy)

    badge = {"count": count, "labels": labels} if count else None
    return {
        "message_content": msg_red,
        "attachments": redacted_attachments,
        "badge": badge,
    }

