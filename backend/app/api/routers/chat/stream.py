from __future__ import annotations

import json
import logging
import os
import queue
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import anyio
import anyio.to_thread
from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from app.api.core import db
from app.settings import settings
from app.api.deps import current_user, flask_ctx, require_active
from app.api.sse import sse_stream_sync
from app.models.conversation import ConversationModel
from app.models.llm_config import LLMConfigModel
from app.models.message import MessageModel
from app.models.upload import UploadModel
from app.models.user import UserModel
from app.services import spend_gate, stream_concurrency, stream_state
from app.services.dlp_gate import gate_redactable
from app.services.dlp_service import DLPDetector
from app.prompts.canvas import CANVAS_SYSTEM_PROMPT
from app.prompts.data_analyst import DATA_ANALYST_SYSTEM_PROMPT
from app.services.openrouter_service import OpenRouterService
from app.utils.config_resolver import resolve_config as resolve_chat_config
from app.utils.helpers import generate_conversation_title, serialize_doc
from app.utils.ids import is_valid_id
from app.utils.permissions import (
    WORKSPACE_ACCESS_DENIED,
    conversation_workspace_denied,
    resolve_conversation_access,
)
from app.utils.rate_limit import check_rate_limit

from ._common import (
    _MAX_CONCURRENT_STREAMS,
    _KEEPALIVE_INTERVAL,
    _MAX_WALLCLOCK_SECONDS,
    _DATA_FILE_EXTS,
    _append_artifact_recaps,
    _attachment_text_for_dlp,
    _filter_owned_attachments,
    _format_tool_result_for_model,
    _gate_and_redact_chat_turn,
    _is_data_attachment,
    _json_body,
    _logger,
    _persist_file_artifacts,
    _prune_dead_file_artifacts,
    _resolve_user_lang,
    _sse_event,
    _text_has_url,
    router,
)

from .data_path import (
    _DATA_ANALYSIS_TEMPERATURE,
    _DATA_FEATURE,
    _DATA_CAPPED_NARRATION_NOTE,
    _DATA_LOOP_DONE,
    _RUN_PYTHON_TOOL,
    _data_analysis_prefs,
    _run_data_analysis_sync,
)
from .titles import _TITLE_EXECUTOR, _generate_title_async

# ---------------------------------------------------------------------------
# chat_stream_bp — SSE stream (same /api/chat prefix).
# ---------------------------------------------------------------------------
@router.post("/stream")
async def stream_chat(request: Request, user: dict = Depends(current_user)):
    """SSE endpoint for chat streaming. Replaces the WebSocket send_message event.

    Every request-scoped value (user, body, derived ids/lang) is pre-fetched
    into locals BEFORE the generator is built — the flask_ctx context is gone
    once this handler returns, so the generator opens its own app_context.
    """
    user_id = str(user["_id"])
    data = await _json_body(request)

    conversation_id = data.get("conversation_id")
    config_id = data.get("config_id")
    message_content = (data.get("message") or "").strip()
    # Reject any attachment whose upload_id isn't owned by the sender before it
    # is scanned / persisted / inlined (cross-tenant upload IDOR guard).
    attachments = _filter_owned_attachments(data.get("attachments", []), user_id)
    intent = data.get("intent")
    web_search = bool(data.get("web_search"))
    dlp_redact = bool(data.get("dlp_redact"))
    quoted_text = (data.get("quoted_text") or "").strip() or None
    if quoted_text and len(quoted_text) > 4000:
        quoted_text = quoted_text[:4000]

    # Validation
    if not message_content:
        return JSONResponse({"error": "Message content is required"}, status_code=400)

    if not config_id:
        return JSONResponse({"error": "config_id is required"}, status_code=400)

    # Per-user rate limit (cost/DoS speed-bump) — INDEPENDENT of billing
    # enforcement so it protects even with the spend gate off. In-process per
    # worker; effective ceiling is max_calls * worker_count.
    retry = check_rate_limit("chat_stream", user_id, max_calls=30, window=60)
    if retry is not None:
        return JSONResponse(
            {"error": "rate_limited", "retry_after": retry},
            status_code=429,
            headers={"Retry-After": str(int(retry))},
        )

    # Per-user concurrent-stream cap (DB connection-pool exhaustion DoS guard) —
    # RESERVE-BEFORE-RESPONSE (closes the old count-then-register TOCTOU: the
    # count ran here in the handler but the row was written later inside the
    # producer, so concurrent opens both passed the check). ``reserve`` does the
    # count+insert atomically under a per-user advisory lock; the
    # reservation_id is minted HERE and ``promote``d to the real message_id once
    # the producer creates the assistant message. ``StreamPreflight`` also owns
    # the per-worker global stream permit and releases BOTH on any pre-stream
    # failure (see ``with preflight:`` below).
    preflight = stream_concurrency.StreamPreflight(user_id, _MAX_CONCURRENT_STREAMS)
    if not preflight.reserve():
        return JSONResponse(
            {"error": "too_many_streams", "status": 429},
            status_code=429,
            headers={"Retry-After": "5"},
        )

    # Per-worker global stream ceiling (process-wide pool-DoS hard cap, distinct
    # from the per-user 429 above). One permit per client stream. At the ceiling,
    # return 503 + Retry-After; the per-user reservation is dropped by __exit__
    # (no permit was taken). On the happy path the permit + reservation are both
    # released by the SSE driver's ``on_close``.
    if not preflight.acquire_global():
        with preflight:  # release the reservation we just took
            return JSONResponse(
                {"error": "server_busy", "status": 503},
                status_code=503,
                headers={"Retry-After": "5"},
            )

    # From here a pre-stream exception (DLP block, spend 402, …) or early return
    # must release the reservation + permit. ``with preflight:`` does exactly
    # that on __exit__ UNLESS ``preflight.hand_off()`` was called (which it is,
    # immediately before returning the StreamingResponse). The body is a
    # module-level coroutine so this try/finally can wrap the whole thing without
    # re-indenting ~900 lines.
    with preflight:
        return await _stream_chat_impl(
            request, user, user_id, data, conversation_id, config_id,
            message_content, attachments, intent, web_search, dlp_redact,
            quoted_text, preflight,
        )


