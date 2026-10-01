"""Automate-agent routes, translated from app/routes/automate_agent.py and
app/routes/automate_agent_stream.py.

ONE router mounted under ``/api/automate-agent`` (mirrors the two Flask
blueprints that shared that url_prefix). CRUD endpoints stay plain ``def`` /
``async def``; the streaming ``POST /tasks/run`` follows the SSE bridge pattern:
every request/JWT/body value is captured into handler locals BEFORE the generator
runs, and the generator opens its OWN ``flask_core.app_context()`` (the router-level
``Depends(flask_ctx)`` context is torn down when the handler RETURNS, before the
streaming body executes).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import anyio.to_thread
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.core import db
from app.api.deps import current_user, flask_ctx
from app.api.sse import sse_stream_sync
from app.models.automate_message import AutomateMessageModel
from app.models.automate_task import AutomateTaskModel
from app.services import spend_gate, stream_concurrency
from app.services.browser_use_service import BrowserUseService
from app.services.dlp_gate import (
    DLPBlockedError,
    format_blocked_response,
    gate as dlp_gate,
)
from app.utils.helpers import serialize_doc
from app.utils.network import is_internal_host

logger = logging.getLogger(__name__)

# Router-level dependency: every request runs inside the Flask app_context.
router = APIRouter(dependencies=[Depends(flask_ctx)])

# Terminal statuses — no need to call stop on these.
_TERMINAL = {"completed", "error", "stopped", "timed_out"}

_MAX_WALLCLOCK_SECONDS = 1800   # 30 minutes hard cap
_POLL_INTERVAL = 2              # seconds between polls
_MAX_CONCURRENT_STREAMS = 3
_KEEPALIVE_INTERVAL = 15        # seconds between keepalive pings
_MAX_CONSECUTIVE_POLL_ERRORS = 5  # P2.22 — abort after this many back-to-back poll failures

# Configurable limits
_MAX_CONCURRENT = int(os.environ.get("AUTOMATE_MAX_CONCURRENT", 1))
_DAILY_QUOTA = int(os.environ.get("AUTOMATE_DAILY_QUOTA", 20))

# Match any URL-ish token. P2.23 extends the original `https?://...` to also
# catch dangerous schemes (`javascript:`, `data:`, `file:`, `gopher:`) and
# bare loopback / private-net hostnames that arrive without scheme.
_URL_RE = re.compile(
    r'(?:[a-z][a-z0-9+.-]*:)?//[^\s\'"<>]+|'        # any-scheme URL
    r'\b(?:javascript|file|data|gopher|vbscript|ftp):[^\s\'"<>]*',  # dangerous schemes (no //)
    re.IGNORECASE,
)
_DANGEROUS_SCHEMES = {"javascript", "file", "data", "gopher", "vbscript", "ftp"}
# Bare host-ish tokens (no scheme/`//`) worth IP-classifying: `localhost`,
# bracketed IPv6, a full 4-octet dotted form (incl. octal/hex octets), OR a
# single packed integer / hex IP (>=7 digits / 0x-prefixed) that could decode to
# an internal address. Each candidate is then normalized + classified by
# ``is_internal_host`` (via ``ipaddress``), which understands every IP encoding —
# the regex is only a loose extractor, not the denylist. Deliberately NOT
# matching 2-3 part dotted forms (e.g. "version 2.5") so innocuous decimals in
# the prompt aren't sent to a (potentially failing) DNS resolve and false-blocked.
_BARE_HOST_RE = re.compile(
    # Bracketed IPv6 (`[::1]`) carries its own delimiters — kept OUTSIDE the
    # \b...\b group because `[` / `]` aren't word chars (a \b never fires next to
    # them, so it'd never match inside the boundary group).
    r'\[[0-9a-f:]+\]'                                              # bracketed IPv6
    r'|\b(?:'
    r'localhost'
    r'|(?:0x[0-9a-f]+|0[0-7]*|\d+)(?:\.(?:0x[0-9a-f]+|0[0-7]*|\d+)){3}'  # 4-octet dotted (any base)
    r'|0x[0-9a-f]{6,}'                                            # packed hex IP
    r'|\d{7,}'                                                    # packed decimal IP
    r')\b',
    re.IGNORECASE,
)


def _check_task_urls(task_text: str) -> tuple[bool, str]:
    """Return (ok, host_or_scheme) — block dangerous schemes + internal/loopback hosts.

    NOTE: best-effort denylist, NOT a security boundary. The automate fetch runs
    on browser-use Cloud (not Polymind's network), so this only discourages obvious
    internal-target prompts; it cannot guarantee SSRF safety.

    Covers:
      - `javascript:` / `data:` / `file:` / `gopher:` / `vbscript:` / `ftp:` schemes
      - Any URL whose hostname resolves to a private/internal IP
      - Bare hostnames like `localhost`, dotted-quad, and decimal/octal/hex/short
        IP forms — all normalized through ``is_internal_host`` (``ipaddress``).
    """
    if not task_text:
        return True, ""

    # Walk every URL-ish match.
    for m in _URL_RE.finditer(task_text):
        token = m.group(0)
        # Dangerous schemes — block outright.
        scheme_part = token.split(":", 1)[0].lower()
        if scheme_part in _DANGEROUS_SCHEMES:
            return False, scheme_part + ":"
        parsed = urlparse(token if "//" in token else f"http://{token}")
        # Reject anything that isn't http/https on the resolved scheme side.
        if parsed.scheme and parsed.scheme.lower() not in ("http", "https"):
            return False, parsed.scheme + ":"
        host = parsed.hostname or ""
        if host and is_internal_host(host):
            return False, host

    # Bare host tokens (no scheme prefix) — `localhost/admin`, `10.0.0.1`,
    # `0x7f000001`, `2130706433`, `127.1`, `[::1]`, ... Route each through
    # is_internal_host so encoded IP forms the regex can't enumerate are caught
    # via ipaddress normalization (urlparse strips the [] off bracketed IPv6).
    for m in _BARE_HOST_RE.finditer(task_text):
        token = m.group(0)
        host = urlparse(f"http://{token}").hostname or token
        if is_internal_host(host):
            return False, token
    return True, ""


def sse_event(event_type: str, data: dict) -> str:
    """Format a dict as an SSE named event."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def _sweep_expired_tasks(user_id: str) -> int:
    """P2.21 — sweep tasks whose `deadline_at` has elapsed but status is still
    pending/running. Set status='timed_out' and best-effort stop the upstream
    session. Returns count swept. Called lazily from /tasks listings.
    """
    expired = AutomateTaskModel.find_expired_running()
    swept = 0
    for task in expired:
        tid = str(task["_id"])
        session_id = task.get("session_id")
        if session_id:
            try:
                BrowserUseService.stop_session(session_id, strategy="session")
            except Exception:
                logger.warning("automate sweep: stop_session failed for %s", tid)
        AutomateTaskModel.set_status(tid, "timed_out", error="deadline_exceeded")
        swept += 1
    return swept


# ---------------------------------------------------------------------------
# CRUD — automate_agent_bp
# ---------------------------------------------------------------------------
@router.get("/tasks")
def list_tasks(request: Request, user: dict = Depends(current_user)):
    user_id = str(user["_id"])

    try:
        limit = int(request.query_params.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    try:
        skip = int(request.query_params.get("skip", 0))
    except (TypeError, ValueError):
        skip = 0
    limit = min(limit, 100)

    # Opportunistic deadline sweep (P2.21) — guarantees disconnected clients
    # don't leave runaway billing on browser-use cloud.
    try:
        _sweep_expired_tasks(user_id)
    except Exception:
        logger.exception("automate: sweep failed for user %s", user_id)

    tasks = AutomateTaskModel.find_by_user(user_id, limit=limit, skip=skip)
    total = AutomateTaskModel.count_by_user(user_id)

    return {
        "tasks": [serialize_doc(t) for t in tasks],
        "total": total,
    }


@router.get("/tasks/{task_id}")
def get_task(task_id: str, user: dict = Depends(current_user)):
    user_id = str(user["_id"])

    task = AutomateTaskModel.find_by_id(task_id)
    if not task:
        return JSONResponse({"error": "Task not found"}, status_code=404)

    if str(task["user_id"]) != user_id:
        return JSONResponse({"error": "Not authorized"}, status_code=403)

    messages = AutomateMessageModel.find_by_task(task_id)

    return {
        "task": serialize_doc(task),
        "messages": [serialize_doc(m) for m in messages],
    }


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str, user: dict = Depends(current_user)):
    user_id = str(user["_id"])

    task = AutomateTaskModel.find_by_id(task_id)
    if not task:
        return JSONResponse({"error": "Task not found"}, status_code=404)

    if str(task["user_id"]) != user_id:
        return JSONResponse({"error": "Not authorized"}, status_code=403)

    # Best-effort hard stop before deleting — swallow errors.
    session_id = task.get("session_id")
    if session_id and task.get("status") not in _TERMINAL:
        try:
            BrowserUseService.stop_session(session_id, strategy="session")
        except Exception:
            pass

    deleted = AutomateTaskModel.delete(task_id, user_id)
    if deleted:
        return {"message": "Task deleted"}
    return JSONResponse({"error": "Failed to delete task"}, status_code=500)


@router.post("/tasks/{task_id}/stop")
def stop_task(task_id: str, user: dict = Depends(current_user)):
    user_id = str(user["_id"])

    task = AutomateTaskModel.find_by_id(task_id)
    if not task:
        return JSONResponse({"error": "Task not found"}, status_code=404)

    if str(task["user_id"]) != user_id:
        return JSONResponse({"error": "Not authorized"}, status_code=403)

    if task.get("status") in _TERMINAL:
        return JSONResponse({"error": "Task already in terminal state"}, status_code=400)

    session_id = task.get("session_id")
    if not session_id:
        return JSONResponse({"error": "No active session for this task"}, status_code=400)

    try:
        BrowserUseService.stop_session(session_id, strategy="task")
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)

    AutomateTaskModel.set_status(task_id, "stopped")

    return {"ok": True, "status": "stopped"}


