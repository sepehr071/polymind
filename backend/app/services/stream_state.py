"""
Cross-worker stream-generation state (P0.2) — PG-backed.

The chat/arena/debate SSE endpoints used to track in-flight generations via
process-global dicts (``active_generations`` etc.). Under multi-worker
gunicorn the cancel POST often lands on a *different* worker than the
streaming generator, so the dict lookup failed and cancel was a no-op.

This module persists the cancel flag in Postgres so any worker can see it.
A periodic ``sweep_expired()`` call (via the deploy cron) reaps abandoned
rows. Callers may still keep a per-process dict as a fast read-through
cache; the *authoritative* state lives in Postgres.

API:
    register(session_id, ttl_seconds=300, user_id=None) -> None
    reserve(session_id, user_id, max_active, ttl_seconds=...) -> bool  # cap TOCTOU
    promote(reservation_id, message_id) -> None  # re-key reserved row
    mark_cancelled(session_id) -> bool
    is_cancelled(session_id) -> bool
    clear(session_id) -> None
    owner_of(session_id) -> Optional[str]   # for cancel-endpoint authz
    count_active(user_id) -> int            # per-user concurrent-stream cap
"""

from __future__ import annotations

from typing import Optional

from app.models.stream_state import StreamStateModel


def register(session_id: str, ttl_seconds: int = 300, user_id: Optional[str] = None) -> None:
    """Mark a session as active. Resets ``cancelled`` to False on re-register."""
    StreamStateModel.register(session_id, ttl_seconds=ttl_seconds, user_id=user_id)


def reserve(session_id: str, user_id: Optional[str], max_active: int,
            ttl_seconds: Optional[int] = None) -> bool:
    """Reserve-before-response stream slot for the per-user cap (TOCTOU-safe).

    Atomically counts the user's active streams and inserts the reservation row
    iff under ``max_active`` (under a per-user advisory lock). Returns True when
    reserved (caller proceeds), False when at the cap (caller returns 429).
    """
    if ttl_seconds is None:
        return StreamStateModel.try_reserve(session_id, user_id, max_active)
    return StreamStateModel.try_reserve(session_id, user_id, max_active, ttl_seconds)


def promote(reservation_id: str, message_id: str) -> None:
    """Re-key a reserved row from the handler reservation_id to the message_id."""
    StreamStateModel.promote(reservation_id, message_id)


def mark_cancelled(session_id: str) -> bool:
    """Set ``cancelled=True`` for the session. Returns True if a doc matched."""
    return StreamStateModel.mark_cancelled(session_id)


def is_cancelled(session_id: str) -> bool:
    """Read the cancelled flag. Returns False if the row is missing."""
    return StreamStateModel.is_cancelled(session_id)


def clear(session_id: str) -> None:
    """Remove the row. Safe to call in a finally block."""
    StreamStateModel.clear(session_id)


def owner_of(session_id: str) -> Optional[str]:
    """Return the ``user_id`` that registered the session, or None."""
    return StreamStateModel.owner_of(session_id)


def count_active(user_id: str) -> int:
    """Count a user's live (non-expired, non-cancelled) streams.

    Backs the per-user concurrent-stream cap enforced in the chat/arena/debate
    SSE handlers (DB connection-pool exhaustion DoS guard).
    """
    return StreamStateModel.count_active(user_id)
