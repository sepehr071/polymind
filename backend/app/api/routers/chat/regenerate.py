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

@router.post("/regenerate/{message_id}")
async def regenerate_message(
    message_id: str,
    request: Request,
    user: dict = Depends(require_active),
):
    """Regenerate an assistant message. Optionally create a branch instead of deleting."""
    user_id = str(user["_id"])

    data = await _json_body(request)
    create_branch = data.get("create_branch", False)
    branch_name = data.get("branch_name")

    message = MessageModel.find_by_id(message_id)
    if not message or message["role"] != "assistant":
        return JSONResponse({"error": "Message not found or not regeneratable"}, status_code=404)

    # Access: owner OR a member of a team this chat is shared into.
    conversation = ConversationModel.find_by_id(message["conversation_id"])
    _role, acc_err = resolve_conversation_access(conversation, user_id, "viewer")
    if acc_err:
        return JSONResponse({"error": "Conversation not found"}, status_code=404)
    if conversation_workspace_denied(conversation, user):
        return JSONResponse(dict(WORKSPACE_ACCESS_DENIED), status_code=403)

    conversation_id = str(conversation["_id"])
    current_branch = message.get("branch_id", "main")

    # Get config. An optional ``config_id`` in the body overrides the
    # conversation's saved config for THIS regeneration only (model-switch on
    # regenerate) — the conversation row is NOT mutated. Resolved through the
    # same path as /send (``resolve_chat_config``) so ``quick:<model>`` /
    # ``agent:<key>`` prefixes and project-scoped LLMConfig gating behave
    # identically. The resolved ``config["model_id"]`` is stamped onto the new
    # assistant message below, so metadata.model_id reflects the swapped model.
    # Saved chat config is usually `quick:<model>` (or `agent:<key>`), not an
    # llm_configs UUID. find_by_id on that string is always None → every
    # default-model regenerate 404'd. Same resolver as /send.
    config_key = data.get("config_id") or conversation.get("config_id")
    config = (
        resolve_chat_config(config_key, user_id, conversation.get("project_id"))
        if config_key else None
    )
    if not config:
        return JSONResponse({"error": "Config not found"}, status_code=404)

    # Canvas parity on regenerate: the original turn was generated under the
    # Canvas Coder contract (metadata.intent == 'canvas'). Re-apply that system
    # prompt — whatever model is in play — or the regenerated reply stops being
    # a single runnable ```html fence.
    regen_intent = (message.get("metadata") or {}).get("intent")
    if regen_intent == "canvas":
        config = {**config, "system_prompt": CANVAS_SYSTEM_PROMPT}

    # Get all messages in the branch
    all_messages = MessageModel.find_by_conversation(conversation_id, branch_id=current_branch)

    # Find the user message that prompted this assistant response
    target_user_msg = None
    for i, msg in enumerate(all_messages):
        if str(msg["_id"]) == message_id:
            # Find the previous user message
            for j in range(i - 1, -1, -1):
                if all_messages[j]["role"] == "user":
                    target_user_msg = all_messages[j]
                    break
            break

    if not target_user_msg:
        return JSONResponse({"error": "No user message found"}, status_code=400)

    # Spend gate (pre-flight budget/credit enforcement). Regeneration triggers a
    # new billable LLM completion, so gate it like /send + /stream. Runs BEFORE
    # any destructive branch op so a 402 leaves the conversation untouched.
    # Resolves the same ws/project ids used below for usage attribution.
    # Offloaded to a worker thread so it never stalls the event loop.
    def _regen_spend() -> None:
        spend_gate.gate(
            user_id=user_id,
            workspace_id=conversation.get("workspace_id") or user.get("active_workspace_id"),
            project_id=conversation.get("project_id"),
            origin="web",
            feature=_DATA_FEATURE if regen_intent == "data" else "chat",
        )

    await anyio.to_thread.run_sync(_regen_spend)

    target_branch = current_branch
    new_branch_id = None

    if create_branch:
        # Create a new branch from the user message
        new_branch_id = str(uuid.uuid4())[:12]
        branch_data = {
            "id": new_branch_id,
            "name": branch_name or "Regeneration branch",
            "parent_branch": current_branch,
            "branch_point_message_id": str(target_user_msg["_id"]),
        }
        ConversationModel.add_branch(conversation_id, branch_data)

        # Bulk-copy in one commit (was N commits via per-message copy_to_branch).
        # ``copy_many_to_branch`` allocates a contiguous block of fresh monotonic
        # ``seq`` values, so cloned rows never collide on the
        # ``uq_messages_conv_seq`` (conversation_id, seq) unique constraint.
        messages_to_copy = MessageModel.find_up_to(conversation_id, str(target_user_msg["_id"]), current_branch)
        MessageModel.copy_many_to_branch(messages_to_copy, new_branch_id)

        target_branch = new_branch_id
        ConversationModel.set_active_branch(conversation_id, new_branch_id)
    else:
        # Delete the old assistant message and any subsequent messages
        MessageModel.delete_after_message(conversation_id, str(target_user_msg["_id"]), branch_id=current_branch)

    # Get context for generation (messages in target branch)
    context_messages = MessageModel.find_by_conversation(conversation_id, branch_id=target_branch)

    params = config.get("parameters", {})
    start_time = time.time()

    # Get user AI preferences and build enhanced system prompt
    full_user = UserModel.find_by_id(user_id)
    ai_prefs = full_user.get("ai_preferences", {}) if full_user else {}
    enhanced_prompt = OpenRouterService.build_enhanced_system_prompt(
        config.get("system_prompt"),
        ai_prefs,
        model_id=config["model_id"],
        include_identity=True,
    )

    regen_workspace_id = conversation.get("workspace_id") or user.get("active_workspace_id")
    regen_project_id = conversation.get("project_id")
    # Owner-scope for attachment inlining (shared chats may carry teammate
    # uploads; per-message sender_user_id wins, this is the fallback).
    regen_conv_owner_id = str(conversation.get("user_id")) if conversation.get("user_id") else user_id
    # Reuse the prompting user turn's web_search preference if it was recorded.
    regen_web_search = bool((target_user_msg.get("metadata") or {}).get("web_search"))
    # web_fetch auto-enables when the target user message text contains a URL.
    regen_web_fetch = _text_has_url(target_user_msg.get("content"))
    # DLP parity: regeneration introduces NO new user text — the prompting user
    # message (and its attachment text) was already DLP-scrubbed at send/edit
    # time and persisted in that form. The context below is rebuilt from those
    # persisted rows, so the LLM automatically receives the scrubbed text; the
    # stored ``metadata.dlp_redacted`` flag already reflects it. Re-running the
    # gate here would only re-scan already-redacted text (wasted classify cost /
    # duplicate event), so we intentionally do not.

    # Data Analyzer parity on regenerate: the original turn ran the agentic
    # run_python flow (metadata.intent == 'data'). Re-prepare the dataset and
    # re-run the tool loop NON-streamed (this handler returns JSON, not SSE),
    # persist data_artifacts + intent, and return the assembled message early.
    # Fails CLOSED (graceful message, no crash) when the sandbox/data is absent.
    if regen_intent == "data":
        regen_target_attachments = target_user_msg.get("attachments") or []

        def _data_regen():
            try:
                from app.services.sandbox_service import SandboxService
                from app.services.data_analysis_service import prepare_dataset
                if not SandboxService.available():
                    return {"content": (
                        "Data analysis is unavailable on this server right now."
                    ), "data_artifacts": {"steps": [], "artifacts": []},
                        "finish_reason": "stop", "error": None}
            except Exception as e:  # noqa: BLE001
                _logger.warning("data regen sandbox unavailable: %s", e)
                return {"content": (
                    "Data analysis is unavailable on this server right now."
                ), "data_artifacts": {"steps": [], "artifacts": []},
                    "finish_reason": "stop", "error": None}

            ctx = None
            try:
                ctx = prepare_dataset(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    attachments=regen_target_attachments,
                    workspace_id=str(regen_workspace_id) if regen_workspace_id else None,
                    project_id=str(regen_project_id) if regen_project_id else None,
                    status_cb=None,  # no SSE on the regen JSON path
                )
            except Exception as e:  # noqa: BLE001
                _logger.warning("data regen prepare_dataset failed: %s", e)
                ctx = None
            if ctx is None:
                return {"content": (
                    "I couldn't find a data file to analyze for this message."
                ), "data_artifacts": {"steps": [], "artifacts": []},
                    "finish_reason": "stop", "error": None}

            # Strip data files from EVERY user turn (preview-only ingestion) — not
            # just the latest, else a prior turn's CSV leaks back in as huge TSV.
            cm_list = list(context_messages)
            for idx in range(len(cm_list)):
                cm = cm_list[idx]
                if cm.get("role") != "user":
                    continue
                kept = [a for a in (cm.get("attachments") or [])
                        if not _is_data_attachment(a)]
                if len(kept) != len(cm.get("attachments") or []):
                    cm = dict(cm)
                    cm["attachments"] = kept
                    cm_list[idx] = cm
            # Recap each prior assistant turn's emitted artifacts (B) so the model
            # remembers what it already produced on a follow-up regenerate.
            _append_artifact_recaps(cm_list)
            fmt = OpenRouterService.format_messages_for_api_ex(
                cm_list, user_id=regen_conv_owner_id
            )
            # Trim chat AI-preferences to language-only (C): generic chat
            # instructions must not override the data-analyst contract.
            data_system_prompt = OpenRouterService.build_enhanced_system_prompt(
                DATA_ANALYST_SYSTEM_PROMPT + "\n\n" + (ctx.get("preview_markdown") or ""),
                _data_analysis_prefs(ai_prefs),
            )
            from app.services.data_model_router import (
                pick_data_analysis_model,
                reasoning_effort_for_model,
            )
            data_model = pick_data_analysis_model(target_user_msg.get("content"))
            return _run_data_analysis_sync(
                formatted_messages=fmt["messages"],
                system_prompt=data_system_prompt,
                model=data_model,
                params=params,
                max_rounds=int(settings.get("DATA_PY_MAX_ROUNDS", 14)),
                workdir=ctx.get("workdir"),
                sandbox_run=SandboxService.run,
                user_id=user_id,
                conversation_id=conversation_id,
                workspace_id=str(regen_workspace_id) if regen_workspace_id else None,
                project_id=str(regen_project_id) if regen_project_id else None,
                manifest=ctx.get("manifest"),
                reasoning_effort=reasoning_effort_for_model(data_model),
            )

        data_out = await anyio.to_thread.run_sync(_data_regen)
        generation_time_ms = int((time.time() - start_time) * 1000)

        assistant_message = MessageModel.create_assistant_message(
            conversation_id=conversation_id,
            content=data_out["content"],
            model_id=config["model_id"],
            generation_time_ms=generation_time_ms,
            finish_reason=data_out["finish_reason"],
            branch_id=target_branch,
        )
        MessageModel.merge_metadata(
            str(assistant_message["_id"]),
            {"intent": "data", "data_artifacts": data_out["data_artifacts"]},
        )
        assistant_message.setdefault("metadata", {})["intent"] = "data"
        assistant_message["metadata"]["data_artifacts"] = data_out["data_artifacts"]

        response_data = {
            "message": serialize_doc(assistant_message),
            "branch_id": target_branch,
        }
        if new_branch_id:
            response_data["new_branch_id"] = new_branch_id
            updated_conv = ConversationModel.find_by_id(conversation_id)
            response_data["branches"] = serialize_doc(updated_conv.get("branches", []))
        return JSONResponse(response_data, status_code=200)

    # Chat UI sends stream=true: drop already happened above, then tokens SSE
    # out like /stream. JSON below stays for tests, branching, and the data path.
    if data.get("stream"):
        def _produce(stop_event):
            fmt = OpenRouterService.format_messages_for_api_ex(
                context_messages, user_id=regen_conv_owner_id
            )
            plugins = list(fmt.get("plugins") or [])
            if fmt.get("has_native_pdf"):
                engine = settings.get("PDF_OCR_ENGINE", "mistral-ocr")
                plugins.append({"id": "file-parser", "pdf": {"engine": engine}})

            assistant_message = MessageModel.create(
                conversation_id=conversation_id,
                role="assistant",
                content="",
                metadata={"model_id": config["model_id"], **({"intent": regen_intent} if regen_intent else {})},
                branch_id=target_branch,
            )
            message_id = str(assistant_message["_id"])
            yield _sse_event("message_start", {
                "message_id": message_id,
                "conversation_id": conversation_id,
                "branch_id": target_branch,
            })
            db.session.remove()

            full_content = ""
            annotations: list = []
            finish_reason = "stop"
            prompt_tokens = 0
            completion_tokens = 0
            gen_start = time.time()
            last_yield = gen_start
            try:
                stream = OpenRouterService.chat_completion(
                    messages=fmt["messages"],
                    model=config["model_id"],
                    system_prompt=enhanced_prompt,
                    temperature=params.get("temperature", 0.7),
                    max_tokens=params.get("max_tokens", 32000),
                    stream=True,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    feature="chat",
                    workspace_id=str(regen_workspace_id) if regen_workspace_id else None,
                    project_id=str(regen_project_id) if regen_project_id else None,
                    origin="web",
                    web_search=regen_web_search,
                    web_fetch=regen_web_fetch,
                    plugins=plugins or None,
                )
                for chunk in stream:
                    if stop_event.is_set():
                        finish_reason = "cancelled"
                        break
                    if time.time() - gen_start > _MAX_WALLCLOCK_SECONDS:
                        yield _sse_event("message_error", {
                            "message_id": message_id,
                            "error": "Stream timed out",
                            "conversation_id": conversation_id,
                        })
                        MessageModel.mark_error(message_id, "Stream timed out")
                        return
                    if time.time() - last_yield >= _KEEPALIVE_INTERVAL:
                        yield ": keepalive\n\n"
                        last_yield = time.time()
                    if "error" in chunk:
                        error_msg = chunk["error"].get("message", "Generation failed")
                        yield _sse_event("message_error", {
                            "message_id": message_id,
                            "error": error_msg,
                            "conversation_id": conversation_id,
                        })
                        MessageModel.mark_error(message_id, error_msg)
                        return
                    if chunk.get("done"):
                        if chunk.get("annotations"):
                            annotations = chunk["annotations"]
                        break
                    choices = chunk.get("choices") or []
                    if not choices:
                        usage = chunk.get("usage") or {}
                        if usage:
                            prompt_tokens = usage.get("prompt_tokens", prompt_tokens)
                            completion_tokens = usage.get("completion_tokens", completion_tokens)
                        continue
                    if choices[0].get("finish_reason"):
                        finish_reason = choices[0]["finish_reason"]
                    delta = choices[0].get("delta") or {}
                    piece = delta.get("content") or ""
                    if piece:
                        full_content += piece
                        yield _sse_event("message_chunk", {
                            "message_id": message_id,
                            "content": piece,
                            "conversation_id": conversation_id,
                        })
                        last_yield = time.time()
                    usage = chunk.get("usage") or {}
                    if usage:
                        prompt_tokens = usage.get("prompt_tokens", prompt_tokens)
                        completion_tokens = usage.get("completion_tokens", completion_tokens)
                    chunk_ann = (choices[0].get("message") or {}).get("annotations") or delta.get("annotations")
                    if chunk_ann:
                        annotations = chunk_ann
            except Exception as e:  # noqa: BLE001
                yield _sse_event("message_error", {
                    "message_id": message_id,
                    "error": str(e),
                    "conversation_id": conversation_id,
                })
                return

            generation_time_ms = int((time.time() - gen_start) * 1000)
            meta = {
                "model_id": config["model_id"],
                "tokens": {"prompt": prompt_tokens, "completion": completion_tokens},
                "generation_time_ms": generation_time_ms,
                "finish_reason": finish_reason,
                **({"intent": regen_intent} if regen_intent else {}),
                **({"annotations": annotations} if annotations else {}),
            }
            MessageModel.update_content_and_metadata(message_id, full_content, meta)
            payload = {
                "message_id": message_id,
                "content": full_content,
                "conversation_id": conversation_id,
                "branch_id": target_branch,
                "metadata": meta,
            }
            if regen_intent:
                payload["intent"] = regen_intent
            if annotations:
                payload["annotations"] = annotations
            yield _sse_event("message_complete", payload)

        return sse_stream_sync(_produce, runner_name="chat-regen-runner")

    # Offload the blocking LLM round-trip off the event loop (see send_message).
    # Format (incl. PDF base64 read) runs inside the worker.
    def _completion():
        fmt = OpenRouterService.format_messages_for_api_ex(
            context_messages, user_id=regen_conv_owner_id
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
            web_search=regen_web_search,
            web_fetch=regen_web_fetch,
            plugins=plugins or None,
        )

    response = await anyio.to_thread.run_sync(_completion)

    generation_time_ms = int((time.time() - start_time) * 1000)

    if "error" in response:
        return JSONResponse(
            {"error": response["error"].get("message", "Generation failed")},
            status_code=500,
        )

    choices = response.get("choices", [])
    content = choices[0]["message"]["content"] if choices else ""
    usage = response.get("usage", {})

    assistant_message = MessageModel.create_assistant_message(
        conversation_id=conversation_id,
        content=content,
        model_id=config["model_id"],
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        generation_time_ms=generation_time_ms,
        finish_reason=choices[0].get("finish_reason", "stop") if choices else "stop",
        branch_id=target_branch,
    )

    # Persist message annotations (PDF OCR-replay + web_search citations).
    regen_annotations = response.get("annotations")
    if regen_annotations:
        MessageModel.merge_metadata(
            str(assistant_message["_id"]), {"annotations": regen_annotations}
        )
        assistant_message.setdefault("metadata", {})["annotations"] = regen_annotations

    # Carry the canvas intent onto the regenerated turn so FUTURE regenerations
    # (and any canvas-aware UI) keep recognizing it.
    if regen_intent == "canvas":
        MessageModel.merge_metadata(str(assistant_message["_id"]), {"intent": "canvas"})
        assistant_message.setdefault("metadata", {})["intent"] = "canvas"

    response_data = {
        "message": serialize_doc(assistant_message),
        "branch_id": target_branch,
    }

    if new_branch_id:
        response_data["new_branch_id"] = new_branch_id
        # Get updated branches
        updated_conv = ConversationModel.find_by_id(conversation_id)
        response_data["branches"] = serialize_doc(updated_conv.get("branches", []))

    return JSONResponse(response_data, status_code=200)


