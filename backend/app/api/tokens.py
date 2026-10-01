"""PyJWT token minting + decoding — Flask-free replacement for the
``flask_jwt_extended`` ``create_access_token`` / ``create_refresh_token`` /
``decode_token`` the auth router used.

Produces tokens with the same claim set the Flask stack did (sub, type, fresh,
jti, iat, nbf, exp, role, + any extra claims), so ``resolve_user_from_token``
(app/api/deps.py) and the test harness (tests/api/conftest._mint) verify them
interchangeably. HS256, signed with ``JWT_SECRET_KEY``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import jwt as pyjwt
from sqlalchemy import select

from app.settings import settings


def _role_for(identity) -> str:
    """Embed the user's DB role (default ``user``) — mirrors the old
    ``app/extensions.add_claims_to_token`` additional-claims loader so the UI
    can gate features without an extra round-trip. Must run with a live
    ``db.session`` scope (the request/thread already has one).
    """
    from app.extensions import db
    from app.models.user import User

    try:
        uid = uuid.UUID(str(identity))
    except (ValueError, TypeError):
        return "user"
    try:
        role = db.session.execute(
            select(User.role).where(User.id == uid)
        ).scalar_one_or_none()
        return role or "user"
    except Exception:  # noqa: BLE001
        return "user"


def _claims(identity, token_type, extra, expires_delta, *, fresh=None) -> dict:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(identity),
        "jti": str(uuid.uuid4()),
        "type": token_type,
        "iat": now,
        "nbf": now,
        "exp": now + expires_delta,
        "role": _role_for(identity),
    }
    if fresh is not None:
        claims["fresh"] = fresh
    if extra:
        claims.update(extra)
    return claims


def mint_access(identity, additional_claims=None) -> str:
    """Mint an access token (type=access, fresh=False)."""
    claims = _claims(
        identity, "access", additional_claims,
        settings["JWT_ACCESS_TOKEN_EXPIRES"], fresh=False,
    )
    return pyjwt.encode(claims, settings["JWT_SECRET_KEY"], algorithm="HS256")


def mint_refresh(identity, additional_claims=None) -> str:
    """Mint a refresh token (type=refresh)."""
    claims = _claims(
        identity, "refresh", additional_claims,
        settings["JWT_REFRESH_TOKEN_EXPIRES"],
    )
    return pyjwt.encode(claims, settings["JWT_SECRET_KEY"], algorithm="HS256")


def decode(token, allow_expired=False) -> dict:
    """Verify + decode a locally-minted JWT. Mirrors flask_jwt_extended's
    decode_token: HS256/RS256, audience unchecked, expiry optional.
    Raises pyjwt.ExpiredSignatureError on expiry when ``allow_expired`` is False.
    """
    return pyjwt.decode(
        token,
        settings["JWT_SECRET_KEY"],
        algorithms=["HS256", "RS256"],
        options={"verify_aud": False, "verify_exp": not allow_expired},
    )


__all__ = ["mint_access", "mint_refresh", "decode"]
