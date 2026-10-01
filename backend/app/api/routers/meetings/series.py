"""Meeting-series router routes — plain CRUD + glossary."""
from __future__ import annotations

import logging

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from app.api.deps import feature_dep, require_active
from app.models.meeting import MeetingModel
from app.models.meeting_series import (
    VALID_EMAIL_TONES,
    VALID_KEYTERM_SOURCES,
    KeytermModel,
    MeetingSeriesModel,
    SpeakerNameModel,
)
from app.services import meeting_glossary
from app.utils.helpers import serialize_doc

from ._common import _json_body, series_router

logger = logging.getLogger(__name__)


def _serialize(doc) -> dict:
    return serialize_doc(doc)


def _owned_series_or_404(series_id: str, user_id: str):
    """Return (series, error_response). error_response is a JSONResponse or None."""
    series = MeetingSeriesModel.find_owned(series_id, user_id)
    if not series:
        return None, JSONResponse({'error': 'Series not found'}, status_code=404)
    return series, None


# ---------------------------------------------------------------------------
# GET /list — list series w/ meeting count.
# ---------------------------------------------------------------------------

@series_router.get("/list")
def list_series(
    user: dict = Depends(require_active),
    _feat: dict = Depends(feature_dep('meetings')),
):
    user_id = str(user['_id'])

    series_list = MeetingSeriesModel.list_for_user(user_id)

    # Decorate w/ meeting_count — ONE grouped COUNT for the whole batch
    # (was an N+1: one count query per series).
    series_ids = [s.get('_id') for s in series_list if s.get('_id')]
    try:
        count_map = MeetingModel.count_by_series_for_owner(user_id, series_ids)
    except Exception as exc:
        logger.warning("list_series: batch count failed: %s", exc)
        count_map = {}

    out = []
    for s in series_list:
        item = _serialize(s)
        item['meeting_count'] = count_map.get(str(s.get('_id')), 0)
        out.append(item)

    return {'series': out}


# ---------------------------------------------------------------------------
# POST /create — create series. 409 on duplicate (owner_id, name).
# ---------------------------------------------------------------------------

@series_router.post("/create")
async def create_series(
    request: Request,
    user: dict = Depends(require_active),
    _feat: dict = Depends(feature_dep('meetings')),
):
    from sqlalchemy.exc import IntegrityError

    user_id = str(user['_id'])

    data = await _json_body(request)
    name = (data.get('name') or '').strip()
    if not name:
        return JSONResponse({'error': 'name is required'}, status_code=400)
    if len(name) > 200:
        return JSONResponse({'error': 'name must be ≤ 200 characters'}, status_code=400)

    email_tone_raw = data.get('email_tone', 'formal')
    if email_tone_raw not in VALID_EMAIL_TONES:
        return JSONResponse({
            'error': f"email_tone must be one of {sorted(VALID_EMAIL_TONES)}",
        }, status_code=400)

    try:
        series_id = MeetingSeriesModel.create(user_id, {
            'name': name,
            'email_tone': email_tone_raw,
        })
    except IntegrityError:
        return JSONResponse({'error': 'A series with this name already exists', 'code': 'duplicate_name'}, status_code=409)

    series = MeetingSeriesModel.find_by_id(series_id)
    return JSONResponse({'series': _serialize(series)}, status_code=201)


# ---------------------------------------------------------------------------
# GET /{series_id}
# ---------------------------------------------------------------------------

@series_router.get("/{series_id}")
def get_series(
    series_id: str,
    user: dict = Depends(require_active),
    _feat: dict = Depends(feature_dep('meetings')),
):
    user_id = str(user['_id'])
    series, err = _owned_series_or_404(series_id, user_id)
    if err:
        return err
    return {'series': _serialize(series)}


# ---------------------------------------------------------------------------
# PATCH /{series_id}
# ---------------------------------------------------------------------------

@series_router.patch("/{series_id}")
async def update_series(
    series_id: str,
    request: Request,
    user: dict = Depends(require_active),
    _feat: dict = Depends(feature_dep('meetings')),
):
    from sqlalchemy.exc import IntegrityError

    user_id = str(user['_id'])

    series, err = _owned_series_or_404(series_id, user_id)
    if err:
        return err

    data = await _json_body(request)
    update: dict = {}

    if 'name' in data:
        name = (data.get('name') or '').strip()
        if not name:
            return JSONResponse({'error': 'name cannot be empty'}, status_code=400)
        if len(name) > 200:
            return JSONResponse({'error': 'name must be ≤ 200 characters'}, status_code=400)
        update['name'] = name

    if 'email_tone' in data:
        tone = data.get('email_tone')
        if tone not in VALID_EMAIL_TONES:
            return JSONResponse({
                'error': f"email_tone must be one of {sorted(VALID_EMAIL_TONES)}",
            }, status_code=400)
        update['email_tone'] = tone

    if not update:
        return JSONResponse({'error': 'No mutable fields supplied'}, status_code=400)

    try:
        MeetingSeriesModel.update(series_id, user_id, update)
    except IntegrityError:
        return JSONResponse({'error': 'A series with this name already exists', 'code': 'duplicate_name'}, status_code=409)

    refreshed = MeetingSeriesModel.find_owned(series_id, user_id)
    return {'series': _serialize(refreshed)}


