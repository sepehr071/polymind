"""Tender / RFQ assistant — SSE analyze + presentation handoff."""
from __future__ import annotations

import json
import logging

import anyio.to_thread
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.core import db
from app.api.deps import current_user, feature_dep, flask_ctx
from app.api.sse import sse_stream_sync
from app.prompts.tender import TENDER_MAX_FILES, TENDER_MODES
from app.services import dlp_gate, spend_gate, stream_concurrency, tender_service
from app.utils.studio_dlp import gate_text

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


@router.post("/analyze")
async def analyze(
    request: Request,
    user: dict = Depends(current_user),
    _feat: dict = Depends(feature_dep("tender_assistant")),
):
    body = await _json_body(request)
    raw_ids = body.get("upload_ids") or []
    if not isinstance(raw_ids, list) or not raw_ids:
        return JSONResponse({"error": "upload_ids required", "status": 400}, status_code=400)
    upload_ids = [str(u).strip() for u in raw_ids if u][:TENDER_MAX_FILES]
    notes = body.get("notes") or ""
    if not isinstance(notes, str):
        notes = str(notes)
    mode = (body.get("mode") or "tender").strip()
    if mode not in TENDER_MODES:
        mode = "tender"
    lang = (body.get("lang") or "fa")[:2]
    if lang not in ("fa", "en"):
        lang = "fa"
    currency_unit = body.get("currency_unit") or "toman"
    workspace_id = body.get("workspace_id")
    project_id = body.get("project_id")
    dlp_confirmed = bool(body.get("dlp_confirmed"))
    dlp_confirm_token = body.get("dlp_confirm_token")
    user_id = _uid(user)

    def _dlp() -> None:
        with db.session_scope():
            text = gate_text(
                notes if isinstance(notes, str) else str(notes or ""),
                user_id,
                upload_ids,
                empty_sentinel="[tender attachments]",
            )
            dlp_gate.gate(
                text=text,
                user_id=user_id,
                workspace_id=workspace_id,
                project_id=project_id,
                source="tender",
                source_ref={"feature": "tender", "mode": mode},
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
            feature="tender",
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
                pack = tender_service.run_analyze(
                    upload_ids=upload_ids,
                    notes=notes,
                    mode=mode,
                    lang=lang,
                    currency_unit=currency_unit,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    user_id=user_id,
                )
                if stop_event.is_set():
                    return
                yield _sse("result", pack)
                yield _sse("done", {})
            except ValueError as exc:
                yield _sse("error", {"error": str(exc), "status": 400})
            except Exception as exc:  # noqa: BLE001
                logger.warning("tender analyze failed: %s", exc)
                yield _sse("error", {"error": str(exc), "status": 500})

    with preflight:
        preflight.hand_off()
        return sse_stream_sync(
            _produce, runner_name="tenders-runner", on_close=preflight.on_close,
        )


@router.post("/handoff-presentation")
async def handoff_presentation(
    request: Request,
    user: dict = Depends(current_user),
    _feat: dict = Depends(feature_dep("tender_assistant")),
):
    """Return sessionStorage-ready presentation brief (no DB draft required)."""
    body = await _json_body(request)
    # Accept either raw result-ish fields or nested result
    result = body.get("result") if isinstance(body.get("result"), dict) else body
    seed = tender_service.outline_seed_from_result(result or {})
    if body.get("title"):
        seed["topic"] = str(body["title"])
    if body.get("lang"):
        seed["language"] = body["lang"]
    return {"handoff": seed, "path": "/presentations"}
