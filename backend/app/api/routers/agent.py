"""All-in-one router agent — /api/agent.

  * POST /stream          — SSE: new or continuing agent turn
  * POST /{id}/clarify    — SSE: resume after ask_user answers
  * GET  /                — list kind=agent conversations (thin wrapper)

DLP + spend run in the handler before SSE. Tool-loop producer lives in
``app.services.agent_turn.produce_agent_turn``.
"""
from __future__ import annotations

import logging
from typing import Optional

import anyio.to_thread
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.deps import current_user, feature_dep, flask_ctx, require_active
from app.api.sse import sse_stream_sync
from app.models.conversation import ConversationModel
from app.models.message import MessageModel
from app.services import agent_service as asvc
from app.services import spend_gate, stream_concurrency
from app.services.agent_turn import produce_agent_turn
from app.services.chat_attachments import (
    attachment_text_for_dlp,
    filter_owned_attachments,
    is_data_attachment,
)
from app.services.dlp_gate import gate_redactable
from app.utils.helpers import serialize_doc
from app.utils.permissions import (
    WORKSPACE_ACCESS_DENIED,
    conversation_workspace_denied,
    resolve_conversation_access,
)

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(flask_ctx)])

_FEATURE = asvc.AGENT_FEATURE
_MAX_CONCURRENT_STREAMS = 3