# ---------------------------------------------------------------------------
# DELETE /{series_id} — cascade keyterms + speaker_names + unset meetings.series_id.
# ---------------------------------------------------------------------------

@series_router.delete("/{series_id}")
def delete_series(
    series_id: str,
    user: dict = Depends(require_active),
    _feat: dict = Depends(feature_dep('meetings')),
):
    user_id = str(user['_id'])

    series, err = _owned_series_or_404(series_id, user_id)
    if err:
        return err

    try:
        KeytermModel.delete_for_series(series_id)
    except Exception as exc:
        logger.warning("delete_series: keyterm cascade failed for %s: %s", series_id, exc)
    try:
        SpeakerNameModel.delete_for_series(series_id)
    except Exception as exc:
        logger.warning("delete_series: speaker_names cascade failed for %s: %s", series_id, exc)
    try:
        MeetingModel.null_series_for_owner(user_id, series_id)
    except Exception as exc:
        logger.warning("delete_series: meetings unset failed for %s: %s", series_id, exc)

    deleted = MeetingSeriesModel.delete(series_id, user_id)
    if not deleted:
        return JSONResponse({'error': 'Failed to delete series'}, status_code=500)

    return {'message': 'Series deleted'}


# ---------------------------------------------------------------------------
# GET /{series_id}/keyterms?source=manual|suggested|accepted
# ---------------------------------------------------------------------------

@series_router.get("/{series_id}/keyterms")
def list_keyterms(
    series_id: str,
    request: Request,
    user: dict = Depends(require_active),
    _feat: dict = Depends(feature_dep('meetings')),
):
    user_id = str(user['_id'])
    series, err = _owned_series_or_404(series_id, user_id)
    if err:
        return err

    source = (request.query_params.get('source') or '').strip() or None
    if source and source not in VALID_KEYTERM_SOURCES:
        return JSONResponse({
            'error': f"source must be one of {sorted(VALID_KEYTERM_SOURCES)}",
        }, status_code=400)

    terms = meeting_glossary.list_keyterms(series_id, source=source)
    return {'keyterms': [_serialize(t) for t in terms]}


# ---------------------------------------------------------------------------
# POST /{series_id}/keyterms — add manual term (promotes SUGGESTED → MANUAL).
# ---------------------------------------------------------------------------

@series_router.post("/{series_id}/keyterms")
async def add_keyterm(
    series_id: str,
    request: Request,
    user: dict = Depends(require_active),
    _feat: dict = Depends(feature_dep('meetings')),
):
    user_id = str(user['_id'])
    series, err = _owned_series_or_404(series_id, user_id)
    if err:
        return err

    data = await _json_body(request)
    term = (data.get('term') or '').strip()
    if not term:
        return JSONResponse({'error': 'term is required'}, status_code=400)

    doc = meeting_glossary.add_manual_term(series_id, term)
    if doc is None:
        return JSONResponse({'error': 'term failed validation (length/word-count/numeric-only)'}, status_code=400)

    return JSONResponse({'keyterm': _serialize(doc)}, status_code=201)


# ---------------------------------------------------------------------------
# POST /{series_id}/keyterms/{term_id}/accept
# ---------------------------------------------------------------------------

@series_router.post("/{series_id}/keyterms/{term_id}/accept")
def accept_keyterm(
    series_id: str,
    term_id: str,
    user: dict = Depends(require_active),
    _feat: dict = Depends(feature_dep('meetings')),
):
    user_id = str(user['_id'])
    series, err = _owned_series_or_404(series_id, user_id)
    if err:
        return err

    term = KeytermModel.find_by_id(term_id)
    if not term or term.get('series_id') != series_id:
        return JSONResponse({'error': 'Keyterm not found'}, status_code=404)

    ok = meeting_glossary.accept_term(term_id)
    if not ok:
        return JSONResponse({'error': 'Failed to accept keyterm'}, status_code=500)

    refreshed = KeytermModel.find_by_id(term_id)
    return {'keyterm': _serialize(refreshed)}


# ---------------------------------------------------------------------------
# DELETE /{series_id}/keyterms/{term_id} — reject = delete.
# ---------------------------------------------------------------------------

@series_router.delete("/{series_id}/keyterms/{term_id}")
def reject_keyterm(
    series_id: str,
    term_id: str,
    user: dict = Depends(require_active),
    _feat: dict = Depends(feature_dep('meetings')),
):
    user_id = str(user['_id'])
    series, err = _owned_series_or_404(series_id, user_id)
    if err:
        return err

    term = KeytermModel.find_by_id(term_id)
    if not term or term.get('series_id') != series_id:
        return JSONResponse({'error': 'Keyterm not found'}, status_code=404)

    ok = meeting_glossary.reject_term(term_id)
    if not ok:
        return JSONResponse({'error': 'Failed to delete keyterm'}, status_code=500)

    return {'message': 'Keyterm deleted'}


# ---------------------------------------------------------------------------
# GET /{series_id}/speaker-names
# ---------------------------------------------------------------------------

@series_router.get("/{series_id}/speaker-names")
def list_speaker_names(
    series_id: str,
    user: dict = Depends(require_active),
    _feat: dict = Depends(feature_dep('meetings')),
):
    user_id = str(user['_id'])
    series, err = _owned_series_or_404(series_id, user_id)
    if err:
        return err

    rows = SpeakerNameModel.list_for_series(series_id)
    return {'speaker_names': [_serialize(r) for r in rows]}
