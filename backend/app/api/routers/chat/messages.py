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
    _RUN_PYTHON_TOOL,
    _data_analysis_prefs,
    _run_data_analysis_sync,
)
from .titles import _TITLE_EXECUTOR, _generate_title_async

@router.get("/{conversation_id}/messages")
def get_messages(
    conversation_id: str,
    request: Request,
    user: dict = Depends(require_active),
):
    """Get messages for a conversation."""
    user_id = str(user["_id"])

    # Access: owner OR a member of a team this chat is shared into. The helper
    # also enforces the project ACL for an owner who has lost project access.
    conversation = ConversationModel.find_by_id(conversation_id)
    _role, acc_err = resolve_conversation_access(conversation, user_id, "viewer")
    if acc_err:
        msg, status = acc_err
        payload = {"error": msg}
        if status == 403:
            payload["status"] = 403
        return JSONResponse(payload, status_code=status)

    page = int(request.query_params.get("page", 1))
    limit = int(request.query_params.get("limit", 100))
    skip = (page - 1) * limit

    # Get branch_id from query params, default to active branch
    branch_id = request.query_params.get("branch_id", conversation.get("active_branch", "main"))

    messages = MessageModel.find_by_conversation(conversation_id, skip=skip, limit=limit, branch_id=branch_id)
    total = MessageModel.count_by_conversation(conversation_id)

    return JSONResponse({
        "messages": serialize_doc(messages),
        "total": total,
        "page": page,
        "limit": limit,
        "branch_id": branch_id,
    }, status_code=200)


@router.delete("/messages/{message_id}")
def delete_message(message_id: str, user: dict = Depends(require_active)):
    """Delete a message."""
    user_id = str(user["_id"])

    message = MessageModel.find_by_id(message_id)
    if not message:
        return JSONResponse({"error": "Message not found"}, status_code=404)

    # Access: owner OR shared-team member; a member may delete only their own turns.
    conversation = ConversationModel.find_by_id(message["conversation_id"])
    _role, acc_err = resolve_conversation_access(conversation, user_id, "viewer")
    if acc_err or (_role != "owner" and str(message.get("sender_user_id") or "") != user_id):
        return JSONResponse({"error": "Message not found"}, status_code=404)

    MessageModel.delete(message_id)

    return JSONResponse({"message": "Message deleted"}, status_code=200)


