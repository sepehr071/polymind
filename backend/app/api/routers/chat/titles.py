"""Background conversation title generation."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from app.api.core import db
from app.models.conversation import ConversationModel
from app.services.openrouter_service import OpenRouterService

from ._common import _logger

# Auto-title generation runs off the stream's runner thread so the user message
# turns blue immediately. A SHARED, bounded pool (NOT a fresh thread per new
# conversation) caps the concurrent title-LLM round-trips a burst of new chats
# can spawn — an unbounded ``threading.Thread`` per conversation could pile up
# threads + DB sessions under load. Daemon workers so process exit isn't blocked.
_TITLE_EXECUTOR = ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="chat-title"
)


def _generate_title_async(conv_id, message, orig_title, uid, ws_id, proj_id):
    """Best-effort background title refresh for a brand-new conversation.

    Runs on the shared ``_TITLE_EXECUTOR``. Opens its own contextvar-scoped DB
    session (``db.session_scope()`` — the same scope the old per-conversation
    thread entered via ``flask_core.app_context()``) for the LLM call + the title
    UPDATE, then tears it down. Fire-and-forget: failures are logged, never
    surfaced and never allowed to crash the worker.
    """
    try:
        with db.session_scope():
            better_title = OpenRouterService.generate_title(
                message,
                user_id=uid,
                conversation_id=conv_id,
                workspace_id=str(ws_id) if ws_id else None,
                project_id=str(proj_id) if proj_id else None,
                origin="web",
            )
            if better_title and better_title != orig_title:
                ConversationModel.update(conv_id, {"title": better_title})
    except Exception:  # noqa: BLE001 — fire-and-forget, must never raise
        _logger.exception("Title generation failed for conversation %s", conv_id)

