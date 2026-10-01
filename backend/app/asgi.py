"""FastAPI ("bridge") ASGI app — the parallel app for the Flask -> FastAPI
migration.

Run target: ``uvicorn app.asgi:app``. The legacy Flask app (``wsgi:app``) stays
deployable and is unaffected. This app reuses the Flask core (models + services)
verbatim by running every request inside a Flask app_context (see
``app.api.deps.flask_ctx``).
"""
from __future__ import annotations

import logging

import anyio
import anyio.to_thread
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware

from app.api.core import flask_core
from app.api.errors import install_exception_handlers
from app.api.routers import ALL_ROUTERS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Production secret-strength / CORS guard.
#
# ProductionConfig.validate() enforces SECRET_KEY + JWT_SECRET_KEY >= 32 chars
# and explicit CORS (or SAME_ORIGIN=1). It was historically only reachable from
# the dead legacy get_config() path, NOT from the live `gunicorn app.asgi:app`
# boot — so prod could boot with a weak JWT_SECRET_KEY (which also seeds the DLP
# confirm-token HMAC). Run it HERE so a missing/short secret is a HARD boot
# failure in prod.
#
# Gated STRICTLY on FLASK_ENV == "production": local dev + the pytest suite
# import the app on the base Config (no secrets required) and must keep booting.
# This only invokes the existing validation; it does NOT repoint `settings` at
# ProductionConfig, so prod CORS/cookie behavior is unchanged.
# ---------------------------------------------------------------------------
def _validate_production_config() -> None:
    import os

    if os.environ.get("FLASK_ENV") != "production":
        return
    from app.config import ProductionConfig

    ProductionConfig.validate()


_validate_production_config()

# Interactive API docs (/docs, /redoc, /openapi.json) are dev-only — gate them
# off in prod so the route inventory + schemas aren't exposed to anonymous
# callers. Gated strictly on FLASK_ENV == "production" (mirrors the secret guard).
import os as _os  # noqa: E402

_DOCS_ENABLED = _os.environ.get("FLASK_ENV") != "production"
app = FastAPI(
    title="Polymind API",
    default_response_class=JSONResponse,
    docs_url="/docs" if _DOCS_ENABLED else None,
    redoc_url="/redoc" if _DOCS_ENABLED else None,
    openapi_url="/openapi.json" if _DOCS_ENABLED else None,
)


# ---------------------------------------------------------------------------
# Security headers — mirror utils/security.add_security_headers on every
# response. Added BEFORE CORS so CORS ends up OUTERMOST (Starlette applies the
# last-added middleware first on the response path).
# ---------------------------------------------------------------------------
# API responses never render active content, so they get the strictest possible
# CSP. Applied only in production: in dev/test the Swagger UI at /docs serves
# HTML with inline scripts that 'default-src none' would break (and /docs is
# disabled in prod anyway). The SPA document CSP is shipped separately as a
# <meta> tag baked at build time (frontend/vite.config.js).
_API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
_CSP_ON_API = _os.environ.get("FLASK_ENV") == "production"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        if _CSP_ON_API:
            response.headers["Content-Security-Policy"] = _API_CSP
        return response


app.add_middleware(SecurityHeadersMiddleware)


# ---------------------------------------------------------------------------
# CSRF guard for cookie-authenticated mutations.
#
# With the httpOnly auth-cookie migration, a browser now authenticates by an
# ambient cookie the browser auto-attaches cross-site — the classic CSRF vector.
# Defense: a non-GET/HEAD/OPTIONS request to /api/** that is authenticated BY
# COOKIE (access cookie present) and carries NO Authorization: Bearer header MUST
# send a custom ``X-CSRF-Token`` header (any non-empty value). A custom header
# can't be forged by a cross-site <form>/<img>/navigation and is subject to CORS
# preflight for fetch/XHR, so its presence proves a same-origin (or
# CORS-permitted) caller.
#
# Deliberately EXEMPT:
#   - safe methods (GET/HEAD/OPTIONS) — no state change + CORS preflight is OPTIONS
#   - non-/api paths (SPA assets, etc.)
#   - requests carrying a Bearer header — API clients / tests authenticate by
#     header, not by an ambient cookie, so they're not a CSRF vector
#   - requests with NO access cookie at all — pre-auth flows have no cookie
#     credential to abuse, so blocking them would only break first-login
#   - the auth-bootstrap endpoints themselves (login / refresh / keycloak-sync):
#     these are the named pre-auth flows. They establish or ROTATE the session
#     and are gated by their OWN credential (password / valid refresh token /
#     valid KC token), so an ambient cookie can't drive them. They must stay open
#     even when a STALE access cookie is still in the jar (e.g. re-login right
#     after a password change leaves the old, now-revoked cookie attached — a
#     login must not 403). Refresh-from-cookie also lands here.
# ---------------------------------------------------------------------------
class CsrfMiddleware(BaseHTTPMiddleware):
    _SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
    _EXEMPT_PATHS = frozenset({
        "/api/auth/login",
        "/api/auth/refresh",
        "/api/auth/keycloak/sync",
    })

    async def dispatch(self, request, call_next):
        from app.api.cookies import access_cookie_name

        if (
            request.method not in self._SAFE_METHODS
            and request.url.path.startswith("/api")
            and request.url.path not in self._EXEMPT_PATHS
            and not (request.headers.get("Authorization") or request.headers.get("authorization"))
            and request.cookies.get(access_cookie_name())
            and not request.headers.get("X-CSRF-Token")
        ):
            return JSONResponse({"error": "csrf_failed", "status": 403}, status_code=403)
        return await call_next(request)


