"""CV checker — SSE run."""
from __future__ import annotations

import json
import logging

import anyio.to_thread
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.core import db
from app.api.deps import current_user, feature_dep, flask_ctx
from app.api.sse import sse_stream_sync
from app.prompts.cv_checker import CV_CHECKER_LANGS, CV_CHECKER_MODES
from app.services import cv_checker_service, dlp_gate, spend_gate, stream_concurrency
from app.utils.studio_dlp import cv_message_text, gate_text

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(flask_ctx)])

_MAX_CONCURRENT_STREAMS = 3


async def _json_body(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def _sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _uid(user) -> str:
    return str(user["_id"]) if isinstance(user, dict) else str(user.id)


@router.post("/run")
async def run(
    request: Request,
    user: dict = Depends(current_user),
    _feat: dict = Depends(feature_dep("cv_checker")),
):
    body = await _json_body(request)
    mode = (body.get("mode") or "screen").strip()
    if mode not in CV_CHECKER_MODES:
        return JSONResponse({"error": "mode must be screen|improve", "status": 400}, status_code=400)
    lang = (body.get("lang") or "fa")[:2]
    if lang not in CV_CHECKER_LANGS:
        lang = "fa"
    cv_upload_id = str(body.get("cv_upload_id") or "").strip()
    if not cv_upload_id:
        return JSONResponse({"error": "cv_upload_id is required", "status": 400}, status_code=400)
    jd_text = body.get("jd_text") or ""
    if not isinstance(jd_text, str):
        jd_text = str(jd_text)
    if len(jd_text) > 50000:
        jd_text = jd_text[:50000]
    jd_upload_id = body.get("jd_upload_id")
    jd_upload_id = str(jd_upload_id).strip() if jd_upload_id else None
    focus = body.get("focus") or ""
    if not isinstance(focus, str):
        focus = str(focus)
    workspace_id = body.get("workspace_id")
    project_id = body.get("project_id")
    dlp_confirmed = bool(body.get("dlp_confirmed"))
    dlp_confirm_token = body.get("dlp_confirm_token")
    user_id = _uid(user)

    def _dlp() -> None:
        with db.session_scope():
            upload_ids = [cv_upload_id] + ([jd_upload_id] if jd_upload_id else [])
            text = gate_text(
                cv_message_text(focus, jd_text),
                user_id,
                upload_ids,
                empty_sentinel="[cv attachment]",
            )
            dlp_gate.gate(
                text=text,
                user_id=user_id,
                workspace_id=workspace_id,
                project_id=project_id,
                source="cv_checker",
                source_ref={"feature": "cv_checker", "mode": mode, "cv_upload_id": cv_upload_id},
                confirmed=dlp_confirmed,
                dlp_confirm_token=dlp_confirm_token,
                user_lang=lang,
            )

    await anyio.to_thread.run_sync(_dlp)

    def _spend() -> None:
        spend_gate.gate(
            user_id=user_id,
            workspace_id=workspace_id,
            project_id=project_id,
            origin="web",
            feature="cv_checker",
        )

    await anyio.to_thread.run_sync(_spend)

    preflight = stream_concurrency.StreamPreflight(user_id, _MAX_CONCURRENT_STREAMS)
    if not preflight.reserve():
        return JSONResponse(
            {"error": "too_many_streams", "status": 429},
            status_code=429,
            headers={"Retry-After": "5"},
        )
    if not preflight.acquire_global():
        with preflight:
            return JSONResponse(
                {"error": "server_busy", "status": 503},
                status_code=503,
                headers={"Retry-After": "5"},
            )

    def _produce(stop_event):
        with db.session_scope():
            try:
                yield _sse("status", {"phase": "extracting"})
                if stop_event.is_set():
                    return
                yield _sse("status", {"phase": "analyzing"})
                pack = cv_checker_service.run_check(
                    mode=mode,
                    lang=lang,
                    cv_upload_id=cv_upload_id,
                    jd_text=jd_text,
                    jd_upload_id=jd_upload_id,
                    focus=focus,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    user_id=user_id,
                )
                if stop_event.is_set():
                    return
                yield _sse("done", pack)
            except ValueError as exc:
                yield _sse("error", {"error": str(exc), "status": 400})
            except Exception as exc:  # noqa: BLE001
                logger.warning("cv_checker failed: %s", exc)
                yield _sse("error", {"error": str(exc), "status": 500})

    with preflight:
        preflight.hand_off()
        return sse_stream_sync(
            _produce, runner_name="cv-checker-runner", on_close=preflight.on_close,
        )
