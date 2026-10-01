"""In-app helper guide (SSE) router.

Mounted at ``/api/helper``. Ported from app/routes/helper.py.
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections import deque
from typing import Optional
from uuid import uuid4

import anyio
import anyio.to_thread
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.deps import current_user, flask_ctx
from app.api.sse import sse_stream_sync

logger = logging.getLogger(__name__)

helper_router = APIRouter(dependencies=[Depends(flask_ctx)])

async def _json_body(request: Request) -> dict:
    """Read the request JSON body, tolerating empty/garbage like get_json(silent=True)."""
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


# ===========================================================================
# Helper guide  (helper_bp -> /api/helper)
# ===========================================================================

# Hard-locked model. Never read from request body — the helper is a fixed
# product surface, not a model picker.
HELPER_MODEL = "google/gemini-3.5-flash-lite"

# Rolling history window passed to the LLM.
HELPER_HISTORY_WINDOW = 30

# Deep-link extraction — matches `[label](/path)` markdown links and keeps the
# target. We filter to relative (router-internal) paths only.
_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)\s]+)\)")


# ---------------------------------------------------------------------------
# Per-user rate limiter — 30 requests / 60 seconds, PER WORKER (ported VERBATIM
# from app/routes/helper.py). The in-process deque store is shared across the
# worker's threads, not across workers; effective cap is `workers * MAX`.
# ---------------------------------------------------------------------------

_RATE_LIMIT_WINDOW = 60
_RATE_LIMIT_MAX = 30
_helper_rate: dict[str, deque] = {}

_SWEEP_EVERY_N = 200
_sweep_counter = 0


def _sweep_inactive_buckets(now: float) -> None:
    cutoff = now - (2 * _RATE_LIMIT_WINDOW)
    stale = [
        uid for uid, dq in _helper_rate.items()
        if not dq or dq[-1] < cutoff
    ]
    for uid in stale:
        _helper_rate.pop(uid, None)


def _check_rate_limit(user_id: str) -> Optional[int]:
    global _sweep_counter
    now = time.monotonic()
    window_start = now - _RATE_LIMIT_WINDOW

    _sweep_counter += 1
    if _sweep_counter >= _SWEEP_EVERY_N:
        _sweep_counter = 0
        _sweep_inactive_buckets(now)

    dq = _helper_rate.setdefault(user_id, deque())
    while dq and dq[0] < window_start:
        dq.popleft()
    if len(dq) >= _RATE_LIMIT_MAX:
        retry_after = int(_RATE_LIMIT_WINDOW - (now - dq[0])) + 1
        return max(retry_after, 1)
    dq.append(now)
    return None


def extract_markdown_links(text: str) -> list[str]:
    """Return relative-path targets from markdown `[label](/path)` links."""
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for match in _MARKDOWN_LINK_RE.finditer(text):
        target = match.group(1).strip()
        if not target.startswith("/"):
            continue
        if target in seen:
            continue
        seen.add(target)
        out.append(target)
    return out


def _sse_event(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def _strip_ids(messages: list) -> list:
    """Remove ObjectId-only internal fields for the JSON response."""
    from app.utils.helpers import serialize_doc

    out = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        cleaned = {k: v for k, v in m.items() if k != "_id"}
        out.append(cleaned)
    return serialize_doc(out)


def _resolve_workspace(user_id, workspace_id_str: Optional[str]) -> Optional[dict]:
    """Return the workspace doc if the user can read it, else None."""
    from app.models.workspace import WorkspaceModel
    from app.utils.helpers import validate_object_id
    from app.utils.permissions import check_workspace_access

    if not workspace_id_str or not validate_object_id(workspace_id_str):
        return None
    if not check_workspace_access(user_id, workspace_id_str, "viewer"):
        return None
    return WorkspaceModel.find_by_id(workspace_id_str)


def _resolve_project(user_id, project_id_str: Optional[str]) -> Optional[dict]:
    """Return the project doc if the user can read it, else None."""
    from app.models.project import ProjectModel
    from app.utils.helpers import validate_object_id
    from app.utils.permissions import check_project_access

    if not project_id_str or not validate_object_id(project_id_str):
        return None
    if not check_project_access(user_id, project_id_str, "viewer"):
        return None
    return ProjectModel.find_by_id(project_id_str)


@helper_router.post("/stream")
async def stream_helper(request: Request, user: dict = Depends(current_user)):
    """SSE stream for the in-app helper guide."""
    from app.models.helper_conversation import HelperConversationModel
    from app.prompts.helper_system import build_helper_system_prompt
    from app.services import stream_state
    from app.services.dlp_gate import gate_redactable
    from app.services.openrouter_service import OpenRouterService
    from app.utils.permissions import get_workspace_role

    user_id = str(user["_id"])

    body = await _json_body(request)
    message_content = (body.get("message") or "").strip()
    if not message_content:
        return JSONResponse({"error": "Message content is required"}, status_code=400)

    # Rate limit
    retry_after = _check_rate_limit(user_id)
    if retry_after is not None:
        return JSONResponse(
            {"error": "rate_limited", "retry_after": retry_after},
            status_code=429,
            headers={"Retry-After": str(int(retry_after))},
        )

    # Per-worker global stream ceiling (process-wide pool-DoS hard cap). The
    # helper has no per-user concurrent cap (only the rate limit above), so it
    # just takes ONE global permit; at the ceiling, 503 + Retry-After. The permit
    # is released by the SSE driver's ``on_close`` (crash / disconnect / EOF).
    from app.services import stream_concurrency

    if not stream_concurrency.try_acquire():
        return JSONResponse(
            {"error": "server_busy", "status": 503},
            status_code=503,
            headers={"Retry-After": "5"},
        )

    page_context = body.get("page_context") or {}
    route = (page_context.get("route") or "/").strip() or "/"
    params = page_context.get("params") or {}
    if not isinstance(params, dict):
        params = {}

    workspace_id = page_context.get("workspace_id") or user.get("active_workspace_id")
    workspace_id_str = str(workspace_id) if workspace_id else None
    project_id_str = page_context.get("project_id") or None

    workspace = _resolve_workspace(user["_id"], workspace_id_str)
    project = _resolve_project(user["_id"], project_id_str)
    member_role = (
        get_workspace_role(user["_id"], workspace["_id"]) if workspace else None
    )

    # --- DLP pre-flight ---------------------------------------------------
    # Runs in the handler body (inside the router-level flask_ctx). A block /
    # confirm-required raises DLPBlockedError, normalized to 403 by the global
    # handler in app.api.errors — same wire shape the Flask route emitted.
    body_lang = (body.get("lang") or "").strip()
    user_lang = (
        body_lang
        or user.get("ai_preferences", {}).get("user_info", {}).get("language", "en")
        or "en"
    )[:2].lower()
    # Offload the blocking DLP gate (DB read + always-on LLM classify, up to
    # ~10s) to a worker thread so it never stalls the event loop. anyio copies
    # the contextvars Context (incl. the Flask app_context) into the worker and
    # the loop awaits it, so DB/JWT access inside the gate stays valid.
    # DLPBlockedError still propagates to the global 403 handler unchanged.
    helper_dlp_redact = bool(body.get("dlp_redact"))

    def _gate() -> dict:
        return gate_redactable(
            text=message_content,
            user_id=user["_id"],
            workspace_id=workspace["_id"] if workspace else None,
            project_id=project["_id"] if project else None,
            source="helper",
            source_ref={"route": route},
            force_redact=helper_dlp_redact,
            confirmed=bool(body.get("dlp_confirmed")),
            dlp_confirm_token=body.get("dlp_confirm_token"),
            user_lang=user_lang,
        )

    # --- Spend pre-flight -------------------------------------------------
    # Budget/credit enforcement immediately after DLP, BEFORE the SSE stream is
    # constructed, so a breach is a clean HTTP 402 (never an in-stream error).
    # workspace_id may be None (helper isn't always company-scoped) — the gate
    # still enforces the user-level budget. Offloaded like the DLP gate.
    from app.services import spend_gate

    def _spend() -> None:
        spend_gate.gate(
            user_id=user["_id"],
            workspace_id=workspace["_id"] if workspace else None,
            project_id=project["_id"] if project else None,
            origin="helper",
            feature="helper",
        )

    # The DLP + spend gates raise (403 / 402) to the global handlers BEFORE the
    # stream is handed off — on any such raise return the global permit (no
    # ``on_close`` will fire for a stream that never started).
    try:
        helper_gate_res = await anyio.to_thread.run_sync(_gate)
        # When redaction fired, send the SCRUBBED message to the helper LLM. The
        # local list + the persisted user turn both use ``message_content``.
        if helper_gate_res.get("redacted"):
            message_content = helper_gate_res["redacted_text"]
        await anyio.to_thread.run_sync(_spend)
    except BaseException:
        stream_concurrency.release()
        raise

    # --- Build prompt + history ------------------------------------------
    system_prompt = build_helper_system_prompt(
        user=user,
        workspace=workspace,
        project=project,
        member_role=member_role,
        route=route,
        params=params,
    )

    history = HelperConversationModel.rolling_window(user_id, n=HELPER_HISTORY_WINDOW)
    formatted_messages = [
        {"role": m["role"], "content": m["content"]}
        for m in history
        if m.get("role") in ("user", "assistant", "system") and m.get("content")
    ]
    formatted_messages.append({"role": "user", "content": message_content})

    # Persist the user turn before streaming so a mid-stream cancel still
    # leaves the question on the record.
    HelperConversationModel.append_message(
        user_id=user["_id"],
        role="user",
        content=message_content,
        page_context={
            "route": route,
            "params": params,
            "workspace_id": workspace_id_str,
            "project_id": project_id_str,
        },
    )

    message_id = f"helper_msg:{uuid4()}"
    stream_state.register(message_id, user_id=user_id)

    # Capture the user UUID + workspace doc id as request-scoped locals BEFORE
    # the generator (the flask_ctx is torn down once we return — the generator
    # opens its own).
    user_oid = user["_id"]

    def _produce(stop_event):
        # Pure streaming logic, ported VERBATIM from the Flask route. Runs on the
        # ``sse_stream_sync`` runner thread, inside the single Flask app_context it
        # owns (so DB/service calls here see a live context). Does NOT manage the
        # context or scoped session itself — the driver handles push/pop + cleanup.
        # ``stop_event`` is set by the SSE driver on client disconnect; checking it
        # per chunk lets an abandoned tab stop the helper LLM stream promptly
        # instead of running it to completion (burning the pinned conn + OpenRouter
        # cost).
        full_content = ""
        finish_reason = "stop"

        # Opening event so the client can hook up the cancel button.
        yield _sse_event("message_start", {
            "message_id": message_id,
            "route": route,
        })

        try:
            stream = OpenRouterService.chat_completion(
                messages=formatted_messages,
                model=HELPER_MODEL,
                system_prompt=system_prompt,
                temperature=0.4,
                max_tokens=800,
                stream=True,
                user_id=user_id,
                conversation_id=None,
                feature="helper",
                workspace_id=workspace_id_str,
                project_id=project_id_str,
                origin="helper",
            )

            for chunk in stream:
                # Client TCP-disconnected: the SSE driver set the stop_event so we
                # break out promptly, run the finally (clears stream_state), and
                # the runner thread releases its pinned DB connection back to the
                # pool — closing a connection-exhaustion DoS window.
                if stop_event.is_set():
                    finish_reason = "cancelled"
                    break

                if stream_state.is_cancelled(message_id):
                    finish_reason = "cancelled"
                    break

                if "error" in chunk:
                    error_msg = chunk["error"].get("message", "Unknown error")
                    yield _sse_event("message_error", {
                        "message_id": message_id,
                        "error": error_msg,
                    })
                    return

                if chunk.get("done"):
                    break

                choices = chunk.get("choices") or []
                if choices:
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content") or ""
                    if content:
                        full_content += content
                        yield _sse_event("message_chunk", {
                            "message_id": message_id,
                            "content": content,
                        })
                    if choices[0].get("finish_reason"):
                        finish_reason = choices[0]["finish_reason"]

        except Exception as e:  # pragma: no cover - defensive
            logger.exception("helper stream failed: %s", e)
            yield _sse_event("message_error", {
                "message_id": message_id,
                "error": str(e),
            })
            return
        finally:
            stream_state.clear(message_id)

        # Persist the assistant turn with extracted deep links.
        deep_links = extract_markdown_links(full_content)
        try:
            HelperConversationModel.append_message(
                user_id=user_oid,
                role="assistant",
                content=full_content,
                page_context={
                    "route": route,
                    "params": params,
                },
                deep_links=deep_links,
            )
        except Exception as e:  # pragma: no cover - persistence best-effort
            logger.warning("helper history persist failed: %s", e)

        yield _sse_event("message_complete", {
            "message_id": message_id,
            "content": full_content,
            "deep_links": deep_links,
            "finish_reason": finish_reason,
        })

    # The centralized ``sse_stream_sync`` driver runs ``_produce`` on ONE
    # dedicated thread that owns a single ``flask_core.app_context()`` for the
    # whole stream lifetime (so a Flask context never spans a Starlette yield —
    # see app/api/sse.py) and tears the scoped session down on exit. ``on_close``
    # returns the global stream permit exactly once (crash / disconnect / EOF).
    return sse_stream_sync(
        _produce,
        runner_name="helper-stream-runner",
        on_close=stream_concurrency.release,
    )


@helper_router.post("/cancel/{message_id}")
async def cancel_helper(message_id: str, user: dict = Depends(current_user)):
    """Cancel an in-flight helper stream owned by this user."""
    from app.services import stream_state

    user_id = str(user["_id"])

    owner = stream_state.owner_of(message_id)
    if owner is None:
        return JSONResponse({"error": "Generation not found"}, status_code=404)
    if owner != user_id:
        return JSONResponse({"error": "Not authorized"}, status_code=403)
    stream_state.mark_cancelled(message_id)
    return {"success": True, "message": "Generation cancelled"}


@helper_router.post("/clear")
async def clear_helper(user: dict = Depends(current_user)):
    """Clear this user's helper conversation history."""
    from app.models.helper_conversation import HelperConversationModel

    HelperConversationModel.clear(user["_id"])
    return {"ok": True}


@helper_router.get("/history")
async def get_helper_history(user: dict = Depends(current_user)):
    """Return this user's helper conversation history (oldest -> newest)."""
    from app.models.helper_conversation import HelperConversationModel

    history = HelperConversationModel.get_history(user["_id"])
    return {"messages": _strip_ids(history)}



__all__ = ["helper_router"]
