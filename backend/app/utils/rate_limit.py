"""Shared in-process per-user sliding-window rate limiter.

Centralizes the pattern that ``routers/misc_b.py`` (helper 30/60s) and
``routers/dlp.py`` (DLP 60/60s) each open-coded as a module-local deque, so the
expensive paid endpoints (chat / arena / debate / image-gen streams) can apply
the same speed-bump without duplicating the bookkeeping five times.

Scope + guarantees (read before relying on it):
- **In-process / per-worker only** — state lives in THIS worker's memory, exactly
  like the two existing limiters. Under multi-worker gunicorn (the prod boot runs
  ``-k uvicorn.workers.UvicornWorker`` with multiple workers) each worker keeps
  its OWN window, so the effective limit is ``max_calls × worker_count``: a user
  pinned to different workers across requests gets that many calls per window. A
  worker restart also resets every window. This is a cost/DoS speed-bump, NOT a
  distributed quota; do not treat it as an exact global budget (that is what the
  spend gate is for).
- **Thread-safe** — handlers run in anyio worker threads, so unlike the two
  lock-free originals this guards the shared dict with a lock. Append/popleft
  under the lock keep concurrent streams on one user from corrupting a deque.
- Keyed by ``(bucket, user_id)`` so different endpoints keep independent windows.

Cross-worker upgrade (sketch — NOT implemented; the per-worker speed-bump is
deliberate for now). The cheapest exact global limiter that needs no Redis is a
PG fixed-window counter: a table ``rate_limit_counter(key text, window_start
timestamptz, count int, PRIMARY KEY (key, window_start))`` keyed by
``key = f"{bucket}:{user_id}"`` and ``window_start = floor(now / window) *
window`` (the current fixed window's start). Each call does one atomic upsert::

    INSERT INTO rate_limit_counter (key, window_start, count)
    VALUES (:key, :window_start, 1)
    ON CONFLICT (key, window_start)
    DO UPDATE SET count = rate_limit_counter.count + 1
    RETURNING count;

If the returned ``count > max_calls`` the call is over the limit (you may then
DELETE/decrement to avoid charging the rejected call, or just let it lapse).
Fixed (not sliding) windows trade a little burst tolerance at window edges for a
single indexed write per call; reap old rows with a periodic
``DELETE WHERE window_start < now() - interval``. This is exact across workers
because Postgres is the shared store — but every limited call becomes a DB
round-trip, so adopt it only where an exact global cap is actually required.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

# (bucket, user_id) -> deque[monotonic timestamps]
_buckets: dict[tuple[str, str], deque] = {}
_lock = threading.Lock()

# Opportunistic memory reclamation: every N admitted calls, drop buckets whose
# newest entry is older than two windows (idle users) so the dict can't grow
# unbounded across a long-lived worker.
_SWEEP_EVERY_N = 500
_sweep_counter = 0


def _sweep_locked(now: float) -> None:
    stale = [
        key for key, dq in _buckets.items()
        if not dq or (now - dq[-1]) > (2 * _LONGEST_WINDOW_SEEN)
    ]
    for key in stale:
        _buckets.pop(key, None)


_LONGEST_WINDOW_SEEN = 60  # grows to the largest window any caller uses


def check_rate_limit(bucket: str, user_id: str, *, max_calls: int, window: int) -> Optional[int]:
    """Record one call for ``(bucket, user_id)`` under a sliding ``window``.

    Returns ``None`` when the call is admitted (and records it), or the number
    of seconds the caller should wait (``Retry-After``) when the limit is hit
    (the call is NOT recorded in that case).

    Args:
        bucket:    logical endpoint group, e.g. ``"chat_stream"``, ``"image_gen"``.
        user_id:   acting user id (stringified).
        max_calls: calls allowed within the window.
        window:    sliding window length in seconds.

    Recommended 429 shape (mirror the existing routers)::

        retry = check_rate_limit("chat_stream", user_id, max_calls=30, window=60)
        if retry is not None:
            return JSONResponse(
                {"error": "rate_limited", "retry_after": retry},
                status_code=429,
                headers={"Retry-After": str(int(retry))},
            )
    """
    global _sweep_counter, _LONGEST_WINDOW_SEEN
    key = (bucket, str(user_id))
    now = time.monotonic()
    window_start = now - window

    with _lock:
        if window > _LONGEST_WINDOW_SEEN:
            _LONGEST_WINDOW_SEEN = window

        _sweep_counter += 1
        if _sweep_counter >= _SWEEP_EVERY_N:
            _sweep_counter = 0
            _sweep_locked(now)

        dq = _buckets.setdefault(key, deque())
        while dq and dq[0] < window_start:
            dq.popleft()
        if len(dq) >= max_calls:
            retry_after = int(window - (now - dq[0])) + 1
            return max(retry_after, 1)
        dq.append(now)
        return None
