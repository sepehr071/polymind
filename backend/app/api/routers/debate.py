"""Debate routes, translated from app/routes/debate.py and
app/routes/debate_stream.py.

Both Flask blueprints (``debate_bp`` + ``debate_stream_bp``) mount under the
SAME url_prefix ``/api/debate`` in ``app/__init__.py``, so they collapse into a
single FastAPI router here.

The SSE ``/stream`` endpoint is SERIAL (no fan-out threads): the whole debate
runs inside one generator. Every request/JWT/body value is captured into handler
locals BEFORE ``sse_stream`` is returned, then the generator opens its OWN Flask
``app_context`` (the router-level ``Depends(flask_ctx)`` context is torn down
once the handler returns, before the streaming body runs). The
``[DEBATE_CONCLUDED]`` marker handling is delegated verbatim to
``DebateService`` exactly as the Flask route did.

``DLPBlockedError`` from ``dlp_gate.gate()`` propagates to the global handler
(403 ``{code, matches}``) — we do NOT catch it here (the Flask routes caught it
and called ``format_blocked_response`` manually; the bridge does that globally).
"""
from __future__ import annotations

import json
import time

import anyio
import anyio.to_thread
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.deps import current_user, flask_ctx
from app.api.sse import sse_stream_sync
from app.models.debate_message import DebateMessageModel
from app.models.debate_session import DebateSessionModel
from app.models.llm_config import LLMConfigModel
from app.models.user import UserModel
from app.services import spend_gate, stream_concurrency, stream_state
from app.services.debate_service import DebateService
from app.services.dlp_gate import gate_redactable
from app.services.openrouter_service import OpenRouterService
from app.utils.config_resolver import resolve_config
from app.utils.helpers import serialize_doc
from app.utils.quick_models import QUICK_MODELS
from app.utils.rate_limit import check_rate_limit

# Router-level dependency: every request runs inside the Flask app_context.
router = APIRouter(dependencies=[Depends(flask_ctx)])

# Per-user concurrent-stream cap (DB connection-pool exhaustion DoS guard). A
# debate pins one connection but can run many rounds.
_MAX_CONCURRENT_STREAMS = 3

_KEEPALIVE_INTERVAL = 15        # seconds between keepalive SSE comments
_MAX_WALLCLOCK_SECONDS = 1800   # 30-minute hard cap on a single stream


async def _json_body(request: Request) -> dict:
    """Read the request JSON body, tolerating empty/garbage like get_json(silent=True)."""
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def sse_event(event_type: str, data: dict) -> str:
    """Format data as SSE event."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


# ---------------------------------------------------------------------------
# /api/debate  (debate_bp)
# ---------------------------------------------------------------------------
@router.get("/sessions")
def list_sessions(request: Request, user: dict = Depends(current_user)):
    """List user's debate sessions with pagination."""
    user_id = str(user["_id"])

    qp = request.query_params
    try:
        page = int(qp.get("page", 1))
    except (TypeError, ValueError):
        page = 1
    try:
        limit = int(qp.get("limit", 20))
    except (TypeError, ValueError):
        limit = 20
    limit = min(limit, 50)  # Cap at 50

    sessions = DebateSessionModel.find_by_user(user_id, page=page, limit=limit)
    total = DebateSessionModel.count_by_user(user_id)

    # Enrich sessions with config names
    enriched_sessions = []
    for session in sessions:
        session_data = serialize_doc(session)

        # Get config names
        config_names = []
        for config_id in session.get("config_ids", []):
            config_id_str = str(config_id)
            if config_id_str.startswith("quick:"):
                model_id = config_id_str.replace("quick:", "")
                config_names.append(QUICK_MODELS.get(model_id, model_id))
            else:
                config = LLMConfigModel.find_by_id(config_id_str)
                if config:
                    config_names.append(config.get("name", "Unknown"))
                else:
                    config_names.append("Deleted Config")

        # Get judge name
        judge_config_id = str(session.get("judge_config_id", ""))
        if judge_config_id.startswith("quick:"):
            model_id = judge_config_id.replace("quick:", "")
            judge_name = QUICK_MODELS.get(model_id, model_id)
        else:
            judge_config = LLMConfigModel.find_by_id(judge_config_id)
            judge_name = judge_config.get("name", "Unknown") if judge_config else "Deleted Config"

        session_data["config_names"] = config_names
        session_data["judge_name"] = judge_name
        enriched_sessions.append(session_data)

    return {
        "sessions": enriched_sessions,
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit,
    }


