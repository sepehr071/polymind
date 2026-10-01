"""Meeting CRUD routes: upload, list, get, patch, delete, cancel, regenerate, speakers, media."""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Optional

from fastapi import Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.api.deps import feature_dep, require_active
from app.models.meeting import MEETING_STATUS, MeetingModel
from app.models.meeting_summary import MeetingSummaryModel
from app.models.meeting_transcript import MeetingTranscriptModel
from app.services import meeting_glossary, meeting_storage, meetings_pipeline, series_match
from app.services.meeting_storage import AudioTooLargeError
from app.settings import settings

from . import _common
from ._common import (
    _json_body,
    _serialize_meeting,
    _serialize_summary,
    _serialize_transcript,
    router,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# POST /upload — multipart, 500MB cap enforced by save_audio_stream.
# ---------------------------------------------------------------------------

@router.post("/upload")
def upload_meeting(
    file: UploadFile = File(...),
    title: str = Form(None),
    series_id: str = Form(None),
    meeting_brief: str = Form(None),
    num_speakers: str = Form(None),
    user: dict = Depends(require_active),
    _feat: dict = Depends(feature_dep('meetings')),
):
    """Multipart upload — Starlette spools the body to a SpooledTemporaryFile.

    Starlette's ``UploadFile.file`` is a *sync* file-like object; it is fed
    unchanged to ``meeting_storage.save_audio_stream`` (the 1 MB-chunked writer
    that enforces ``MEETING_MAX_AUDIO_BYTES`` and raises ``AudioTooLargeError``
    on overflow). There is no Flask ``MAX_CONTENT_LENGTH=16MB`` cap to bypass
    here — Starlette streams the whole body regardless.
    """
    user_id = str(user['_id'])

    max_bytes = int(settings.get('MEETING_MAX_AUDIO_BYTES', 500 * 1024 * 1024))

    if file is None or not file.filename:
        return JSONResponse({'error': "Missing 'file' multipart part"}, status_code=400)

    title = (title or '').strip() or None
    series_id = (series_id or '').strip() or None
    meeting_brief = (meeting_brief or '').strip() or None

    raw_num_speakers = (num_speakers or '').strip()
    num_speakers_val: Optional[int] = None
    if raw_num_speakers:
        try:
            ns = int(raw_num_speakers)
            num_speakers_val = ns if ns > 0 else None
        except ValueError:
            return JSONResponse({'error': 'num_speakers must be a positive integer'}, status_code=400)

    meeting_id = str(uuid.uuid4())

    try:
        # file.file = sync SpooledTemporaryFile (UNCHANGED into the writer).
        absolute_path, _ext, written_bytes = meeting_storage.save_audio_stream(
            file.file,
            meeting_id=meeting_id,
            user_id=user_id,
            content_type=file.content_type,
            filename=file.filename,
            max_bytes=max_bytes,
        )
    except AudioTooLargeError:
        return JSONResponse({
            'error': 'Audio file too large',
            'code': 'audio_too_large',
            'max_bytes': max_bytes,
        }, status_code=413)
    except OSError as exc:
        logger.exception("upload: filesystem failure for %s", meeting_id)
        return JSONResponse({'error': f'Failed to save audio: {exc}'}, status_code=500)

    duration_s = meeting_storage.probe_duration_seconds(absolute_path)

    create_data = {
        '_id': meeting_id,
        'original_filename': file.filename or 'audio',
        'audio_path': absolute_path,
        'title': title or file.filename or 'Untitled meeting',
        'duration_s': duration_s,
        'num_speakers': num_speakers_val,
        'meeting_brief': meeting_brief,
        'series_id': series_id,
        'status': MEETING_STATUS['UPLOADED'],
        'speakers': [],
    }

    try:
        MeetingModel.create(user_id, create_data)
    except Exception as exc:
        logger.exception("upload: failed to insert meeting doc")
        # Best-effort cleanup of the on-disk file before bubbling.
        try:
            Path(absolute_path).unlink(missing_ok=True)
        except Exception:
            pass
        return JSONResponse({'error': f'Failed to create meeting: {exc}'}, status_code=500)

    # Dispatch the background pipeline. Thread captures the current app.
    # Call via module attr so monkeypatch on package/_common takes effect.
    _common._dispatch_pipeline(meeting_id)

    meeting = MeetingModel.find_by_id(meeting_id)
    return JSONResponse({
        'message': 'Meeting upload accepted',
        'meeting': _serialize_meeting(meeting),
        'bytes_written': written_bytes,
    }, status_code=201)


# ---------------------------------------------------------------------------
# GET /list — list meetings for the current user.
# ---------------------------------------------------------------------------

_LIST_DEFAULT_LIMIT = 30
_LIST_MAX_LIMIT = 100


def _parse_pagination(request: Request) -> tuple[int, int]:
    """Clamp ``?limit=&offset=`` to sane bounds. Bad input falls back to defaults."""
    try:
        limit = int(request.query_params.get('limit', _LIST_DEFAULT_LIMIT))
    except (TypeError, ValueError):
        limit = _LIST_DEFAULT_LIMIT
    limit = max(1, min(limit, _LIST_MAX_LIMIT))

    try:
        offset = int(request.query_params.get('offset', 0))
    except (TypeError, ValueError):
        offset = 0
    offset = max(0, offset)
    return limit, offset


@router.get("/list")
def list_meetings(
    request: Request,
    user: dict = Depends(require_active),
    _feat: dict = Depends(feature_dep('meetings')),
):
    user_id = str(user['_id'])

    series_id = (request.query_params.get('series_id') or '').strip() or None
    q = (request.query_params.get('q') or '').strip() or None
    limit, offset = _parse_pagination(request)

    # Fetch limit+1 to derive has_more without a second COUNT query.
    rows = MeetingModel.list_for_user(
        user_id, series_id=series_id, q=q, skip=offset, limit=limit + 1,
    )
    has_more = len(rows) > limit
    meetings = rows[:limit]
    return {
        'meetings': [_serialize_meeting(m) for m in meetings],
        'has_more': has_more,
    }


# ---------------------------------------------------------------------------
# GET /suggest-series — fuzzy match incoming title against user's series.
# Declared BEFORE GET /{meeting_id} so the literal segment wins routing.
# ---------------------------------------------------------------------------

@router.get("/suggest-series")
def suggest_series_route(
    request: Request,
    user: dict = Depends(require_active),
    _feat: dict = Depends(feature_dep('meetings')),
):
    title = (request.query_params.get('title') or '').strip()
    if not title:
        return {'suggestion': None}

    suggestion = series_match.suggest_series(title, owner_id=user['_id'])
    if suggestion is None:
        return {'suggestion': None}

    return {
        'suggestion': {
            'series_id': suggestion.series_id,
            'name': suggestion.name,
            'score': suggestion.score,
        }
    }


# ---------------------------------------------------------------------------
# GET /{meeting_id}
# ---------------------------------------------------------------------------

@router.get("/{meeting_id}")
def get_meeting(
    meeting_id: str,
    user: dict = Depends(require_active),
    _feat: dict = Depends(feature_dep('meetings')),
):
    user_id = str(user['_id'])
    meeting = MeetingModel.find_owned(meeting_id, user_id)
    if not meeting:
        return JSONResponse({'error': 'Meeting not found'}, status_code=404)
    return {'meeting': _serialize_meeting(meeting)}


# ---------------------------------------------------------------------------
# PATCH /{meeting_id} — body {title?, series_id?}.
# ---------------------------------------------------------------------------

@router.patch("/{meeting_id}")
async def patch_meeting(
    meeting_id: str,
    request: Request,
    user: dict = Depends(require_active),
    _feat: dict = Depends(feature_dep('meetings')),
):
    user_id = str(user['_id'])

    meeting = MeetingModel.find_owned(meeting_id, user_id)
    if not meeting:
        return JSONResponse({'error': 'Meeting not found'}, status_code=404)

    data = await _json_body(request)
    update: dict = {}

    if 'title' in data:
        title = data.get('title')
        if title is None:
            update['title'] = None
        elif isinstance(title, str):
            update['title'] = title.strip() or None
        else:
            return JSONResponse({'error': 'title must be a string'}, status_code=400)

    if 'series_id' in data:
        series_id = data.get('series_id')
        if series_id is None or (isinstance(series_id, str) and series_id.strip() == ''):
            update['series_id'] = None
        elif isinstance(series_id, str):
            update['series_id'] = series_id.strip()
        else:
            return JSONResponse({'error': 'series_id must be a string or null'}, status_code=400)

    if not update:
        return JSONResponse({'error': 'No mutable fields supplied'}, status_code=400)

    MeetingModel.update(meeting_id, user_id, update)
    refreshed = MeetingModel.find_owned(meeting_id, user_id)
    return {'meeting': _serialize_meeting(refreshed)}


# ---------------------------------------------------------------------------
# DELETE /{meeting_id} — cascade audio + transcript + summaries.
# ---------------------------------------------------------------------------

@router.delete("/{meeting_id}")
def delete_meeting(
    meeting_id: str,
    user: dict = Depends(require_active),
    _feat: dict = Depends(feature_dep('meetings')),
):
    user_id = str(user['_id'])

    meeting = MeetingModel.find_owned(meeting_id, user_id)
    if not meeting:
        return JSONResponse({'error': 'Meeting not found'}, status_code=404)

    # Best-effort cleanup ordering: audio first, then transcript, then summaries,
    # finally the meeting doc itself.
    audio_path = meeting.get('audio_path')
    if audio_path:
        try:
            Path(audio_path).unlink(missing_ok=True)
        except Exception as exc:
            logger.warning("delete: failed to unlink audio %s: %s", audio_path, exc)

    try:
        MeetingTranscriptModel.delete(meeting_id)
    except Exception as exc:
        logger.warning("delete: transcript cascade failed for %s: %s", meeting_id, exc)

    try:
        MeetingSummaryModel.delete_for_meeting(meeting_id)
    except Exception as exc:
        logger.warning("delete: summaries cascade failed for %s: %s", meeting_id, exc)

    deleted = MeetingModel.delete(meeting_id, user_id)
    if not deleted:
        return JSONResponse({'error': 'Failed to delete meeting'}, status_code=500)

    return {'message': 'Meeting deleted'}


# ---------------------------------------------------------------------------
# GET /{meeting_id}/transcript
# ---------------------------------------------------------------------------

@router.get("/{meeting_id}/transcript")
def get_transcript(
    meeting_id: str,
    request: Request,
    user: dict = Depends(require_active),
    _feat: dict = Depends(feature_dep('meetings')),
):
    user_id = str(user['_id'])
    if not MeetingModel.find_owned(meeting_id, user_id):
        return JSONResponse({'error': 'Meeting not found'}, status_code=404)
    transcript = MeetingTranscriptModel.find_by_meeting(meeting_id)
    if not transcript:
        return JSONResponse({'error': 'Transcript not available yet'}, status_code=404)
    include_words = request.query_params.get('include') == 'words'
    return {'transcript': _serialize_transcript(transcript, include_words=include_words)}


# ---------------------------------------------------------------------------
# GET /{meeting_id}/summary — latest summary doc.
# ---------------------------------------------------------------------------

@router.get("/{meeting_id}/summary")
def get_summary(
    meeting_id: str,
    user: dict = Depends(require_active),
    _feat: dict = Depends(feature_dep('meetings')),
):
    user_id = str(user['_id'])
    if not MeetingModel.find_owned(meeting_id, user_id):
        return JSONResponse({'error': 'Meeting not found'}, status_code=404)
    summary = MeetingSummaryModel.find_latest_for_meeting(meeting_id)
    if not summary:
        return JSONResponse({'error': 'Summary not available yet'}, status_code=404)
    return {'summary': _serialize_summary(summary)}


# ---------------------------------------------------------------------------
# GET /{meeting_id}/audio — owner-only file stream (404 not 403).
# ---------------------------------------------------------------------------

@router.get("/{meeting_id}/audio")
def get_audio(
    meeting_id: str,
    user: dict = Depends(require_active),
    _feat: dict = Depends(feature_dep('meetings')),
):
    user_id = str(user['_id'])

    meeting = MeetingModel.find_owned(meeting_id, user_id)
    if not meeting:
        return JSONResponse({'error': 'Meeting not found'}, status_code=404)

    audio_path = meeting.get('audio_path')
    if not audio_path:
        return JSONResponse({'error': 'Meeting not found'}, status_code=404)

    path = Path(audio_path)
    if not path.is_file():
        return JSONResponse({'error': 'Meeting not found'}, status_code=404)

    # send_from_directory -> FileResponse (Starlette streams the file).
    return FileResponse(str(path), filename=path.name)


# ---------------------------------------------------------------------------
# PATCH /{meeting_id}/speakers/{speaker_id} — rename one embedded speaker.
# ---------------------------------------------------------------------------

@router.patch("/{meeting_id}/speakers/{speaker_id}")
async def rename_speaker(
    meeting_id: str,
    speaker_id: str,
    request: Request,
    user: dict = Depends(require_active),
    _feat: dict = Depends(feature_dep('meetings')),
):
    user_id = str(user['_id'])

    meeting = MeetingModel.find_owned(meeting_id, user_id)
    if not meeting:
        return JSONResponse({'error': 'Meeting not found'}, status_code=404)

    data = await _json_body(request)
    raw = data.get('display_name')
    display_name: Optional[str]
    if raw is None:
        display_name = None
    elif isinstance(raw, str):
        display_name = raw.strip() or None
    else:
        return JSONResponse({'error': 'display_name must be a string or null'}, status_code=400)

    MeetingModel.set_speaker_name(meeting_id, speaker_id, display_name)

    # Sync to series glossary + speaker-name memory if this meeting belongs
    # to a recurring series (matches the upstream rename UX).
    series_id = meeting.get('series_id')
    if series_id and display_name:
        try:
            meeting_glossary.upsert_speaker_name(series_id, display_name)
        except Exception as exc:
            logger.warning("rename_speaker: speaker_name memory upsert failed: %s", exc)
        try:
            meeting_glossary.add_suggested_terms(series_id, [display_name])
        except Exception as exc:
            logger.warning("rename_speaker: glossary suggestion push failed: %s", exc)

    refreshed = MeetingModel.find_owned(meeting_id, user_id)
    return {'meeting': _serialize_meeting(refreshed)}


# ---------------------------------------------------------------------------
# POST /{meeting_id}/cancel — synchronous status flip + signal pipeline.
# ---------------------------------------------------------------------------

@router.post("/{meeting_id}/cancel")
def cancel_meeting(
    meeting_id: str,
    user: dict = Depends(require_active),
    _feat: dict = Depends(feature_dep('meetings')),
):
    user_id = str(user['_id'])

    meeting = MeetingModel.find_owned(meeting_id, user_id)
    if not meeting:
        return JSONResponse({'error': 'Meeting not found'}, status_code=404)

    current_status = meeting.get('status')
    if current_status == MEETING_STATUS['DONE']:
        return JSONResponse({'error': 'Meeting already complete; cannot cancel'}, status_code=409)

    # Sync flip for instant UI feedback. The pipeline reads CANCELLED_SENTINEL
    # on the error_message field to distinguish a user cancel from a real fail.
    MeetingModel.set_status(
        meeting_id, MEETING_STATUS['FAILED'],
        error_message=meetings_pipeline.CANCELLED_SENTINEL,
    )
    meetings_pipeline.request_cancel(meeting_id)

    refreshed = MeetingModel.find_owned(meeting_id, user_id)
    return {'meeting': _serialize_meeting(refreshed)}


# ---------------------------------------------------------------------------
# POST /{meeting_id}/regenerate-summary
# ---------------------------------------------------------------------------

@router.post("/{meeting_id}/regenerate-summary")
def regenerate_summary_route(
    meeting_id: str,
    user: dict = Depends(require_active),
    _feat: dict = Depends(feature_dep('meetings')),
):
    user_id = str(user['_id'])

    meeting = MeetingModel.find_owned(meeting_id, user_id)
    if not meeting:
        return JSONResponse({'error': 'Meeting not found'}, status_code=404)

    transcript = MeetingTranscriptModel.find_by_meeting(meeting_id)
    if not transcript:
        return JSONResponse({'error': 'Cannot regenerate: no transcript for this meeting'}, status_code=400)

    # Sync flip so the UI sees `summarizing` immediately.
    MeetingModel.set_status(
        meeting_id, MEETING_STATUS['SUMMARIZING'], error_message=None,
    )

    _common._dispatch_regenerate(meeting_id)

    refreshed = MeetingModel.find_owned(meeting_id, user_id)
    return JSONResponse({
        'message': 'Summary regeneration started',
        'meeting': _serialize_meeting(refreshed),
    }, status_code=202)
