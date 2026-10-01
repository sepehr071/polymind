"""Arena routes, translated from app/routes/arena.py + app/routes/arena_stream.py.

Both Flask blueprints (``arena_bp`` + ``arena_stream_bp``) mount at the same
url_prefix ``/api/arena``, so they collapse into a SINGLE FastAPI router here.

Translation notes specific to this group:
  * The CRUD handlers preserve the legacy ``bson.ObjectId.is_valid(...)``
    validation VERBATIM — the live Flask routes still gate config_id /
    project_id / session_id on the 24-hex-char ObjectId shape (CLAUDE.md: bson
    is still imported in arena/configs/debate/users). Quick models (``quick:*``)
    are the only ids that resolve end-to-end on the UUID datastore.
  * ``POST /stream`` is SSE: it fans out 2-4 worker threads via ``queue.Queue``.
    The drain generator opens its OWN ``flask_core.app_context()`` (the
    ``flask_ctx`` dependency's context is gone once the handler returns), and
    every worker thread re-enters ``flask_core.app_context()`` + tears its
    SQLAlchemy session down in a ``finally`` — ported 1:1 from the Flask body.
    All request/JWT/body values are captured as handler locals BEFORE the
    streaming response is returned (i.e. before the first ``yield``).
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time

import anyio
import anyio.to_thread
from bson import ObjectId
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.core import db, flask_core
from app.api.deps import current_user, flask_ctx
from app.api.sse import sse_stream_sync
from app.models.arena_message import ArenaMessageModel
from app.models.arena_session import ArenaSessionModel
from app.models.llm_config import LLMConfigModel
from app.models.user import UserModel
from app.services import spend_gate, stream_concurrency, stream_state
from app.services.dlp_gate import gate_redactable
from app.services.openrouter_service import OpenRouterService
from app.utils.config_resolver import resolve_config as resolve_arena_config
from app.utils.helpers import serialize_doc
from app.utils.permissions import check_project_access
from app.utils.rate_limit import check_rate_limit

# Router-level dependency: every request runs inside the Flask app_context.
router = APIRouter(dependencies=[Depends(flask_ctx)])
_log = logging.getLogger(__name__)

# Per-user concurrent-stream cap (DB connection-pool exhaustion DoS guard). Arena
# fans out 3-5 connections per stream, so a small cap matters more here.
_MAX_CONCURRENT_STREAMS = 3

_KEEPALIVE_INTERVAL = 15        # seconds between keepalive SSE comments
_MAX_WALLCLOCK_SECONDS = 1800   # 30-minute hard cap on a single stream


def sse_event(event_type, data):
    """Format data as SSE event."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


async def _json_body(request: Request) -> dict:
    """Read the request JSON body, tolerating empty/garbage like get_json(silent=True)."""
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        data = {}
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# arena_bp — session CRUD.
# ---------------------------------------------------------------------------
@router.post("/sessions")
async def create_session(request: Request, user: dict = Depends(current_user)):
    """Create a new arena session."""
    user_id = str(user["_id"])
    data = await _json_body(request)

    config_ids = data.get("config_ids", [])
    if len(config_ids) < 2:
        return JSONResponse({"error": "At least 2 configs required"}, status_code=400)
    if len(config_ids) > 4:
        return JSONResponse({"error": "Maximum 4 configs allowed"}, status_code=400)

    # P1.9: accept optional project_id so the session — and every usage_log
    # row it emits via streamed completions — is attributed to the right
    # project. Validate access if provided.
    project_id = data.get("project_id") or None
    if project_id:
        if not isinstance(project_id, str) or not ObjectId.is_valid(project_id):
            return JSONResponse(
                {"error": "project_id must be a valid 24-char hex ObjectId"}, status_code=400
            )
        if not check_project_access(user_id, project_id, "viewer"):
            return JSONResponse(
                {"error": "Project access denied", "code": "project_access_denied"}, status_code=403
            )

    # P1.8: verify the caller can actually see each requested config.
    for config_id in config_ids:
        if isinstance(config_id, str) and config_id.startswith("quick:"):
            cfg = resolve_arena_config(config_id, user_id=user_id, project_id=project_id)
            if not cfg:
                return JSONResponse({"error": f"Config {config_id} not accessible"}, status_code=403)
            continue
        if not isinstance(config_id, str) or not ObjectId.is_valid(config_id):
            return JSONResponse({"error": f"Invalid config id: {config_id}"}, status_code=400)
        cfg = LLMConfigModel.find_by_id(config_id)
        if not cfg:
            return JSONResponse({"error": f"Config {config_id} not found"}, status_code=404)
        # Allow: caller owns it, OR it's public/template, OR it's project-scoped
        # to a project the caller can access.
        is_owner = str(cfg.get("owner_id") or "") == str(user_id)
        visibility = cfg.get("visibility")
        if is_owner or visibility in ("public", "template"):
            continue
        cfg_project_id = cfg.get("project_id")
        if cfg_project_id and check_project_access(user_id, str(cfg_project_id), "viewer"):
            continue
        return JSONResponse({"error": f"Config {config_id} not accessible"}, status_code=403)

    title = data.get("title", "Arena Session")
    session = ArenaSessionModel.create(user_id, config_ids, title)
    # Persist project_id without changing the model signature (model is
    # outside this fix's ownership scope — patched via the existing update()).
    if project_id:
        ArenaSessionModel.update(str(session["_id"]), {"project_id": ObjectId(project_id)})
        session["project_id"] = ObjectId(project_id)

    return JSONResponse({"session": serialize_doc(session)}, status_code=201)