@router.put("/messages/{message_id}")
async def edit_message(
    message_id: str,
    request: Request,
    user: dict = Depends(require_active),
):
    """Edit a user message and optionally regenerate the AI response."""
    # Validate ID format (prevents crash on temp IDs like "temp-123456")
    if not is_valid_id(message_id):
        return JSONResponse({"error": "Invalid message ID format"}, status_code=400)

    user_id = str(user["_id"])
    data = await _json_body(request)

    new_content = (data.get("content") or "").strip()
    regenerate = data.get("regenerate", True)

    if not new_content:
        return JSONResponse({"error": "Content is required"}, status_code=400)

    message = MessageModel.find_by_id(message_id)
    if not message:
        return JSONResponse({"error": "Message not found"}, status_code=404)

    if message["role"] != "user":
        return JSONResponse({"error": "Only user messages can be edited"}, status_code=400)

    # Access: owner OR shared-team member; a member may edit only their own turns.
    conversation = ConversationModel.find_by_id(message["conversation_id"])
    _role, acc_err = resolve_conversation_access(conversation, user_id, "viewer")
    if acc_err or (_role != "owner" and str(message.get("sender_user_id") or "") != user_id):
        return JSONResponse({"error": "Conversation not found"}, status_code=404)
    if conversation_workspace_denied(conversation, user):
        return JSONResponse(dict(WORKSPACE_ACCESS_DENIED), status_code=403)

    conversation_id = str(conversation["_id"])
    branch_id = message.get("branch_id", "main")

    # Pre-flight config check BEFORE destructive ops (P0.1: prevent message loss on 404)
    config = None
    if regenerate:
        # Same as regenerate: `quick:` / `agent:` ids are not llm_configs rows.
        edit_config_key = conversation.get("config_id")
        config = (
            resolve_chat_config(edit_config_key, user_id, conversation.get("project_id"))
            if edit_config_key else None
        )
        if not config:
            return JSONResponse({"error": "Config not found"}, status_code=404)

    # DLP gate (redaction-aware) on the EDITED content before it is persisted +
    # re-sent. ``dlp_redact`` comes from the body, falling back to the original
    # turn's stored redaction flag so editing an already-redacted turn stays
    # redacted. Enforce mode block/confirm/warn is unchanged.
    edit_msg_meta = message.get("metadata") or {}
    edit_dlp_redact = bool(data.get("dlp_redact")) or bool(edit_msg_meta.get("dlp_redacted"))
    edit_ws_id = conversation.get("workspace_id") or user.get("active_workspace_id")
    edit_user_lang = _resolve_user_lang(data, user)
    edit_confirmed = bool(data.get("dlp_confirmed"))
    edit_confirm_token = data.get("dlp_confirm_token")

    def _edit_gate() -> dict:
        return _gate_and_redact_chat_turn(
            user=user,
            workspace_id=edit_ws_id,
            project_id=conversation.get("project_id"),
            message_content=new_content,
            attachments=[],
            force_redact=edit_dlp_redact,
            confirmed=edit_confirmed,
            dlp_confirm_token=edit_confirm_token,
            user_lang=edit_user_lang,
            source_ref={"conversation_id": conversation_id},
        )

    edit_gate_out = await anyio.to_thread.run_sync(_edit_gate)
    new_content = edit_gate_out["message_content"]
    edit_dlp_badge = edit_gate_out["badge"]

    # Spend gate (pre-flight budget/credit enforcement). Only a regenerating edit
    # triggers a new LLM completion, so gate only then — a pure text edit (no
    # regenerate) makes no billable call. Runs AFTER the DLP gate, BEFORE any
    # destructive op / completion, so a breach is a clean HTTP 402. Reuses the
    # edit handler's resolved ws/project ids. Offloaded to a worker thread.
    if regenerate:
        def _edit_spend() -> None:
            spend_gate.gate(
                user_id=user_id,
                workspace_id=edit_ws_id,
                project_id=conversation.get("project_id"),
                origin="web",
                feature="chat",
            )

        await anyio.to_thread.run_sync(_edit_spend)

    # Store edit history. Stamp `edited_at` with now() (not the original
    # created_at — that lied about when the edit happened).
    edit_history = message.get("edit_history", [])
    edit_history.append({
        "content": message["content"],
        "edited_at": datetime.now(timezone.utc).isoformat(),
    })

    # Update the message content (already DLP-scrubbed above when in redact mode).
    MessageModel.update_with_edit_history(message_id, new_content, edit_history)
    # Persist the redaction badge so the edited turn renders the UI marker and a
    # later regenerate/edit knows to keep redacting.
    if edit_dlp_badge:
        MessageModel.merge_metadata(message_id, {"dlp_redacted": edit_dlp_badge})

    # Delete all messages after this one if regenerating
    deleted_count = 0
    if regenerate:
        deleted_count = MessageModel.delete_after_message(conversation_id, message_id, branch_id=branch_id)

    updated_message = MessageModel.find_by_id(message_id)

    response_data = {
        "message": serialize_doc(updated_message),
        "deleted_count": deleted_count if regenerate else 0,
    }

    # If regenerating, generate new AI response (config already validated above)
    if regenerate:
        # Get context including the edited message (in the same branch)
        messages = MessageModel.find_by_conversation(conversation_id, branch_id=branch_id)

        params = config.get("parameters", {})
        start_time = time.time()

        # Get user AI preferences and build enhanced system prompt
        ai_prefs = user.get("ai_preferences", {})
        enhanced_prompt = OpenRouterService.build_enhanced_system_prompt(
            config.get("system_prompt"),
            ai_prefs,
            model_id=config["model_id"],
            include_identity=True,
        )

        # Resolve workspace_id + project_id from the conversation so the
        # regenerated message's usage_log row attributes correctly.
        regen_workspace_id = conversation.get("workspace_id") or user.get("active_workspace_id")
        regen_project_id = conversation.get("project_id")
        # Reuse the original turn's web_search preference if it was recorded.
        edit_web_search = bool((message.get("metadata") or {}).get("web_search"))
        # web_fetch auto-enables when the edited user text contains a URL.
        edit_web_fetch = _text_has_url(new_content)

        # Offload the blocking LLM round-trip off the event loop (see
        # send_message). Format (incl. PDF base64 read) runs inside the worker.
        edit_conv_owner_id = str(conversation.get("user_id")) if conversation.get("user_id") else user_id

        def _completion():
            fmt = OpenRouterService.format_messages_for_api_ex(
                messages, user_id=edit_conv_owner_id
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
                workspace_id=str(regen_workspace_id) if regen_workspace_id else None,
                project_id=str(regen_project_id) if regen_project_id else None,
                origin="web",
                web_search=edit_web_search,
                web_fetch=edit_web_fetch,
                plugins=plugins or None,
            )

        ai_response = await anyio.to_thread.run_sync(_completion)

        generation_time_ms = int((time.time() - start_time) * 1000)

        if "error" in ai_response:
            error_msg = ai_response["error"].get("message", "Generation failed")
            error_message = MessageModel.create_error_message(
                conversation_id=conversation_id,
                error_message=error_msg,
                model_id=config["model_id"],
            )
            return JSONResponse({
                "error": error_msg,
                **response_data,
                "assistant_message": serialize_doc(error_message),
            }, status_code=500)

        choices = ai_response.get("choices", [])
        content = choices[0]["message"]["content"] if choices else ""
        usage = ai_response.get("usage", {})

        assistant_message = MessageModel.create_assistant_message(
            conversation_id=conversation_id,
            content=content,
            model_id=config["model_id"],
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            generation_time_ms=generation_time_ms,
            finish_reason=choices[0].get("finish_reason", "stop") if choices else "stop",
            branch_id=branch_id,
        )

        # Persist message annotations (PDF OCR-replay + web_search citations).
        edit_annotations = ai_response.get("annotations")
        if edit_annotations:
            MessageModel.merge_metadata(
                str(assistant_message["_id"]), {"annotations": edit_annotations}
            )
            assistant_message.setdefault("metadata", {})["annotations"] = edit_annotations

        # Update stats
        UserModel.increment_usage(
            user_id,
            messages=1,
            tokens=usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0),
        )

        response_data["assistant_message"] = serialize_doc(assistant_message)

    return JSONResponse(response_data, status_code=200)


