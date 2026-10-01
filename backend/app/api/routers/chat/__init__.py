"""Chat routes package (was a single fat ``chat.py``).

``from app.api.routers.chat import router`` still works. Helpers used by tests
are re-exported under their historical private names.
"""
from __future__ import annotations

from app.services.chat_attachments import (
    filter_owned_attachments as _filter_owned_attachments,
    is_data_attachment as _is_data_attachment,
    attachment_text_for_dlp as _attachment_text_for_dlp,
)
from app.services.chat_artifacts import (
    append_artifact_recaps as _append_artifact_recaps,
    format_tool_result_for_model as _format_tool_result_for_model,
    persist_file_artifacts as _persist_file_artifacts,
    prune_dead_file_artifacts as _prune_dead_file_artifacts,
    summarize_artifacts as _summarize_artifacts,
)

from ._common import router

# Side-effect imports: register routes on the shared router.
from . import send as _send  # noqa: F401
from . import messages as _messages  # noqa: F401
from . import regenerate as _regenerate  # noqa: F401
from . import stream as _stream  # noqa: F401
from . import titles as _titles  # noqa: F401
from . import data_path as _data_path  # noqa: F401

__all__ = [
    "router",
    "_filter_owned_attachments",
    "_is_data_attachment",
    "_attachment_text_for_dlp",
    "_append_artifact_recaps",
    "_format_tool_result_for_model",
    "_persist_file_artifacts",
    "_prune_dead_file_artifacts",
    "_summarize_artifacts",
]