@router.get("/sessions")
def list_sessions(
    request: Request,
    page: int = 1,
    limit: int = 20,
    user: dict = Depends(current_user),
):
    """List user's arena sessions."""
    user_id = str(user["_id"])
    limit = min(max(limit, 1), 50)

    skip = (page - 1) * limit
    sessions = ArenaSessionModel.find_by_user(user_id, skip=skip, limit=limit)
    total = ArenaSessionModel.count_by_user(user_id)

    return {
        "sessions": [serialize_doc(s) for s in sessions],
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit if limit else 1,
    }


@router.patch("/sessions/{session_id}")
async def update_session(session_id: str, request: Request, user: dict = Depends(current_user)):
    """Update a session — currently supports {config_ids, title}."""
    user_id = str(user["_id"])
    if not ObjectId.is_valid(session_id):
        return JSONResponse({"error": "Invalid session id"}, status_code=400)

    session = ArenaSessionModel.find_by_id(session_id)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    if str(session["user_id"]) != user_id:
        return JSONResponse({"error": "Unauthorized"}, status_code=403)

    data = await _json_body(request)
    updates: dict = {}

    if "title" in data:
        title = str(data["title"]).strip()
        if not title:
            return JSONResponse({"error": "title must be non-empty"}, status_code=400)
        updates["title"] = title[:200]

    if "config_ids" in data:
        config_ids = data.get("config_ids") or []
        if not isinstance(config_ids, list) or len(config_ids) < 2:
            return JSONResponse({"error": "At least 2 configs required"}, status_code=400)
        if len(config_ids) > 4:
            return JSONResponse({"error": "Maximum 4 configs allowed"}, status_code=400)

        project_id = session.get("project_id")
        project_id_str = str(project_id) if project_id else None
        normalized: list = []
        for cid in config_ids:
            if not isinstance(cid, str):
                return JSONResponse({"error": f"Invalid config id: {cid}"}, status_code=400)
            if cid.startswith("quick:"):
                cfg = resolve_arena_config(cid, user_id=user_id, project_id=project_id_str)
                if not cfg:
                    return JSONResponse({"error": f"Config {cid} not accessible"}, status_code=403)
                normalized.append(cid)
                continue
            if not ObjectId.is_valid(cid):
                return JSONResponse({"error": f"Invalid config id: {cid}"}, status_code=400)
            cfg = LLMConfigModel.find_by_id(cid)
            if not cfg:
                return JSONResponse({"error": f"Config {cid} not found"}, status_code=404)
            is_owner = str(cfg.get("owner_id") or "") == str(user_id)
            visibility = cfg.get("visibility")
            if is_owner or visibility in ("public", "template"):
                normalized.append(ObjectId(cid))
                continue
            cfg_project_id = cfg.get("project_id")
            if cfg_project_id and check_project_access(user_id, str(cfg_project_id), "viewer"):
                normalized.append(ObjectId(cid))
                continue
            return JSONResponse({"error": f"Config {cid} not accessible"}, status_code=403)
        updates["config_ids"] = normalized

    if not updates:
        return JSONResponse({"error": "No supported fields to update"}, status_code=400)

    ArenaSessionModel.update(session_id, updates)
    refreshed = ArenaSessionModel.find_by_id(session_id)
    return {"session": serialize_doc(refreshed)}


