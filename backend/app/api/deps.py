"""FastAPI dependencies: the Flask "bridge" + auth gates.

CRITICAL CORRECTNESS RULE (non-negotiable): the Flask app_context is bound to the
request's async task in ``flask_ctx`` — an ASYNC dependency. A sync ``yield``
dependency does NOT work here: FastAPI runs a sync generator dep's __enter__ and
__exit__ in two SEPARATE threadpool threads, so Flask's contextvar push-token is
invalid at pop() (LookupError). Binding on the async task instead means every sync
handler/dep (each run in an anyio worker thread) inherits the SAME AppContext via
contextvar propagation -> one scoped ``db.session`` per request, isolated across
requests. The session is removed via ``anyio.to_thread.run_sync`` (a worker thread,
where the psycopg3 connection was used) before the context is popped on the task —
never closing the connection on the event loop.

Auth deliberately re-implements the JWT decode path from ``app/extensions.py``
using PyJWT directly (flask_jwt_extended needs a Flask *request*, which a
FastAPI handler doesn't have). The token shapes + key selection + blocklist +
identity lookup are mirrored exactly so a token minted by either stack verifies
on the other.
"""
from __future__ import annotations

import uuid
from typing import Callable

import anyio
import jwt
from fastapi import Depends, Request
from sqlalchemy import select

from app.api.core import db
from app.api.errors import AuthError
from app.extensions import _session_scope
from app.settings import settings


# ---------------------------------------------------------------------------
# The bridge: bind a Flask app_context to the request's async task so every
# sync handler/dependency (each run in an anyio worker thread) inherits it via
# contextvar propagation, then tear the SQLAlchemy session down in a worker
# thread (the thread the psycopg3 connection was actually used on).
#
# Why an ASYNC dependency (not a sync `yield` one):
#   FastAPI runs a sync generator dependency's __enter__ and __exit__ in two
#   SEPARATE run_in_threadpool calls — i.e. on two DIFFERENT worker threads.
#   Flask's AppContext.push/pop use a contextvar whose set-token is only valid
#   in the context it was set in, so a split __enter__/__exit__ raises
#   LookupError on pop(). Binding the contextvar on the async task instead means
#   every worker thread's copied context sees the SAME AppContext (so db.session
#   resolves to one scoped session across the request), and push/pop both run in
#   the task's own context.
#
# Why remove the session in a worker thread:
#   db.session.remove() closes the psycopg3 connection. psycopg3 connections are
#   not safe to close from a different thread than the one that used them; the
#   request's queries ran in worker threads, so we close there too — NOT on the
#   event loop. (Pushing/popping in async middleware, by contrast, would tear the
#   session down on the loop thread = cross-thread close = corruption under load.)
# ---------------------------------------------------------------------------
async def flask_ctx():
    """Bind a fresh DB-session scope to this request's async task.

    A unique contextvar token is set on the request task; anyio worker threads
    (each sync handler/dependency runs in one) inherit the SAME token via the
    copied contextvars Context, so one scoped ``db.session`` serves the whole
    request and is isolated across requests. The session is removed on a worker
    thread (the psycopg3 connection owner) BEFORE the token is reset on the task
    — never closing the connection on the event loop.

    Name kept: every router declares ``dependencies=[Depends(flask_ctx)]``.
    """
    token = _session_scope.set(object())
    try:
        yield
    finally:
        await anyio.to_thread.run_sync(db.session.remove)
        _session_scope.reset(token)


# ---------------------------------------------------------------------------
# Token resolution — mirrors app/extensions.py decode_key_loader +
# user_lookup_loader + blocklist loader, byte-exact error bodies.
# ---------------------------------------------------------------------------
_HEX24 = "0123456789abcdefABCDEF"