@router.post("/sessions")
async def create_session(request: Request, user: dict = Depends(current_user)):
    """Create a new debate session."""
    user_id = str(user["_id"])
    data = await _json_body(request)

    # Validate required fields
    topic = (data.get("topic") or "").strip()
    if not topic:
        return JSONResponse({"error": "Topic is required"}, status_code=400)

    # DLP gate — scan debate topic before persisting and before LLM dispatch.
    body_lang = (data.get("lang") or "").strip()
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
    create_dlp_redact = bool(data.get("dlp_redact"))

    def _gate() -> dict:
        return gate_redactable(
            text=topic,
            user_id=user["_id"],
            workspace_id=user.get("active_workspace_id"),
            project_id=None,
            source="debate",
            source_ref={"phase": "create_session"},
            force_redact=create_dlp_redact,
            confirmed=bool(data.get("dlp_confirmed")),
            dlp_confirm_token=data.get("dlp_confirm_token"),
            user_lang=user_lang,
        )

    create_gate_res = await anyio.to_thread.run_sync(_gate)
    # Persist the SCRUBBED topic when redaction fired, so the stored session
    # (and the later stream rebuilt from it) carries the redacted text.
    if create_gate_res.get("redacted"):
        topic = create_gate_res["redacted_text"]

    # Spend gate — pre-flight budget/credit enforcement, AFTER the DLP gate and
    # BEFORE the session is persisted so a breach is a clean HTTP 402
    # (BudgetExceededError -> global handler). Same workspace/project the DLP
    # gate uses (create has no project context yet -> project_id=None).
    def _spend() -> None:
        spend_gate.gate(
            user_id=user["_id"],
            workspace_id=user.get("active_workspace_id"),
            project_id=None,
            origin="web",
        )

    await anyio.to_thread.run_sync(_spend)

    config_ids = data.get("config_ids", [])
    if not config_ids or len(config_ids) < 2:
        return JSONResponse({"error": "At least 2 debater configs are required"}, status_code=400)
    if len(config_ids) > 5:
        return JSONResponse({"error": "Maximum 5 debater configs allowed"}, status_code=400)

    judge_config_id = data.get("judge_config_id")
    if not judge_config_id:
        return JSONResponse({"error": "Judge config is required"}, status_code=400)

    # Validate the caller can actually see each requested config — NOT just that
    # it exists. ``resolve_config`` enforces ownership/visibility (and rejects a
    # ``quick:`` id that is not a curated model), mirroring the arena create gate.
    # Create has no project context (DLP/spend gates pass project_id=None), so a
    # foreign project-scoped config is correctly invisible here. Without this a
    # foreign PRIVATE config id was accepted + persisted, then later reflected
    # (name + model_id) by GET /sessions/{id} (IDOR disclosure).
    for config_id in config_ids:
        if resolve_config(config_id, user_id, None) is None:
            return JSONResponse(
                {"error": f"Config {config_id} not accessible"}, status_code=403
            )

    if resolve_config(judge_config_id, user_id, None) is None:
        return JSONResponse(
            {"error": "Judge config not accessible"}, status_code=403
        )

    # Get optional settings
    rounds = data.get("rounds", 3)
    rounds = max(0, min(rounds, 20))  # 0-20 rounds (0 = infinite)

    max_tokens = data.get("max_tokens", 2048)
    max_tokens = max(256, min(max_tokens, 8192))  # 256-8192 tokens

    # New debate settings
    thinking_type = data.get("thinking_type", "balanced")
    if thinking_type not in ["logical", "feeling", "balanced"]:
        thinking_type = "balanced"

    response_length = data.get("response_length", "balanced")
    if response_length not in ["short", "balanced", "long"]:
        response_length = "balanced"

    # Create session
    session = DebateSessionModel.create(
        user_id=user_id,
        topic=topic,
        config_ids=config_ids,
        judge_config_id=judge_config_id,
        rounds=rounds,
        max_tokens=max_tokens,
        thinking_type=thinking_type,
        response_length=response_length,
    )

    return JSONResponse(
        {"session": serialize_doc(session), "message": "Debate session created"},
        status_code=201,
    )


