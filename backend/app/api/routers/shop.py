"""Shop assistant — multi-agent Digikala/Technolife price compare (SSE)."""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from typing import Any

import anyio.to_thread
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.core import db
from app.api.deps import current_user, feature_dep, flask_ctx
from app.api.sse import sse_stream_sync
from app.prompts.shop import SHOP_CATEGORIES, SHOP_LANGS, SHOP_MODEL
from app.services import dlp_gate, shop_service, spend_gate, stream_concurrency
from app.utils.studio_dlp import shop_message_text

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(flask_ctx)])

_KEEPALIVE_INTERVAL = 15
_RUN_DONE = object()
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
    _feat: dict = Depends(feature_dep("shop_assistant")),
):
    body = await _json_body(request)
    need = (body.get("need") or "").strip()
    if not need:
        return JSONResponse({"error": "need is required", "status": 400}, status_code=400)

    try:
        qty = int(body.get("qty") or 1)
    except (TypeError, ValueError):
        qty = 1
    qty = max(1, min(qty, 9999))

    max_budget_toman = body.get("max_budget_toman")
    if max_budget_toman is not None and max_budget_toman != "":
        try:
            max_budget_toman = int(max_budget_toman)
            if max_budget_toman <= 0:
                max_budget_toman = None
        except (TypeError, ValueError):
            max_budget_toman = None
    else:
        max_budget_toman = None

    category = (body.get("category") or "auto").strip()
    if category not in SHOP_CATEGORIES:
        category = "auto"
    lang = (body.get("lang") or "fa")[:2]
    if lang not in SHOP_LANGS:
        lang = "fa"
    notes = body.get("notes") or ""
    if not isinstance(notes, str):
        notes = str(notes)
    notes = notes.strip()[:2000]

    workspace_id = body.get("workspace_id")
    project_id = body.get("project_id")
    dlp_confirmed = bool(body.get("dlp_confirmed"))
    dlp_confirm_token = body.get("dlp_confirm_token")
    user_id = _uid(user)

    def _dlp() -> None:
        with db.session_scope():
            text = shop_message_text(need, qty, max_budget_toman, notes) or "[shop]"
            dlp_gate.gate(
                text=text,
                user_id=user_id,
                workspace_id=workspace_id,
                project_id=project_id,
                source="shop",
                source_ref={"feature": "shop_assistant", "model_id": SHOP_MODEL},
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
            feature="shop_assistant",
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
                yield _sse("status", {
                    "phase": "planning",
                    "message_key": "planning",
                    "elapsed_s": 0,
                    "model_id": SHOP_MODEL,
                })
                if stop_event.is_set():
                    return

                box: dict = {}
                frame_q: queue.Queue = queue.Queue()

                def _emit(phase: str, extra: dict) -> None:
                    if stop_event.is_set():
                        return
                    payload: dict[str, Any] = {
                        "phase": phase,
                        "message_key": phase,
                        "elapsed_s": int(time.time() - started),
                        "model_id": SHOP_MODEL,
                    }
                    if extra:
                        payload.update(extra)
                    # Progressive events
                    if phase == "plan_ready":
                        frame_q.put(("plan", payload.get("plan") or {}))
                        frame_q.put(("status", {
                            "phase": "searching",
                            "message_key": "searching",
                            "elapsed_s": payload["elapsed_s"],
                            "model_id": SHOP_MODEL,
                        }))
                    elif phase == "candidates":
                        frame_q.put(("candidates", {
                            "merchant": payload.get("merchant"),
                            "items": payload.get("items") or [],
                            "count": payload.get("count") or 0,
                        }))
                    else:
                        frame_q.put(("status", {
                            "phase": phase if phase != "search_done" else "comparing",
                            "message_key": phase if phase != "search_done" else "comparing",
                            "elapsed_s": payload["elapsed_s"],
                            "model_id": SHOP_MODEL,
                        }))

                def _run():
                    try:
                        with db.session_scope():
                            box["pack"] = shop_service.run_pipeline(
                                need=need,
                                qty=qty,
                                max_budget_toman=max_budget_toman,
                                category=category,
                                lang=lang,
                                notes=notes,
                                workspace_id=workspace_id,
                                project_id=project_id,
                                user_id=user_id,
                                on_status=_emit,
                            )
                    except Exception as exc:  # noqa: BLE001
                        box["exc"] = exc
                    finally:
                        frame_q.put(_RUN_DONE)

                thr = threading.Thread(target=_run, name="shop-or", daemon=True)
                thr.start()
                last_keepalive = time.time()
                last_phase = "planning"
                while True:
                    if stop_event.is_set():
                        break
                    try:
                        item = frame_q.get(timeout=1.0)
                    except queue.Empty:
                        now = time.time()
                        elapsed = int(now - started)
                        if now - last_keepalive >= _KEEPALIVE_INTERVAL:
                            yield _sse("status", {
                                "phase": last_phase,
                                "message_key": last_phase,
                                "elapsed_s": elapsed,
                                "model_id": SHOP_MODEL,
                                "heartbeat": True,
                            })
                            last_keepalive = now
                        continue
                    if item is _RUN_DONE:
                        break
                    if isinstance(item, tuple) and len(item) == 2:
                        ev, data = item
                        if ev == "status" and isinstance(data, dict):
                            last_phase = data.get("phase") or last_phase
                        yield _sse(ev, data if isinstance(data, dict) else {"data": data})
                        last_keepalive = time.time()

                thr.join(timeout=5)
                if thr.is_alive():
                    logger.warning(
                        "shop worker still alive after join (stop=%s)",
                        stop_event.is_set(),
                    )
                if stop_event.is_set():
                    return
                if "exc" in box:
                    exc = box["exc"]
                    if isinstance(exc, ValueError):
                        yield _sse("error", {"error": str(exc), "status": 400})
                    else:
                        logger.warning("shop failed: %s", exc)
                        yield _sse("error", {"error": str(exc), "status": 500})
                    return
                pack = box.get("pack") or {}
                elapsed = int(time.time() - started)
                yield _sse("status", {
                    "phase": "done",
                    "message_key": "done",
                    "elapsed_s": elapsed,
                    "model_id": SHOP_MODEL,
                })
                yield _sse("done", pack)
            except ValueError as exc:
                yield _sse("error", {"error": str(exc), "status": 400})
            except Exception as exc:  # noqa: BLE001
                logger.warning("shop failed: %s", exc)
                yield _sse("error", {"error": str(exc), "status": 500})

    with preflight:
        preflight.hand_off()
        return sse_stream_sync(
            _produce, runner_name="shop-runner", on_close=preflight.on_close,
        )