# ---------------------------------------------------------------------------
# Stream — automate_agent_stream_bp.  SSE POST /tasks/run
# ---------------------------------------------------------------------------
@router.post("/tasks/run")
async def run_task(request: Request, user: dict = Depends(current_user)):
    """Create a browser-use session and stream events to the client.

    Body:
        task  (str, required)
        model (str, optional — default claude-sonnet-4.6)

    Events:
        task_started    {task_id, session_id, live_url, model}
        message         {cursor_id, role, type, summary, screenshot_url}
        status_change   {status}
        task_complete   {output, total_messages, duration_ms}
        error           {message, code}
    """
    # Pre-fetch ALL request-context data BEFORE entering the generator
    # (the flask_ctx context is gone once this handler returns — the generator
    # opens its own).
    user_id = str(user["_id"])
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        data = {}
    data = data if isinstance(data, dict) else {}

    task_text = (data.get("task") or "").strip()
    if not task_text:
        return JSONResponse({"error": "task is required"}, status_code=400)

    model = (data.get("model") or "claude-sonnet-4.6").strip()

    # DLP gate — scan NL task prompt before it leaves for browser-use Cloud.
    # Runs inside the still-live flask_ctx app_context (handler not yet returned).
    body_lang = (data.get("lang") or "").strip()
    user_lang = (
        body_lang
        or user.get("ai_preferences", {}).get("user_info", {}).get("language", "en")
        or "en"
    )[:2].lower()
    # Offloaded off the event loop: the gate does a blocking DB read plus a
    # smart-scan LLM round-trip (~10s) — running it inline would freeze every
    # request on the worker. Mirrors the spend gate below. DLPBlockedError raised
    # inside the closure propagates through run_sync to the handler below.
    def _dlp() -> None:
        dlp_gate(
            text=task_text,
            user_id=user["_id"],
            workspace_id=user.get("active_workspace_id"),
            project_id=None,
            source="automate",
            source_ref={"phase": "run_task"},
            confirmed=bool(data.get("dlp_confirmed")),
            dlp_confirm_token=data.get("dlp_confirm_token"),
            user_lang=user_lang,
        )

    try:
        await anyio.to_thread.run_sync(_dlp)
    except DLPBlockedError as dlp_exc:
        return JSONResponse(format_blocked_response(dlp_exc), status_code=403)

    # Resolve workspace/project scope so the usage log row gets attributed
    # correctly. Automate runs aren't project-scoped today; workspace falls
    # back to the user's active workspace.
    workspace_id = str(user["active_workspace_id"]) if user.get("active_workspace_id") else None

    # Spend gate — pre-flight budget / prepaid-credit enforcement, mirroring the
    # DLP gate. Runs BEFORE any sse_stream_sync is constructed so a breach is a
    # clean HTTP 402 (never an in-stream SSE error). Offloaded off the event
    # loop because the gate does blocking DB point-reads;
    # BudgetExceededError propagates to the global 402 handler.
    def _spend() -> None:
        spend_gate.gate(
            user_id=user_id,
            workspace_id=workspace_id,
            project_id=None,
            origin="web",
        )

    await anyio.to_thread.run_sync(_spend)

    # --- Task URL validation (SSRF guard) ---
    url_ok, blocked_host = _check_task_urls(task_text)
    if not url_ok:
        return JSONResponse({"error": "task_url_blocked", "host": blocked_host}, status_code=400)

    # --- Per-user concurrent cap ---
    concurrent = AutomateTaskModel.count_active_by_user(user_id)
    if concurrent >= _MAX_CONCURRENT:
        return JSONResponse({"error": "concurrent_limit"}, status_code=429)

    # --- Per-user daily quota ---
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    daily_count = AutomateTaskModel.count_created_since(user_id, today_start)
    if daily_count >= _DAILY_QUOTA:
        return JSONResponse({"error": "daily_quota_exhausted"}, status_code=429)

    # Per-user stream reservation + per-worker global permit (same as chat/studio).
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

    # The centralized ``sse_stream_sync`` driver runs the producer on ONE
    # dedicated thread that owns a single ``flask_core.app_context()`` for the
    # whole stream lifetime (including the polling loop that sleeps between
    # frames), so a Flask context never spans a Starlette yield — see
    # app/api/sse.py for the full root-cause writeup.
    with preflight:
        preflight.hand_off()
        return sse_stream_sync(
            lambda stop_event: _run_task_stream(
                stop_event, user_id, task_text, model, workspace_id
            ),
            runner_name="automate-stream-runner",
            on_close=preflight.on_close,
        )