@router.get("/sessions/{session_id}")
def get_session(session_id: str, user: dict = Depends(current_user)):
    """Get a debate session with all messages."""
    user_id = str(user["_id"])

    session = DebateSessionModel.find_by_id(session_id)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    if str(session["user_id"]) != user_id:
        return JSONResponse({"error": "Not authorized"}, status_code=403)

    # Get messages
    messages = DebateMessageModel.find_by_session(session_id)

    # Build config mapping with full details for frontend
    config_map = {}
    debaters = []
    for config_id in session.get("config_ids", []):
        config_id_str = str(config_id)
        if config_id_str.startswith("quick:"):
            # Handle quick model
            model_id = config_id_str.replace("quick:", "")
            model_name = QUICK_MODELS.get(model_id, model_id)
            config_map[config_id_str] = model_name
            debaters.append({
                "_id": config_id_str,
                "name": model_name,
                "model_id": model_id,
                "isQuickModel": True,
            })
        else:
            config = LLMConfigModel.find_by_id(config_id_str)
            if config:
                config_map[config_id_str] = config.get("name", "Unknown")
                debaters.append({
                    "_id": config_id_str,
                    "name": config.get("name", "Unknown"),
                    "model_id": config.get("model_id", ""),
                })
            else:
                config_map[config_id_str] = "Deleted Config"
                debaters.append({
                    "_id": config_id_str,
                    "name": "Deleted Config",
                    "model_id": "",
                })

    judge_config_id_str = str(session.get("judge_config_id", ""))
    if judge_config_id_str.startswith("quick:"):
        model_id = judge_config_id_str.replace("quick:", "")
        judge_name = QUICK_MODELS.get(model_id, model_id)
        judge_data = {
            "_id": judge_config_id_str,
            "name": judge_name,
            "model_id": model_id,
            "isQuickModel": True,
        }
    else:
        judge_config = LLMConfigModel.find_by_id(judge_config_id_str)
        judge_name = judge_config.get("name", "Unknown") if judge_config else "Deleted Config"
        judge_data = None
        if judge_config:
            judge_data = {
                "_id": judge_config_id_str,
                "name": judge_config.get("name", "Unknown"),
                "model_id": judge_config.get("model_id", ""),
            }

    # Enrich messages with speaker names
    enriched_messages = []
    for msg in messages:
        msg_data = serialize_doc(msg)
        config_id = str(msg.get("config_id", ""))
        if msg.get("role") == "judge":
            msg_data["speaker_name"] = f"Judge ({judge_name})"
        else:
            msg_data["speaker_name"] = config_map.get(config_id, "Unknown")
        enriched_messages.append(msg_data)

    session_data = serialize_doc(session)
    session_data["config_names"] = list(config_map.values())
    session_data["judge_name"] = judge_name
    session_data["debaters"] = debaters
    session_data["judge"] = judge_data
    session_data["messages"] = enriched_messages

    return {"session": session_data}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, user: dict = Depends(current_user)):
    """Delete a debate session and all its messages."""
    user_id = str(user["_id"])

    session = DebateSessionModel.find_by_id(session_id)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    if str(session["user_id"]) != user_id:
        return JSONResponse({"error": "Not authorized"}, status_code=403)

    # Delete messages first
    deleted_messages = DebateMessageModel.delete_by_session(session_id)

    # Delete session
    deleted = DebateSessionModel.delete(session_id, user_id)

    if deleted:
        return {"message": "Session deleted", "deleted_messages": deleted_messages}
    return JSONResponse({"error": "Failed to delete session"}, status_code=500)


