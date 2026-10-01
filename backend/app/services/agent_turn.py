"""Agent turn SSE producer (extracted from the agent router).

Orchestration for a single agent stream/clarify turn: conversation setup,
optional dataset prep, tool loop (ask_user / generate_image / run_python +
server web tools), narration, and message finalization.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from typing import Any, Dict, List, Optional

from app.api.core import db
from app.models.conversation import ConversationModel
from app.models.generated_image import GeneratedImageModel
from app.models.message import MessageModel
from app.prompts.agent_orchestrator import AGENT_ORCHESTRATOR_PROMPT
from app.services import agent_service as asvc
from app.services import spend_gate, stream_state
from app.services.chat_artifacts import (
    append_artifact_recaps,
    format_tool_result_for_model,
    persist_file_artifacts,
    prune_dead_file_artifacts,
)
from app.services.chat_attachments import is_data_attachment
from app.services.openrouter_service import OpenRouterService, ToolLoopPause
from app.settings import settings
from app.utils.helpers import generate_conversation_title, serialize_doc
from app.utils.permissions import resolve_conversation_access

logger = logging.getLogger(__name__)

_FEATURE = asvc.AGENT_FEATURE
_KEEPALIVE_INTERVAL = 15
_MAX_WALLCLOCK_SECONDS = 1800
_LOOP_DONE = object()
_AGENT_TEMPERATURE = 0.3


def _sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def produce_agent_turn(
    *,
    stop_event,
    user: dict,
    user_id: str,
    message_content: str,
    attachments: list,
    conversation_id: Optional[str],
    reservation_id: str,
    model_id: str,
    include_python: bool,
    ws_id_s: Optional[str],
    proj_id_s: Optional[str],
    dlp_badge,
    resume: Optional[dict],
):
    gen_start = time.time()
    last_yield = gen_start
    nonlocal_conversation_id = conversation_id
    is_new = False

    # --- conversation ---
    if resume:
        conversation = ConversationModel.find_by_id(
            nonlocal_conversation_id, include_branches=False,
        )
        if not conversation:
            yield _sse("error", {"message": "Conversation not found"})
            return
    elif nonlocal_conversation_id:
        conversation = ConversationModel.find_by_id(
            nonlocal_conversation_id, include_branches=False,
        )
        _role, _acc_err = resolve_conversation_access(conversation, user_id, "viewer")
        if _acc_err:
            yield _sse("error", {"message": "Conversation not found"})
            return
    else:
        is_new = True
        title = generate_conversation_title(message_content or "Agent")
        conversation = ConversationModel.create(
            user_id=user_id,
            config_id=f"agent:{model_id}",
            title=title,
            kind="agent",
            project_id=proj_id_s,
            workspace_id=ws_id_s,
        )
        nonlocal_conversation_id = str(conversation["_id"])
        yield _sse("conversation_created", {
            "conversation": serialize_doc(conversation),
        })

    branch_id = conversation.get("active_branch") or "main"

    # --- resume path: reuse existing assistant placeholder ---
    if resume:
        message_id = resume["message_id"]
        stream_state.promote(reservation_id, message_id)
        stream_state.register(message_id, user_id=user_id)
        yield _sse("message_start", {
            "message_id": message_id,
            "conversation_id": nonlocal_conversation_id,
            "branch_id": branch_id,
            "resumed": True,
        })
        yield _sse("status", {
            "phase": "thinking",
            "conversation_id": nonlocal_conversation_id,
            "resumed": True,
        })
        formatted_messages = list(resume["tool_messages"] or [])
        # tool_messages already embed the system prompt from the first loop —
        # strip a leading system so we don't double-prepand below.
        while (
            formatted_messages
            and isinstance(formatted_messages[0], dict)
            and formatted_messages[0].get("role") == "system"
        ):
            formatted_messages.pop(0)
        # Append tool result for ask_user
        formatted_messages.append({
            "role": "tool",
            "tool_call_id": resume["tool_call_id"],
            "name": "ask_user",
            "content": resume["answer_text"],
        })
        # Keep pending_clarify + tool_messages until message_complete succeeds.
        # Clearing them here made a proxy drop unrecoverable (Retry → 400
        # "No pending clarification" with no way to re-run image gen).
        if hasattr(MessageModel, "merge_metadata"):
            MessageModel.merge_metadata(message_id, {
                "resume_in_progress": True,
            })
    else:
        user_meta = {}
        if dlp_badge:
            user_meta["dlp_redacted"] = dlp_badge
        # Retry after silent drop: last row is same user text (optionally
        # followed by incomplete assistant) — reuse, don't duplicate.
        user_message = None
        try:
            recent = MessageModel.get_context_messages(
                nonlocal_conversation_id, limit=4, branch_id=branch_id,
            ) or []
            content_key = (message_content or "").strip()
            if recent and content_key:
                last = recent[-1]
                last_role = last.get("role")
                last_content = (last.get("content") or "").strip()
                if last_role == "user" and last_content == content_key:
                    user_message = last
                elif last_role == "assistant" and len(recent) >= 2:
                    meta_l = last.get("metadata") or {}
                    fr = meta_l.get("finish_reason")
                    incomplete = fr in ("cancelled", "error") or not last_content
                    prev = recent[-2]
                    if (
                        incomplete
                        and prev.get("role") == "user"
                        and (prev.get("content") or "").strip() == content_key
                    ):
                        user_message = prev
        except Exception:  # noqa: BLE001
            user_message = None
        if not user_message:
            user_message = MessageModel.create_user_message(
                conversation_id=nonlocal_conversation_id,
                content=message_content,
                attachments=attachments,
                branch_id=branch_id,
                metadata=(user_meta or None),
                sender_user_id=user_id,
            )
        yield _sse("message_saved", {
            "message": serialize_doc(user_message),
            "conversation_id": nonlocal_conversation_id,
            "branch_id": branch_id,
        })

        context_messages = MessageModel.get_context_messages(
            nonlocal_conversation_id, limit=20, branch_id=branch_id,
        )
        # Strip tabular/data attachments from prompt when sandbox will hold them
        if include_python:
            for idx in range(len(context_messages)):
                cm = context_messages[idx]
                if cm.get("role") != "user":
                    continue
                kept = [
                    a for a in (cm.get("attachments") or [])
                    if not is_data_attachment(a)
                ]
                if len(kept) != len(cm.get("attachments") or []):
                    cm = dict(cm)
                    cm["attachments"] = kept
                    context_messages[idx] = cm
            append_artifact_recaps(context_messages)

        owner_id = str(conversation.get("user_id") or user_id)
        fmt = OpenRouterService.format_messages_for_api_ex(
            context_messages, user_id=owner_id,
        )
        formatted_messages = fmt["messages"]
        req_plugins = list(fmt.get("plugins") or [])
        if fmt.get("has_native_pdf"):
            engine = settings.get("PDF_OCR_ENGINE", "mistral-ocr")
            req_plugins.append({"id": "file-parser", "pdf": {"engine": engine}})
        else:
            req_plugins = None

        assistant_message = MessageModel.create(
            conversation_id=nonlocal_conversation_id,
            role="assistant",
            content="",
            metadata={"model_id": model_id, "intent": "agent"},
            branch_id=branch_id,
        )
        message_id = str(assistant_message["_id"])
        stream_state.promote(reservation_id, message_id)
        stream_state.register(message_id, user_id=user_id)
        yield _sse("message_start", {
            "message_id": message_id,
            "conversation_id": nonlocal_conversation_id,
            "branch_id": branch_id,
        })

    # system prompt (+ wall-clock so "latest news" is not 2024/25 memory)
    ai_prefs = user.get("ai_preferences") or {}
    system_prompt = OpenRouterService.build_enhanced_system_prompt(
        AGENT_ORCHESTRATOR_PROMPT + asvc.current_time_block(),
        ai_prefs,
        model_id=model_id,
        include_identity=False,
    )
    agent_web_params = asvc.web_search_params()

    frame_q: "queue.Queue" = queue.Queue()
    steps: list = []
    all_artifacts: list = []
    image_artifacts: list = []
    loop_result_box: dict = {}
    file_dedupe: dict = {}
    workdir = None
    ctx: dict = {}

    # Dataset prep (optional)
    sandbox_ok = False
    SandboxService = None
    if include_python:
        try:
            from app.services.sandbox_service import SandboxService as _SS
            from app.services.data_analysis_service import prepare_dataset
            SandboxService = _SS
            sandbox_ok = bool(SandboxService.available())
        except Exception as e:  # noqa: BLE001
            logger.warning("agent sandbox unavailable: %s", e)
            sandbox_ok = False
            prepare_dataset = None  # type: ignore

        if sandbox_ok and prepare_dataset is not None and not resume:
            prep_box: dict = {}

            def _status_cb(ev: dict) -> None:
                frame_q.put(_sse("data_status", {
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
                    frame_q.put(_LOOP_DONE)

            t = threading.Thread(target=_run_prepare, name="agent-prep", daemon=True)
            t.start()
            while True:
                if stop_event.is_set():
                    break
                try:
                    frame = frame_q.get(timeout=1.0)
                except queue.Empty:
                    if time.time() - last_yield >= _KEEPALIVE_INTERVAL:
                        yield ": keepalive\n\n"
                        last_yield = time.time()
                    continue
                if frame is _LOOP_DONE:
                    break
                yield frame
                last_yield = time.time()
            t.join(timeout=5)
            if prep_box.get("error"):
                logger.warning("agent prepare_dataset failed: %s", prep_box["error"])
            ctx = prep_box.get("ctx") or {}
            workdir = ctx.get("workdir")
            preview = ctx.get("preview_markdown") or ""
            if preview or workdir:
                from app.prompts.data_analyst import SANDBOX_PYTHON_RULES
                system_prompt = (
                    system_prompt
                    + "\n\n"
                    + SANDBOX_PYTHON_RULES
                    + (("\n\n## Dataset preview\n" + preview) if preview else "")
                )
        elif sandbox_ok and resume:
            # Resume: try re-prepare from empty attachments (workdir may exist via conv)
            try:
                from app.services.data_analysis_service import prepare_dataset as _pd
                ctx = _pd(
                    user_id=user_id,
                    conversation_id=nonlocal_conversation_id,
                    attachments=[],
                    workspace_id=ws_id_s,
                    project_id=proj_id_s,
                    stop_event=stop_event,
                ) or {}
                workdir = ctx.get("workdir")
                preview = ctx.get("preview_markdown") or ""
                if preview or workdir:
                    from app.prompts.data_analyst import SANDBOX_PYTHON_RULES
                    system_prompt = (
                        system_prompt
                        + "\n\n"
                        + SANDBOX_PYTHON_RULES
                        + (("\n\n## Dataset preview\n" + preview) if preview else "")
                    )
            except Exception as e:  # noqa: BLE001
                logger.warning("agent resume dataset: %s", e)

    # Only expose run_python when a real workdir is ready — otherwise the model
    # wastes rounds calling a tool that always errors.
    has_data = bool(workdir)
    tools = asvc.build_agent_tools(include_run_python=has_data)
    reasoning = asvc.reasoning_effort()

    # Early status so FE can show thinking (not "analyzing data").
    yield _sse("status", {
        "phase": "thinking",
        "conversation_id": nonlocal_conversation_id,
        "has_data": has_data,
    })

    db.session.remove()

    def _tool_executor(name: str, args: dict) -> str:
        step_no = len(steps) + 1
        args = args or {}

        if name == "ask_user":
            questions = asvc.normalize_questions(args.get("questions"))
            if not questions:
                return "[tool error] ask_user requires at least one question"
            frame_q.put(_sse("tool_call", {
                "step": step_no, "name": "ask_user", "questions": questions,
            }))
            raise ToolLoopPause({
                "questions": questions,
                "step": step_no,
            })

        if name == "generate_image":
            # Hard cap: 2 successful gens per turn (soft prompt alone was ignored).
            n_ok_so_far = sum(
                1 for s in steps
                if isinstance(s, dict) and s.get("name") == "generate_image" and s.get("ok")
            )
            if n_ok_so_far >= 2:
                return (
                    "[tool error] Image limit reached for this turn (2). "
                    "Do NOT call generate_image again. Write a short caption only."
                )
            prompt = (args.get("prompt") or "").strip()
            if not prompt:
                return "[tool error] prompt required"
            aspect = args.get("aspect_ratio") or None
            frame_q.put(_sse("tool_call", {
                "step": step_no, "name": "generate_image", "prompt": prompt[:200],
            }))
            frame_q.put(_sse("status", {
                "phase": "generating_image",
                "prompt": prompt[:120],
                "conversation_id": nonlocal_conversation_id,
            }))
            try:
                spend_gate.gate(
                    user_id=user_id,
                    workspace_id=ws_id_s,
                    project_id=proj_id_s,
                    origin="web",
                    feature=_FEATURE,
                )
            except spend_gate.BudgetExceededError as exc:
                err = f"budget exceeded ({exc.scope})"
                frame_q.put(_sse("tool_result", {
                    "step": step_no, "name": "generate_image", "error": err,
                }))
                return f"[tool error] {err}"

            try:
                res = OpenRouterService.generate_image(
                    prompt=prompt,
                    model=asvc.image_model(),
                    aspect_ratio=aspect,
                    n=1,
                    user_id=user_id,
                    conversation_id=nonlocal_conversation_id,
                    feature=_FEATURE,
                    workspace_id=ws_id_s,
                    project_id=proj_id_s,
                    origin="web",
                )
            except Exception as exc:  # noqa: BLE001
                err = str(exc)[:400] or "image generation failed"
                logger.warning("agent generate_image crashed: %s", exc, exc_info=True)
                frame_q.put(_sse("tool_result", {
                    "step": step_no, "name": "generate_image", "error": err,
                }))
                return f"[tool error] {err}"

            if not res.get("success"):
                err = res.get("error") or "image generation failed"
                logger.warning(
                    "agent generate_image failed model=%s err=%s",
                    asvc.image_model(), err,
                )
                frame_q.put(_sse("tool_result", {
                    "step": step_no, "name": "generate_image", "error": err,
                }))
                # Hint model to rewrite prompt (Gemini IMAGE_RECITATION / safety).
                return (
                    f"[tool error] {err}. "
                    "Rewrite the prompt (avoid logos/text/recitation-like "
                    "content) and call generate_image again."
                )

            img_data = res.get("image_data") or (res.get("images") or [None])[0]
            if not img_data or not isinstance(img_data, str):
                err = "image generation returned empty payload"
                frame_q.put(_sse("tool_result", {
                    "step": step_no, "name": "generate_image", "error": err,
                }))
                return f"[tool error] {err}"
            if not img_data.startswith("data:image"):
                err = "image generation returned unsupported payload (expected data URI)"
                frame_q.put(_sse("tool_result", {
                    "step": step_no, "name": "generate_image", "error": err,
                }))
                return f"[tool error] {err}"

            try:
                # generated_images.conversation_id FK → image_conversations ONLY
                # (Image Studio threads). Agent chat ids live in `conversations`
                # and MUST NOT be passed here — that FK violation ate a successful
                # OpenRouter image and returned "[tool error]" to the model.
                # Keep the agent chat id in metadata for audit/trace.
                row = GeneratedImageModel.create(
                    user_id=user_id,
                    prompt=prompt,
                    model_id=asvc.image_model(),
                    image_data=img_data,
                    settings={"aspect_ratio": aspect, "source": "agent"},
                    metadata={
                        "agent": True,
                        "agent_conversation_id": nonlocal_conversation_id,
                    },
                    conversation_id=None,
                )
            except Exception as exc:  # noqa: BLE001
                err = f"failed to save image: {exc}"[:400]
                logger.warning("agent image persist failed: %s", exc, exc_info=True)
                frame_q.put(_sse("tool_result", {
                    "step": step_no, "name": "generate_image", "error": err,
                }))
                return f"[tool error] {err}"

            img_id = str(row.get("_id") or row.get("id") or "")
            thumb = row.get("thumb_b64") or row.get("thumb")
            # /file = raw image/* bytes for <img src>; /{id} alone is JSON (Studio).
            media_url = f"/api/image-gen/{img_id}/file" if img_id else None
            art = {
                "type": "image",
                "id": img_id,
                "prompt": prompt,
                # FE can load full image via image-gen /file; thumb for inline.
                # Model returns `thumb` (not thumb_b64) from _image_to_dict.
                "thumb_b64": thumb,
                "thumb": thumb,
                "url": media_url,
            }
            image_artifacts.append(art)
            all_artifacts.append(art)
            steps.append({"step": step_no, "name": "generate_image", "ok": True})
            frame_q.put(_sse("tool_result", {
                "step": step_no, "name": "generate_image", "artifacts": [art],
            }))
            frame_q.put(_sse("artifact", art))
            # Stream the image into the live assistant turn immediately so the
            # user is not stuck staring at thinking-dots while the model writes
            # a caption (or while the next completion is slow).
            if art.get("url"):
                alt = (prompt or "image").replace("\n", " ").replace("]", "")[:80]
                frame_q.put(_sse("message_chunk", {
                    "message_id": message_id,
                    "conversation_id": nonlocal_conversation_id,
                    "content": f"\n\n![{alt}]({art['url']})\n\n",
                }))
            frame_q.put(_sse("status", {
                "phase": "finishing",
                "conversation_id": nonlocal_conversation_id,
            }))
            n_ok = sum(
                1 for s in steps
                if isinstance(s, dict) and s.get("name") == "generate_image" and s.get("ok")
            )
            extra = ""
            if n_ok >= 2:
                extra = (
                    " You already generated enough images for this turn. "
                    "Do NOT call generate_image again. Write a short caption only."
                )
            return asvc.dump_json({
                "ok": True,
                "image_id": img_id,
                "url": art.get("url"),
                "note": (
                    "Image generated and ALREADY shown to the user in the chat UI. "
                    "Reply with a brief caption in the user's language. "
                    "Do not claim you cannot show images."
                    + extra
                ),
            })

        if name == "run_python":
            code = args.get("code") or ""
            frame_q.put(_sse("tool_call", {
                "step": step_no, "name": "run_python", "code": code[:500],
            }))
            if not workdir or SandboxService is None:
                err = "no dataset prepared for this conversation"
                frame_q.put(_sse("tool_result", {
                    "step": step_no, "name": "run_python", "error": err,
                }))
                return f"[tool error] {err}"
            try:
                spend_gate.gate(
                    user_id=user_id,
                    workspace_id=ws_id_s,
                    project_id=proj_id_s,
                    origin="web",
                    feature=_FEATURE,
                )
            except spend_gate.BudgetExceededError as exc:
                err = f"budget exceeded ({exc.scope})"
                frame_q.put(_sse("tool_result", {
                    "step": step_no, "name": "run_python", "error": err,
                }))
                return f"[tool error] {err}"

            result = SandboxService.run(
                workdir=workdir,
                code=code,
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
            artifacts = [
                a for a in (result.get("artifacts") or []) if isinstance(a, dict)
            ]
            artifacts = persist_file_artifacts(
                artifacts, workdir=workdir, user_id=user_id, dedupe=file_dedupe,
            )
            all_artifacts.extend(artifacts)
            steps.append({
                "step": step_no,
                "name": "run_python",
                "code": code,
                "error": result.get("error"),
            })
            frame_q.put(_sse("tool_result", {
                "step": step_no,
                "name": "run_python",
                "stdout": (result.get("stdout") or "")[:2000],
                "error": result.get("error"),
                "artifacts": artifacts,
            }))
            for a in artifacts:
                frame_q.put(_sse("artifact", a))
            result["artifacts"] = artifacts
            return format_tool_result_for_model(
                result, manifest=ctx.get("manifest"),
            )

        # Server tools (subagent/web) are executed by OpenRouter — client should
        # not receive function tool_calls for them. If a model invents a name:
        return f"[tool error] unknown tool {name!r}"

    def _loop_status_cb(ev: dict) -> None:
        """Surface server-tool activity (web_search / web_fetch) to the FE."""
        if not isinstance(ev, dict):
            return
        phase = ev.get("phase")
        if not phase:
            return
        # Persist web steps so reload keeps the timeline (not only live chips).
        if phase in ("web_search", "web_fetch"):
            if not any(
                isinstance(s, dict) and s.get("name") == phase and s.get("ok")
                for s in steps
            ):
                steps.append({
                    "step": len(steps) + 1,
                    "name": phase,
                    "ok": True,
                })
        frame_q.put(_sse("status", {
            "phase": phase,
            "conversation_id": nonlocal_conversation_id,
            **{k: v for k, v in ev.items() if k != "phase"},
        }))

    def _run_loop():
        try:
            with db.session_scope():
                loop_result_box["result"] = OpenRouterService.run_tool_loop(
                    model=model_id,
                    messages=formatted_messages,
                    tools=tools,
                    tool_executor=_tool_executor,
                    system_prompt=system_prompt,
                    max_rounds=asvc.max_rounds(),
                    temperature=_AGENT_TEMPERATURE,
                    max_tokens=32000,
                    reasoning_effort=reasoning,
                    user_id=user_id,
                    conversation_id=nonlocal_conversation_id,
                    feature=_FEATURE,
                    workspace_id=ws_id_s,
                    project_id=proj_id_s,
                    origin="web",
                    stop_event=stop_event,
                    web_search=True,
                    web_fetch=True,
                    web_search_params=agent_web_params,
                    on_status=_loop_status_cb,
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("agent tool loop crashed: %s", e, exc_info=True)
            loop_result_box["error"] = str(e)
        finally:
            frame_q.put(_LOOP_DONE)

    loop_thread = threading.Thread(
        target=_run_loop, name="agent-loop", daemon=True,
    )
    loop_thread.start()

    try:
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
                    stop_event.set()
                    break
                continue
            if frame is _LOOP_DONE:
                break
            yield frame
            last_yield = time.time()
    finally:
        # Allow in-flight image gen / OR round to finish writing artifacts
        # before we invent an empty "no answer" body (was join 5s → race).
        join_s = 30.0 if stop_event.is_set() else 10.0
        loop_thread.join(timeout=join_s)

    loop_result = loop_result_box.get("result") or {}
    loop_error = loop_result_box.get("error") or loop_result.get("error")
    was_cancelled = bool(stop_event.is_set()) and loop_result.get("finish_reason") != "clarify"

    # --- clarify pause ---
    if loop_result.get("finish_reason") == "clarify":
        questions = (loop_result.get("pause") or {}).get("questions") or []
        tool_call_id = loop_result.get("pending_tool_call_id")
        tool_messages = list(loop_result.get("messages") or [])
        # Drop leading system from stored history (run_tool_loop embeds it;
        # resume path re-applies AGENT_ORCHESTRATOR_PROMPT).
        while (
            tool_messages
            and isinstance(tool_messages[0], dict)
            and tool_messages[0].get("role") == "system"
        ):
            tool_messages.pop(0)
        MessageModel.update_content_and_metadata(
            message_id,
            "",  # no final text yet
            {
                "model_id": model_id,
                "intent": "agent",
                "finish_reason": "clarify",
                "pending_clarify": {
                    "questions": questions,
                    "tool_call_id": tool_call_id,
                    "created_at": time.time(),
                },
                "tool_messages": tool_messages,
                "agent_has_data": has_data,
                "agent_steps": steps,
                "agent_artifacts": all_artifacts,
            },
        )
        stream_state.clear(message_id)
        yield _sse("clarify", {
            "conversation_id": nonlocal_conversation_id,
            "message_id": message_id,
            "questions": questions,
        })
        yield _sse("done", {
            "conversation_id": nonlocal_conversation_id,
            "message_id": message_id,
            "status": "clarify",
        })
        return

    # --- narration ---
    full_content = ""
    finish_reason = "stop"
    loop_content = (loop_result.get("content") or "").strip()
    loop_capped = bool(loop_result.get("capped"))
    narration_msgs = loop_result.get("messages")
    narration_system = None if narration_msgs else system_prompt
    narration_msgs = narration_msgs or formatted_messages

    if not loop_error and not loop_capped and loop_content:
        for i in range(0, len(loop_content), 80):
            if stop_event.is_set():
                finish_reason = "cancelled"
                break
            piece = loop_content[i:i + 80]
            full_content += piece
            yield _sse("message_chunk", {
                "message_id": message_id,
                "content": piece,
                "conversation_id": nonlocal_conversation_id,
            })
            last_yield = time.time()
    elif not loop_error:
        try:
            if loop_capped:
                narration_msgs = list(narration_msgs) + [{
                    "role": "system",
                    "content": (
                        "You reached the tool-round limit. Finish with what you "
                        "already know. Do not call more tools."
                    ),
                }]
            # Narration: no reasoning effort — Gemini often returns empty
            # content with only reasoning when effort is set.
            stream = OpenRouterService.chat_completion(
                messages=narration_msgs,
                model=model_id,
                system_prompt=narration_system,
                temperature=_AGENT_TEMPERATURE,
                max_tokens=32000,
                stream=True,
                reasoning_effort=None,
                user_id=user_id,
                conversation_id=nonlocal_conversation_id,
                feature=_FEATURE,
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
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                content = delta.get("content") or ""
                if content:
                    full_content += content
                    yield _sse("message_chunk", {
                        "message_id": message_id,
                        "content": content,
                        "conversation_id": nonlocal_conversation_id,
                    })
                    last_yield = time.time()
                if choices[0].get("finish_reason"):
                    finish_reason = choices[0]["finish_reason"]
        except Exception as e:  # noqa: BLE001
            loop_error = str(e)

    if not full_content:
        full_content = (loop_result.get("content") or "").strip()
    if not full_content and not loop_error:
        # Last resort: model returned empty content (common with reasoning-only
        # Gemini turns). Force one short non-reasoning completion.
        try:
            rescue = OpenRouterService.chat_completion(
                messages=(narration_msgs or formatted_messages) + [
                    {
                        "role": "user",
                        "content": (
                            "Please give your final answer to the user now in "
                            "their language. Do not call tools."
                        ),
                    }
                ],
                model=model_id,
                temperature=_AGENT_TEMPERATURE,
                max_tokens=4000,
                stream=False,
                reasoning_effort=None,
                user_id=user_id,
                conversation_id=nonlocal_conversation_id,
                feature=_FEATURE,
                workspace_id=ws_id_s,
                project_id=proj_id_s,
                origin="web",
            )
            if isinstance(rescue, dict) and not rescue.get("error"):
                rmsg = ((rescue.get("choices") or [{}])[0].get("message") or {})
                full_content = OpenRouterService._message_text(rmsg)
        except Exception as e:  # noqa: BLE001
            logger.warning("agent rescue narration failed: %s", e)
    img_arts = [a for a in all_artifacts if isinstance(a, dict) and a.get("type") == "image"]

    if not full_content:
        if img_arts:
            # Image already delivered via SSE — don't fail the turn empty.
            full_content = "تصویر آماده است."
        elif was_cancelled:
            full_content = "درخواست لغو شد."
            finish_reason = "cancelled"
        elif loop_error:
            err_s = str(loop_error)
            if "ProxyError" in err_s or "proxy" in err_s.lower() or "Max retries" in err_s:
                full_content = (
                    "اتصال به سرویس هوش مصنوعی موقتاً قطع شد (خروجی شبکه). "
                    "لطفاً چند ثانیه بعد دوباره تلاش کنید."
                )
            else:
                full_content = (
                    "متأسفانه انجام این کار با خطا روبه‌رو شد. "
                    f"جزئیات: {err_s[:240]}"
                )
            finish_reason = "error"
        else:
            full_content = "پاسخی تولید نشد. لطفاً دوباره پیام بفرستید."

    if was_cancelled and finish_reason not in ("clarify",):
        finish_reason = "cancelled"

    # Durable image display: embed markdown so the transcript shows the image
    # even if the FE artifact strip fails to hydrate.
    # URL must be /file (raw image/*) — plain /{id} is JSON and breaks <img>.
    if img_arts:
        md_parts = []
        for a in img_arts:
            aid = a.get("id")
            url = a.get("url")
            if not url and aid:
                url = f"/api/image-gen/{aid}/file"
            elif url and aid and url.rstrip("/").endswith(str(aid)):
                # Legacy artifact shape without /file suffix.
                url = f"/api/image-gen/{aid}/file"
            if not url:
                continue
            # Skip if this URL was already streamed/written into the body.
            if url in full_content:
                continue
            alt = (a.get("prompt") or "image").replace("\n", " ").strip()[:120] or "image"
            # Same-origin path — MarkdownRenderer + browser send cookies.
            md_parts.append(f"![{alt}]({url})")
        if md_parts:
            full_content = (full_content.rstrip() + "\n\n" + "\n\n".join(md_parts)).strip()

    stream_state.clear(message_id)
    if all_artifacts:
        try:
            all_artifacts = prune_dead_file_artifacts(all_artifacts, file_dedupe)
        except Exception:  # noqa: BLE001
            pass

    annotations = loop_result.get("annotations") or None
    if isinstance(annotations, list) and not annotations:
        annotations = None
    used_web = bool(loop_result.get("used_web"))
    # Only put python-shaped steps into data_artifacts (DataAnalysisBlock).
    python_steps = [
        s for s in steps
        if isinstance(s, dict) and (
            s.get("name") == "run_python" or s.get("code")
        )
    ]
    meta_out = {
        "model_id": model_id,
        "intent": "agent",
        "finish_reason": finish_reason,
        "agent_steps": steps,
        "agent_artifacts": all_artifacts,
        "data_artifacts": {
            "steps": python_steps,
            "artifacts": [
                a for a in all_artifacts if a.get("type") != "image"
            ],
        },
        # Terminal success: drop clarify resume state for good.
        "pending_clarify": None,
        "tool_messages": None,
        "resume_in_progress": None,
        "used_web": used_web,
    }
    if annotations:
        meta_out["annotations"] = annotations

    MessageModel.update_content_and_metadata(
        message_id,
        full_content,
        meta_out,
    )
    ConversationModel.increment_message_count(nonlocal_conversation_id)

    # Complete the turn FIRST so the client can drop isStreaming / typing
    # chrome. Title polish used to run BEFORE these frames and blocked the
    # SSE close while OpenRouter hung — FE stayed in "thinking" forever.
    yield _sse("message_complete", {
        "message_id": message_id,
        "conversation_id": nonlocal_conversation_id,
        "content": full_content,
        "artifacts": all_artifacts,
        "steps": steps,
        "annotations": annotations,
        "used_web": used_web,
    })
    yield _sse("done", {
        "conversation_id": nonlocal_conversation_id,
        "message_id": message_id,
        "status": "ok",
    })

    if is_new and message_content and not stop_event.is_set():
        # Best-effort title after the client is unblocked.
        try:
            with db.session_scope():
                better = OpenRouterService.generate_title(
                    message_content,
                    user_id=user_id,
                    conversation_id=nonlocal_conversation_id,
                    workspace_id=ws_id_s,
                    project_id=proj_id_s,
                    origin="web",
                )
                if better:
                    ConversationModel.update_title(nonlocal_conversation_id, better)
                    yield _sse("title_updated", {
                        "conversation_id": nonlocal_conversation_id,
                        "title": better,
                    })
        except Exception:  # noqa: BLE001
            pass