app.add_middleware(CsrfMiddleware)


# ---------------------------------------------------------------------------
# CORS — mirror app/__init__.py:45-54 origin parsing. allow_credentials=True.
# When no explicit origins are configured, fall back to '*' (dev) like flask-cors.
# Added LAST so it is the outermost middleware.
# ---------------------------------------------------------------------------
def _parse_cors_origins() -> list[str]:
    raw_origins = flask_core.config.get("CORS_ORIGINS")
    if not raw_origins:
        return ["*"]
    if isinstance(raw_origins, str):
        origins_list = [o.strip() for o in raw_origins.split(",") if o.strip() and o.strip() != "*"]
    else:
        origins_list = [o for o in raw_origins if o and o != "*"]
    return origins_list or ["*"]


_cors_origins = _parse_cors_origins()
# allow_credentials=True with '*' is invalid per spec; Starlette handles the
# wildcard credentials case, but mirror the flask-cors intent: explicit list
# when configured, else allow-all-origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Exception handlers (legacy-shaped bodies).
# ---------------------------------------------------------------------------
install_exception_handlers(app)


# ---------------------------------------------------------------------------
# Routers.
# ---------------------------------------------------------------------------
for _router, _prefix in ALL_ROUTERS:
    app.include_router(_router, prefix=_prefix)


# ---------------------------------------------------------------------------
# Startup: raise the anyio worker-thread limiter. Sync handlers + sync deps
# (the flask_ctx bridge) run in anyio's thread pool; long-lived SSE streams
# would otherwise exhaust the default ~40-token pool under concurrency.
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def _raise_thread_limiter() -> None:
    try:
        limiter = anyio.to_thread.current_default_thread_limiter()
        limiter.total_tokens = 200
        logger.info("anyio thread limiter raised to %s tokens", limiter.total_tokens)
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not raise anyio thread limiter: %s", exc)


@app.on_event("startup")
async def _warm_openrouter() -> None:
    """Pre-open keep-alive to OpenRouter (via egress proxy) so first chat is fast."""
    try:
        from app.services.openrouter_service import warm_openrouter_connection

        await anyio.to_thread.run_sync(warm_openrouter_connection)
        logger.info("openrouter connection warm done")
    except Exception as exc:  # noqa: BLE001
        logger.warning("openrouter warm skipped: %s", exc)


# ---------------------------------------------------------------------------
# Startup: seed default accounts + the platform_settings singleton. This
# lived in the Flask factory (app/__init__.py) and was lost in the FastAPI
# migration — without it a fresh DB has NO admin and NO platform admin
# (operator login 401s forever). Best-effort: a seeding failure must never
# block boot (e.g. DB briefly unavailable; first real request will surface it).
# ---------------------------------------------------------------------------
def _seed_defaults() -> None:
    import os

    from app.extensions import db
    from app.models.platform_settings import PlatformSettingsModel

    with db.session_scope():
        PlatformSettingsModel.ensure_singleton()

        admin_email = os.environ.get("ADMIN_EMAIL")
        admin_password = os.environ.get("ADMIN_PASSWORD")
        if admin_email and admin_password:
            from app.models.user import UserModel
            UserModel.ensure_default_admin(
                admin_email, admin_password,
                display_name=os.environ.get("ADMIN_NAME", "Admin"),
            )


@app.on_event("startup")
async def _seed_default_accounts() -> None:
    try:
        await anyio.to_thread.run_sync(_seed_defaults)
    except Exception as exc:  # noqa: BLE001
        logger.warning("startup seeding skipped: %s", exc)


# Hourly prune of Data Analyzer workdirs under DATA_SANDBOX_ROOT (mtime TTL).
# Opportunistic prune still runs in prepare_dataset; this bounds disk without
# waiting for the next analysis on a quiet host.
_DATA_WORKDIR_PRUNE_INTERVAL_S = 3600


@app.on_event("startup")
async def _start_data_workdir_pruner() -> None:
    import asyncio

    async def _loop() -> None:
        # Short initial delay so boot + seed finish first.
        await asyncio.sleep(60)
        while True:
            try:
                from app.services.data_analysis_service import prune_workdirs
                await anyio.to_thread.run_sync(prune_workdirs)
            except Exception as exc:  # noqa: BLE001
                logger.warning("data workdir prune skipped: %s", exc)
            await asyncio.sleep(_DATA_WORKDIR_PRUNE_INTERVAL_S)

    try:
        asyncio.create_task(_loop(), name="data-workdir-pruner")
    except TypeError:
        # Python <3.11: create_task has no name=
        asyncio.create_task(_loop())


__all__ = ["app"]