def _run_task_stream(stop_event, user_id: str, task_text: str, model: str, workspace_id):
    """The SSE body. Runs inside the generator's own flask_core.app_context()."""
    start_time = time.time()
    deadline = start_time + _MAX_WALLCLOCK_SECONDS
    last_keepalive = start_time
    consecutive_poll_errors = 0
    task_id = None

    try:
        # 1. Persist pending task record (with explicit deadline so a
        # disconnected SSE client can be swept later — P2.21).
        task_id = AutomateTaskModel.create(user_id, task_text, model)
        AutomateTaskModel.update(task_id, {
            "deadline_at": datetime.fromtimestamp(deadline, tz=timezone.utc).isoformat(),
            "workspace_id": workspace_id,
        })

        # 2. Create cloud session
        try:
            session = BrowserUseService.create_session(task_text, model)
        except Exception as e:
            AutomateTaskModel.set_status(task_id, "error", error=str(e))
            yield sse_event("error", {"message": str(e), "code": "session_create_failed"})
            return

        session_id = session.get("id") or session.get("session_id", "")
        live_url = session.get("live_url")

        # Fallback: live_url sometimes only populated after session enters running state.
        if not live_url and session_id:
            try:
                refreshed = BrowserUseService.get_session(session_id)
                live_url = refreshed.get("live_url") or live_url
            except Exception:
                pass  # best effort

        AutomateTaskModel.set_session(task_id, session_id, live_url)
        AutomateTaskModel.set_status(task_id, "running")

        yield sse_event("task_started", {
            "task_id": task_id,
            "session_id": session_id,
            "live_url": live_url,
            "model": model,
        })

        # 3. Polling loop
        last_cursor = None
        last_known_status = "running"

        while True:
            # Release the runner thread's pinned DB connection back to the pool
            # for the duration of this poll's network round-trip + sleep. The
            # automate models auto-commit, so all prior writes are durable here;
            # ``db.session.remove()`` disposes the current scoped session and the
            # next DB write (AutomateMessageModel.create / increment_message_count)
            # lazily re-creates one under the SAME contextvar scope key the runner
            # opened. Without this, a single conn is pinned for the whole ≤30-min
            # task even though it sits idle ~2s between every poll.
            db.session.commit()
            db.session.remove()

            # Client TCP-disconnected: the SSE driver set the stop_event, so we
            # halt the upstream browser-use Cloud session (stops provider-side
            # billing), mark the task stopped, and break — running the cleanup
            # ``finally`` and releasing the pinned connection promptly instead of
            # burning the full 30-min wall-clock cap on an abandoned tab.
            if stop_event.is_set():
                if session_id:
                    try:
                        BrowserUseService.stop_session(session_id, strategy="session")
                    except Exception:
                        logger.warning(
                            "automate: stop_session failed on disconnect for task %s",
                            task_id,
                        )
                AutomateTaskModel.set_status(task_id, "stopped")
                break

            elapsed = time.time() - start_time

            # Hard time cap
            if elapsed > _MAX_WALLCLOCK_SECONDS:
                AutomateTaskModel.set_status(task_id, "timed_out")
                yield sse_event("error", {
                    "message": "Task timed out after 30 minutes",
                    "code": "timeout",
                })
                break

            # Keepalive ping (raw SSE comment — proxies won't drop idle connection).
            if time.time() - last_keepalive >= _KEEPALIVE_INTERVAL:
                yield ":keepalive\n\n"
                last_keepalive = time.time()

            # Fetch new messages since last cursor.
            try:
                messages_resp = BrowserUseService.list_messages(
                    session_id, after=last_cursor
                )
            except Exception as e:
                consecutive_poll_errors += 1
                logger.warning(
                    "list_messages error (%d/%d): %s",
                    consecutive_poll_errors, _MAX_CONSECUTIVE_POLL_ERRORS, e,
                )
                if consecutive_poll_errors >= _MAX_CONSECUTIVE_POLL_ERRORS:
                    AutomateTaskModel.set_status(task_id, "error", error=f"poll_failures: {e}")
                    yield sse_event("error", {
                        "message": f"Lost contact with browser-use after {consecutive_poll_errors} retries",
                        "code": "poll_failed",
                    })
                    return
                time.sleep(_POLL_INTERVAL)
                continue

            messages = messages_resp.get("messages") or []
            for msg in messages:
                cursor_id = msg.get("id") or msg.get("cursor_id", "")
                role = msg.get("role", "")
                msg_type = msg.get("type", "")
                summary = msg.get("summary")
                screenshot_url = msg.get("screenshot_url")
                msg_data = msg.get("data")

                AutomateMessageModel.create(
                    task_id=task_id,
                    cursor_id=cursor_id,
                    role=role,
                    type=msg_type,
                    summary=summary,
                    data=msg_data,
                    screenshot_url=screenshot_url,
                )
                AutomateTaskModel.increment_message_count(task_id)

                yield sse_event("message", {
                    "cursor_id": cursor_id,
                    "role": role,
                    "type": msg_type,
                    "summary": summary,
                    "screenshot_url": screenshot_url,
                })

                last_cursor = cursor_id

            # Poll session status.
            try:
                session_state = BrowserUseService.get_session(session_id)
            except Exception as e:
                consecutive_poll_errors += 1
                logger.warning(
                    "get_session error (%d/%d): %s",
                    consecutive_poll_errors, _MAX_CONSECUTIVE_POLL_ERRORS, e,
                )
                if consecutive_poll_errors >= _MAX_CONSECUTIVE_POLL_ERRORS:
                    AutomateTaskModel.set_status(task_id, "error", error=f"poll_failures: {e}")
                    yield sse_event("error", {
                        "message": f"Lost contact with browser-use after {consecutive_poll_errors} retries",
                        "code": "poll_failed",
                    })
                    return
                time.sleep(_POLL_INTERVAL)
                continue

            # Successful poll resets the consecutive error counter.
            consecutive_poll_errors = 0

            current_status = session_state.get("status", "")

            if current_status and current_status != last_known_status:
                last_known_status = current_status
                yield sse_event("status_change", {"status": current_status})

            if current_status in _TERMINAL:
                output = session_state.get("output")
                duration_ms = int((time.time() - start_time) * 1000)

                # browser-use Cloud bills provider-side and does not surface a
                # per-task cost field; nothing to write to usage_logs here.
                # Direct UsageLogModel.create from routes is forbidden.
                task = AutomateTaskModel.find_by_id(task_id)
                total_messages = (task or {}).get("message_count", 0)
                AutomateTaskModel.set_status(task_id, current_status, output=output)

                yield sse_event("task_complete", {
                    "output": output,
                    "total_messages": total_messages,
                    "duration_ms": duration_ms,
                })
                break

            time.sleep(_POLL_INTERVAL)

    except Exception as e:
        logger.exception("Unexpected error in automate stream for task %s", task_id)
        if task_id:
            try:
                AutomateTaskModel.set_status(task_id, "error", error=str(e))
            except Exception:
                pass
        yield sse_event("error", {"message": str(e), "code": "unexpected_error"})


__all__ = ["router"]