async def _json_body(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def _uid(user) -> str:
    return str(user["_id"]) if isinstance(user, dict) else str(user.id)


def _filter_owned(attachments, user_id):
    return filter_owned_attachments(attachments, user_id)


def _attachment_text(attachments, user_id=None) -> str:
    return attachment_text_for_dlp(attachments, user_id=user_id)


def _thread_has_data_files(conversation_id: str, branch_id: str = "main") -> bool:
    """True if any recent user message in the thread carries data-like files."""
    try:
        msgs = MessageModel.get_context_messages(
            conversation_id, limit=20, branch_id=branch_id,
        )
    except Exception:  # noqa: BLE001
        return False
    for m in msgs or []:
        if m.get("role") != "user":
            continue
        atts = m.get("attachments") or []
        if asvc.needs_dataset(atts):
            return True
        for a in atts:
            if isinstance(a, dict) and is_data_attachment(a):
                return True
    return False


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------
@router.get("")
async def list_agent_conversations(
    request: Request,
    user: dict = Depends(require_active),
    _feat=Depends(feature_dep("agent")),
):
    user_id = _uid(user)
    try:
        skip = max(0, int(request.query_params.get("skip") or 0))
        limit = min(50, max(1, int(request.query_params.get("limit") or 20)))
    except (TypeError, ValueError):
        skip, limit = 0, 20
    search = (request.query_params.get("search") or "").strip() or None
    from app.api.routers.conversations import _resolve_list_workspace

    workspace_id, err = _resolve_list_workspace(
        user, request.query_params.get("workspace_id")
    )
    if err:
        return err
    if workspace_id is None:
        return {"conversations": []}
    rows = ConversationModel.find_by_user(
        user_id, skip=skip, limit=limit, search=search, kind="agent",
        workspace_id=workspace_id,
    )
    return {"conversations": [serialize_doc(r) for r in rows]}


# ---------------------------------------------------------------------------
# Stream (new turn)
# ---------------------------------------------------------------------------
@router.post("/stream")
async def agent_stream(
    request: Request,
    user: dict = Depends(require_active),
    _feat=Depends(feature_dep("agent")),
):
    user_id = _uid(user)
    data = await _json_body(request)
    message_content = (data.get("message") or data.get("content") or "").strip()
    attachments = data.get("attachments") or []
    if not isinstance(attachments, list):
        attachments = []
    attachments = _filter_owned(attachments, user_id)
    conversation_id = data.get("conversation_id")
    if conversation_id is not None:
        conversation_id = str(conversation_id)

    if not message_content and not attachments:
        return JSONResponse({"error": "message required"}, status_code=400)

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

    with preflight:
        preflight_conv = None
        if conversation_id:
            preflight_conv = ConversationModel.find_by_id(
                conversation_id, include_branches=False,
            )
            role, acc_err = resolve_conversation_access(preflight_conv, user_id, "viewer")
            if acc_err:
                msg, status = acc_err
                return JSONResponse({"error": msg, "status": status}, status_code=status)
            if conversation_workspace_denied(preflight_conv, user):
                return JSONResponse(dict(WORKSPACE_ACCESS_DENIED), status_code=403)
            if preflight_conv.get("kind") != "agent":
                return JSONResponse(
                    {"error": "Not an agent conversation", "status": 400},
                    status_code=400,
                )

        ws_id = (
            (preflight_conv or {}).get("workspace_id") or user.get("active_workspace_id")
        )
        proj_id = (
            preflight_conv.get("project_id") if preflight_conv else data.get("project_id")
        )
        ws_id_s = str(ws_id) if ws_id else None
        proj_id_s = str(proj_id) if proj_id else None

        att_text = _attachment_text(attachments, user_id=user["_id"])
        dlp_text = f"{message_content}\n\n{att_text}" if att_text else message_content
        user_lang = (data.get("lang") or "fa")[:8]
        confirmed = bool(data.get("dlp_confirmed"))
        confirm_token = data.get("dlp_confirm_token")

        def _gate():
            return gate_redactable(
                text=dlp_text,
                user_id=user["_id"],
                workspace_id=ws_id,
                project_id=proj_id,
                source="agent",
                source_ref={"feature": "agent"},
                force_redact=bool(data.get("dlp_redact")),
                confirmed=confirmed,
                dlp_confirm_token=confirm_token,
                user_lang=user_lang,
            )

        gate_res = await anyio.to_thread.run_sync(_gate)

        def _spend():
            spend_gate.gate(
                user_id=user_id,
                workspace_id=ws_id_s,
                project_id=proj_id_s,
                origin="web",
                feature=_FEATURE,
            )

        await anyio.to_thread.run_sync(_spend)

        dlp_badge = None
        if gate_res.get("redacted") and gate_res.get("redacted_text"):
            red = gate_res.get("redacted_text") or message_content
            if att_text and red.endswith(att_text):
                message_content = red[: -len(att_text)].rstrip()
            else:
                message_content = red.split("\n\n", 1)[0]
            dlp_badge = {
                "count": len(gate_res.get("redactions") or []) or 1,
                "labels": ["redacted"],
            }

        model_id = asvc.orchestrator_model()
        # Only spin the data sandbox when THIS turn attaches data-like files,
        # or (cheap check) the thread already has prior data attachments.
        # NEVER `or bool(conversation_id)` — that forced prepare_dataset +
        # "analyzing data" on every follow-up chat turn (slow + wrong chrome).
        include_python = asvc.needs_dataset(attachments)
        if not include_python and conversation_id:
            include_python = _thread_has_data_files(conversation_id)
        reservation_id = preflight.reservation_id

        def producer(stop_event):
            yield from produce_agent_turn(
                stop_event=stop_event,
                user=user,
                user_id=user_id,
                message_content=message_content,
                attachments=attachments,
                conversation_id=conversation_id,
                reservation_id=reservation_id,
                model_id=model_id,
                include_python=include_python,
                ws_id_s=ws_id_s,
                proj_id_s=proj_id_s,
                dlp_badge=dlp_badge,
                resume=None,
            )

        preflight.hand_off()
        return sse_stream_sync(
            producer,
            runner_name="agent-stream",
            on_close=preflight.on_close,
        )


# ---------------------------------------------------------------------------
# Clarify resume
# ---------------------------------------------------------------------------
@router.post("/{conversation_id}/clarify")
async def agent_clarify(
    conversation_id: str,
    request: Request,
    user: dict = Depends(require_active),
    _feat=Depends(feature_dep("agent")),
):
    user_id = _uid(user)
    data = await _json_body(request)
    answers = data.get("answers") if isinstance(data.get("answers"), dict) else {}

    conv = ConversationModel.find_by_id(conversation_id, include_branches=False)
    role, acc_err = resolve_conversation_access(conv, user_id, "viewer")
    if acc_err:
        msg, status = acc_err
        return JSONResponse({"error": msg, "status": status}, status_code=status)
    if conversation_workspace_denied(conv, user):
        return JSONResponse(dict(WORKSPACE_ACCESS_DENIED), status_code=403)
    if conv.get("kind") != "agent":
        return JSONResponse({"error": "Not an agent conversation"}, status_code=400)

    # Find latest assistant message with pending clarify (or interrupted resume
    # that still has tool_messages — allows Retry after a proxy drop).
    branch = conv.get("active_branch") or "main"
    msgs = MessageModel.get_context_messages(conversation_id, limit=5, branch_id=branch)
    pending_msg = None
    for m in reversed(msgs or []):
        meta = m.get("metadata") or {}
        if meta.get("pending_clarify") or (
            meta.get("tool_messages")
            and meta.get("finish_reason") == "clarify"
        ):
            pending_msg = m
            break
    if not pending_msg:
        return JSONResponse({"error": "No pending clarification"}, status_code=400)

    meta = pending_msg.get("metadata") or {}
    pending = meta.get("pending_clarify") or {}
    questions = pending.get("questions") or []
    tool_call_id = pending.get("tool_call_id")
    tool_messages = meta.get("tool_messages")
    if not tool_call_id or not isinstance(tool_messages, list):
        return JSONResponse({"error": "Invalid pending clarify state"}, status_code=400)
    # Concurrent double-submit: second resume while first still running.
    if meta.get("resume_in_progress"):
        return JSONResponse(
            {"error": "Clarify resume already in progress", "status": 409},
            status_code=409,
        )

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

    with preflight:
        ws_id = conv.get("workspace_id") or user.get("active_workspace_id")
        ws_id_s = str(ws_id) if ws_id else None
        proj_id = conv.get("project_id")
        proj_id_s = str(proj_id) if proj_id else None

        answer_text = asvc.format_answers_for_model(questions, answers)
        user_lang = (data.get("lang") or "fa")[:8]
        confirmed = bool(data.get("dlp_confirmed"))
        confirm_token = data.get("dlp_confirm_token")

        def _gate_answers():
            return gate_redactable(
                text=answer_text or "",
                user_id=user["_id"],
                workspace_id=ws_id,
                project_id=proj_id,
                source="agent",
                source_ref={"feature": "agent_clarify"},
                force_redact=bool(data.get("dlp_redact")),
                confirmed=confirmed,
                dlp_confirm_token=confirm_token,
                user_lang=user_lang,
            )

        gate_res = await anyio.to_thread.run_sync(_gate_answers)
        if gate_res.get("redacted") and gate_res.get("redacted_text"):
            answer_text = gate_res["redacted_text"]

        def _spend():
            spend_gate.gate(
                user_id=user_id,
                workspace_id=ws_id_s,
                project_id=proj_id_s,
                origin="web",
                feature=_FEATURE,
            )

        await anyio.to_thread.run_sync(_spend)

        resume = {
            "message_id": str(pending_msg.get("_id") or pending_msg.get("id")),
            "tool_messages": tool_messages,
            "tool_call_id": tool_call_id,
            "answer_text": answer_text,
            "include_python": bool(meta.get("agent_has_data")),
        }
        reservation_id = preflight.reservation_id

        def producer(stop_event):
            yield from produce_agent_turn(
                stop_event=stop_event,
                user=user,
                user_id=user_id,
                message_content="",
                attachments=[],
                conversation_id=conversation_id,
                reservation_id=reservation_id,
                model_id=asvc.orchestrator_model(),
                include_python=resume["include_python"],
                ws_id_s=ws_id_s,
                proj_id_s=proj_id_s,
                dlp_badge=None,
                resume=resume,
            )

        preflight.hand_off()
        return sse_stream_sync(
            producer,
            runner_name="agent-clarify",
            on_close=preflight.on_close,
        )
