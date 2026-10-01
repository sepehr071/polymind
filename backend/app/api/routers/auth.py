"""Auth + Keycloak SSO routes, translated from app/routes/auth.py and
app/routes/keycloak_auth.py.

Every Flask handler maps 1:1 to a FastAPI path operation. Bodies are read via
``await request.json()`` (the legacy routes used ``request.get_json(silent=True)``
and tolerated missing/garbage bodies, so we do too). Tokens are minted with
flask_jwt_extended INSIDE the flask_ctx app_context (the router-level
``Depends(flask_ctx)`` guarantees it) so the resulting JWTs carry the same
claims and verify via ``resolve_user_from_token``.
"""
from __future__ import annotations

import logging
import os
import time

import anyio.to_thread
import jwt as pyjwt
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from app.api.tokens import (
    decode as decode_token,
    mint_access as create_access_token,
    mint_refresh as create_refresh_token,
)

from app.api.cookies import (
    clear_auth_cookies,
    refresh_cookie_name,
    set_auth_cookies,
)
from app.api.deps import current_user, flask_ctx
from app.api.errors import AuthError
from app.utils.errors import APIError
from app.config import Config
from app.models.revoked_token import RevokedTokenModel
from app.models.user import UserModel
from app.utils.helpers import serialize_doc  # noqa: F401 — parity import
from app.utils.validators import validate_password

logger = logging.getLogger(__name__)

# Router-level dependency: every request runs inside the Flask app_context.
router = APIRouter(dependencies=[Depends(flask_ctx)])


async def _json_body(request: Request) -> dict:
    """Read the request JSON body, tolerating empty/garbage like get_json(silent=True)."""
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# /api/auth  (auth_bp)
# ---------------------------------------------------------------------------
# NOTE: the public self-register HTTP route was removed — onboarding is
# Keycloak-only (see CLAUDE.md "Public login = Keycloak-only"). ``UserModel.create``
# is still used elsewhere (KC provisioning, admin user-create, seed); only the
# HTTP endpoint is gone.
@router.post("/login")
async def login(request: Request):
    from app.models.platform_settings import PlatformSettingsModel
    from app.utils.login_throttle import (
        clear_for_email,
        is_blocked,
        record_failure,
        retry_after_seconds,
    )

    data = await _json_body(request)
    if not data:
        return JSONResponse({"error": "No data provided"}, status_code=400)

    email = (data.get("email") or "").strip()
    password = data.get("password", "")
    if not email or not password:
        return JSONResponse({"error": "Email and password are required"}, status_code=400)

    client_ip = (request.client.host if request.client else "") or ""
    if is_blocked(client_ip, email):
        retry = retry_after_seconds()
        return JSONResponse(
            {"error": "Too many failed attempts. Try again later.", "code": "login_throttled"},
            status_code=429,
            headers={"Retry-After": str(retry)},
        )

    from app.models.user import dummy_password_verify

    # bcrypt verify (~50-100ms) blocks the event loop and would freeze every
    # concurrent request, so the lookup+verify runs in a worker thread. The
    # unknown-email branch still performs one full bcrypt comparison via
    # dummy_password_verify so its timing matches a real (wrong-password)
    # verify — preserving the user-enumeration protection, just offloaded.
    def _verify_user():
        u = UserModel.find_by_email(email)
        if u:
            ok = UserModel.verify_password(u, password)
        else:
            dummy_password_verify(password)
            ok = False
        return u, ok

    user, user_password_ok = await anyio.to_thread.run_sync(_verify_user)

    if not user_password_ok:
        record_failure(client_ip, email)
        return JSONResponse({"error": "Invalid email or password"}, status_code=401)

    if user.get("status", {}).get("is_banned", False):
        return JSONResponse({
            "error": "Account has been suspended",
            "reason": user.get("status", {}).get("ban_reason", "No reason provided"),
        }, status_code=403)

    user_id = str(user["_id"])
    access_token = create_access_token(identity=user_id)
    refresh_token = create_refresh_token(identity=user_id)

    UserModel.update_last_active(user_id)
    clear_for_email(email)

    try:
        features = PlatformSettingsModel.get()["features"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("PlatformSettingsModel.get features failed: %s", exc)
        features = {}

    response = JSONResponse({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": 900,
        "features": features,
        "user": {
            "id": user_id,
            "email": user["email"],
            "display_name": user["profile"]["display_name"],
            "role": user["role"],
            "avatar_url": user["profile"].get("avatar_url"),
            # Merged verbatim into the authMe cache — OnboardingGate reads
            # settings.onboarding_seen_at without waiting for a /me refetch.
            "settings": user.get("settings", {}),
            "sso": bool(user.get("keycloak_sub")),
        },
    }, status_code=200)
    set_auth_cookies(response, access_token, refresh_token)
    return response


def _extract_refresh_token(request: Request, body: dict) -> tuple[str, bool]:
    """Locate the refresh token: refresh COOKIE first, then Authorization header,
    then JSON body. Returns ``(token, from_cookie)``.

    ``from_cookie`` drives the response-body token omission in ``refresh`` — when
    the credential rode in via the httpOnly cookie, the rotated tokens MUST NOT be
    echoed in JSON (an XSS could otherwise ``fetch`` /refresh with
    ``credentials:'include'`` and read fresh tokens, defeating httpOnly). API
    clients / tests that present a header or body token still get body tokens.
    """
    cookie_token = request.cookies.get(refresh_cookie_name())
    if cookie_token:
        return cookie_token, True

    auth = request.headers.get("Authorization") or request.headers.get("authorization")
    if auth:
        parts = auth.split()
        if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1]:
            return parts[1], False

    body_token = body.get("refresh_token")
    if body_token:
        return body_token, False

    raise AuthError(401, {"error": "Missing or malformed token", "code": "token_missing"})


