"""Per-worker global stream-concurrency semaphore (SSE pool-DoS hard ceiling).

The per-user reservation in ``stream_state`` caps how many concurrent streams a
SINGLE user can hold; it does NOT bound the total across all users. Every live
SSE stream pins at least one psycopg3 connection for its lifetime (chat/helper =
1, arena fan-out = several, but see the 1-permit rule below), so without a
process-wide ceiling a burst of distinct users can still exhaust the connection
pool (``DB_POOL_SIZE + DB_MAX_OVERFLOW``) and stall unrelated requests on
``pool_timeout``.

This module exposes a module-level ``threading.BoundedSemaphore`` sized to keep
the worker's concurrent stream count below pool capacity. It is per-worker and
per-process (like ``utils/rate_limit``): under multi-worker gunicorn the
effective global ceiling is ``_CEILING × worker_count``. That is intentional —
the pool is also per-worker, so a per-worker ceiling is exactly the right scope.

Permit accounting (READ BEFORE CHANGING):
    Acquire ONE permit per CLIENT STREAM, never one per arena/debate fan-out
    branch. A single arena stream pins a handful of connections internally, but
    it is still one client connection and one ``on_close`` release; minting N
    permits for it would (a) drain the semaphore far faster than the pool
    actually fills and (b) make the release math (one ``on_close`` -> one
    ``release()``) wrong. Size ``_CEILING`` to account for arena/debate pinning
    multiple connections each (default 14 streams vs. a 50-connection pool).

``BoundedSemaphore`` raises ``ValueError`` on over-release — that is the
leak/double-release ALARM. The release is wired through the SSE driver's
``on_close``, which fires exactly once per stream, so a raised ValueError here
means a stream released without acquiring (or released twice) and must be fixed
at the call site, not papered over.
"""
from __future__ import annotations

import logging
import os
import threading
import uuid

from app.services import stream_state

_logger = logging.getLogger(__name__)

# Max concurrent client streams this worker will admit. Sized below pool
# capacity (DB_POOL_SIZE 20 + DB_MAX_OVERFLOW 30 = 50) with headroom for
# arena/debate streams pinning 3-5 connections each and for non-stream requests
# needing a connection. Env-overridable for load tuning / tests.
_CEILING = int(os.environ.get("MAX_CONCURRENT_STREAMS_PER_WORKER", "14"))

_semaphore = threading.BoundedSemaphore(_CEILING)


def try_acquire() -> bool:
    """Try to take one stream permit WITHOUT blocking.

    Returns True when a permit was acquired (caller MUST arrange exactly one
    matching ``release()`` — wire it through the SSE driver's ``on_close``), or
    False when the worker is already at its ceiling (caller returns 503).
    """
    return _semaphore.acquire(blocking=False)


def release() -> None:
    """Return one stream permit.

    Wired through ``sse_stream_sync(on_close=...)`` so it fires exactly once per
    stream (producer crash / client disconnect / normal EOF all funnel through
    the runner-thread finally). ``BoundedSemaphore`` raises ``ValueError`` on
    over-release — let it: that is the double-release / leak alarm, not a case to
    swallow here.
    """
    _semaphore.release()


def available() -> int:
    """Best-effort current free-permit count (diagnostics/tests only).

    Reads the BoundedSemaphore's private counter — fine for assertions in tests
    and ad-hoc introspection; do NOT gate admission on it (use ``try_acquire``).
    """
    return _semaphore._value  # type: ignore[attr-defined]


class StreamPreflight:
    """Owns the per-user reservation + per-worker stream permit until hand-off.

    Shared by every SSE streaming handler (chat / arena / debate / helper) so the
    reserve-before-response + dual-release wiring is written once. Usage::

        preflight = StreamPreflight(user_id, max_active)
        if not preflight.reserve():        # per-user cap (atomic, TOCTOU-safe)
            return JSONResponse(429 ...)
        if not preflight.acquire_global(): # per-worker ceiling
            with preflight:                # release the reservation just taken
                return JSONResponse(503 ...)
        with preflight:                    # releases on any pre-stream failure
            ...                            # DLP/spend gates, etc. (may raise)
            preflight.hand_off()           # success: ownership -> on_close
            return sse_stream_sync(producer, on_close=preflight.on_close)

    ``reserve()`` inserts a row keyed by a minted ``reservation_id``; the producer
    later calls ``stream_state.promote(reservation_id, real_id)`` so the SAME
    counted row backs cancel-by-id (no double-count). Both resources are released
    by ``__exit__`` (covering any pre-stream exception or early ``return``) UNLESS
    ``hand_off()`` was called — then release ownership passes to the SSE driver's
    ``on_close`` (the single chokepoint firing once at stream end). ``release()``
    is guarded so the permit is never double-released (``BoundedSemaphore`` would
    raise ``ValueError`` on over-release — that is the leak alarm).
    """

    __slots__ = ("user_id", "max_active", "reservation_id", "_have_permit", "_handed_off")

    def __init__(self, user_id: str, max_active: int,
                 reservation_id: str | None = None) -> None:
        self.user_id = user_id
        self.max_active = max_active
        # When the stream's final id is ALREADY known at the handler (debate's
        # session_id), reserve directly under it so the producer's ``register``
        # is an idempotent refresh of the SAME counted row (no promote needed).
        # Otherwise mint one and ``promote`` it to the real id in the producer.
        self.reservation_id = str(reservation_id) if reservation_id else str(uuid.uuid4())
        self._have_permit = False
        self._handed_off = False

    def reserve(self) -> bool:
        """Atomically take the per-user slot. False => at cap (caller 429s)."""
        return stream_state.reserve(self.reservation_id, self.user_id, self.max_active)

    def acquire_global(self) -> bool:
        """Take one per-worker permit. False => at ceiling (caller 503s)."""
        self._have_permit = try_acquire()
        return self._have_permit

    def hand_off(self) -> None:
        """Transfer release ownership to the SSE driver's ``on_close``."""
        self._handed_off = True

    def release(self) -> None:
        """Drop the reservation row + return the permit. Once per resource."""
        stream_state.clear(self.reservation_id)
        if self._have_permit:
            self._have_permit = False
            try:
                release()
            except Exception:  # noqa: BLE001 — over-release alarm shouldn't mask anything
                _logger.exception("stream_concurrency over-release on stream close")

    def on_close(self) -> None:
        """``sse_stream_sync`` chokepoint — releases reservation + permit once."""
        self.release()

    def __enter__(self) -> "StreamPreflight":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if not self._handed_off:
            self.release()
        return False  # never suppress the exception
