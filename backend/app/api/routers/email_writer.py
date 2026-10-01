"""Email / letter writer — SSE generate."""
from __future__ import annotations

import json
import logging

import anyio.to_thread
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.core import db
from app.api.deps import current_user, feature_dep, flask_ctx
from app.api.sse import sse_stream_sync
from app.prompts.email_writer import TEMPLATE_IDS, TONES, LANGS
from app.services import dlp_gate, email_writer_service, spend_gate, stream_concurrency
from app.utils.studio_dlp import email_writer_scan_text

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


@router.post("/generate")
async def generate(
    request: Request,
    user: dict = Depends(current_user),
    _feat: dict = Depends(feature_dep("email_writer")),
):
    body = await _json_body(request)
    template_id = (body.get("template_id") or "").strip()
    if template_id not in TEMPLATE_IDS:
        return JSONResponse(
            {"error": f"unknown template_id (allowed: {sorted(TEMPLATE_IDS)})", "status": 400},
            status_code=400,
        )
    fields = body.get("fields") if isinstance(body.get("fields"), dict) else {}
    recipient = str(fields.get("recipient") or "").strip()
    points = str(fields.get("points") or "").strip()
    if not recipient or not points:
        return JSONResponse(
            {"error": "fields.recipient and fields.points are required", "status": 400},
            status_code=400,
        )
    lang = (body.get("lang") or "fa")[:2]
    if lang not in LANGS:
        lang = "fa"
    tone = (body.get("tone") or "formal").strip()
    if tone not in TONES:
        tone = "formal"
    workspace_id = body.get("workspace_id")
    project_id = body.get("project_id")
    dlp_confirmed = bool(body.get("dlp_confirmed"))
    dlp_confirm_token = body.get("dlp_confirm_token")
    user_id = _uid(user)

    def _dlp() -> None:
        with db.session_scope():
            text = email_writer_scan_text(template_id, fields) or "[email_writer]"
            dlp_gate.gate(
                text=text,
                user_id=user_id,
                workspace_id=workspace_id,
                project_id=project_id,
                source="email_writer",
                source_ref={"feature": "email_writer", "template_id": template_id},
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
            feature="email_writer",
        )

    await anyio.to_thread.run_sync(_spend)

    tid, flds, lg, tn, wid, pid, uid = (
        template_id, fields, lang, tone, workspace_id, project_id, user_id,
    )

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
                yield _sse("status", {"phase": "drafting"})
                for ev in email_writer_service.stream_draft(
                    template_id=tid,
                    fields=flds,
                    lang=lg,
                    tone=tn,
                    workspace_id=wid,
                    project_id=pid,
                    user_id=uid,
                ):
                    if stop_event.is_set():
                        break
                    if ev.get("type") == "token":
                        yield _sse("token", {"text": ev.get("text") or ""})
                    elif ev.get("type") == "done":
                        yield _sse("done", {
                            "content": ev.get("content") or "",
                            "template_id": ev.get("template_id"),
                            "lang": ev.get("lang"),
                            "tone": ev.get("tone"),
                        })
            except Exception as exc:  # noqa: BLE001
                logger.warning("email_writer stream failed: %s", exc)
                yield _sse("error", {"error": str(exc), "status": 500})

    with preflight:
        preflight.hand_off()
        return sse_stream_sync(
            _produce, runner_name="email-writer-runner", on_close=preflight.on_close,
        )