@router.get("/sessions/{session_id}")
def get_session(session_id: str, request: Request, user: dict = Depends(current_user)):
    """Get session with messages."""
    user_id = str(user["_id"])

    session = ArenaSessionModel.find_by_id(session_id)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    if str(session["user_id"]) != user_id:
        return JSONResponse({"error": "Unauthorized"}, status_code=403)

    messages = ArenaMessageModel.find_by_session(session_id)

    # Resolve each id (UUID persona OR `quick:<model>`) — find_by_ids misses
    # synthetic quick models, which is what the picker actually sends.
    proj = str(session["project_id"]) if session.get("project_id") else None
    configs = []
    for cid in session.get("config_ids") or []:
        cfg = resolve_arena_config(str(cid), user_id, proj)
        if cfg:
            configs.append(serialize_doc(cfg))

    return {
        "session": serialize_doc(session),
        "messages": [serialize_doc(m) for m in messages],
        "configs": configs,
    }


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, request: Request, user: dict = Depends(current_user)):
    """Delete a session and its messages."""
    user_id = str(user["_id"])

    session = ArenaSessionModel.find_by_id(session_id)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    if str(session["user_id"]) != user_id:
        return JSONResponse({"error": "Unauthorized"}, status_code=403)

    ArenaMessageModel.delete_by_session(session_id)
    ArenaSessionModel.delete(session_id)

    return {"message": "Session deleted"}