def resolve_user_from_token(token: str) -> dict:
    """Verify a JWT and return the legacy user dict, or raise AuthError.

    MUST run inside a Flask app_context (the ``flask_ctx`` dependency provides
    it) — it touches ``flask_core.config`` + ``db.session``.
    """
    # 1. Read alg/kid from the unverified header to choose the key.
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as exc:
        raise AuthError(401, {"error": "Invalid token", "code": "token_invalid", "detail": str(exc)})

    alg = (header or {}).get("alg", "")
    if alg == "RS256":
        from app.services.keycloak import get_keycloak_client

        client = get_keycloak_client()
        if client is None:
            raise AuthError(401, {"error": "Invalid token", "code": "token_invalid",
                                  "detail": "RS256 token presented but Keycloak not configured"})
        kid = header.get("kid")
        if not kid:
            raise AuthError(401, {"error": "Invalid token", "code": "token_invalid",
                                  "detail": "RS256 token missing 'kid' header"})
        try:
            key = client._public_key_for(kid)
        except jwt.InvalidTokenError as exc:
            raise AuthError(401, {"error": "Invalid token", "code": "token_invalid", "detail": str(exc)})
    else:
        key = settings["JWT_SECRET_KEY"]

    # 2. Verify signature + expiry. Accept both algorithm families like the
    #    Flask stack (JWT_DECODE_ALGORITHMS = ['RS256', 'HS256']).
    try:
        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256", "HS256"],
            options={"verify_aud": False},
        )
    except jwt.ExpiredSignatureError:
        raise AuthError(401, {"error": "Token has expired", "code": "token_expired"})
    except jwt.InvalidTokenError as exc:
        raise AuthError(401, {"error": "Invalid token", "code": "token_invalid", "detail": str(exc)})

    # Token-type confinement: refresh tokens are exchanged ONLY at /refresh
    # (via _refresh_identity), never accepted as bearer credentials on
    # protected routes. Locally-minted access tokens carry type='access';
    # Keycloak RS256 tokens carry no app `type` claim (None) and are unaffected.
    tok_type = payload.get("type")
    if tok_type is not None and tok_type != "access":
        raise AuthError(401, {"error": "Invalid token", "code": "token_invalid", "detail": "wrong token type"})

    # 3. Blocklist check (revoked tokens).
    jti = payload.get("jti")
    if jti:
        from app.models.revoked_token import RevokedToken

        revoked = db.session.execute(
            select(RevokedToken.id).where(RevokedToken.jti == jti).limit(1)
        ).scalar_one_or_none()
        if revoked is not None:
            raise AuthError(401, {"error": "Token has been revoked", "code": "token_revoked"})

    # 4. Identity resolution — mirror user_lookup_loader.
    identity = payload.get("sub")
    if not identity:
        raise AuthError(401, {"error": "Missing or malformed token", "code": "token_missing"})

    # Reject legacy 24-hex Mongo ObjectIds outright.
    if isinstance(identity, str) and len(identity) == 24 and all(c in _HEX24 for c in identity):
        raise AuthError(401, {"error": "Missing or malformed token", "code": "token_missing"})

    try:
        uid = uuid.UUID(str(identity))
    except (ValueError, TypeError):
        raise AuthError(401, {"error": "Missing or malformed token", "code": "token_missing"})

    from app.models.user import User, _user_to_legacy_dict

    row = db.session.execute(
        select(User).where(User.keycloak_sub == uid)
    ).scalar_one_or_none()
    if row is None:
        row = db.session.execute(
            select(User).where(User.id == uid)
        ).scalar_one_or_none()
    user = _user_to_legacy_dict(row)

    if user is None:
        raise AuthError(401, {"error": "Missing or malformed token", "code": "token_missing"})

    # Password-change cutoff (UserModel rows only). A successful password change
    # stamps `settings.tokens_valid_after` (epoch seconds, JWT `iat` units), so
    # any access/refresh token minted before the change — including a still-valid
    # long-lived refresh token — is rejected. Backward-compatible: the field is
    # absent until a password change sets it, so existing tokens are unaffected.
    # KC RS256 tokens belong to SSO users who never set a DB password, so
    # tokens_valid_after stays unset and the check is skipped for them.
    cutoff = (user.get("settings") or {}).get("tokens_valid_after")
    iat = payload.get("iat")
    if cutoff is not None and iat is not None:
        try:
            if int(iat) < int(cutoff):
                raise AuthError(401, {"error": "Token has been revoked", "code": "token_revoked"})
        except (TypeError, ValueError):
            # Malformed cutoff/iat — fail open rather than lock everyone out.
            pass

    # Stash the raw claims for downstream gates (e.g. logout reads claims.jti).
    user.setdefault("_jwt_claims", payload)
    return user


