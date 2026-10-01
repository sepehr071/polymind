"""
Login throttle (P0.3) — PG-backed.

Bounds credential-stuffing attacks by counting failed login attempts per
(ip, email) tuple over a 15-minute sliding window. Backed by the
``login_attempt_log`` Postgres table via ``LoginAttemptModel``. After 5 fails
in the window the login route returns HTTP 429 with a ``Retry-After`` header.

Sweep policy: rows older than the window are GC'd by an explicit
``LoginAttemptModel.sweep_older_than(minutes=15)`` call from the deploy cron
(PG has no built-in TTL like Mongo did; we trade laziness for portability).

Why no captcha: out of scope per audit anchor — captcha integration would
require frontend + provider work, and the throttle alone closes the
unbounded-attempt hole.
"""

from __future__ import annotations

from app.models.login_attempt import LoginAttemptModel

_WINDOW_SECONDS = 15 * 60  # 15 minutes
_MAX_ATTEMPTS = 5


def record_failure(ip: str, email: str) -> None:
    """Log a single failed-login attempt for the (ip, email) pair."""
    LoginAttemptModel.record(ip, email)


def count_recent_failures(ip: str, email: str) -> int:
    """Return the number of failed attempts for (ip, email) inside the
    current 15-minute window."""
    return LoginAttemptModel.count_recent(ip, email, _WINDOW_SECONDS)


def is_blocked(ip: str, email: str) -> bool:
    """Return True when the (ip, email) pair has hit the failure cap."""
    return count_recent_failures(ip, email) >= _MAX_ATTEMPTS


def retry_after_seconds() -> int:
    """Conservative ``Retry-After`` header value (full window length)."""
    return _WINDOW_SECONDS


def clear_for_email(email: str) -> None:
    """Wipe all logged attempts for ``email`` after successful login."""
    LoginAttemptModel.clear_for_email(email)