# ---------------------------------------------------------------------------
# arena_stream_bp — SSE parallel streaming + cancel.
# ---------------------------------------------------------------------------
@router.post("/stream")
async def stream_arena(request: Request, user: dict = Depends(current_user)):
    """SSE endpoint for arena parallel streaming.

    Streams chunks from multiple configs interleaved into single response.
    """
    user_id = str(user["_id"])
    data = await _json_body(request)

    session_id = data.get("session_id")
    message_content = data.get("message", "").strip()
    config_ids = data.get("config_ids", [])

    # Validation
    if not message_content:
        return JSONResponse({"error": "Message is required"}, status_code=400)

    if not config_ids or len(config_ids) < 2:
        return JSONResponse({"error": "At least 2 configs required"}, status_code=400)

    # Per-user rate limit (cost/DoS speed-bump) — INDEPENDENT of billing
    # enforcement. Lower cap than chat: each arena stream fans out 2-4 LLM calls.
    retry = check_rate_limit("arena_stream", user_id, max_calls=12, window=60)
    if retry is not None:
        return JSONResponse(
            {"error": "rate_limited", "retry_after": retry},
            status_code=429,
            headers={"Retry-After": str(int(retry))},
        )

    # Per-user concurrent-stream cap (DB connection-pool exhaustion DoS guard) —
    # RESERVE-BEFORE-RESPONSE (closes the count-then-register TOCTOU). ``reserve``
    # counts+inserts atomically under a per-user advisory lock; the producer
    # ``promote``s the reservation_id to the (possibly new) session_id and its
    # existing ``register`` becomes an idempotent refresh of the SAME row.
    preflight = stream_concurrency.StreamPreflight(user_id, _MAX_CONCURRENT_STREAMS)
    if not preflight.reserve():
        return JSONResponse(
            {"error": "too_many_streams", "status": 429},
            status_code=429,
            headers={"Retry-After": "5"},
        )
    # Per-worker global stream ceiling (process-wide pool-DoS hard cap, distinct
    # from the per-user 429). ONE permit per client stream — NOT one per arena
    # fan-out branch (a single arena stream is one client connection + one
    # on_close; minting N would drain the semaphore far faster than the pool
    # fills). At the ceiling, 503 + drop the reservation.
    if not preflight.acquire_global():
        with preflight:
            return JSONResponse(
                {"error": "server_busy", "status": 503},
                status_code=503,
                headers={"Retry-After": "5"},
            )

    # DLP gate — scan user-typed message before persisting and before LLM call.
    # DLPBlockedError is handled globally (403 {code, matches}).
    project_id_for_dlp = None
    if session_id:
        _sess = ArenaSessionModel.find_by_id(session_id)
        if _sess:
            project_id_for_dlp = _sess.get("project_id")
    user_lang = (
        user.get("ai_preferences", {}).get("user_info", {}).get("language", "en")
        or "en"
    )[:2].lower()
    # Offload the blocking DLP gate (DB read + always-on LLM classify, up to
    # ~10s) to a worker thread so it never stalls the event loop. anyio copies
    # the contextvars Context (incl. the Flask app_context) into the worker and
    # the loop awaits it, so DB/JWT access inside the gate stays valid.
    # DLPBlockedError still propagates to the global 403 handler unchanged.
    arena_dlp_redact = bool(data.get("dlp_redact"))

    def _gate() -> dict:
        return gate_redactable(
            text=message_content,
            user_id=user["_id"],
            workspace_id=user.get("active_workspace_id"),
            project_id=project_id_for_dlp,
            source="arena",
            source_ref={"session_id": session_id},
            force_redact=arena_dlp_redact,
            confirmed=bool(data.get("dlp_confirmed")),
            dlp_confirm_token=data.get("dlp_confirm_token"),
            user_lang=user_lang,
        )

    # The DLP + spend gates raise (DLPBlockedError 403 / BudgetExceededError 402)
    # to the global handlers, BEFORE the stream is handed off. On any such raise
    # the reservation + permit must be released (no ``on_close`` will fire), so
    # both awaits run under a release-on-error guard.
    def _spend() -> None:
        spend_gate.gate(
            user_id=user["_id"],
            workspace_id=user.get("active_workspace_id"),
            project_id=project_id_for_dlp,
            origin="web",
        )

    try:
        arena_gate_res = await anyio.to_thread.run_sync(_gate)
        # When redaction fired (workspace ``mode=redact`` OR the client's
        # ``dlp_redact`` flag), forward the SCRUBBED message — the per-config
        # fan-out below reads ``message_content`` directly, and the persisted user
        # message must also hold the scrubbed text.
        if arena_gate_res.get("redacted"):
            message_content = arena_gate_res["redacted_text"]
        # Spend gate — pre-flight budget/credit enforcement, AFTER the DLP gate
        # and BEFORE any streaming response is constructed so a breach is a clean
        # HTTP 402 instead of an in-stream SSE error.
        await anyio.to_thread.run_sync(_spend)
    except BaseException:
        preflight.release()
        raise

    # Capture request-scoped values as locals before the generator runs — the
    # flask_ctx app_context is torn down once this handler returns.
    active_workspace_id = user.get("active_workspace_id")

    # The centralized ``sse_stream_sync`` driver runs this producer on ONE
    # dedicated thread that owns a single ``flask_core.app_context()`` for the
    # whole stream lifetime (so a Flask context never spans a Starlette yield —
    # see app/api/sse.py for the full root-cause writeup). The producer yields
    # fully-formed SSE frames; the per-config fan-out below still uses its OWN
    # inner ``event_queue`` + worker threads, forwarded into yielded frames.
    def _produce(stop_event):
        nonlocal session_id
        try:
            yield from _produce_body(stop_event)
        except Exception as exc:
            _log.exception("arena stream producer failed")
            yield sse_event("error", {"error": str(exc), "message": str(exc)})

    def _produce_body(stop_event):
        nonlocal session_id

        # Create or get session
        if session_id:
            session = ArenaSessionModel.find_by_id(session_id)
            if not session or str(session["user_id"]) != user_id:
                yield sse_event("error", {"message": "Session not found"})
                return
        else:
            session = ArenaSessionModel.create(user_id, config_ids, "Arena Session")
            session_id = str(session["_id"])
            yield sse_event("arena_session_created", {"session": serialize_doc(session)})

        # Save user message
        user_message = ArenaMessageModel.create(
            session_id=session_id,
            role="user",
            content=message_content,
        )

        yield sse_event("arena_user_message", {
            "session_id": session_id,
            "message": serialize_doc(user_message),
        })

        # Get conversation history
        history = ArenaMessageModel.find_by_session(session_id)

        # Fetch all configs — same resolver as debate (UUID persona + `quick:`).
        proj_id_for_resolve = str(session["project_id"]) if session.get("project_id") else None
        configs = {}
        for config_id in config_ids:
            config = resolve_arena_config(config_id, user_id, proj_id_for_resolve)
            if config:
                configs[config_id] = config
            else:
                yield sse_event("arena_message_error", {
                    "session_id": session_id,
                    "config_id": config_id,
                    "error": "Config not found",
                })

        # Create placeholder messages for each config
        message_ids = {}
        for config_id in configs:
            assistant_message = ArenaMessageModel.create(
                session_id=session_id,
                role="assistant",
                content="",
                config_id=config_id,
            )
            message_ids[config_id] = str(assistant_message["_id"])

        # Get user AI preferences for enhanced prompts
        full_user = UserModel.find_by_id(user_id)
        ai_prefs = full_user.get("ai_preferences", {}) if full_user else {}

        ws_id = str(active_workspace_id) if active_workspace_id else None
        proj_id = str(session["project_id"]) if session.get("project_id") else None

        # Re-key the handler's reservation row (taken before the response
        # started) to the finalized session_id so the SAME counted row backs
        # cancel-by-session-id; ``register`` then refreshes it (idempotent).
        stream_state.promote(preflight.reservation_id, session_id)
        # Initialize cancellation tracking (PG-backed for multi-worker — P0.2)
        stream_state.register(session_id, user_id=user_id)

        # Use thread-safe queue for collecting events from threads
        event_queue = queue.Queue()
        active_threads = []

        # Capture the Flask core for thread context (already concrete).
        app = flask_core

        def generate_for_config(config_id, config, message_id):
                    """Generate response for a single config."""
                    # Wrap entire function body with app context for thread safety.
                    # Required for OpenRouterService (uses current_app.config) + DB ops.
                    with app.app_context():
                        try:
                            # Emit start
                            event_queue.put(("arena_message_start", {
                                "session_id": session_id,
                                "config_id": config_id,
                                "message_id": message_id,
                            }))

                            # Build context messages
                            formatted_messages = []
                            for msg in history:
                                if msg["role"] == "user":
                                    formatted_messages.append({"role": "user", "content": msg["content"]})
                                elif (
                                    msg["role"] == "assistant"
                                    and msg.get("config_id")
                                    and str(msg["config_id"]) == config_id
                                ):
                                    formatted_messages.append({"role": "assistant", "content": msg["content"]})

                            # Add current message
                            formatted_messages.append({"role": "user", "content": message_content})

                            # Stream response
                            start_time = time.time()
                            full_content = ""
                            prompt_tokens = 0
                            completion_tokens = 0

                            # Throttle the cross-worker cancel SELECT to ~0.75s
                            # (first chunk checks immediately). Each fan-out
                            # worker thread keeps its OWN monotonic clock — that
                            # is correct, they run concurrently.
                            _CANCEL_CHECK_INTERVAL = 0.75
                            last_cancel_check = 0.0

                            params = config.get("parameters", {})

                            # Build enhanced system prompt with user preferences
                            enhanced_prompt = OpenRouterService.build_enhanced_system_prompt(
                                config.get("system_prompt"),
                                ai_prefs,
                            )

                            stream = OpenRouterService.chat_completion(
                                messages=formatted_messages,
                                model=config["model_id"],
                                system_prompt=enhanced_prompt,
                                temperature=params.get("temperature", 0.7),
                                # 32000 matches config_resolver's chat-output cap:
                                # reasoning models bill thinking against this budget
                                # and starve at 2048 (truncated/empty replies).
                                max_tokens=params.get("max_tokens", 32000),
                                top_p=params.get("top_p", 1.0),
                                stream=True,
                                user_id=user_id,
                                conversation_id=None,
                                feature="arena",
                                workspace_id=ws_id,
                                project_id=proj_id,
                                origin="arena",
                            )

                            for chunk in stream:
                                # Client TCP-disconnected: the SSE driver set the
                                # stop_event — stop this fan-out worker promptly so
                                # its finally tears down the scoped session and its
                                # DB connection returns to the pool.
                                if stop_event.is_set():
                                    break

                                # Check for cancellation (cross-worker — reads from
                                # PG), throttled to ~0.75s so we don't hit the DB
                                # on every token.
                                _now_mono = time.monotonic()
                                if _now_mono - last_cancel_check >= _CANCEL_CHECK_INTERVAL:
                                    last_cancel_check = _now_mono
                                    if stream_state.is_cancelled(session_id):
                                        break

                                if "error" in chunk:
                                    event_queue.put(("arena_message_error", {
                                        "session_id": session_id,
                                        "config_id": config_id,
                                        "message_id": message_id,
                                        "error": chunk["error"].get("message", "Unknown error"),
                                    }))
                                    return

                                if chunk.get("done"):
                                    break

                                choices = chunk.get("choices", [])
                                if choices:
                                    delta = choices[0].get("delta", {})
                                    content = delta.get("content", "")
                                    if content:
                                        full_content += content
                                        event_queue.put(("arena_message_chunk", {
                                            "session_id": session_id,
                                            "config_id": config_id,
                                            "message_id": message_id,
                                            "content": content,
                                        }))

                                    usage = chunk.get("usage", {})
                                    if usage:
                                        prompt_tokens = usage.get("prompt_tokens", prompt_tokens)
                                        completion_tokens = usage.get("completion_tokens", completion_tokens)

                            generation_time = int((time.time() - start_time) * 1000)

                            # Update message in database
                            ArenaMessageModel.update_content_and_metadata(
                                message_id,
                                full_content,
                                {
                                    "model_id": config["model_id"],
                                    "tokens": {"prompt": prompt_tokens, "completion": completion_tokens},
                                    "generation_time_ms": generation_time,
                                },
                            )

                            # Emit completion
                            event_queue.put(("arena_message_complete", {
                                "session_id": session_id,
                                "config_id": config_id,
                                "message_id": message_id,
                                "content": full_content,
                                "metadata": {
                                    "model_id": config["model_id"],
                                    "tokens": {"prompt": prompt_tokens, "completion": completion_tokens},
                                    "generation_time_ms": generation_time,
                                },
                            }))

                        except Exception as e:  # noqa: BLE001
                            event_queue.put(("arena_message_error", {
                                "session_id": session_id,
                                "config_id": config_id,
                                "message_id": message_id,
                                "error": str(e),
                            }))
                        finally:
                            # Each worker thread used its own scoped session —
                            # tear it down on the thread that owns the psycopg3 conn.
                            db.session.remove()

        # Start threads for each config
        for config_id, config in configs.items():
            thread = threading.Thread(
                target=generate_for_config,
                args=(config_id, config, message_ids[config_id]),
            )
            thread.daemon = True
            thread.start()
            active_threads.append(thread)

        # Forward fan-out events to the SSE stream until all threads complete.
        gen_start = time.time()
        last_event_ts = gen_start
        completed_configs = set()
        while len(completed_configs) < len(configs):
            try:
                event_type, event_data = event_queue.get(timeout=0.1)
                yield sse_event(event_type, event_data)
                last_event_ts = time.time()

                # Track completions and errors
                if event_type in ("arena_message_complete", "arena_message_error"):
                    completed_configs.add(event_data.get("config_id"))

            except queue.Empty:
                # Client TCP-disconnected: mark cancelled so the fan-out workers
                # (which poll is_cancelled as a backstop, alongside the stop_event)
                # stop, then break out so the producer's cleanup runs and every
                # pinned DB connection returns to the pool promptly.
                if stop_event.is_set():
                    stream_state.mark_cancelled(session_id)
                    break

                # Wall-clock cap — stop background threads (they poll
                # is_cancelled) and abort the stream cleanly.
                if time.time() - gen_start > _MAX_WALLCLOCK_SECONDS:
                    stream_state.mark_cancelled(session_id)
                    yield sse_event("arena_message_error", {
                        "session_id": session_id,
                        "config_id": None,
                        "error": "Arena stream timed out",
                    })
                    stream_state.clear(session_id)
                    return

                # Idle keepalive — emit a raw SSE comment when no real
                # event has been forwarded to the client for ~15s.
                if time.time() - last_event_ts >= _KEEPALIVE_INTERVAL:
                    yield ": keepalive\n\n"
                    last_event_ts = time.time()

                # Check if all threads are done
                if all(not t.is_alive() for t in active_threads):
                    # Drain any remaining events
                    while not event_queue.empty():
                        event_type, event_data = event_queue.get_nowait()
                        yield sse_event(event_type, event_data)
                        if event_type in ("arena_message_complete", "arena_message_error"):
                            completed_configs.add(event_data.get("config_id"))
                    break
                continue

        # Cleanup
        stream_state.clear(session_id)

    # The driver owns the single app_context + tears down the runner-thread's
    # scoped session on exit. Hand off release ownership: ``on_close`` fires once
    # in the runner-thread finally (crash / disconnect / EOF) and drops the
    # reservation row + returns the global permit together.
    preflight.hand_off()
    return sse_stream_sync(
        _produce, runner_name="arena-stream-runner", on_close=preflight.on_close
    )


@router.post("/cancel/{session_id}")
def cancel_arena_generation(session_id: str, request: Request, user: dict = Depends(current_user)):
    """Cancel arena generation for a session."""
    user_id = str(user["_id"])

    session = ArenaSessionModel.find_by_id(session_id)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    if str(session["user_id"]) != user_id:
        return JSONResponse({"error": "Not authorized"}, status_code=403)

    if stream_state.mark_cancelled(session_id):
        return {"success": True, "message": "Arena generation cancelled"}

    return JSONResponse({"error": "No active generation"}, status_code=404)


__all__ = ["router"]
