"""POST /{meeting_id}/action-pack — second-pass FA/EN action pack."""
from __future__ import annotations

import logging

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from app.api.core import db
from app.api.deps import feature_dep, require_active
from app.models.meeting import MEETING_STATUS, MeetingModel
from app.models.meeting_summary import MeetingSummaryModel
from app.models.meeting_transcript import MeetingTranscriptModel
from app.services import dlp_gate, spend_gate
from app.services import meeting_action_pack_service

from ._common import router

logger = logging.getLogger(__name__)


@router.post("/{meeting_id}/action-pack")
async def action_pack_route(
    meeting_id: str,
    request: Request,
    user: dict = Depends(require_active),
    _feat: dict = Depends(feature_dep('meetings')),
):
    import anyio.to_thread

    user_id = str(user['_id'])
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}
    lang = (body.get('lang') or 'fa')[:2]
    if lang not in ('fa', 'en'):
        lang = 'fa'
    workspace_id = body.get('workspace_id')
    dlp_confirmed = bool(body.get('dlp_confirmed'))
    dlp_confirm_token = body.get('dlp_confirm_token')

    meeting = MeetingModel.find_owned(meeting_id, user_id)
    if not meeting:
        return JSONResponse({'error': 'Meeting not found', 'status': 404}, status_code=404)
    if meeting.get('status') != MEETING_STATUS['DONE']:
        return JSONResponse(
            {'error': 'meeting_not_ready', 'status': 400},
            status_code=400,
        )

    transcript = MeetingTranscriptModel.find_by_meeting(meeting_id)
    summary = MeetingSummaryModel.find_latest_for_meeting(meeting_id)
    from app.utils.studio_dlp import meeting_action_pack_scan_text
    # Stable FE-rebuildable body (title+transcript+exec) — not full seed.
    dlp_seed = meeting_action_pack_scan_text(meeting, transcript, summary)

    def _dlp() -> None:
        with db.session_scope():
            dlp_gate.gate(
                text=dlp_seed,
                user_id=user_id,
                workspace_id=workspace_id,
                project_id=None,
                source='meeting',
                source_ref={'feature': 'meeting_action_pack', 'meeting_id': meeting_id},
                confirmed=dlp_confirmed,
                dlp_confirm_token=dlp_confirm_token,
                user_lang=lang,
            )

    await anyio.to_thread.run_sync(_dlp)

    def _spend() -> None:
        spend_gate.gate(
            user_id=user_id,
            workspace_id=workspace_id,
            project_id=None,
            origin='web',
            feature='meeting_action_pack',
        )

    await anyio.to_thread.run_sync(_spend)

    def _run():
        with db.session_scope():
            return meeting_action_pack_service.generate_and_persist(
                meeting_id=meeting_id,
                user_id=user_id,
                lang=lang,
                workspace_id=workspace_id,
            )

    try:
        pack = await anyio.to_thread.run_sync(_run)
    except LookupError:
        return JSONResponse({'error': 'Meeting not found', 'status': 404}, status_code=404)
    except ValueError as exc:
        return JSONResponse({'error': str(exc), 'status': 400}, status_code=400)
    except RuntimeError as exc:
        return JSONResponse({'error': str(exc), 'status': 502}, status_code=502)
    except Exception as exc:  # noqa: BLE001
        logger.warning('action pack failed: %s', exc)
        return JSONResponse({'error': str(exc), 'status': 500}, status_code=500)

    return pack