async def _stream_chat_impl(
    request, user, user_id, data, conversation_id, config_id,
    message_content, attachments, intent, web_search, dlp_redact,
    quoted_text, preflight,
):
    """Body of the chat SSE handler, after the reservation + permit are held.

    Split out of ``stream_chat`` so the reserve/acquire ``with preflight:`` block
    can wrap the entire body (any pre-stream exception or early return releases
    the reservation + permit) without re-indenting the whole function. On the
    success path the closing ``sse_stream_sync`` call passes ``on_close`` and the
    caller's ``preflight.hand_off()`` transfers release ownership to it.
    """
    reservation_id = preflight.reservation_id

    # Fetch the conversation up front (continuing one) for access gating + config
    # resolution. A non-owner contributor sends under the conversation's existing
    # config, resolved as the OWNER (so the owner's private persona resolves) and
    # cannot switch the model; a non-member gets a clean 4xx HERE rather than an
    # in-stream error. New conversations are stamped into the caller's active
    # org, owner = caller.
    preflight_conv = None
    is_owner_stream = True
    if conversation_id:
        # Only scalar fields (config_id, user_id, project_id) + the access gate
        # are read off this dict, never ``branches`` — skip branch hydration.
        preflight_conv = ConversationModel.find_by_id(
            conversation_id, include_branches=False
        )
        role, acc_err = resolve_conversation_access(preflight_conv, user_id, "viewer")
        if acc_err:
            msg, status = acc_err
            payload = {"error": msg}
            if status == 403:
                payload["status"] = 403
            return JSONResponse(payload, status_code=status)
        if conversation_workspace_denied(preflight_conv, user):
            return JSONResponse(dict(WORKSPACE_ACCESS_DENIED), status_code=403)
        is_owner_stream = role == "owner"

    if preflight_conv is not None and not is_owner_stream:
        config_id = preflight_conv.get("config_id") or config_id
        cfg_user_id = str(preflight_conv["user_id"])
        cfg_project_id = preflight_conv.get("project_id")
    else:
        cfg_user_id = user_id
        cfg_project_id = preflight_conv.get("project_id") if preflight_conv else None

    # Get config (supports quick models). Pass acting user + project scope so the
    # resolver blocks cross-user private personas and gates project-scoped ones.
    config = resolve_chat_config(config_id, cfg_user_id, cfg_project_id)
    if not config:
        return JSONResponse({"error": "Config not found"}, status_code=404)

    is_quick_model = str(config_id).startswith("quick:")
    is_agent_model = str(config_id).startswith("agent:")

    # Canvas intent: keep the USER-SELECTED model but swap in the strict
    # Canvas Coder system prompt (single runnable ```html fence contract).
    # The frontend no longer pins canvas to a dedicated agent config — the
    # model comes from the picker, only the prompt changes.
    if intent == "canvas":
        config = {**config, "system_prompt": CANVAS_SYSTEM_PROMPT}

    # Optional per-message reasoning effort (composer "thinking" switcher).
    # Whitelisted; absent/invalid -> None -> no `reasoning` field on the
    # OpenRouter payload (provider default). Ignored by non-reasoning models.
    reasoning_effort = data.get("reasoning_effort")
    if reasoning_effort not in ("low", "medium", "high"):
        reasoning_effort = None

    # DLP gate — scan user-typed message before persisting and before LLM call.
    # DLPBlockedError is handled globally (403 {code, matches}).
    project_id_for_dlp = preflight_conv.get("project_id") if preflight_conv else None
    # Prefer explicit UI language from request body (i18next current language);
    # fall back to user.ai_preferences.user_info.language; final fallback 'en'.
    user_lang = _resolve_user_lang(data, user)

    # The DLP gate does a DB read + an always-on blocking LLM classify (a
    # ``requests`` POST, up to ~10s). Offload it to a worker thread so it never
    # stalls the event loop; anyio copies the contextvars Context (incl. the
    # Flask app_context) into the worker and the loop awaits it, so DB/JWT access
    # inside the gate stays valid. DLPBlockedError still propagates to the global
    # 403 handler unchanged. The attachment-text read also runs in the worker.
    #
    # ``gate_redactable`` is a drop-in superset of the old ``gate``: in enforce
    # mode it block/confirm/warns exactly as before (forwarding the confirm
    # flag + HMAC token); in redact mode (workspace policy ``mode=redact`` OR
    # the client's ``dlp_redact`` flag) it scrubs sensitive spans out and
    # returns the redacted message + non-PDF attachment text, which we persist +
    # send instead of the raw values. The scrub happens BEFORE persist so the
    # LLM payload (rebuilt from the persisted row) is automatically scrubbed.
    redact_ws_id = user.get("active_workspace_id")
    stream_confirmed = bool(data.get("dlp_confirmed"))
    stream_confirm_token = data.get("dlp_confirm_token")

    def _gate() -> dict:
        return _gate_and_redact_chat_turn(
            user=user,
            workspace_id=redact_ws_id,
            project_id=project_id_for_dlp,
            message_content=message_content,
            attachments=attachments,
            force_redact=dlp_redact,
            confirmed=stream_confirmed,
            dlp_confirm_token=stream_confirm_token,
            user_lang=user_lang,
            source_ref={"conversation_id": conversation_id},
        )

    gate_out = await anyio.to_thread.run_sync(_gate)
    # Splice the scrubbed message + attachments back into the handler locals the
    # generator closes over, so persistence + the LLM payload use them.
    message_content = gate_out["message_content"]
    attachments = gate_out["attachments"]
    dlp_redacted_meta = gate_out["badge"]
    # web_fetch auto-enables when the (scrubbed) user message text contains a URL.
    web_fetch = _text_has_url(message_content)

    # Spend gate (pre-flight budget/credit enforcement). Runs AFTER the DLP gate
    # and BEFORE the SSE response is constructed, so a breach is a real HTTP 402
    # (BudgetExceededError -> global handler) rather than an in-stream SSE error.
    # Reuses the same ws/project ids the DLP gate resolved for attribution.
    # Offloaded to a worker thread so it never stalls the event loop.
    def _spend() -> None:
        spend_gate.gate(
            user_id=user_id,
            workspace_id=redact_ws_id,
            project_id=project_id_for_dlp,
            origin="web",
            feature=_DATA_FEATURE if intent == "data" else "chat",
        )

    await anyio.to_thread.run_sync(_spend)

    # Check user token limit
    if user["usage"]["tokens_limit"] != -1:
        if user["usage"]["tokens_used"] >= user["usage"]["tokens_limit"]:
            return JSONResponse({"error": "Token limit reached"}, status_code=429)

    # The centralized ``sse_stream_sync`` driver runs this producer on ONE
    # dedicated thread that owns a single DB-session scope for the whole stream
    # lifetime, so the scope never spans a Starlette yield (see app/api/sse.py).
    # The producer yields fully-formed SSE frames and uses burst-and-remove to
    # release its pooled connection during the OpenRouter network wait (below);
    # background title refresh runs on the shared ``_TITLE_EXECUTOR``.
    def _produce(stop_event):
        nonlocal_conversation_id = conversation_id

        # Generator-level wall-clock cap + idle keepalive tracking.
        gen_start = time.time()
        last_yield = gen_start

        # Create or get conversation. The producer reads only scalar fields
        # (config_id, active_branch, project_id, workspace_id) + the access
        # gate (user_id / _id) off this dict — never ``branches`` — so skip the
        # per-turn branch hydration SELECT.
        is_new_conversation = False
        if nonlocal_conversation_id:
            conversation = ConversationModel.find_by_id(
                nonlocal_conversation_id, include_branches=False
            )
            _role, _acc_err = resolve_conversation_access(conversation, user_id, "viewer")
            if _acc_err:
                yield _sse_event("error", {"message": "Conversation not found"})
                return
            # Persist a mid-conversation model switch (OWNER only). The composer
            # writes the picker's config_id on every send, but the conversation
            # row keeps its creation-time value, so a page refresh (which restores
            # from conversation.config_id) would otherwise snap back to the
            # original model. Stamp the new id so the selection survives reload.
            # Contributing members cannot switch the model.
            if _role == "owner" and config_id and conversation.get("config_id") != config_id:
                ConversationModel.update(nonlocal_conversation_id, {"config_id": config_id})
                conversation["config_id"] = config_id
        else:
            # Create new conversation with temporary title
            is_new_conversation = True
            title = generate_conversation_title(message_content)
            conversation = ConversationModel.create(
                user_id=user_id,
                config_id=config_id,
                title=title,
                workspace_id=user.get("active_workspace_id"),
            )
            nonlocal_conversation_id = str(conversation["_id"])

            # Notify about new conversation
            yield _sse_event("conversation_created", {
                "conversation": serialize_doc(conversation),
            })

        # Get active branch
        branch_id = conversation.get("active_branch", "main")

        # Generate a better title off the runner thread (new conversations
        # only) on a SHARED bounded pool — see ``_TITLE_EXECUTOR`` / fire-and-
        # forget semantics. The submit never raises into the stream.
        if is_new_conversation:
            title_ws_id = conversation.get("workspace_id") or user.get("active_workspace_id")
            title_proj_id = conversation.get("project_id")
            _TITLE_EXECUTOR.submit(
                _generate_title_async,
                nonlocal_conversation_id,
                message_content,
                title,
                user_id,
                title_ws_id,
                title_proj_id,
            )

        # Save user message. ``message_content`` + ``attachments`` are already
        # the DLP-scrubbed versions (redacted in the handler before the
        # generator ran). Stamp a small redaction badge into metadata for the UI.
        user_meta = {}
        if dlp_redacted_meta:
            user_meta["dlp_redacted"] = dlp_redacted_meta
        if quoted_text:
            user_meta["quoted_text"] = quoted_text
        # Persist the web_search preference so edit/regenerate can replay it.
        if web_search:
            user_meta["web_search"] = True
        user_message = MessageModel.create_user_message(
            conversation_id=nonlocal_conversation_id,
            content=message_content,
            attachments=attachments,
            branch_id=branch_id,
            metadata=(user_meta or None),
            sender_user_id=user_id,
        )

        yield _sse_event("message_saved", {
            "message": serialize_doc(user_message),
            "conversation_id": nonlocal_conversation_id,
            "branch_id": branch_id,
        })

        # Get conversation context (for the current branch). Format with the
        # extended formatter so PDF attachments forward natively and the
        # file-parser plugin is wired below. The PDF base64 read happens HERE on
        # the dedicated runner thread (after the SSE response has already
        # started) — never on the event loop, so stream start is not blocked.
        context_messages = MessageModel.get_context_messages(
            nonlocal_conversation_id, limit=20, branch_id=branch_id
        )
        stream_conv_owner_id = (
            str(conversation.get("user_id")) if conversation.get("user_id") else user_id
        )
        fmt = OpenRouterService.format_messages_for_api_ex(
            context_messages, user_id=stream_conv_owner_id
        )
        formatted_messages = fmt["messages"]
        req_plugins = list(fmt.get("plugins") or [])
        if fmt.get("has_native_pdf"):
            engine = settings.get("PDF_OCR_ENGINE", "mistral-ocr")
            req_plugins.append({"id": "file-parser", "pdf": {"engine": engine}})

        # Create placeholder for assistant message
        assistant_message = MessageModel.create(
            conversation_id=nonlocal_conversation_id,
            role="assistant",
            content="",
            metadata={**{"model_id": config["model_id"]}, **(({"intent": intent}) if intent else {})},
            branch_id=branch_id,
        )
        message_id = str(assistant_message["_id"])

        # Re-key the reservation row (taken in the handler before the response
        # started) to the real message_id so the SAME counted row now backs
        # cancel-by-message-id — no double-count, no gap. ``register`` then
        # refreshes it (TTL bump / cancelled reset) via the session_id upsert.
        stream_state.promote(reservation_id, message_id)
        # Store generation task for cancellation (PG-backed, cross-worker).
        stream_state.register(message_id, user_id=user_id)

        # Emit message start
        yield _sse_event("message_start", {
            "message_id": message_id,
            "conversation_id": nonlocal_conversation_id,
            "branch_id": branch_id,
        })

        # Start streaming response
        start_time = time.time()
        full_content = ""
        prompt_tokens = 0
        completion_tokens = 0
        finish_reason = "stop"
        annotations: list = []  # PDF file annotations + web_search url_citations

        # Throttle the cross-worker cancel SELECT: a DB round-trip per token is
        # wasteful + leaves the conn idle-in-transaction. Check at most every
        # ~0.75s (first check fires immediately so an already-cancelled stream
        # stops at once). ``time.monotonic`` is correct here — the producer runs
        # on the single sync runner thread.
        _CANCEL_CHECK_INTERVAL = 0.75
        last_cancel_check = 0.0

        # Burst-and-remove (SSE pool-DoS fix): every pre-stream DB write above
        # (conversation fetch/create, model-switch stamp, user-message insert,
        # context fetch, assistant placeholder, stream_state.register) has
        # already COMMITTED, and the producer holds only plain dicts past this
        # point (facades return dicts — no live ORM rows to detach). Drop the
        # scoped session now so its psycopg3 connection returns to the pool for
        # the entire multi-second-to-multi-minute OpenRouter network wait; the
        # scoped session lazily re-creates a fresh connection on the next DB
        # touch (the throttled cancel polls + the terminal finalize burst +
        # OpenRouter ``_record_usage`` firing from inside the stream generator).
        # At N concurrent streams this stops pinning N idle connections.
        db.session.remove()

        try:
            params = config.get("parameters", {})

            # Get user AI preferences and build enhanced system prompt
            ai_prefs = user.get("ai_preferences", {})
            enhanced_prompt = OpenRouterService.build_enhanced_system_prompt(
                config.get("system_prompt"),
                ai_prefs,
                model_id=config["model_id"],
                include_identity=True,
            )

            ws_id = user.get("active_workspace_id")
            proj_id = conversation.get("project_id")
            stream = OpenRouterService.chat_completion(
                messages=formatted_messages,
                model=config["model_id"],
                system_prompt=enhanced_prompt,
                temperature=params.get("temperature", 0.7),
                max_tokens=params.get("max_tokens", 32000),
                top_p=params.get("top_p", 1.0),
                frequency_penalty=params.get("frequency_penalty", 0.0),
                presence_penalty=params.get("presence_penalty", 0.0),
                stream=True,
                user_id=user_id,
                conversation_id=nonlocal_conversation_id,
                feature="chat",
                workspace_id=str(ws_id) if ws_id else None,
                project_id=str(proj_id) if proj_id else None,
                origin="web",
                web_search=web_search,
                web_fetch=web_fetch,
                plugins=req_plugins or None,
                reasoning_effort=reasoning_effort,
            )

            for chunk in stream:
                # Client TCP-disconnected: the SSE driver set the stop_event so
                # we break out promptly, run the finally (clears stream_state),
                # and the runner thread releases its pinned DB connection back to
                # the pool — closing a connection-exhaustion DoS window.
                if stop_event.is_set():
                    finish_reason = "cancelled"
                    break

                # Check for cancellation (cross-worker — reads from PG), throttled
                # to ~0.75s so we don't hit the DB on every token. ``is_cancelled``
                # already rolls back its read transaction; we additionally drop the
                # scoped session right after so the poll's psycopg3 connection
                # returns to the pool BETWEEN polls (during the inter-chunk network
                # wait) instead of staying checked out idle for the whole stream.
                # Re-checkout on the next poll is a cheap pool op (no TCP setup).
                _now_mono = time.monotonic()
                if _now_mono - last_cancel_check >= _CANCEL_CHECK_INTERVAL:
                    last_cancel_check = _now_mono
                    _cancelled = stream_state.is_cancelled(message_id)
                    db.session.remove()
                    if _cancelled:
                        finish_reason = "cancelled"
                        break

                # Wall-clock cap — abort a stalled stream cleanly.
                if time.time() - gen_start > _MAX_WALLCLOCK_SECONDS:
                    error_msg = "Stream timed out"
                    yield _sse_event("message_error", {
                        "message_id": message_id,
                        "error": error_msg,
                        "conversation_id": nonlocal_conversation_id,
                    })
                    MessageModel.mark_error(message_id, error_msg)
                    return

                # Idle keepalive — emit a raw SSE comment when the upstream
                # has produced no client-bound bytes for ~15s.
                if time.time() - last_yield >= _KEEPALIVE_INTERVAL:
                    yield ": keepalive\n\n"
                    last_yield = time.time()

                if "error" in chunk:
                    error_msg = chunk["error"].get("message", "Unknown error")
                    yield _sse_event("message_error", {
                        "message_id": message_id,
                        "error": error_msg,
                        "conversation_id": nonlocal_conversation_id,
                    })
                    MessageModel.mark_error(message_id, error_msg)
                    return

                if chunk.get("done"):
                    # Terminal dict carries the accumulated annotations.
                    if chunk.get("annotations"):
                        annotations = chunk["annotations"]
                    break

                # Extract content from chunk
                choices = chunk.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        full_content += content
                        yield _sse_event("message_chunk", {
                            "message_id": message_id,
                            "content": content,
                            "conversation_id": nonlocal_conversation_id,
                        })
                        last_yield = time.time()

                    # Capture annotations if they ride on a chunk (terminal
                    # non-delta message or a provider that streams them early).
                    chunk_ann = (
                        (choices[0].get("message") or {}).get("annotations")
                        or delta.get("annotations")
                    )
                    if chunk_ann:
                        annotations = chunk_ann

                    # Check for finish reason
                    if choices[0].get("finish_reason"):
                        finish_reason = choices[0]["finish_reason"]

                # Get usage info if available
                usage = chunk.get("usage", {})
                if usage:
                    prompt_tokens = usage.get("prompt_tokens", prompt_tokens)
                    completion_tokens = usage.get("completion_tokens", completion_tokens)

        except Exception as e:  # noqa: BLE001
            yield _sse_event("message_error", {
                "message_id": message_id,
                "error": str(e),
                "conversation_id": nonlocal_conversation_id,
            })
            return

        finally:
            # Clean up generation task
            stream_state.clear(message_id)

        # Calculate generation time
        generation_time_ms = int((time.time() - start_time) * 1000)

        # Update assistant message with full content. Fold annotations (PDF
        # file annotations for OCR-replay + web_search url_citations) into the
        # metadata in the same atomic write.
        MessageModel.update_content_and_metadata(
            message_id,
            full_content,
            {
                "model_id": config["model_id"],
                "tokens": {
                    "prompt": prompt_tokens,
                    "completion": completion_tokens,
                },
                "generation_time_ms": generation_time_ms,
                "finish_reason": finish_reason,
                **({"intent": intent} if intent else {}),
                **({"annotations": annotations} if annotations else {}),
            },
        )

        # Update stats
        ConversationModel.increment_message_count(
            nonlocal_conversation_id,
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
        )
        UserModel.increment_usage(user_id, messages=2, tokens=prompt_tokens + completion_tokens)
        if not is_quick_model and not is_agent_model:
            LLMConfigModel.increment_uses(config_id)

        # Emit completion
        payload = {
            "message_id": message_id,
            "content": full_content,
            "conversation_id": nonlocal_conversation_id,
            "branch_id": branch_id,
            "metadata": {
                "model_id": config["model_id"],
                "tokens": {
                    "prompt": prompt_tokens,
                    "completion": completion_tokens,
                },
                "generation_time_ms": generation_time_ms,
                "finish_reason": finish_reason,
            },
        }
        if intent:
            payload["intent"] = intent
        if annotations:
            # Surface web_search citations to the client + a flag that a PDF was
            # parsed (file annotations are an OCR-replay cache, not UI content).
            payload["annotations"] = annotations
            payload["citations"] = [
                a for a in annotations
                if isinstance(a, dict) and a.get("type") == "url_citation"
            ]
            payload["has_file_annotations"] = any(
                isinstance(a, dict) and a.get("type") == "file" for a in annotations
            )
        yield _sse_event("message_complete", payload)

        # Check if title was updated (for new conversations). Only ``title`` is
        # read, so skip the branch hydration SELECT.
        if is_new_conversation:
            updated_conv = ConversationModel.find_by_id(
                nonlocal_conversation_id, include_branches=False
            )
            if updated_conv and updated_conv.get("title") != title:
                yield _sse_event("title_updated", {
                    "conversation_id": nonlocal_conversation_id,
                    "title": updated_conv["title"],
                })

    def _produce_data_analysis(stop_event):
        """Producer for the Data Analyzer mode (intent == 'data').

        Mirrors ``_produce``'s conversation/message/placeholder bookkeeping and
        the burst-and-remove DB pattern, but instead of a single streamed
        completion it runs an agentic ``run_python`` tool loop (pandas in a
        sandbox over the user's uploaded data) and then streams the final
        narration. DLP + spend gates already ran in the handler before this
        response — none are added here.
        """
        nonlocal_conversation_id = conversation_id
        gen_start = time.time()
        last_yield = gen_start

        # --- conversation get/create (same access + scalar-field rules as _produce)
        is_new_conversation = False
        if nonlocal_conversation_id:
            conversation = ConversationModel.find_by_id(
                nonlocal_conversation_id, include_branches=False
            )
            _role, _acc_err = resolve_conversation_access(conversation, user_id, "viewer")
            if _acc_err:
                yield _sse_event("error", {"message": "Conversation not found"})
                return
            if _role == "owner" and config_id and conversation.get("config_id") != config_id:
                ConversationModel.update(nonlocal_conversation_id, {"config_id": config_id})
                conversation["config_id"] = config_id
        else:
            is_new_conversation = True
            title = generate_conversation_title(message_content)
            conversation = ConversationModel.create(
                user_id=user_id, config_id=config_id, title=title, kind="data",
                workspace_id=user.get("active_workspace_id"),
            )
            nonlocal_conversation_id = str(conversation["_id"])
            yield _sse_event("conversation_created", {
                "conversation": serialize_doc(conversation),
            })

        branch_id = conversation.get("active_branch", "main")

        if is_new_conversation:
            title_ws_id = conversation.get("workspace_id") or user.get("active_workspace_id")
            title_proj_id = conversation.get("project_id")
            _TITLE_EXECUTOR.submit(
                _generate_title_async, nonlocal_conversation_id, message_content,
                title, user_id, title_ws_id, title_proj_id,
            )

        # --- persist the user message (DLP-scrubbed already)
        user_meta = {}
        if dlp_redacted_meta:
            user_meta["dlp_redacted"] = dlp_redacted_meta
        if quoted_text:
            user_meta["quoted_text"] = quoted_text
        user_message = MessageModel.create_user_message(
            conversation_id=nonlocal_conversation_id,
            content=message_content,
            attachments=attachments,
            branch_id=branch_id,
            metadata=(user_meta or None),
            sender_user_id=user_id,
        )
        yield _sse_event("message_saved", {
            "message": serialize_doc(user_message),
            "conversation_id": nonlocal_conversation_id,
            "branch_id": branch_id,
        })

        # --- build the LLM context, but DROP the tabular data attachments from the
        # final user turn so the formatter never injects the giant TSV. The
        # sandbox reads those files off disk independently; the model gets the
        # compact preview_markdown (appended to the system prompt below).
        context_messages = MessageModel.get_context_messages(
            nonlocal_conversation_id, limit=20, branch_id=branch_id
        )
        # Strip the tabular data files from EVERY user turn so the formatter never
        # injects their (huge) extracted TSV text — the sandbox reads them off disk
        # and the model gets the compact preview instead. Must hit ALL turns (not
        # just the latest): on a follow-up, a prior turn's CSV would otherwise leak
        # back in as ~50k tokens of TSV. Operate on shallow copies; the persisted
        # rows keep their attachments untouched.
        for idx in range(len(context_messages)):
            cm = context_messages[idx]
            if cm.get("role") != "user":
                continue
            kept = [a for a in (cm.get("attachments") or [])
                    if not _is_data_attachment(a)]
            if len(kept) != len(cm.get("attachments") or []):
                cm = dict(cm)
                cm["attachments"] = kept
                context_messages[idx] = cm
        # Recap prior assistant turns' emitted artifacts (B): the model only sees
        # prose content, so without this it forgets what it already rendered on a
        # follow-up. Shallow-copies the touched rows; persisted rows untouched.
        _append_artifact_recaps(context_messages)
        data_conv_owner_id = (
            str(conversation.get("user_id")) if conversation.get("user_id") else user_id
        )
        fmt = OpenRouterService.format_messages_for_api_ex(
            context_messages, user_id=data_conv_owner_id
        )
        formatted_messages = fmt["messages"]

        # --- assistant placeholder (intent stamped, mirrors _produce)
        assistant_message = MessageModel.create(
            conversation_id=nonlocal_conversation_id,
            role="assistant",
            content="",
            metadata={**{"model_id": config["model_id"]}, **({"intent": intent} if intent else {})},
            branch_id=branch_id,
        )
        message_id = str(assistant_message["_id"])
        # Re-key the handler's reservation row to the real message_id (see the
        # streaming producer) so the counted row backs cancel-by-message-id.
        stream_state.promote(reservation_id, message_id)
        stream_state.register(message_id, user_id=user_id)
        yield _sse_event("message_start", {
            "message_id": message_id,
            "conversation_id": nonlocal_conversation_id,
            "branch_id": branch_id,
        })

        ws_id = user.get("active_workspace_id")
        proj_id = conversation.get("project_id")
        ws_id_s = str(ws_id) if ws_id else None
        proj_id_s = str(proj_id) if proj_id else None

        # Bridge queue: created BEFORE dataset prep so extraction status frames
        # (and later the tool-loop frames) share one drain. prepare_dataset can
        # OCR a freshly-attached PDF for ~60s — without these frames the stream is
        # silent the whole time. The tool_executor below reuses this same queue.
        frame_q: "queue.Queue" = queue.Queue()

        # --- prepare the dataset (DB/disk reads). Lazy-import the sandbox layer so
        # this module imports cleanly before the sibling services land; a missing
        # sandbox or no data file fails CLOSED with a graceful assistant message.
        try:
            from app.services.sandbox_service import SandboxService
            from app.services.data_analysis_service import prepare_dataset
            sandbox_available = bool(SandboxService.available())
        except Exception as e:  # noqa: BLE001 — services not present / import error
            _logger.warning("data-analysis sandbox unavailable: %s", e)
            SandboxService = None  # type: ignore
            prepare_dataset = None  # type: ignore
            sandbox_available = False

        # Run prepare_dataset on a helper thread (mirrors _run_loop): its
        # status_cb fires SYNCHRONOUSLY mid-call, so the producer must be free to
        # drain + yield frames meanwhile. prepare_dataset manages its OWN session
        # scopes, so this RAW thread needs no db wrapper. The producer's session
        # scope stays untouched until the burst-and-remove below.
        ctx = None
        if sandbox_available and prepare_dataset is not None:
            prep_box: dict = {}

            def _status_cb(ev: dict) -> None:
                # ev == {'phase': 'extracting', 'file': <name>} per freshly OCR'd doc.
                frame_q.put(_sse_event("data_status", {
                    "phase": "extracting",
                    "file": (ev or {}).get("file"),
                    "conversation_id": nonlocal_conversation_id,
                }))

            def _run_prepare():
                try:
                    prep_box["ctx"] = prepare_dataset(
                        user_id=user_id,
                        conversation_id=nonlocal_conversation_id,
                        attachments=attachments,
                        workspace_id=ws_id_s,
                        project_id=proj_id_s,
                        status_cb=_status_cb,
                        stop_event=stop_event,
                    )
                except Exception as e:  # noqa: BLE001
                    prep_box["error"] = e
                finally:
                    frame_q.put(_DATA_LOOP_DONE)

            prep_thread = threading.Thread(
                target=_run_prepare, name="data-analysis-prepare", daemon=True
            )
            prep_thread.start()
            # Drain extraction frames until the prepare thread signals done.
            while True:
                if stop_event.is_set():
                    break
                try:
                    frame = frame_q.get(timeout=1.0)
                except queue.Empty:
                    if time.time() - last_yield >= _KEEPALIVE_INTERVAL:
                        yield ": keepalive\n\n"
                        last_yield = time.time()
                    if time.time() - gen_start > _MAX_WALLCLOCK_SECONDS:
                        break
                    continue
                if frame is _DATA_LOOP_DONE:
                    break
                yield frame
                last_yield = time.time()
            prep_thread.join(timeout=5)
            if prep_thread.is_alive():
                _logger.warning(
                    "prepare_dataset thread still alive after join "
                    "(stop=%s conversation=%s)",
                    stop_event.is_set(),
                    nonlocal_conversation_id,
                )
            if prep_box.get("error") is not None:
                _logger.warning("prepare_dataset failed: %s", prep_box["error"])
                ctx = None
            else:
                ctx = prep_box.get("ctx")

        def _finish_graceful(text: str):
            """Persist + emit a no-tool assistant message and complete the stream."""
            MessageModel.update_content_and_metadata(
                message_id, text,
                {
                    "model_id": config["model_id"],
                    "finish_reason": "stop",
                    **({"intent": intent} if intent else {}),
                },
            )
            payload = {
                "message_id": message_id,
                "content": text,
                "conversation_id": nonlocal_conversation_id,
                "branch_id": branch_id,
                "metadata": {"model_id": config["model_id"], "finish_reason": "stop"},
            }
            if intent:
                payload["intent"] = intent
            return _sse_event("message_complete", payload)

        # Turn cancelled during dataset prep (client disconnect): end cleanly
        # WITHOUT the misleading "couldn't find a data file" message — ctx is None
        # here only because the prep thread was abandoned mid-extraction, not
        # because there was no data. The on_close callback releases the reservation.
        if stop_event.is_set():
            stream_state.clear(message_id)
            return

        # Fail-closed: no data file OR sandbox missing -> graceful message, finish.
        if not sandbox_available:
            stream_state.clear(message_id)
            yield _finish_graceful(
                "Data analysis is unavailable on this server right now. "
                "Please try again later or contact an administrator."
            )
            return
        if ctx is None:
            stream_state.clear(message_id)
            yield _finish_graceful(
                "I couldn't find a data file to analyze. Please attach a CSV, "
                "Excel, or similar tabular file and ask again."
            )
            return

        # Dual-model path: simple describe/schema → fast flash; complex stats/
        # joins/modeling → Sonnet. Router lives in data_model_router (env-tunable).
        from app.services.data_model_router import (
            pick_data_analysis_model,
            reasoning_effort_for_model,
        )
        data_model = pick_data_analysis_model(message_content)
        config["model_id"] = data_model
        data_reasoning = reasoning_effort_for_model(data_model)

        # --- build the data-analyst config: system prompt + dataset preview.
        ai_prefs = user.get("ai_preferences", {})
        base_prompt = DATA_ANALYST_SYSTEM_PROMPT + "\n\n" + (ctx.get("preview_markdown") or "")
        # Trim chat AI-preferences down to ONLY the language preference for this
        # specialized flow: build_enhanced_system_prompt prepends the user's
        # custom_instructions + tone/style/expertise, which would override the
        # data-analyst contract (PROSE-only, emit order, no-$ currency,
        # deterministic compute). Keep language so "respond in Persian" still works.
        data_prefs = _data_analysis_prefs(ai_prefs)
        enhanced_prompt = OpenRouterService.build_enhanced_system_prompt(base_prompt, data_prefs)
        params = config.get("parameters", {})
        max_rounds = int(settings.get("DATA_PY_MAX_ROUNDS", 14))
        workdir = ctx.get("workdir")

        # Dataset ready — the model is about to start reasoning + running code.
        yield _sse_event("data_status", {
            "phase": "analyzing",
            "file": None,
            "conversation_id": nonlocal_conversation_id,
        })
        last_yield = time.time()

        # Burst-and-remove: every pre-flight DB write committed; the tool loop is
        # pure network + sandbox (no DB) so drop the pooled connection for the
        # whole multi-round wait. The scoped session lazily re-creates on the
        # terminal finalize burst + _record_usage from inside chat_completion.
        db.session.remove()

        # Reuse the bridge queue created before dataset prep: the tool_executor
        # runs ON A HELPER THREAD (so the sandbox subprocess never blocks frame
        # draining) and pushes SSE frames here; this generator drains them in real
        # time. Steps + artifacts accumulate in shared lists guarded by the GIL
        # (single producer thread, append-only).
        steps: list = []
        all_artifacts: list = []
        loop_result_box: dict = {}
        # {original_name: (upload_id, disk_filename)} carried across rounds so a
        # re-emitted output (model regenerates report.xlsx) deletes its prior row.
        file_dedupe: dict = {}

        def _tool_executor(name: str, args: dict) -> str:
            step_no = len(steps) + 1
            code = (args or {}).get("code") or "" if name == "run_python" else ""
            frame_q.put(_sse_event("tool_call", {"step": step_no, "code": code}))
            if name != "run_python":
                # Unknown tool — tell the model so it self-corrects.
                steps.append({"step": step_no, "code": code, "stdout": "",
                              "error": f"unknown tool {name!r}"})
                return f"[tool error] unknown tool {name!r}"
            # Mid-loop spend re-check — multi-round Sonnet can exceed preflight.
            try:
                spend_gate.gate(
                    user_id=user_id,
                    workspace_id=ws_id_s,
                    project_id=proj_id_s,
                    origin="web",
                    feature=_DATA_FEATURE,
                )
            except spend_gate.BudgetExceededError as exc:
                err = f"budget exceeded ({exc.scope}): analysis stopped"
                steps.append({"step": step_no, "code": code, "stdout": "",
                              "error": err})
                frame_q.put(_sse_event("tool_result", {
                    "step": step_no,
                    "stdout": "",
                    "error": err,
                    "artifacts": [],
                }))
                if stop_event is not None:
                    stop_event.set()
                return f"[tool error] {err}"
            result = SandboxService.run(
                workdir=workdir,
                code=code,
                # Prefer DATA_SANDBOX_* (Config); DATA_PY_* kept as legacy alias.
                timeout_s=int(
                    settings.get("DATA_SANDBOX_TIMEOUT_S")
                    or settings.get("DATA_PY_TIMEOUT_S", 20)
                ),
                mem_mb=int(
                    settings.get("DATA_SANDBOX_MEM_MB")
                    or settings.get("DATA_PY_MEM_MB", 1024)
                ),
                stop_event=stop_event,
            )
            result = result if isinstance(result, dict) else {}
            artifacts = [a for a in (result.get("artifacts") or []) if isinstance(a, dict)]
            # Persist file artifacts to downloadable uploads (enriches with
            # upload_id/url, drops the failed/over-cap ones). Runs on the loop
            # helper thread INSIDE _run_loop's db.session_scope (DB writes safe).
            artifacts = _persist_file_artifacts(
                artifacts, workdir=workdir, user_id=user_id, dedupe=file_dedupe,
            )
            all_artifacts.extend(artifacts)
            steps.append({
                "step": step_no,
                "code": code,
                "stdout": result.get("stdout") or "",
                "error": result.get("error"),
            })
            frame_q.put(_sse_event("tool_result", {
                "step": step_no,
                "stdout": result.get("stdout") or "",
                "error": result.get("error"),
                "artifacts": artifacts,
            }))
            # Feed the model the POST-persist artifact list so its delivery recap
            # ("report.xlsx is ready") only names files that actually persisted.
            result["artifacts"] = artifacts
            return _format_tool_result_for_model(result, manifest=ctx.get("manifest"))

        def _run_loop():
            # This is a RAW thread (not anyio.to_thread, which copies contextvars)
            # — so it does NOT inherit the runner thread's DB-session scope. Each
            # tool round's chat_completion -> _record_usage writes usage_logs +
            # spend_rollups via db.session, so open a fresh contextvar-scoped
            # session here (the documented background-thread pattern). The sandbox
            # subprocess itself touches no DB.
            try:
                with db.session_scope():
                    loop_result_box["result"] = OpenRouterService.run_tool_loop(
                        model=config["model_id"],
                        messages=formatted_messages,
                        tools=[_RUN_PYTHON_TOOL],
                        tool_executor=_tool_executor,
                        system_prompt=enhanced_prompt,
                        max_rounds=max_rounds,
                        temperature=_DATA_ANALYSIS_TEMPERATURE,
                        max_tokens=params.get("max_tokens", 32000),
                        reasoning_effort=data_reasoning,
                        user_id=user_id,
                        conversation_id=nonlocal_conversation_id,
                        feature=_DATA_FEATURE,
                        workspace_id=ws_id_s,
                        project_id=proj_id_s,
                        origin="web",
                        stop_event=stop_event,
                    )
            except Exception as e:  # noqa: BLE001
                _logger.warning("data-analysis tool loop crashed: %s", e, exc_info=True)
                loop_result_box["error"] = str(e)
            finally:
                frame_q.put(_DATA_LOOP_DONE)

        # Client may have disconnected during prompt/model setup after prep.
        if stop_event.is_set():
            stream_state.clear(message_id)
            return

        loop_thread = threading.Thread(
            target=_run_loop, name="data-analysis-loop", daemon=True
        )
        loop_thread.start()

        # Drain tool SSE frames in real time until the loop thread signals done.
        try:
            while True:
                if stop_event.is_set():
                    break
                try:
                    frame = frame_q.get(timeout=1.0)
                except queue.Empty:
                    # Idle keepalive during long sandbox/network waits.
                    if time.time() - last_yield >= _KEEPALIVE_INTERVAL:
                        yield ": keepalive\n\n"
                        last_yield = time.time()
                    if time.time() - gen_start > _MAX_WALLCLOCK_SECONDS:
                        # Hit the hard wall-clock ceiling. SET stop_event so the
                        # DETACHED tool-loop thread aborts at the next round boundary
                        # (and SandboxService.run reaps any in-flight child) instead
                        # of running on after we finalize — billing further rounds +
                        # creating orphan upload rows the finalized message never
                        # references. Bounds the trailing work to <=1 round, same as
                        # the client-disconnect path.
                        stop_event.set()
                        break
                    continue
                if frame is _DATA_LOOP_DONE:
                    break
                yield frame
                last_yield = time.time()
        finally:
            loop_thread.join(timeout=5)
            if loop_thread.is_alive():
                _logger.warning(
                    "data-analysis tool-loop thread still alive after join "
                    "(stop=%s conversation=%s)",
                    stop_event.is_set(),
                    nonlocal_conversation_id,
                )

        loop_result = loop_result_box.get("result") or {}
        loop_error = loop_result_box.get("error") or loop_result.get("error")

        # --- stream the FINAL narration. run_tool_loop returns the conversation
        # context (incl. tool round-trips) in result['messages']; issue ONE
        # streamed completion WITHOUT tools to narrate. (When capped, this also
        # forces the model to wrap up without another tool call.)
        full_content = ""
        finish_reason = "stop"
        loop_content = (loop_result.get("content") or "").strip()
        loop_capped = bool(loop_result.get("capped"))
        narration_msgs = loop_result.get("messages")
        # ``narration_msgs`` from run_tool_loop ALREADY leads with the system prompt;
        # pass system_prompt to chat_completion ONLY when falling back to the bare
        # context (else a SECOND identical ~4k-token system block is prepended).
        narration_system = None if narration_msgs else enhanced_prompt
        narration_msgs = narration_msgs or formatted_messages

        if not loop_error and not loop_capped and loop_content:
            # The tool loop already generated AND BILLED the final answer on its
            # terminal non-tool round (run_tool_loop returns it as ``content`` but
            # omits it from ``messages`` so it isn't double-listed). Re-issuing a
            # streamed narration would pay for the priciest full-context round a
            # SECOND time — so chunk the already-billed text to the client instead.
            # (Mirrors the regen path's ``capped or not content`` guard.)
            for _i in range(0, len(loop_content), 80):
                if stop_event.is_set():
                    finish_reason = "cancelled"
                    break
                piece = loop_content[_i:_i + 80]
                full_content += piece
                yield _sse_event("message_chunk", {
                    "message_id": message_id,
                    "content": piece,
                    "conversation_id": nonlocal_conversation_id,
                })
                last_yield = time.time()
        elif not loop_error:
            try:
                if loop_capped:
                    # Force-stopped at the round cap — tell the model so it wraps up
                    # over already-computed results instead of narrating a truncated
                    # analysis as if complete.
                    narration_msgs = narration_msgs + [
                        {"role": "system", "content": _DATA_CAPPED_NARRATION_NOTE}
                    ]
                # db.session was removed; chat_completion's _record_usage re-opens
                # lazily inside the stream generator (same pattern as _produce).
                stream = OpenRouterService.chat_completion(
                    messages=narration_msgs,
                    model=config["model_id"],
                    system_prompt=narration_system,
                    temperature=_DATA_ANALYSIS_TEMPERATURE,
                    max_tokens=params.get("max_tokens", 32000),
                    stream=True,
                    reasoning_effort=data_reasoning,
                    user_id=user_id,
                    conversation_id=nonlocal_conversation_id,
                    feature=_DATA_FEATURE,
                    workspace_id=ws_id_s,
                    project_id=proj_id_s,
                    origin="web",
                )
                for chunk in stream:
                    if stop_event.is_set():
                        finish_reason = "cancelled"
                        break
                    if "error" in chunk:
                        loop_error = chunk["error"].get("message", "narration failed")
                        break
                    if chunk.get("done"):
                        break
                    choices = chunk.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            full_content += content
                            yield _sse_event("message_chunk", {
                                "message_id": message_id,
                                "content": content,
                                "conversation_id": nonlocal_conversation_id,
                            })
                            last_yield = time.time()
                        if choices[0].get("finish_reason"):
                            finish_reason = choices[0]["finish_reason"]
            except Exception as e:  # noqa: BLE001
                loop_error = str(e)

        # Fall back to the loop's last non-streamed text if the narration stream
        # produced nothing (or errored after tools already ran).
        if not full_content:
            full_content = (loop_result.get("content") or "").strip()
        if not full_content:
            full_content = (
                "I ran into a problem completing the analysis."
                if loop_error else "Analysis complete."
            )

        stream_state.clear(message_id)

        # Drop file artifacts whose upload row was superseded by a same-name re-emit
        # (cross-round dedupe hard-deleted the prior row) before persisting, so no
        # dead 404 download card lands in metadata.data_artifacts.
        all_artifacts = _prune_dead_file_artifacts(all_artifacts, file_dedupe)
        data_artifacts = {"steps": steps, "artifacts": all_artifacts}
        # --- persist content + data_artifacts + intent in one atomic write
        MessageModel.update_content_and_metadata(
            message_id, full_content,
            {
                "model_id": config["model_id"],
                "finish_reason": finish_reason,
                "data_artifacts": data_artifacts,
                **({"intent": intent} if intent else {}),
            },
        )
        ConversationModel.increment_message_count(nonlocal_conversation_id)
        UserModel.increment_usage(user_id, messages=2, tokens=0)

        payload = {
            "message_id": message_id,
            "content": full_content,
            "conversation_id": nonlocal_conversation_id,
            "branch_id": branch_id,
            "metadata": {"model_id": config["model_id"], "finish_reason": finish_reason},
            "data_artifacts": data_artifacts,
        }
        if intent:
            payload["intent"] = intent
        yield _sse_event("message_complete", payload)

        if is_new_conversation:
            updated_conv = ConversationModel.find_by_id(
                nonlocal_conversation_id, include_branches=False
            )
            if updated_conv and updated_conv.get("title") != title:
                yield _sse_event("title_updated", {
                    "conversation_id": nonlocal_conversation_id,
                    "title": updated_conv["title"],
                })

    # Hand off release ownership to the SSE driver: ``on_close`` fires exactly
    # once in the runner-thread finally (producer crash / client disconnect /
    # normal EOF) and releases BOTH the reservation row and the global permit.
    preflight.hand_off()
    if intent == "data":
        return sse_stream_sync(
            _produce_data_analysis,
            runner_name="chat-data-analysis-runner",
            on_close=preflight.on_close,
        )
    return sse_stream_sync(
        _produce, runner_name="chat-stream-runner", on_close=preflight.on_close
    )

