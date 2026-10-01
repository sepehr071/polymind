"""httpOnly auth-cookie helpers — the server half of the cookie-auth migration.

Tokens are no longer kept in browser-readable JS; the access/refresh JWTs ride
in httpOnly cookies the frontend can't read (mitigating token theft via XSS).

Cookie names + attributes branch on prod-vs-dev (``FLASK_ENV == 'production'``):

  prod  → ``__Host-access`` / ``__Host-refresh``
          ``HttpOnly; Secure; SameSite=Lax; Path=/`` (NO Domain — the ``__Host-``
          prefix REQUIRES Secure + Path=/ + no Domain, and forbids path-scoping,
          so BOTH cookies are Path=/).
  dev   → ``access_token`` / ``refresh_token``
          same attrs but NO Secure + plain names so plain-http localhost works.

Cookie ``Max-Age`` is read from the JWT lifetimes in ``app.config`` (via
``settings``) so the cookie and the token it carries expire together.
"""
from __future__ import annotations

import os
from datetime import timedelta

from starlette.responses import Response

from app.settings import settings


def _is_production() -> bool:
    """Prod vs dev/test gate — mirrors the asgi.py secret/CSP guards."""
    return os.environ.get("FLASK_ENV") == "production"


def access_cookie_name() -> str:
    """``__Host-access`` in prod, ``access_token`` in dev/test."""
    return "__Host-access" if _is_production() else "access_token"


def refresh_cookie_name() -> str:
    """``__Host-refresh`` in prod, ``refresh_token`` in dev/test."""
    return "__Host-refresh" if _is_production() else "refresh_token"


def _max_age_seconds(key: str, fallback: int) -> int:
    """Read a JWT lifetime from config as whole seconds.

    ``JWT_ACCESS_TOKEN_EXPIRES`` / ``JWT_REFRESH_TOKEN_EXPIRES`` are ``timedelta``
    on every Config subclass; tolerate a bare int/float too (defensive only for
    a hand-overridden config), falling back if absent/garbage.
    """
    value = settings.get(key)
    if isinstance(value, timedelta):
        return int(value.total_seconds())
    if isinstance(value, (int, float)):
        return int(value)
    return fallback


def _cookie_kwargs(*, max_age: int) -> dict:
    """Shared ``set_cookie`` kwargs, branched on prod vs dev.

    prod adds ``secure=True`` (required by the ``__Host-`` prefix); dev omits it
    so plain-http localhost can set the cookie. ``samesite='lax'`` + ``path='/'``
    + no ``domain`` hold in both envs.
    """
    return {
        "max_age": max_age,
        "path": "/",
        "httponly": True,
        "secure": _is_production(),
        "samesite": "lax",
    }


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """Write both auth cookies on ``response`` with the contract attributes.

    Access-cookie Max-Age = access-token lifetime; refresh-cookie Max-Age =
    refresh-token lifetime — so each cookie outlives its JWT by nothing.
    """
    response.set_cookie(
        access_cookie_name(),
        access_token,
        **_cookie_kwargs(max_age=_max_age_seconds("JWT_ACCESS_TOKEN_EXPIRES", 3600)),
    )
    response.set_cookie(
        refresh_cookie_name(),
        refresh_token,
        **_cookie_kwargs(max_age=_max_age_seconds("JWT_REFRESH_TOKEN_EXPIRES", 2592000)),
    )


def clear_auth_cookies(response: Response) -> None:
    """Delete both auth cookies (logout). Same name/path/secure/samesite as when
    they were set, so the browser actually drops them (a mismatched path/secure
    leaves the cookie in place)."""
    for name in (access_cookie_name(), refresh_cookie_name()):
        response.delete_cookie(
            name,
            path="/",
            httponly=True,
            secure=_is_production(),
            samesite="lax",
        )


__all__ = [
    "access_cookie_name",
    "refresh_cookie_name",
    "set_auth_cookies",
    "clear_auth_cookies",
]
