"""GET /{meeting_id}/stream — SSE pipeline status (poll-loop)."""
from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import Depends
from fastapi.responses import JSONResponse

from app.api.core import db, flask_core
from app.api.deps import feature_dep, require_active
from app.api.sse import sse_stream
from app.models.meeting import MEETING_STATUS, MeetingModel

from ._common import _sse_event, router

logger = logging.getLogger(__name__)

# Terminal statuses for SSE polling exit conditions.
_TERMINAL_STATUSES = {MEETING_STATUS['DONE'], MEETING_STATUS['FAILED']}
_IN_FLIGHT_STATUSES = {
    MEETING_STATUS['UPLOADED'],
    MEETING_STATUS['TRANSCRIBING'],
    MEETING_STATUS['SUMMARIZING'],
}
_POLL_INTERVAL_S = 1.0
_KEEPALIVE_INTERVAL_S = 15.0
_SSE_MAX_WALLCLOCK_S = 60 * 60  # safety: hang up after 1h on the SSE channel


@router.get("/{meeting_id}/stream")
def stream_status(
    meeting_id: str,
    user: dict = Depends(require_active),
    _feat: dict = Depends(feature_dep('meetings')),
):
    user_id = str(user['_id'])

    # Ownership check happens inside the flask_ctx context (still alive here).
    meeting = MeetingModel.find_owned(meeting_id, user_id)
    if not meeting:
        return JSONResponse({'error': 'Meeting not found'}, status_code=404)

    # The flask_ctx context is torn down when this handler returns — the
    # generator opens its OWN Flask context per poll (mirrors the Flask route's
    # `with app.app_context()` blocks). All request-scoped values are already
    # captured as locals (meeting_id) above.
    def generate():
        start_time = time.time()
        last_keepalive = start_time
        last_status: Optional[str] = None

        # Emit a synthetic "current state" event up-front so the client can
        # render an accurate UI immediately, regardless of which phase the
        # pipeline is in.
        try:
            with flask_core.app_context():
                try:
                    doc = MeetingModel.find_by_id(meeting_id) or {}
                finally:
                    db.session.remove()
            initial_status = doc.get('status')
            if initial_status is not None:
                last_status = initial_status
                yield _sse_event('phase_change', {
                    'status': initial_status,
                    'error_message': doc.get('error_message'),
                })
                if initial_status in _TERMINAL_STATUSES:
                    final_event = 'meeting_complete' if initial_status == MEETING_STATUS['DONE'] else 'error'
                    payload = {'status': initial_status, 'error_message': doc.get('error_message')}
                    yield _sse_event(final_event, payload)
                    return
        except Exception as exc:
            logger.exception("stream: initial poll failed for %s", meeting_id)
            yield _sse_event('error', {'message': str(exc), 'code': 'stream_init_failed'})
            return

        # Poll loop.
        while True:
            elapsed = time.time() - start_time
            if elapsed > _SSE_MAX_WALLCLOCK_S:
                yield _sse_event('error', {
                    'message': 'SSE wallclock exceeded',
                    'code': 'sse_timeout',
                })
                return

            now = time.time()
            if now - last_keepalive >= _KEEPALIVE_INTERVAL_S:
                yield ":keepalive\n\n"
                last_keepalive = now

            try:
                with flask_core.app_context():
                    try:
                        doc = MeetingModel.find_by_id(meeting_id) or {}
                    finally:
                        db.session.remove()
            except Exception as exc:
                logger.warning("stream: poll error for %s: %s", meeting_id, exc)
                time.sleep(_POLL_INTERVAL_S)
                continue

            status = doc.get('status')
            if status != last_status:
                last_status = status
                yield _sse_event('phase_change', {
                    'status': status,
                    'error_message': doc.get('error_message'),
                })

            if status == MEETING_STATUS['DONE']:
                yield _sse_event('meeting_complete', {'status': status})
                return
            if status == MEETING_STATUS['FAILED']:
                yield _sse_event('error', {
                    'status': status,
                    'error_message': doc.get('error_message'),
                })
                return

            if status not in _IN_FLIGHT_STATUSES:
                # Unknown / stale status — bail rather than loop forever.
                yield _sse_event('error', {
                    'message': f'Unknown status: {status!r}',
                    'code': 'unknown_status',
                })
                return

            time.sleep(_POLL_INTERVAL_S)

    return sse_stream(generate())
