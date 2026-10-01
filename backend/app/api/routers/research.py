"""Deep research — allowlisted models, SSE run."""
from __future__ import annotations

import json
import logging
import queue
import threading
import time

import anyio.to_thread
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.core import db
from app.api.deps import current_user, feature_dep, flask_ctx
from app.api.sse import sse_stream_sync
from app.prompts.research import RESEARCH_MODES
from app.services import dlp_gate, research_service, spend_gate, stream_concurrency
from app.utils.studio_dlp import gate_text, research_message_text

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(flask_ctx)])

_MAX_CONCURRENT_STREAMS = 3

# Idle comment interval while OpenRouter deep call blocks (non-stream).
# Proxies / FE idle timers drop silent SSE; mirror chat/agent keepalives.
_KEEPALIVE_INTERVAL = 15
_RUN_DONE = object()

# Progressive activity narrative while the model is black-box busy.
# (elapsed_seconds_threshold, phase_id) — FE i18n via status.<phase>
_PROGRESS_STAGES = (
    (0, "preparing"),
    (2, "searching"),
    (25, "reading"),
    (55, "analyzing"),
    (100, "writing"),
    (200, "deepening"),
)


def _phase_for_elapsed(elapsed: float) -> str:
    phase = _PROGRESS_STAGES[0][1]
    for threshold, name in _PROGRESS_STAGES:
        if elapsed >= threshold:
            phase = name
        else:
            break
    return phase


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


@router.get("/models")
async def list_models(
    user: dict = Depends(current_user),
    _feat: dict = Depends(feature_dep("research_assistant")),
):
    return {"models": research_service.model_catalog()}


@router.post("/run")
async def run(
    request: Request,
    user: dict = Depends(current_user),
    _feat: dict = Depends(feature_dep("research_assistant")),
):
    body = await _json_body(request)
    query = (body.get("query") or "").strip()
    if not query:
        return JSONResponse({"error": "query is required", "status": 400}, status_code=400)
    mode = (body.get("mode") or "deep").strip()
    if mode not in RESEARCH_MODES:
        return JSONResponse(
            {"error": f"mode must be one of {sorted(RESEARCH_MODES)}", "status": 400},
            status_code=400,
        )
    model_id = body.get("model_id")
    try:
        mid = research_service.resolve_model(mode=mode, model_id=model_id)
    except ValueError as exc:
        return JSONResponse({"error": str(exc), "status": 400}, status_code=400)

    lang = (body.get("lang") or "fa")[:2]
    if lang not in ("fa", "en"):
        lang = "fa"
    focus = body.get("focus") or ""
    if not isinstance(focus, str):
        focus = str(focus)
    upload_ids = [str(u).strip() for u in (body.get("upload_ids") or []) if u][:5]
    knowledge_ids = [str(k).strip() for k in (body.get("knowledge_ids") or []) if k][:20]
    workspace_id = body.get("workspace_id")
    project_id = body.get("project_id")
    dlp_confirmed = bool(body.get("dlp_confirmed"))
    dlp_confirm_token = body.get("dlp_confirm_token")
    user_id = _uid(user)

    from app.prompts.research import RESEARCH_MODELS
    supports = RESEARCH_MODELS[mid]["supports_files"]
    if upload_ids and not supports and mode == "deep_files":
        return JSONResponse(
            {"error": "selected model does not support files", "status": 400},
            status_code=400,
        )

    def _dlp() -> None:
        with db.session_scope():
            # Message = query+focus only so FE preflight can match byte-for-byte.
            # Uploads join via gate_text (= /dlp/scan). Knowledge is injected into
            # the LLM context later, not the confirm HMAC text (v1).
            text = gate_text(
                research_message_text(query, focus),
                user_id,
                upload_ids,
                empty_sentinel="[research]",
            )
            dlp_gate.gate(
                text=text,
                user_id=user_id,
                workspace_id=workspace_id,
                project_id=project_id,
                source="research",
                source_ref={"feature": "research", "mode": mode, "model_id": mid},
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
            feature="research",
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
                started = time.time()
                last_phase = "preparing"
                yield _sse("status", {
                    "phase": "preparing",
                    "message_key": "preparing",
                    "elapsed_s": 0,
                    "model_id": mid,
                    "mode": mode,
                })
                if stop_event.is_set():
                    return

                # Run blocking OpenRouter call off the SSE generator thread so
                # we can emit activity status + keepalives (otherwise proxies
                # drop the stream and the UI looks frozen).
                box: dict = {}
                frame_q: queue.Queue = queue.Queue()

                def _run():
                    try:
                        with db.session_scope():
                            box["pack"] = research_service.run_research(
                                query=query,
                                mode=mode,
                                model_id=mid,
                                lang=lang,
                                focus=focus,
                                upload_ids=upload_ids,
                                knowledge_ids=knowledge_ids,
                                workspace_id=workspace_id,
                                project_id=project_id,
                                user_id=user_id,
                                stop_event=stop_event,
                            )
                    except Exception as exc:  # noqa: BLE001
                        box["exc"] = exc
                    finally:
                        frame_q.put(_RUN_DONE)

                thr = threading.Thread(target=_run, name="research-or", daemon=True)
                thr.start()
                last_keepalive = time.time()
                while True:
                    if stop_event.is_set():
                        break
                    try:
                        item = frame_q.get(timeout=1.0)
                    except queue.Empty:
                        now = time.time()
                        elapsed = now - started
                        phase = _phase_for_elapsed(elapsed)
                        if phase != last_phase:
                            last_phase = phase
                            yield _sse("status", {
                                "phase": phase,
                                "message_key": phase,
                                "elapsed_s": int(elapsed),
                                "model_id": mid,
                                "mode": mode,
                            })
                            last_keepalive = now
                        elif now - last_keepalive >= _KEEPALIVE_INTERVAL:
                            # Heartbeat status (same phase) so FE timer + proxy stay alive
                            yield _sse("status", {
                                "phase": phase,
                                "message_key": phase,
                                "elapsed_s": int(elapsed),
                                "model_id": mid,
                                "mode": mode,
                                "heartbeat": True,
                            })
                            last_keepalive = now
                        continue
                    if item is _RUN_DONE:
                        break
                thr.join(timeout=5)
                # In-flight OpenRouter HTTP cannot be aborted mid-request; stream
                # permit is released by on_close. Worker may keep billing until timeout.
                if thr.is_alive():
                    logger.warning(
                        "research worker still alive after join "
                        "(stop=%s; in-flight OpenRouter call may continue until timeout)",
                        stop_event.is_set(),
                    )

                if stop_event.is_set():
                    return
                if "exc" in box:
                    exc = box["exc"]
                    if isinstance(exc, ValueError):
                        yield _sse("error", {"error": str(exc), "status": 400})
                    else:
                        logger.warning("research failed: %s", exc)
                        yield _sse("error", {"error": str(exc), "status": 500})
                    return
                pack = box.get("pack") or {}
                elapsed = int(time.time() - started)
                yield _sse("status", {
                    "phase": "citing",
                    "message_key": "citing",
                    "elapsed_s": elapsed,
                    "model_id": mid,
                    "mode": mode,
                })
                yield _sse("done", pack)
            except ValueError as exc:
                yield _sse("error", {"error": str(exc), "status": 400})
            except Exception as exc:  # noqa: BLE001
                logger.warning("research failed: %s", exc)
                yield _sse("error", {"error": str(exc), "status": 500})

    with preflight:
        preflight.hand_off()
        return sse_stream_sync(
            _produce, runner_name="research-runner", on_close=preflight.on_close,
        )