def _verify_refresh_claims(token: str) -> dict:
    """Verify a refresh-type JWT and return its decoded claims.

    Equivalent to ``@jwt_required(refresh=True)`` — rejects non-refresh tokens.
    Runs inside the flask_ctx app_context.
    """
    try:
        claims = decode_token(token)
    except pyjwt.ExpiredSignatureError:
        raise AuthError(401, {"error": "Token has expired", "code": "token_expired"})
    except Exception as exc:  # noqa: BLE001
        raise AuthError(401, {"error": "Invalid token", "code": "token_invalid", "detail": str(exc)})
    if claims.get("type") != "refresh":
        raise AuthError(401, {"error": "Only refresh tokens are allowed", "code": "token_invalid"})
    if RevokedTokenModel.is_revoked(claims.get("jti")):
        raise AuthError(401, {"error": "Token has been revoked", "code": "token_revoked"})

    # Password-change cutoff: a refresh token is jti-revocation-only, so without
    # this check the long-lived refresh token would survive a password change.
    # Mirror resolve_user_from_token — UserModel rows only.
    identity = claims.get("sub")
    iat = claims.get("iat")
    if identity and iat is not None:
        user = UserModel.find_by_id(identity)
        cutoff = ((user or {}).get("settings") or {}).get("tokens_valid_after")
        if cutoff is not None:
            try:
                if int(iat) < int(cutoff):
                    raise AuthError(401, {"error": "Token has been revoked", "code": "token_revoked"})
            except (TypeError, ValueError):
                pass
    return claims


@router.post("/refresh")
async def refresh(request: Request):
    body = await _json_body(request)
    token, from_cookie = _extract_refresh_token(request, body)
    claims = _verify_refresh_claims(token)

    identity = claims.get("sub")
    access_token = create_access_token(identity=identity)
    new_refresh_token = create_refresh_token(identity=identity)

    try:
        old_jti = claims.get("jti")
        if old_jti:
            RevokedTokenModel.add(old_jti, user_id=identity)
    except Exception as exc:  # noqa: BLE001
        logger.warning("refresh: failed to revoke old refresh jti: %s", exc)

    # CRITICAL XSS defense: when the refresh credential arrived via the httpOnly
    # COOKIE, the rotated tokens are returned ONLY in cookies — never in the JSON
    # body — so script can't read them. The header/body (API-client/test) path
    # keeps echoing body tokens for back-compat.
    payload: dict = {"token_type": "Bearer", "expires_in": 900}
    if not from_cookie:
        payload["access_token"] = access_token
        payload["refresh_token"] = new_refresh_token

    response = JSONResponse(payload, status_code=200)
    set_auth_cookies(response, access_token, new_refresh_token)
    return response