_VALID_FEEDBACK = {"up", "down", None}


@router.post("/messages/{message_id}/feedback")
async def message_feedback(
    message_id: str,
    request: Request,
    user: dict = Depends(require_active),
):
    """Set / clear a thumbs up/down rating on an assistant message.

    Rides the existing ``message_metadata`` JSONB — no schema migration. The
    write is a shallow JSONB merge so sibling keys (annotations, model_id,
    tokens, dlp_redacted, …) are preserved; a null rating removes the key.
    """
    if not is_valid_id(message_id):
        return JSONResponse({"error": "Invalid message ID format"}, status_code=400)

    user_id = str(user["_id"])
    data = await _json_body(request)
    rating = data.get("rating")

    if rating not in _VALID_FEEDBACK:
        return JSONResponse(
            {"error": "rating must be one of 'up', 'down', or null"}, status_code=400
        )

    message = MessageModel.find_by_id(message_id)
    if not message:
        return JSONResponse({"error": "Message not found"}, status_code=404)

    if message["role"] != "assistant":
        return JSONResponse(
            {"error": "Only assistant messages can be rated"}, status_code=400
        )

    # Access: owner OR a member of a team this chat is shared into (members may
    # rate assistant turns in a collaborative chat).
    conversation = ConversationModel.find_by_id(message["conversation_id"])
    _role, acc_err = resolve_conversation_access(conversation, user_id, "viewer")
    if acc_err:
        return JSONResponse({"error": "Conversation not found"}, status_code=404)

    if rating is None:
        # merge_metadata can't delete a key — fetch, pop, replace wholesale.
        meta = dict(message.get("metadata") or {})
        meta.pop("feedback", None)
        MessageModel.update_metadata(message_id, meta)
    else:
        MessageModel.merge_metadata(message_id, {"feedback": rating})

    return JSONResponse(
        {"success": True, "message_id": message_id, "rating": rating},
        status_code=200,
    )



@router.post("/cancel/{message_id}")
def cancel_generation(message_id: str, user: dict = Depends(current_user)):
    """Cancel an ongoing generation."""
    user_id = str(user["_id"])

    owner = stream_state.owner_of(message_id)
    if owner is None:
        return JSONResponse({"error": "Generation not found"}, status_code=404)
    if owner != user_id:
        return JSONResponse({"error": "Not authorized"}, status_code=403)
    stream_state.mark_cancelled(message_id)
    return JSONResponse({"success": True, "message": "Generation cancelled"}, status_code=200)

