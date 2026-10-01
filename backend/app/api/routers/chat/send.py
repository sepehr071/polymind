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

from .titles import _TITLE_EXECUTOR, _generate_title_async

# ---------------------------------------------------------------------------
# chat_bp — non-streaming send.
# ---------------------------------------------------------------------------
@router.post("/send")
async def send_message(request: Request, user: dict = Depends(require_active)):
    """Send a message and get AI response (non-streaming)."""
    user_id = str(user["_id"])
    data = await _json_body(request)

    conversation_id = data.get("conversation_id")
    config_id = data.get("config_id")
    message_content = (data.get("message") or "").strip()
    # Reject any attachment whose upload_id isn't owned by the sender before it
    # is scanned / persisted / inlined (cross-tenant upload IDOR guard).
    attachments = _filter_owned_attachments(data.get("attachments", []), user_id)
    dlp_redact = bool(data.get("dlp_redact"))
    quoted_text = (data.get("quoted_text") or "").strip() or None
    if quoted_text and len(quoted_text) > 4000:
        quoted_text = quoted_text[:4000]

    if not message_content:
        return JSONResponse({"error": "Message content is required"}, status_code=400)

    if not config_id:
        return JSONResponse({"error": "config_id is required"}, status_code=400)

    # Per-user rate limit — the /send path also triggers an LLM generation, so it
    # shares the chat_stream bucket. INDEPENDENT of billing enforcement.
    retry = check_rate_limit("chat_stream", user_id, max_calls=30, window=60)
    if retry is not None:
        return JSONResponse(
            {"error": "rate_limited", "retry_after": retry},
            status_code=429,
            headers={"Retry-After": str(int(retry))},
        )

    # Fetch the conversation up front (when continuing one) to (a) gate access —
    # owner OR a member of a team it's shared into — and (b) resolve the config
    # correctly. A contributing member sends under the conversation's existing
    # config, resolved as the OWNER (so the owner's private persona still works)
    # and cannot switch the model; the owner keeps full model-switch behaviour.
    # New conversations are stamped into the caller's active org, owner = caller.
    conversation = None
    is_owner = True
    if conversation_id:
        conversation = ConversationModel.find_by_id(conversation_id)
        role, acc_err = resolve_conversation_access(conversation, user_id, "viewer")
        if acc_err:
            msg, status = acc_err
            payload = {"error": msg}
            if status == 403:
                payload["status"] = 403
            return JSONResponse(payload, status_code=status)
        if conversation_workspace_denied(conversation, user):
            return JSONResponse(dict(WORKSPACE_ACCESS_DENIED), status_code=403)
        is_owner = role == "owner"

    if conversation is not None and not is_owner:
        config_id = conversation.get("config_id") or config_id
        cfg_user_id = str(conversation["user_id"])
        cfg_project_id = conversation.get("project_id")
    else:
        cfg_user_id = user_id
        cfg_project_id = conversation.get("project_id") if conversation else None

    # Get config (supports quick models). Pass acting user + project scope so the
    # resolver blocks cross-user private personas and gates project-scoped ones.
    config = resolve_chat_config(config_id, cfg_user_id, cfg_project_id)
    if not config:
        return JSONResponse({"error": "Config not found"}, status_code=404)

    is_quick_model = str(config_id).startswith("quick:")

    # Check token limit
    if user["usage"]["tokens_limit"] != -1:
        if user["usage"]["tokens_used"] >= user["usage"]["tokens_limit"]:
            return JSONResponse({"error": "Token limit reached"}, status_code=429)

    # Create or get conversation
    if conversation_id:
        # Persist a mid-conversation model switch (owner only) so a page refresh
        # restores the user's currently-selected model (see streaming path).
        if is_owner and config_id and conversation.get("config_id") != config_id:
            ConversationModel.update(conversation_id, {"config_id": config_id})
            conversation["config_id"] = config_id
    else:
        title = generate_conversation_title(message_content)
        conversation = ConversationModel.create(
            user_id=user_id,
            config_id=config_id,
            title=title,
            workspace_id=user.get("active_workspace_id"),
        )
        conversation_id = str(conversation["_id"])

    # Get active branch
    branch_id = conversation.get("active_branch", "main")

    # DLP gate (redaction-aware). Block/confirm/warn unchanged in enforce mode;
    # in redact mode (workspace ``mode=redact`` OR client ``dlp_redact``) the
    # message + non-PDF attachment text are scrubbed BEFORE persist + LLM call.
    # Offloaded to a worker thread (DB read + always-on LLM classify ~10s).
    send_ws_id = conversation.get("workspace_id") or user.get("active_workspace_id")
    send_user_lang = _resolve_user_lang(data, user)
    send_confirmed = bool(data.get("dlp_confirmed"))
    send_confirm_token = data.get("dlp_confirm_token")

    def _send_gate() -> dict:
        return _gate_and_redact_chat_turn(
            user=user,
            workspace_id=send_ws_id,
            project_id=conversation.get("project_id"),
            message_content=message_content,
            attachments=attachments,
            force_redact=dlp_redact,
            confirmed=send_confirmed,
            dlp_confirm_token=send_confirm_token,
            user_lang=send_user_lang,
            source_ref={"conversation_id": conversation_id},
        )

    gate_out = await anyio.to_thread.run_sync(_send_gate)
    message_content = gate_out["message_content"]
    attachments = gate_out["attachments"]
    send_user_meta = {}
    if gate_out["badge"]:
        send_user_meta["dlp_redacted"] = gate_out["badge"]
    if quoted_text:
        send_user_meta["quoted_text"] = quoted_text
    # Persist the web_search preference so edit/regenerate can replay it.
    if bool(data.get("web_search")):
        send_user_meta["web_search"] = True

    # Spend gate (pre-flight budget/credit enforcement). Mirrors the DLP gate:
    # runs AFTER it, BEFORE any persistence, so a breach is a clean HTTP 402
    # (BudgetExceededError -> global handler). Reuses the same workspace/project
    # ids the DLP gate resolved for attribution. Offloaded to a worker thread
    # (it does a few indexed point-reads) so it never stalls the event loop.
    def _spend() -> None:
        spend_gate.gate(
            user_id=user_id,
            workspace_id=send_ws_id,
            project_id=conversation.get("project_id"),
            origin="web",
            feature="chat",
        )

    await anyio.to_thread.run_sync(_spend)

    # Save user message. Stamp the sender so collaborative (team-shared) chats
    # can attribute each turn; harmless on private chats (the UI only shows a
    # label when the conversation is shared).
    user_message = MessageModel.create_user_message(
        conversation_id=conversation_id,
        content=message_content,
        attachments=attachments,
        branch_id=branch_id,
        metadata=(send_user_meta or None),
        sender_user_id=user_id,
    )

    # Get context (now includes the just-saved user message + its attachments).
    context_messages = MessageModel.get_context_messages(conversation_id, limit=20, branch_id=branch_id)

    start_time = time.time()
    params = config.get("parameters", {})

    # Get user AI preferences and build enhanced system prompt
    ai_prefs = user.get("ai_preferences", {})
    enhanced_prompt = OpenRouterService.build_enhanced_system_prompt(
        config.get("system_prompt"),
        ai_prefs,
        model_id=config["model_id"],
        include_identity=True,
    )

    send_workspace_id = conversation.get("workspace_id") or user.get("active_workspace_id")
    send_project_id = conversation.get("project_id")
    web_search = bool(data.get("web_search"))
    # web_fetch auto-enables when the user's message text contains a URL.
    web_fetch = _text_has_url(message_content)

    # Offload the blocking LLM round-trip to a worker thread so it never stalls
    # the uvicorn event loop. anyio copies the current contextvars Context (incl.
    # the Flask app_context pushed by the flask_ctx dep) into the worker, and the
    # loop awaits it — so the Flask app_context/db.session stay valid and are never touched
    # concurrently. The attachment formatting (incl. any PDF base64 read off
    # disk) runs INSIDE this offloaded callable, never on the event loop.
    conv_owner_id = str(conversation.get("user_id")) if conversation.get("user_id") else user_id

    def _completion():
        fmt = OpenRouterService.format_messages_for_api_ex(
            context_messages, user_id=conv_owner_id
        )
        formatted_messages = fmt["messages"]
        plugins = list(fmt.get("plugins") or [])
        if fmt.get("has_native_pdf"):
            engine = settings.get("PDF_OCR_ENGINE", "mistral-ocr")
            plugins.append({"id": "file-parser", "pdf": {"engine": engine}})
        return OpenRouterService.chat_completion(
            messages=formatted_messages,
            model=config["model_id"],
            system_prompt=enhanced_prompt,
            temperature=params.get("temperature", 0.7),
            max_tokens=params.get("max_tokens", 32000),
            stream=False,
            user_id=user_id,
            conversation_id=conversation_id,
            feature="chat",
            workspace_id=str(send_workspace_id) if send_workspace_id else None,
            project_id=str(send_project_id) if send_project_id else None,
            origin="web",
            web_search=web_search,
            web_fetch=web_fetch,
            plugins=plugins or None,
        )

    response = await anyio.to_thread.run_sync(_completion)

    generation_time_ms = int((time.time() - start_time) * 1000)

    if "error" in response:
        error_msg = response["error"].get("message", "Unknown error")
        error_message = MessageModel.create_error_message(
            conversation_id=conversation_id,
            error_message=error_msg,
            model_id=config["model_id"],
            branch_id=branch_id,
        )
        return JSONResponse({
            "error": error_msg,
            "user_message": serialize_doc(user_message),
            "assistant_message": serialize_doc(error_message),
        }, status_code=500)

    # Extract response content
    choices = response.get("choices", [])
    content = choices[0]["message"]["content"] if choices else ""
    usage = response.get("usage", {})
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    finish_reason = choices[0].get("finish_reason", "stop") if choices else "stop"

    # Save assistant message
    assistant_message = MessageModel.create_assistant_message(
        conversation_id=conversation_id,
        content=content,
        model_id=config["model_id"],
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        generation_time_ms=generation_time_ms,
        finish_reason=finish_reason,
        branch_id=branch_id,
    )

    # Persist message annotations (PDF file annotations for OCR-replay on later
    # turns + web_search url_citations). Merge into metadata so the completion
    # fields (model_id/tokens/…) are preserved.
    annotations = response.get("annotations")
    if annotations:
        MessageModel.merge_metadata(str(assistant_message["_id"]), {"annotations": annotations})
        assistant_message.setdefault("metadata", {})["annotations"] = annotations

    # Update stats
    ConversationModel.increment_message_count(
        conversation_id,
        input_tokens=prompt_tokens,
        output_tokens=completion_tokens,
    )
    UserModel.increment_usage(user_id, messages=2, tokens=prompt_tokens + completion_tokens)
    if not is_quick_model:
        LLMConfigModel.increment_uses(config_id)

    return JSONResponse({
        "conversation_id": conversation_id,
        "user_message": serialize_doc(user_message),
        "assistant_message": serialize_doc(assistant_message),
        "is_new_conversation": conversation_id != data.get("conversation_id"),
    }, status_code=200)