@router.post("/logout")
async def logout(request: Request, user: dict = Depends(current_user)):
    claims = user.get("_jwt_claims") or {}
    # Prefer the RESOLVED account id: for KC tokens claims.sub is the
    # Keycloak uuid, not our users.id. (Column is FK-free since 0011, so
    # either would store — the resolved id is the useful one.)
    user_id = user.get("_id") or claims.get("sub")
    access_jti = claims.get("jti")
    if access_jti:
        RevokedTokenModel.add(access_jti, user_id=user_id)

    data = await _json_body(request)
    # Cookie-first: the refresh token now lives in an httpOnly cookie; fall back
    # to the JSON body for API clients / tests that still post it.
    refresh_token = request.cookies.get(refresh_cookie_name()) or data.get("refresh_token")
    if refresh_token:
        try:
            decoded = decode_token(refresh_token, allow_expired=True)
            refresh_jti = decoded.get("jti")
            if refresh_jti and refresh_jti != access_jti:
                RevokedTokenModel.add(refresh_jti, user_id=user_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("logout: could not decode refresh_token: %s", e)

    response = JSONResponse({"message": "Successfully logged out"}, status_code=200)
    clear_auth_cookies(response)
    return response


@router.get("/me")
async def get_current_user_info(user: dict = Depends(current_user)):
    from app.models.platform_settings import PlatformSettingsModel

    if not user:
        return JSONResponse({"error": "User not found"}, status_code=404)

    try:
        features = PlatformSettingsModel.get()["features"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("PlatformSettingsModel.get features failed: %s", exc)
        features = {}

    created = user.get("created_at")
    return JSONResponse({
        "id": str(user["_id"]),
        "email": user["email"],
        "role": user["role"],
        "profile": {
            "display_name": user["profile"]["display_name"],
            "avatar_url": user["profile"].get("avatar_url"),
            "bio": user["profile"].get("bio", ""),
        },
        "settings": user.get("settings", {}),
        "usage": {
            "messages_sent": user["usage"]["messages_sent"],
            "tokens_used": user["usage"]["tokens_used"],
            "tokens_limit": user["usage"]["tokens_limit"],
        },
        "created_at": created.isoformat() if hasattr(created, "isoformat") else created,
        "features": features,
        "sso": bool(user.get("keycloak_sub")),
    }, status_code=200)


@router.put("/password")
async def change_password(request: Request, user: dict = Depends(current_user)):
    data = await _json_body(request)
    if not data:
        return JSONResponse({"error": "No data provided"}, status_code=400)

    current_password = data.get("current_password", "")
    new_password = data.get("new_password", "")
    if not current_password or not new_password:
        return JSONResponse({"error": "Current and new password are required"}, status_code=400)

    # bcrypt verify blocks the loop — offload so concurrent requests aren't frozen.
    current_password_ok = await anyio.to_thread.run_sync(
        lambda: UserModel.verify_password(user, current_password)
    )
    if not current_password_ok:
        return JSONResponse({"error": "Current password is incorrect"}, status_code=401)

    is_valid, error = validate_password(new_password)
    if not is_valid:
        return JSONResponse({"error": error}, status_code=400)

    # bcrypt truncates at 72 bytes — reject anything longer so two distinct long
    # passwords can't collide on their shared prefix. (validate_password lives in
    # a shared module; the guard is enforced here at the chokepoint instead.)
    from app.models.user import BCRYPT_MAX_PASSWORD_BYTES, password_within_bcrypt_limit

    if not password_within_bcrypt_limit(new_password):
        return JSONResponse(
            {"error": f"Password must be at most {BCRYPT_MAX_PASSWORD_BYTES} bytes"},
            status_code=400,
        )

    import bcrypt

    # hashpw + gensalt is ~100ms+ of CPU work — offload off the event loop.
    new_hash = await anyio.to_thread.run_sync(
        lambda: bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt())
    )
    # Stamp a cutoff so every token minted before this change (including the
    # long-lived refresh token, which is jti-revocation-only otherwise) fails the
    # iat check in resolve_user_from_token. Epoch seconds = JWT `iat` units.
    UserModel.update(user["_id"], {
        "password_hash": new_hash,
        "settings.tokens_valid_after": int(time.time()),
    })
    return JSONResponse({"message": "Password updated successfully"}, status_code=200)


# ---------------------------------------------------------------------------
# /api/auth/keycloak  (keycloak_auth_bp)
# ---------------------------------------------------------------------------
keycloak_router = APIRouter(dependencies=[Depends(flask_ctx)])


def _spa_origin(request: Request) -> str:
    """Public SPA origin for OIDC redirect URIs. Never the API base_url."""
    cfg = flask_core_config()
    app_url = (cfg.get("APP_PUBLIC_URL") or "").strip().rstrip("/")
    if app_url:
        return app_url
    origin = (request.headers.get("origin") or "").strip().rstrip("/")
    if origin and origin.lower() != "null":
        return origin
    return ""


@keycloak_router.get("/config")
async def keycloak_config(request: Request):
    cfg = flask_core_config()
    url = (cfg.get("KEYCLOAK_URL") or "").rstrip("/")
    realm = cfg.get("KEYCLOAK_REALM") or ""
    client_id = cfg.get("KEYCLOAK_CLIENT_ID") or ""
    if not url or not realm or not client_id:
        return JSONResponse({}, status_code=200)
    origin = _spa_origin(request)
    # Constructed from KEYCLOAK_* env — FE prefers live OIDC discovery when
    # it has it. Avoid a discovery HTTP on every /config (login-page load).
    end_session = f"{url}/realms/{realm}/protocol/openid-connect/logout"
    return JSONResponse({
        "url": url,
        "realm": realm,
        "client_id": client_id,
        "redirect_uri": f"{origin}/login/callback" if origin else "",
        "post_logout_redirect_uri": f"{origin}/login" if origin else "",
        "end_session_endpoint": end_session,
        "account_console_url": f"{url}/realms/{realm}/account",
    }, status_code=200)


@keycloak_router.post("/sync")
async def keycloak_sync(request: Request):
    from app.services.keycloak import get_keycloak_client

    client = get_keycloak_client()
    if client is None:
        return JSONResponse({"error": "Keycloak SSO is not configured"}, status_code=503)

    data = await _json_body(request)
    access_token = (data.get("access_token") or "").strip()
    if not access_token:
        return JSONResponse({"error": "access_token is required"}, status_code=400)
    refresh_token = data.get("refresh_token")

    # Opt-in diagnostics ONLY: the previous code dumped the JWT header plus
    # iss/aud/azp/exp/sub/email/preferred_username/realm_access.roles at WARNING
    # on EVERY SSO login — PII + a privileged-account map in prod logs. Gate the
    # non-sensitive, non-verifying claims behind KC_DEBUG_CLAIMS at DEBUG level,
    # and never log email/sub/roles.
    if os.environ.get("KC_DEBUG_CLAIMS"):
        try:
            _hdr = pyjwt.get_unverified_header(access_token)
            _unv = pyjwt.decode(
                access_token,
                options={"verify_signature": False, "verify_aud": False, "verify_exp": False},
            )
            logger.debug(
                "keycloak /sync DEBUG: alg=%s | iss=%s | aud=%s | azp=%s | exp=%s | expected_issuer=%s/realms/%s",
                (_hdr or {}).get("alg"), _unv.get("iss"), _unv.get("aud"),
                _unv.get("azp"), _unv.get("exp"), client.base_url, client.realm,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("keycloak /sync DEBUG: failed to pre-decode token: %s", exc)

    try:
        # Warm path is a cheap RSA verify, but a cold/rotated JWKS triggers a
        # sync requests.get (10s timeout) inside verify_access_token — offload it
        # so a JWKS refresh can't stall the event loop. run_sync re-raises the
        # closure's exception, so the handlers below still see InvalidTokenError
        # (and anything else) exactly as before.
        claims = await anyio.to_thread.run_sync(
            lambda: client.verify_access_token(access_token)
        )
    except pyjwt.InvalidTokenError as exc:
        logger.warning("keycloak /sync: token verification failed: %s: %s", type(exc).__name__, exc)
        return JSONResponse(
            {"error": "Invalid Keycloak access token", "detail": f"{type(exc).__name__}: {exc}"},
            status_code=401,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("keycloak /sync: unexpected verification failure")
        return JSONResponse(
            {"error": "Token verification failed", "detail": f"{type(exc).__name__}: {exc}"},
            status_code=401,
        )

    info = {}
    try:
        info = await anyio.to_thread.run_sync(lambda: client.userinfo(access_token)) or {}
    except Exception as exc:  # noqa: BLE001 — userinfo is best-effort
        logger.warning("keycloak /sync: userinfo failed: %s", exc)
        info = {}
    if not isinstance(info, dict):
        info = {}
    profile = client.extract_profile(claims, info)
    # The three realm roles are the only product levels. Missing role or
    # (except platform-admin) missing org membership refuses the login.
    role = client.map_roles(claims)
    from app.services.keycloak_orgs import (
        KcAccessDenied, assert_can_enter, resolve_organizations, sync_user_organizations,
    )
    orgs = resolve_organizations(
        client, claims, profile.get('sub') or '', access_token,
    )
    try:
        assert_can_enter(role, orgs)
    except KcAccessDenied as denied:
        return JSONResponse(
            {"error": denied.message, "code": denied.code},
            status_code=403,
        )
    if not profile["sub"]:
        return JSONResponse({"error": "Token missing 'sub' claim"}, status_code=401)
    if not profile["email"]:
        return JSONResponse({"error": "Token missing 'email' / 'preferred_username'"}, status_code=401)

    try:
        user = UserModel.upsert_from_keycloak(
            sub=profile["sub"],
            email=profile["email"],
            display_name=profile["display_name"],
            role=role,
            email_verified=profile.get("email_verified", False),
            locale=profile.get("locale"),
        )
    except AttributeError:
        logger.exception("keycloak /sync: UserModel.upsert_from_keycloak missing")
        return JSONResponse({"error": "Keycloak user provisioning is not yet wired"}, status_code=503)
    except APIError as exc:
        # Hardened link refusal (unverified email, or an attempt to auto-link an SSO
        # sub onto an existing password-backed / admin / manager account) — surface
        # the explicit 4xx instead of masking it as a generic 500.
        return JSONResponse(exc.to_dict(), status_code=exc.status_code)
    except Exception:  # noqa: BLE001
        logger.exception("keycloak /sync: failed to upsert user")
        return JSONResponse({"error": "Failed to provision user"}, status_code=500)

    if not user:
        return JSONResponse({"error": "Failed to provision user"}, status_code=500)

    try:
        sync_user_organizations(user, orgs, client.realm_roles(claims))
    except Exception:
        logger.exception("keycloak /sync: org membership sync failed")
        return JSONResponse({"error": "Failed to sync organization membership"}, status_code=500)

    if user.get("status", {}).get("is_banned", False):
        return JSONResponse({
            "error": "Account has been suspended",
            "reason": user.get("status", {}).get("ban_reason", "No reason provided"),
        }, status_code=403)

    user_id = str(user["_id"])
    try:
        UserModel.update_last_active(user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("keycloak /sync: update_last_active failed: %s", exc)

    try:
        from app.models.platform_settings import PlatformSettingsModel

        features = PlatformSettingsModel.get()["features"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("keycloak /sync: PlatformSettingsModel.get features failed: %s", exc)
        features = {}

    now = int(time.time())
    exp = int(claims.get("exp") or now)
    expires_in = max(exp - now, 0)

    # Mint OUR OWN app access+refresh for this user and drive renewals from the
    # refresh COOKIE (we stop relying on client-side Keycloak refresh). The body
    # still echoes the KC access_token/refresh_token for back-compat, but the
    # browser authenticates via the httpOnly cookies set below.
    app_access_token = create_access_token(identity=user_id)
    app_refresh_token = create_refresh_token(identity=user_id)

    profile_doc = user.get("profile") or {}
    response = JSONResponse({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "features": features,
        "user": {
            "id": user_id,
            "email": user["email"],
            "display_name": profile_doc.get("display_name") or profile["display_name"],
            "role": user.get("role", role),
            "avatar_url": profile_doc.get("avatar_url"),
            # Same authMe-cache merge contract as the operator login payload.
            "settings": user.get("settings", {}),
            "sso": True,
        },
    }, status_code=200)
    set_auth_cookies(response, app_access_token, app_refresh_token)
    return response


def flask_core_config():
    """Read the Flask core config (runs inside the flask_ctx app_context)."""
    from app.api.core import flask_core

    return flask_core.config