def _bearer_token(request: Request) -> str:
    auth = request.headers.get("Authorization") or request.headers.get("authorization")
    if not auth:
        raise AuthError(401, {"error": "Missing or malformed token", "code": "token_missing"})
    parts = auth.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise AuthError(401, {"error": "Missing or malformed token", "code": "token_missing"})
    return parts[1]


def _resolve_token(request: Request) -> str:
    """Pick the access token for ``current_user``: cookie FIRST, then header.

    The httpOnly access cookie (``access_cookie_name()``) is the primary
    credential for browser sessions post-migration. The Authorization-header
    path is kept intact as a fallback so API clients + the entire header-based
    test suite keep working — when no cookie is present we delegate to the exact
    same ``_bearer_token`` logic (same 401 bodies on a missing/malformed header).
    """
    from app.api.cookies import access_cookie_name

    cookie_token = request.cookies.get(access_cookie_name())
    if cookie_token:
        return cookie_token
    return _bearer_token(request)


# ---------------------------------------------------------------------------
# Auth dependencies (mirror app/utils/decorators.py + the *_required helpers).
# All gate deps depend on current_user so auth resolves exactly once per request
# and the decorator stacking error precedence is preserved (missing token 401 >
# banned 403 > feature 404).
# ---------------------------------------------------------------------------
def current_user(request: Request) -> dict:
    """Resolve the Bearer token to the legacy user dict; cache on request.state."""
    cached = getattr(request.state, "user", None)
    if cached is not None:
        return cached
    token = _resolve_token(request)
    user = resolve_user_from_token(token)
    request.state.user = user
    return user


def require_admin(user: dict = Depends(current_user)) -> dict:
    if user.get("role") != "admin":
        raise AuthError(403, {"error": "Admin access required", "status": 403})
    return user


def require_manager_or_admin(user: dict = Depends(current_user)) -> dict:
    if user.get("role") not in {"admin", "manager"}:
        raise AuthError(403, {"error": "Manager or admin access required", "status": 403})
    return user


def require_active(user: dict = Depends(current_user)) -> dict:
    if not user:
        raise AuthError(404, {"error": "User not found", "status": 404})
    status = user.get("status") or {}
    if status.get("is_banned", False):
        raise AuthError(403, {
            "error": "Account has been suspended",
            "reason": status.get("ban_reason") or "No reason provided",
            "status": 403,
        })
    return user


def workspace_member_dep(min_role: str = "viewer", id_kwarg: str = "wid") -> Callable:
    """Factory: gate on workspace membership. Reads the path param ``id_kwarg``."""
    def _dep(request: Request, user: dict = Depends(current_user)) -> dict:
        from app.utils.permissions import check_workspace_access

        workspace_id = request.path_params.get(id_kwarg)
        if not workspace_id:
            raise AuthError(400, {"error": f"Missing {id_kwarg} in URL", "status": 400})
        if not check_workspace_access(user["_id"], workspace_id, min_role):
            raise AuthError(403, {"error": "Workspace access denied", "status": 403})
        return user

    return _dep


def project_role_dep(min_role: str = "viewer", id_kwarg: str = "pid") -> Callable:
    """Factory: gate on project access. Reads the path param ``id_kwarg``."""
    def _dep(request: Request, user: dict = Depends(current_user)) -> dict:
        from app.utils.permissions import check_project_access

        project_id = request.path_params.get(id_kwarg)
        if not project_id:
            raise AuthError(400, {"error": f"Missing {id_kwarg} in URL", "status": 400})
        if not check_project_access(user["_id"], project_id, min_role):
            raise AuthError(403, {"error": "Project access denied", "status": 403})
        return user

    return _dep


def feature_dep(name: str) -> Callable:
    """Factory: gate on a platform feature flag. 404 when off (looks absent)."""
    def _dep(request: Request, user: dict = Depends(current_user)) -> dict:
        from app.models.platform_settings import PlatformSettingsModel

        features = getattr(request.state, "platform_features", None)
        if features is None:
            features = PlatformSettingsModel.get().get("features", {}) or {}
            request.state.platform_features = features
        if not features.get(name):
            raise AuthError(404, {"error": "feature_disabled", "feature": name, "status": 404})
        return user

    return _dep


__all__ = [
    "flask_ctx",
    "resolve_user_from_token",
    "current_user",
    "require_admin",
    "require_manager_or_admin",
    "require_active",
    "workspace_member_dep",
    "project_role_dep",
    "feature_dep",
]
