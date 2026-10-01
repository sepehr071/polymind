"""Meetings + meeting-series routers, translated from app/routes/meetings.py
and app/routes/meeting_series.py.

Two routers, mirroring the two Flask blueprints / url_prefixes:
  * ``router``        -> mounted at ``/api/meetings``
  * ``series_router`` -> mounted at ``/api/meeting-series``

Both carry router-level ``Depends(flask_ctx)`` so every request runs inside one
Flask app_context (all existing models + services are reused VERBATIM). The
auth/active/feature decorator stack from the Flask routes maps to FastAPI
``Depends`` gates: ``@jwt_required()`` -> ``Depends(current_user)``,
``@active_user_required`` -> ``Depends(require_active)``,
``@feature_required('meetings')`` -> ``Depends(feature_dep('meetings'))``.

HIGHEST RISK route = ``POST /upload``: a multipart 500MB upload. Starlette's
``UploadFile`` exposes a sync ``SpooledTemporaryFile`` at ``file.file``; that is
fed UNCHANGED into ``meeting_storage.save_audio_stream`` (the same 1 MB-chunked,
``max_bytes``-capped writer the Flask path used), preserving the
``AudioTooLargeError`` -> 413 contract. The background ``_dispatch_pipeline``
daemon thread is kept verbatim.

The ``GET /<id>/stream`` SSE endpoint is a poll-loop: the ``flask_ctx`` context
is gone once the handler returns, so the generator opens its OWN Flask context
per poll (mirroring the Flask route's ``with app.app_context()`` blocks) and
removes the session on exit.

Package re-exports keep monofile test monkeypatches working:
``import app.api.routers.meetings as meetings_router`` + setattr on helpers /
service modules / ``time`` / ``MeetingModel``. Dispatch call sites look up
``_common._dispatch_*`` at call time so package-or-_common patches take effect.
"""
from __future__ import annotations

import time

from app.models.meeting import MeetingModel
from app.services import meeting_glossary, meeting_storage, meetings_pipeline

from ._common import (
    _dispatch_pipeline,
    _dispatch_regenerate,
    _run_in_ctx,
    _serialize_meeting,
    _serialize_summary,
    _serialize_transcript,
    router,
    series_router,
)
from .artifacts import _render_artifact
from . import action_pack, artifacts, crud, series, stream  # noqa: F401 — register routes
from . import _common  # noqa: F401 — tests patch ``meetings_router._common.*``

__all__ = [
    "router",
    "series_router",
    "_common",
    "_dispatch_pipeline",
    "_dispatch_regenerate",
    "_run_in_ctx",
    "_serialize_meeting",
    "_serialize_summary",
    "_serialize_transcript",
    "_render_artifact",
    "MeetingModel",
    "meeting_glossary",
    "meeting_storage",
    "meetings_pipeline",
    "time",
]
