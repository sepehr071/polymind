"""HMAC-signed media URLs (currently: workflow-generated videos).

Why this exists
---------------
``GET /api/uploads/video/{filename}`` is intentionally unauthenticated — the
workflow UI renders clips via a plain ``<video src>`` tag that can't carry a
Bearer token. The on-disk filename (``video_<user>_<gen>.mp4``) was the only
"capability", which is a weak guarantee (it leaks through saved workflow runs,
logs, referrers, ...). This module appends a short HMAC signature + expiry to
the URL so the route can verify the link was minted by us and hasn't expired,
without any per-request DB lookup.

Key + crypto mirror ``app/services/dlp_tokens.py``: HMAC-SHA256 keyed off
``JWT_SECRET_KEY`` (enforced >=32 bytes at boot in prod), base64url, constant-time
compare. A DISTINCT domain prefix (``b"video:"``) is folded into the signed
message so a video signature can never be confused with — or replayed as — a DLP
confirm token, even though both keys are the same secret.

TTL is deliberately LONG (7 days, override via ``MEDIA_URL_SIGNING_TTL_S``):
signed URLs are persisted into workflow runs and re-rendered on later page loads,
so a short TTL would break legitimate replay of saved runs.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time as _time

from app.settings import settings

# Domain-separation prefix so a video signature is cryptographically distinct
# from any other HMAC the same JWT_SECRET_KEY signs (e.g. DLP confirm tokens).
_VIDEO_HMAC_DOMAIN = b"video:"

# 7 days. Saved workflow runs re-render the persisted URL long after mint, so the
# window must outlive a realistic "open this old run again" gap. Override with
# MEDIA_URL_SIGNING_TTL_S (seconds) if a deployment wants a tighter/looser window.
_DEFAULT_VIDEO_URL_TTL_S = 7 * 24 * 60 * 60


def _hmac_key() -> bytes:
    """Pull the HMAC key from JWT_SECRET_KEY (enforced >=32 bytes at boot in prod).

    Mirrors ``dlp_tokens._hmac_key`` — ``settings.get`` is the canonical key
    accessor (NOT a config.py read).
    """
    secret = settings.get("JWT_SECRET_KEY") or ""
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    return secret


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _sign(filename: str, exp: int) -> str:
    """Return the base64url HMAC over ``video:<filename>|<exp>``."""
    msg = _VIDEO_HMAC_DOMAIN + f"{filename}|{exp}".encode("utf-8")
    mac = hmac.new(_hmac_key(), msg, hashlib.sha256).digest()
    return _b64url(mac)


def default_ttl_seconds() -> int:
    """Effective signed-URL TTL: ``MEDIA_URL_SIGNING_TTL_S`` env override, else 7d."""
    raw = os.environ.get("MEDIA_URL_SIGNING_TTL_S")
    if raw:
        try:
            val = int(raw)
            if val > 0:
                return val
        except ValueError:
            pass
    return _DEFAULT_VIDEO_URL_TTL_S


def sign_video_filename(filename: str, *, ttl_seconds: int | None = None) -> tuple[int, str]:
    """Mint ``(exp_epoch, sig_b64)`` for ``filename``.

    ``filename`` MUST be the bare on-disk basename (``video_<user>_<gen>.mp4``),
    matching exactly what ``verify_video_url`` receives from the route's
    ``os.path.basename`` guard — sign the same bytes you later verify.
    """
    ttl = ttl_seconds if ttl_seconds is not None else default_ttl_seconds()
    exp = int(_time.time()) + int(ttl)
    return exp, _sign(filename, exp)


def sign_video_url(filename: str, *, ttl_seconds: int | None = None) -> str:
    """Return the ``exp=<epoch>&sig=<b64url>`` query string for ``filename``.

    Caller appends this to ``/api/uploads/video/<filename>`` with a ``?``. The
    resulting URL is fully self-contained — the frontend needs no change.
    """
    exp, sig = sign_video_filename(filename, ttl_seconds=ttl_seconds)
    return f"exp={exp}&sig={sig}"


def verify_video_url(filename: str, exp: object, sig: object) -> bool:
    """Verify the signature binds ``filename`` and the link hasn't expired.

    Constant-time compare on the MAC; expiry checked against wall-clock. Any
    malformed/missing input returns ``False`` (never raises) so the route can map
    it to a 403.
    """
    if not filename or sig is None or exp is None:
        return False
    try:
        exp_int = int(exp)
    except (TypeError, ValueError):
        return False
    expected = _sign(filename, exp_int)
    if not hmac.compare_digest(expected, str(sig)):
        return False
    if exp_int <= int(_time.time()):
        return False
    return True


def signing_required() -> bool:
    """True when unsigned video URLs must be rejected.

    Production is **fail-closed** unless ``MEDIA_URL_SIGNING_REQUIRED=0`` (or
    ``false``/``no``) explicitly opts out. Dev (non-production) stays
    permissive when the env is unset so local unsigned links still work.

    A PRESENT-but-INVALID signature is always rejected as tampering
    regardless of this flag (handled by the route / ``verify_video_url``).
    """
    raw = os.environ.get("MEDIA_URL_SIGNING_REQUIRED", "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    # Unset: prod requires signatures; dev does not.
    return os.environ.get("FLASK_ENV", "").strip().lower() == "production"