@router.post("/sessions/{session_id}/cancel")
def cancel_session(session_id: str, user: dict = Depends(current_user)):
    """Cancel an in-progress debate session."""
    user_id = str(user["_id"])

    session = DebateSessionModel.find_by_id(session_id)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    if str(session["user_id"]) != user_id:
        return JSONResponse({"error": "Not authorized"}, status_code=403)

    if session.get("status") not in ["pending", "in_progress"]:
        return JSONResponse({"error": "Session cannot be cancelled"}, status_code=400)

    DebateSessionModel.update_status(session_id, "cancelled")

    return {"message": "Session cancelled"}


# ---------------------------------------------------------------------------
# /api/debate  (debate_stream_bp)
# ---------------------------------------------------------------------------
@router.post("/stream")
async def stream_debate(request: Request, user: dict = Depends(current_user)):
    """SSE endpoint for executing a debate (serial, single-generator)."""
    user_id = str(user["_id"])
    data = await _json_body(request)

    session_id = data.get("session_id")
    if not session_id:
        return JSONResponse({"error": "session_id is required"}, status_code=400)

    # Validate session
    session = DebateSessionModel.find_by_id(session_id)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    if str(session["user_id"]) != user_id:
        return JSONResponse({"error": "Not authorized"}, status_code=403)

    if session.get("status") == "completed":
        return JSONResponse({"error": "Debate already completed"}, status_code=400)

    if session.get("status") == "cancelled":
        return JSONResponse({"error": "Debate was cancelled"}, status_code=400)

    # Per-user rate limit (cost/DoS speed-bump) — INDEPENDENT of billing
    # enforcement. A debate spends many LLM calls; keep the cap low.
    retry = check_rate_limit("debate_stream", user_id, max_calls=12, window=60)
    if retry is not None:
        return JSONResponse(
            {"error": "rate_limited", "retry_after": retry},
            status_code=429,
            headers={"Retry-After": str(int(retry))},
        )

    # Per-user concurrent-stream cap (DB connection-pool exhaustion DoS guard) —
    # RESERVE-BEFORE-RESPONSE (closes the count-then-register TOCTOU). The debate
    # session_id is already known + validated here, so reserve DIRECTLY under it:
    # the producer's existing ``register(session_id)`` is then an idempotent
    # refresh of the SAME counted row (no promote needed).
    preflight = stream_concurrency.StreamPreflight(
        user_id, _MAX_CONCURRENT_STREAMS, reservation_id=session_id
    )
    if not preflight.reserve():
        return JSONResponse(
            {"error": "too_many_streams", "status": 429},
            status_code=429,
            headers={"Retry-After": "5"},
        )
    # Per-worker global stream ceiling (process-wide pool-DoS hard cap, distinct
    # from the per-user 429). One permit per client stream. At the ceiling, 503 +
    # drop the reservation.
    if not preflight.acquire_global():
        with preflight:
            return JSONResponse(
                {"error": "server_busy", "status": 503},
                status_code=503,
                headers={"Retry-After": "5"},
            )

    # Pre-fetch all data needed for the debate (avoid app context issues in generator)
    config_ids = session.get("config_ids", [])
    judge_config_id = str(session.get("judge_config_id", ""))
    topic = session.get("topic", "")

    # DLP gate — defence-in-depth scan on the topic at stream entry point so
    # debates created before the gate was wired (or via other entry points)
    # cannot bypass content safety. DLPBlockedError -> global 403 handler.
    body_lang = (data.get("lang") or "").strip()
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
    stream_dlp_redact = bool(data.get("dlp_redact"))

    def _gate() -> dict:
        return gate_redactable(
            text=topic,
            user_id=user["_id"],
            workspace_id=user.get("active_workspace_id"),
            project_id=session.get("project_id"),
            source="debate",
            source_ref={"session_id": session_id},
            force_redact=stream_dlp_redact,
            confirmed=bool(data.get("dlp_confirmed")),
            dlp_confirm_token=data.get("dlp_confirm_token"),
            user_lang=user_lang,
        )

    # Spend gate — pre-flight budget/credit enforcement, AFTER the DLP gate and
    # BEFORE sse_stream_sync is constructed so a breach is a clean HTTP 402
    # (BudgetExceededError -> global handler) instead of an in-stream SSE error.
    # Same workspace/project the DLP gate + usage attribution resolve.
    def _spend() -> None:
        spend_gate.gate(
            user_id=user["_id"],
            workspace_id=user.get("active_workspace_id"),
            project_id=session.get("project_id"),
            origin="web",
        )

    # The DLP + spend gates raise (403 / 402) to the global handlers BEFORE the
    # stream is handed off — on any such raise release the reservation + permit
    # (no ``on_close`` will fire).
    try:
        stream_gate_res = await anyio.to_thread.run_sync(_gate)
        # When the stream-time gate redacted, forward that scrubbed topic into the
        # generator (which closes over ``topic``). The topic was already scrubbed
        # at create time in redact mode; this also covers sessions created before
        # redact-mode was enabled.
        if stream_gate_res.get("redacted"):
            topic = stream_gate_res["redacted_text"]
        await anyio.to_thread.run_sync(_spend)
    except BaseException:
        preflight.release()
        raise

    settings = session.get("settings", {})
    total_rounds = settings.get("rounds", 3)
    max_tokens = settings.get("max_tokens", 2048)

    # Get new debate settings
    thinking_type = settings.get("thinking_type", "balanced")
    response_length = settings.get("response_length", "balanced")

    # Fetch configs (supports quick models). Pass the acting user + the debate
    # session's project scope so the resolver enforces ownership/visibility:
    # the resolver now blocks cross-user private personas, so a debate that
    # legitimately uses the owner's own private config must supply user_id.
    debate_proj_id = session.get("project_id")
    debater_configs = {}
    config_names = {}
    for config_id in config_ids:
        config = resolve_config(config_id, user_id, debate_proj_id)
        if config:
            config_key = str(config_id) if str(config_id).startswith("quick:") else str(config_id)
            debater_configs[config_key] = config
            config_names[config_key] = config.get("name", "Unknown")

    judge_config = resolve_config(judge_config_id, user_id, debate_proj_id)
    if not judge_config:
        with preflight:  # release reservation + permit (no stream handed off)
            return JSONResponse({"error": "Judge config not found"}, status_code=404)

    ws_id = str(user.get("active_workspace_id")) if user.get("active_workspace_id") else None
    proj_id = str(session["project_id"]) if session.get("project_id") else None

    # Get user AI preferences
    full_user = UserModel.find_by_id(user_id)
    ai_prefs = full_user.get("ai_preferences", {}) if full_user else {}

    # The driver runs this producer on ONE dedicated thread owning a single
    # ``flask_core.app_context()`` for the whole stream lifetime (see
    # app/api/sse.py), so a Flask context never spans a Starlette yield.
    def generate(stop_event):
        # Initialize cancellation tracking (PG-backed for multi-worker — P0.2)
        stream_state.register(session_id, user_id=str(user["_id"]))

        # Generator-level wall-clock cap + idle keepalive tracking. A raw SSE
        # comment every ~15s keeps proxies from dropping a connection idling on
        # a slow upstream; the cap bounds total debate lifetime.
        gen_start = time.time()
        last_yield = gen_start

        # Throttle the per-chunk cross-worker cancel SELECT to ~0.75s (the
        # boundary checks between rounds/speakers stay un-throttled — they fire
        # at most once per turn). Reset per stream-segment so the first chunk of
        # each LLM call still checks immediately. ``time.monotonic`` is correct
        # on the single sync runner thread.
        _CANCEL_CHECK_INTERVAL = 0.75
        last_cancel_check = 0.0

        try:
            # Update session status
            DebateSessionModel.update_status(session_id, "in_progress", current_round=1)

            # Determine if infinite mode
            is_infinite = total_rounds == 0
            max_rounds = 20 if is_infinite else total_rounds

            yield sse_event("debate_session_started", {
                "session_id": session_id,
                "topic": topic,
                "total_rounds": total_rounds,
                "is_infinite": is_infinite,
                "debaters": list(config_names.values()),
            })

            # Track all messages for context building
            all_messages = []

            # Execute rounds (while loop for infinite mode support)
            round_num = 0
            all_debaters_concluded = False

            while round_num < max_rounds and not all_debaters_concluded:
                round_num += 1
                concluded_this_round = set()  # Track who concluded this round
                # Client TCP-disconnected — stop the multi-round loop promptly.
                if stop_event.is_set():
                    return
                # Check cancellation
                if stream_state.is_cancelled(session_id):
                    yield sse_event("debate_error", {"message": "Debate cancelled"})
                    DebateSessionModel.update_status(session_id, "cancelled")
                    return

                yield sse_event("debate_round_start", {
                    "session_id": session_id,
                    "round": round_num,
                    "total_rounds": total_rounds,
                    "is_infinite": is_infinite,
                })

                DebateSessionModel.update_status(session_id, "in_progress", current_round=round_num)

                # Each debater speaks in sequence
                for order, config_id in enumerate(debater_configs.keys()):
                    # Client TCP-disconnected — stop before the next debater.
                    if stop_event.is_set():
                        return
                    # Check cancellation
                    if stream_state.is_cancelled(session_id):
                        yield sse_event("debate_error", {"message": "Debate cancelled"})
                        DebateSessionModel.update_status(session_id, "cancelled")
                        return

                    config = debater_configs[config_id]
                    speaker_name = config_names[config_id]

                    yield sse_event("debate_message_start", {
                        "session_id": session_id,
                        "round": round_num,
                        "config_id": config_id,
                        "speaker_name": speaker_name,
                        "order": order,
                    })

                    # Build context for this debater
                    formatted_messages = DebateService.format_messages_for_context(
                        all_messages, config_names
                    )
                    system_prompt = DebateService.build_debater_context(
                        topic, formatted_messages, config, speaker_name,
                        is_infinite=is_infinite,
                        thinking_type=thinking_type,
                        response_length=response_length,
                    )
                    user_prompt = DebateService.build_debater_user_prompt(
                        round_num, total_rounds, is_first_in_round=(order == 0)
                    )

                    # Enhance system prompt with user preferences
                    enhanced_prompt = OpenRouterService.build_enhanced_system_prompt(
                        system_prompt, ai_prefs
                    )

                    params = config.get("parameters", {})

                    # Stream response
                    start_time = time.time()
                    full_content = ""
                    prompt_tokens = 0
                    completion_tokens = 0

                    stream = OpenRouterService.chat_completion(
                        messages=[{"role": "user", "content": user_prompt}],
                        model=config["model_id"],
                        system_prompt=enhanced_prompt,
                        temperature=params.get("temperature", 0.7),
                        max_tokens=max_tokens,
                        top_p=params.get("top_p", 1.0),
                        stream=True,
                        user_id=user_id,
                        conversation_id=None,
                        feature="debate",
                        workspace_id=ws_id,
                        project_id=proj_id,
                        origin="debate",
                    )

                    last_cancel_check = 0.0  # fresh check on this debater's first chunk
                    for chunk in stream:
                        # Client TCP-disconnected: the SSE driver set the
                        # stop_event — stop streaming this debater promptly so the
                        # finally clears stream_state and releases the DB conn.
                        if stop_event.is_set():
                            break

                        # Check cancellation (throttled to ~0.75s — see top of
                        # generate()).
                        _now_mono = time.monotonic()
                        if _now_mono - last_cancel_check >= _CANCEL_CHECK_INTERVAL:
                            last_cancel_check = _now_mono
                            if stream_state.is_cancelled(session_id):
                                break

                        # Wall-clock cap — abort a stalled debate cleanly.
                        if time.time() - gen_start > _MAX_WALLCLOCK_SECONDS:
                            yield sse_event("debate_error", {
                                "session_id": session_id,
                                "error": "Debate stream timed out",
                            })
                            DebateSessionModel.update_status(session_id, "cancelled")
                            return

                        # Idle keepalive — raw SSE comment after ~15s silence.
                        if time.time() - last_yield >= _KEEPALIVE_INTERVAL:
                            yield ": keepalive\n\n"
                            last_yield = time.time()

                        if "error" in chunk:
                            yield sse_event("debate_error", {
                                "session_id": session_id,
                                "round": round_num,
                                "config_id": config_id,
                                "error": chunk["error"].get("message", "Unknown error"),
                            })
                            return

                        if chunk.get("done"):
                            break

                        choices = chunk.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                full_content += content
                                yield sse_event("debate_message_chunk", {
                                    "session_id": session_id,
                                    "round": round_num,
                                    "config_id": config_id,
                                    "content": content,
                                })
                                last_yield = time.time()

                            usage = chunk.get("usage", {})
                            if usage:
                                prompt_tokens = usage.get("prompt_tokens", prompt_tokens)
                                completion_tokens = usage.get("completion_tokens", completion_tokens)

                    generation_time = int((time.time() - start_time) * 1000)

                    # Save message to database
                    metadata = {
                        "model_id": config["model_id"],
                        "tokens": {"prompt": prompt_tokens, "completion": completion_tokens},
                        "generation_time_ms": generation_time,
                    }

                    # Check if debater concluded (infinite mode)
                    debater_concluded = False
                    display_content = full_content
                    if is_infinite and DebateService.check_debate_concluded(full_content):
                        debater_concluded = True
                        concluded_this_round.add(config_id)
                        # Strip marker for display/storage
                        display_content = DebateService.strip_concluded_marker(full_content)

                    DebateMessageModel.create(
                        session_id=session_id,
                        round_num=round_num,
                        config_id=config_id,
                        role="debater",
                        content=display_content,
                        order_in_round=order,
                        metadata=metadata,
                    )

                    # Add to context for next speakers
                    all_messages.append({
                        "round": round_num,
                        "config_id": config_id,
                        "speaker_name": speaker_name,
                        "content": display_content,
                        "role": "debater",
                    })

                    yield sse_event("debate_message_complete", {
                        "session_id": session_id,
                        "round": round_num,
                        "config_id": config_id,
                        "speaker_name": speaker_name,
                        "content": display_content,
                        "concluded": debater_concluded,
                        "metadata": metadata,
                    })

                    # Emit concluded event if applicable
                    if debater_concluded:
                        yield sse_event("debate_debater_concluded", {
                            "session_id": session_id,
                            "round": round_num,
                            "config_id": config_id,
                            "speaker_name": speaker_name,
                        })

                yield sse_event("debate_round_complete", {
                    "session_id": session_id,
                    "round": round_num,
                    "concluded_count": len(concluded_this_round),
                    "total_debaters": len(debater_configs),
                })

                # Check if all debaters concluded (infinite mode)
                if is_infinite and len(concluded_this_round) == len(debater_configs):
                    all_debaters_concluded = True

            # Judge phase
            if stop_event.is_set():
                return
            if stream_state.is_cancelled(session_id):
                yield sse_event("debate_error", {"message": "Debate cancelled"})
                DebateSessionModel.update_status(session_id, "cancelled")
                return

            yield sse_event("debate_judge_start", {
                "session_id": session_id,
                "judge_name": judge_config.get("name", "Judge"),
            })

            # Build judge prompt
            formatted_messages = DebateService.format_messages_for_context(
                all_messages, config_names
            )
            judge_system_prompt = DebateService.build_judge_prompt(
                topic, formatted_messages, list(config_names.values())
            )
            judge_user_prompt = DebateService.build_judge_user_prompt()

            # Enhance with user preferences
            enhanced_judge_prompt = OpenRouterService.build_enhanced_system_prompt(
                judge_system_prompt, ai_prefs
            )

            judge_params = judge_config.get("parameters", {})

            # Stream judge response
            start_time = time.time()
            verdict_content = ""
            prompt_tokens = 0
            completion_tokens = 0

            stream = OpenRouterService.chat_completion(
                messages=[{"role": "user", "content": judge_user_prompt}],
                model=judge_config["model_id"],
                system_prompt=enhanced_judge_prompt,
                temperature=judge_params.get("temperature", 0.7),
                max_tokens=max_tokens * 2,  # Give judge more room
                top_p=judge_params.get("top_p", 1.0),
                stream=True,
                user_id=user_id,
                conversation_id=None,
                feature="debate",
                workspace_id=ws_id,
                project_id=proj_id,
                origin="debate",
            )

            last_cancel_check = 0.0  # fresh check on the judge's first chunk
            for chunk in stream:
                # Client TCP-disconnected: the SSE driver set the stop_event —
                # stop streaming the judge promptly so the finally clears
                # stream_state and releases the DB connection.
                if stop_event.is_set():
                    break

                # Check cancellation (throttled to ~0.75s — see top of generate()).
                _now_mono = time.monotonic()
                if _now_mono - last_cancel_check >= _CANCEL_CHECK_INTERVAL:
                    last_cancel_check = _now_mono
                    if stream_state.is_cancelled(session_id):
                        break

                # Wall-clock cap — abort a stalled judge phase cleanly.
                if time.time() - gen_start > _MAX_WALLCLOCK_SECONDS:
                    yield sse_event("debate_error", {
                        "session_id": session_id,
                        "error": "Debate stream timed out",
                    })
                    DebateSessionModel.update_status(session_id, "cancelled")
                    return

                # Idle keepalive — raw SSE comment after ~15s silence.
                if time.time() - last_yield >= _KEEPALIVE_INTERVAL:
                    yield ": keepalive\n\n"
                    last_yield = time.time()

                if "error" in chunk:
                    yield sse_event("debate_error", {
                        "session_id": session_id,
                        "error": chunk["error"].get("message", "Judge error"),
                    })
                    return

                if chunk.get("done"):
                    break

                choices = chunk.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        verdict_content += content
                        yield sse_event("debate_judge_chunk", {
                            "session_id": session_id,
                            "content": content,
                        })
                        last_yield = time.time()

                    usage = chunk.get("usage", {})
                    if usage:
                        prompt_tokens = usage.get("prompt_tokens", prompt_tokens)
                        completion_tokens = usage.get("completion_tokens", completion_tokens)

            generation_time = int((time.time() - start_time) * 1000)

            # Save judge verdict
            judge_metadata = {
                "model_id": judge_config["model_id"],
                "tokens": {"prompt": prompt_tokens, "completion": completion_tokens},
                "generation_time_ms": generation_time,
            }

            DebateMessageModel.create(
                session_id=session_id,
                round_num=0,  # 0 indicates judge verdict
                config_id=judge_config_id,
                role="judge",
                content=verdict_content,
                order_in_round=0,
                metadata=judge_metadata,
            )

            # Update session with verdict
            DebateSessionModel.set_verdict(session_id, verdict_content)

            yield sse_event("debate_judge_complete", {
                "session_id": session_id,
                "verdict": verdict_content,
                "metadata": judge_metadata,
            })

            yield sse_event("debate_session_complete", {
                "session_id": session_id,
                "status": "completed",
            })

        except Exception as e:  # noqa: BLE001
            yield sse_event("debate_error", {
                "session_id": session_id,
                "error": str(e),
            })
            DebateSessionModel.update_status(session_id, "cancelled")
        finally:
            # Cleanup
            stream_state.clear(session_id)

    # The driver owns the single app_context + tears down the runner-thread's
    # scoped session on exit.
    # Hand off release ownership: ``on_close`` fires once in the runner-thread
    # finally (crash / disconnect / EOF) and drops the reservation row (keyed by
    # session_id) + returns the global permit together.
    preflight.hand_off()
    return sse_stream_sync(
        generate, runner_name="debate-stream-runner", on_close=preflight.on_close
    )


@router.post("/cancel/{session_id}")
def cancel_debate_generation(session_id: str, user: dict = Depends(current_user)):
    """Cancel an in-progress debate generation."""
    user_id = str(user["_id"])

    session = DebateSessionModel.find_by_id(session_id)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    if str(session["user_id"]) != user_id:
        return JSONResponse({"error": "Not authorized"}, status_code=403)

    if stream_state.mark_cancelled(session_id):
        return {"success": True, "message": "Debate generation cancelled"}

    return JSONResponse({"error": "No active generation"}, status_code=404)


__all__ = ["router"]
