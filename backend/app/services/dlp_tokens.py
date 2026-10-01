"""HMAC helpers formerly used for DLP confirm tokens.

Left on disk. The live gate and ``/dlp/scan`` do not mint or honor these
tokens. ``require_confirm`` is not a live action and never unlocks a send.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time as _time
from typing import Optional

from app.settings import settings

# 5-minute TTL — long enough to read the violation modal and click "Send anyway",
# short enough that a leaked token can't be replayed at leisure.
_DLP_CONFIRM_TOKEN_TTL_S = 300


def _hmac_key() -> bytes:
    """Pull the HMAC key from JWT_SECRET_KEY (enforced >=32 bytes at boot in prod)."""
    secret = settings.get("JWT_SECRET_KEY") or ""
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    return secret


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sign_dlp_token(payload: str) -> str:
    """Return ``<payload_b64>.<hmac_b64>``.

    Payload convention: ``f"{text_sha256}|{user_id}|{workspace_id or ''}|{exp_epoch}"``.
    """
    payload_b = payload.encode("utf-8")
    mac = hmac.new(_hmac_key(), payload_b, hashlib.sha256).digest()
    return f"{_b64url(payload_b)}.{_b64url(mac)}"


def mint_dlp_token(
    *, text_sha256: str, user_id: str, workspace_id: Optional[str]
) -> tuple[str, int]:
    """Mint a confirm-token bound to ``(text_sha256, user, workspace)``, 5-min TTL.

    Mirror of the ``/dlp/scan`` minting (``app/api/routers/dlp.py``). Used when a
    server-side gate rejection wants to hand the client a ready-to-replay token
    bound to the EXACT text the gate scanned — the client often can't reproduce
    that text (e.g. chat appends server-extracted attachment text), so a client
    re-scan would mint a token for the wrong sha and the "Send anyway" round-trip
    would loop forever. Returns ``(token, exp_epoch)``.
    """
    exp_epoch = int(_time.time()) + _DLP_CONFIRM_TOKEN_TTL_S
    payload = f"{text_sha256}|{user_id}|{workspace_id or ''}|{exp_epoch}"
    return _sign_dlp_token(payload), exp_epoch


def _verify_dlp_token(
    token: str,
    *,
    text_sha256: str,
    user_id: str,
    workspace_id: Optional[str],
) -> bool:
    """Verify HMAC + expiry + payload binding (constant-time compare)."""
    if not token or not isinstance(token, str) or "." not in token:
        return False
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        payload_bytes = _b64url_decode(payload_b64)
        sig_bytes = _b64url_decode(sig_b64)
    except Exception:
        return False
    expected = hmac.new(_hmac_key(), payload_bytes, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, sig_bytes):
        return False
    try:
        payload = payload_bytes.decode("utf-8")
        parts = payload.split("|")
        if len(parts) != 4:
            return False
        t_sha, t_uid, t_wid, t_exp = parts
        if t_sha != text_sha256:
            return False
        if t_uid != str(user_id):
            return False
        if t_wid != (str(workspace_id) if workspace_id else ""):
            return False
        if int(t_exp) <= int(_time.time()):
            return False
    except Exception:
        return False
    return True
