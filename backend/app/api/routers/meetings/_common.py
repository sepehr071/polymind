"""Shared meetings router objects + helpers."""
from __future__ import annotations

import json
import logging
import threading

from fastapi import APIRouter, Depends, Request

from app.api.deps import flask_ctx
from app.services import meetings_pipeline
from app.utils.helpers import serialize_doc

logger = logging.getLogger(__name__)

# Router-level dependencies: Flask app_context + the meetings feature gate.
# Auth (current_user) is taken per-route below so it resolves to the user dict.
router = APIRouter(dependencies=[Depends(flask_ctx)])
series_router = APIRouter(dependencies=[Depends(flask_ctx)])


async def _json_body(request: Request) -> dict:
    """Read the request JSON body, tolerating empty/garbage like get_json(silent=True)."""
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def _serialize_meeting(doc: dict) -> dict:
    """Render a meeting doc as JSON-safe dict. ObjectId/datetime → str/iso."""
    return serialize_doc(doc)


def _serialize_summary(doc: dict) -> dict:
    raw = serialize_doc(doc)
    out: dict = dict(raw) if isinstance(raw, dict) else {}
    # Frontend contract uses unsuffixed list field names; DB stores `*_json`.
    for src, dst in (
        ('action_items_json', 'action_items'),
        ('decisions_json', 'decisions'),
        ('minutes_json', 'minutes'),
        ('qa_json', 'qa'),
        ('open_questions_json', 'open_questions'),
    ):
        if src in out:
            out[dst] = out.pop(src)
    return out


def _serialize_transcript(doc: dict, *, include_words: bool = False) -> dict:
    """Render a transcript doc as JSON-safe dict.

    By default the heavy per-word ``words_json`` + provider ``raw_json`` blobs
    (multi-MB for long meetings) are stripped — the FE transcript view reads
    only ``plain_text``, and minutes are served pre-segmented off the summary.
    Pass ``include_words=True`` (via ``?include=words``) to keep them.
    """
    out = serialize_doc(doc)
    if not include_words and isinstance(out, dict):
        out.pop('words_json', None)
        out.pop('raw_json', None)
    return out


def _run_in_ctx(fn, *args) -> None:
    """Run a pipeline entrypoint in the background thread.

    The pipeline functions (``run_pipeline`` / ``regenerate_summary``) own their
    OWN short-lived ``db.session_scope()`` around each discrete DB unit, so NO
    pool connection is pinned across the multi-minute ElevenLabs transcription
    or summarizer LLM calls. This wrapper only converts an unexpected crash into
    a log line (the pipeline already records FAILED on its own error paths).
    """
    try:
        fn(*args)
    except Exception:
        logger.exception("background thread crashed in %s", fn.__name__)


def _dispatch_pipeline(meeting_id: str) -> None:
    """Spawn a daemon thread running the pipeline in its own DB-session scope."""
    thread = threading.Thread(
        target=_run_in_ctx,
        args=(meetings_pipeline.run_pipeline, meeting_id),
        daemon=True,
    )
    thread.start()


def _dispatch_regenerate(meeting_id: str) -> None:
    thread = threading.Thread(
        target=_run_in_ctx,
        args=(meetings_pipeline.regenerate_summary, meeting_id),
        daemon=True,
    )
    thread.start()


def _sse_event(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, default=str)}\n\n"
