"""Health check routes mounted at ``/api/v1``.

``/health/check`` = cheap pong; ``/health/status`` = PG + OpenRouter (always 200).
"""
from __future__ import annotations

import logging
import os
import time

from fastapi import APIRouter, Depends

from app.api.core import db, flask_core
from app.api.deps import flask_ctx

logger = logging.getLogger(__name__)

health_router = APIRouter(dependencies=[Depends(flask_ctx)])

_OPENROUTER_PING_URL = "https://openrouter.ai/api/v1/models"
# Direct OR is fast; via prod HTTPS_PROXY tunnel allow headroom under load.
_OPENROUTER_TIMEOUT_S = 10


@health_router.get("/health/check")
def health_check():
    """Pong. Cheap, no deps. Compose healthcheck hits this."""
    return {
        "status": "ok",
        "version": os.environ.get("VERSION_CODE"),
        "commit": os.environ.get("COMMIT_ID"),
    }


@health_router.get("/health/status")
def health_status():
    """Deep status — checks Postgres + OpenRouter. Always HTTP 200, public.

    Public + always-200 by contract so Swarm/edge monitoring never kills the app
    on a transient blip. Dependency results are reduced to ``ok``/latency only —
    raw exception text is NOT reflected to anonymous callers (info-leak guard);
    full error detail is logged server-side.
    """
    from sqlalchemy import text

    deps: dict[str, dict] = {}
    overall_ok = True

    t0 = time.monotonic()
    try:
        db.session.execute(text("SELECT 1")).scalar()
        deps["postgres"] = {"ok": True, "latency_ms": int((time.monotonic() - t0) * 1000)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("health_status: postgres check failed")
        deps["postgres"] = {"ok": False}
        overall_ok = False

    t0 = time.monotonic()
    try:
        # Same chokepoint as all LLM traffic: direct IPv4 (Begzar/hosts) unless
        # OPENROUTER_USE_PROXY=1. Do NOT use bare requests.get (misses IPv4 pin).
        from app.services.openrouter_service import OpenRouterService

        api_key = flask_core.config.get("OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        r = OpenRouterService._request(
            "GET",
            _OPENROUTER_PING_URL,
            headers=headers,
            timeout=_OPENROUTER_TIMEOUT_S,
        )
        deps["openrouter"] = {
            "ok": r.status_code == 200,
            "status_code": r.status_code,
            "latency_ms": int((time.monotonic() - t0) * 1000),
        }
        if r.status_code != 200:
            overall_ok = False
    except Exception:  # noqa: BLE001
        logger.exception("health_status: openrouter check failed")
        deps["openrouter"] = {"ok": False}
        overall_ok = False

    return {
        "status": "ok" if overall_ok else "degraded",
        "version": os.environ.get("VERSION_CODE"),
        "commit": os.environ.get("COMMIT_ID"),
        "dependencies": deps,
    }


__all__ = ["health_router"]
