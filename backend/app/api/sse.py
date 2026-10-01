"""Server-Sent Events helpers for the FastAPI bridge.

Two entry points:

* ``sse_stream(generator)`` — wrap an ALREADY-SAFE sync/async generator of
  ``str`` frames in an SSE ``StreamingResponse``. Use this when the frame source
  needs no Flask app_context, or manages its own context safely (e.g. the
  meetings poll-loop that pushes/pops a context per poll, never across a yield).

* ``sse_stream_sync(producer)`` — the centralized "runner-thread" driver for SSE
  bodies that DO need a Flask app_context spanning yields (DB/JWT/service calls
  between frames). Hand it a zero-arg callable returning a sync generator of
  fully-formed SSE frame strings; it runs the WHOLE generator (and its single
  ``with flask_core.app_context():``) on ONE dedicated daemon thread, while the
  ``StreamingResponse`` body is an ASYNC generator that drains pre-formatted
  frames off a thread-safe queue.

Why the runner thread (the bug it fixes):
    Starlette drives a *sync* streaming body via ``iterate_in_threadpool`` — it
    calls ``next(gen)`` through ``anyio.to_thread.run_sync`` ONCE PER FRAME, and
    anyio runs each call in a FRESH COPY of the contextvars Context. A
    ``with flask_core.app_context():`` that spans a ``yield`` then pushes its
    contextvar token in one frame's context-copy and pops it in the next —
    Flask's ``AppContext.pop`` does ``_cv_app.reset(token)`` which raises
    ``ValueError: <Token ...> was created in a different Context``. Confining the
    whole Flask-context lifetime to ONE worker thread (push AND pop on that
    thread's single context) sidesteps it; the streaming body merely drains a
    queue and NEVER holds a Flask context across an await.
"""
from __future__ import annotations

import inspect
import logging
import queue
import threading
from typing import AsyncIterator, Callable, Iterable, Iterator, Mapping, Optional, Union

import anyio
from starlette.responses import StreamingResponse

from app.api.core import db, flask_core

_log = logging.getLogger(__name__)

_BASE_HEADERS = {
    "Cache-Control": "no-cache",
    # Disable nginx/proxy buffering so frames flush immediately.
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}

# Sentinel pushed onto the frame queue by the runner thread to signal EOF to the
# draining async body. A plain object() can never collide with a real SSE frame.
_DONE = object()

# Upper bound on how long the async body waits for the runner thread to finish
# tearing down its app_context/session after the client disconnects.
_RUNNER_JOIN_TIMEOUT = 1800  # 30-minute hard cap (matches the per-stream caps)


def _make_headers(extra_headers: Optional[Mapping[str, str]]) -> dict:
    headers = dict(_BASE_HEADERS)
    if extra_headers:
        headers.update(extra_headers)
    return headers


def sse_stream(
    generator: Union[Iterator[str], Iterable[str], AsyncIterator[str]],
    extra_headers: Optional[Mapping[str, str]] = None,
) -> StreamingResponse:
    """Wrap an already-safe sync/async generator of ``str`` frames in an SSE response.

    Each yielded item should already be a fully-formed SSE frame, e.g.
    ``f"event: {kind}\\ndata: {json.dumps(payload)}\\n\\n"``. Use this only when
    the generator needs no Flask context across a yield (otherwise reach for
    ``sse_stream_sync``).
    """
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers=_make_headers(extra_headers),
    )


def sse_stream_sync(
    producer: Callable[..., Iterator[str]],
    extra_headers: Optional[Mapping[str, str]] = None,
    *,
    runner_name: str = "sse-stream-runner",
    on_close: Optional[Callable[[], None]] = None,
) -> StreamingResponse:
    """Centralized runner-thread SSE driver — see module docstring for the why.

    ``producer`` is a callable returning a SYNC generator of fully-formed SSE
    frame strings. It is run end-to-end on ONE dedicated daemon thread that owns
    a single ``flask_core.app_context()`` for the whole stream lifetime, so a
    Flask context never spans a Starlette yield. The thread tears its SQLAlchemy
    scoped session down on exit (same thread that used the psycopg3 connection).

    ``on_close`` (optional) is the SINGLE resource-release chokepoint: it is
    invoked EXACTLY ONCE in the runner thread's ``finally`` — covering a producer
    crash, a client disconnect (the drain sets ``stop_event``, the producer
    breaks, the generator returns), and a normal EOF — just before the scoped
    session is torn down. Any exception it raises is swallowed so a release
    failure can never escape the runner. Use it to drop a per-user stream
    reservation and release the per-worker stream semaphore in one place, so the
    two releases compose and fire together regardless of how the stream ended.

    Client-disconnect signalling: the driver creates a ``threading.Event`` and,
    if ``producer`` accepts at least one positional argument, passes the event as
    ``producer(stop_event)`` so the producer can break out of its token loop
    promptly when the client drops the TCP connection (the event is set in the
    drain's ``finally``, which runs on ``GeneratorExit``). Zero-arg legacy
    producers are detected via signature introspection and called ``producer()``
    unchanged — they remain bounded by their own wall-clock caps. Setting the
    event lets an updated producer release its pinned psycopg3 connection back to
    the pool near-instantly instead of waiting out ``_RUNNER_JOIN_TIMEOUT``,
    closing a connection-pool-exhaustion DoS window.

    The ``StreamingResponse`` body is an ASYNC generator that awaits frames off a
    thread-safe queue (``anyio.to_thread.run_sync(q.get)``) until a sentinel, and
    joins the runner thread on close/GeneratorExit so a client disconnect never
    orphans the worker mid-context. The driver holds NO Flask context across an
    await.
    """
    frame_queue: "queue.Queue" = queue.Queue()
    # Set on client disconnect (drain's GeneratorExit/finally) to ask an opt-in
    # producer to stop streaming and release its DB connection promptly.
    stop_event = threading.Event()

    # Opt-in detection: pass the stop_event ONLY to producers that accept a
    # positional arg, so legacy zero-arg producers keep working untouched.
    try:
        _accepts_stop = len(inspect.signature(producer).parameters) >= 1
    except (TypeError, ValueError):
        _accepts_stop = False

    def _run() -> None:
        # The flask_ctx dependency's context is torn down once the handler
        # returns, BEFORE this thread starts — so it opens its OWN app_context
        # for the whole stream lifetime, entered AND exited on THIS one thread,
        # so the contextvar token stays valid for the push/pop pair.
        with flask_core.app_context():
            try:
                gen = producer(stop_event) if _accepts_stop else producer()
                for frame in gen:
                    frame_queue.put(frame)
            except Exception:
                _log.exception("SSE producer crashed (%s)", runner_name)
                raise
            finally:
                # Single release chokepoint: fire ``on_close`` exactly once,
                # before the session teardown, covering producer crash / client
                # disconnect / normal EOF. Guarded so a release failure can never
                # escape the runner thread or skip the session cleanup below.
                if on_close is not None:
                    try:
                        on_close()
                    except Exception:  # noqa: BLE001 — release must never raise out
                        pass
                # Tear down the runner-thread's scoped session (psycopg3 conn
                # owner) on the SAME thread that used it, before its app_context
                # pops. Always emit the sentinel so the async body terminates
                # even if the producer raised before yielding it.
                db.session.remove()
                frame_queue.put(_DONE)

    async def _drain() -> AsyncIterator[str]:
        # Iterated directly in the event-loop task — NEVER holds a Flask context
        # across an await; it only pulls pre-formatted frames produced by the
        # runner thread (which owns the single, thread-local app_context).
        runner = threading.Thread(target=_run, name=runner_name, daemon=True)
        runner.start()
        try:
            while True:
                frame = await anyio.to_thread.run_sync(frame_queue.get)
                if frame is _DONE:
                    break
                yield frame
        finally:
            # Client disconnected (or the body was otherwise closed): ask an
            # opt-in producer to stop BEFORE we join, so it breaks out of its
            # token loop, runs its cancel-cleanup ``finally``, and releases its
            # pinned psycopg3 connection back to the pool right away. Legacy
            # producers ignore this and stay bounded by their own wall-clock cap.
            stop_event.set()
            # The runner tears down its session/app_context in its own finally;
            # wait for it so a client disconnect (GeneratorExit) doesn't orphan
            # the worker mid-context. Join on a worker thread so a still-running
            # producer can't block the event loop (the per-stream wall-clock caps
            # bound the worst case). ``shield`` keeps the join from being aborted
            # by the same cancellation that triggered this finally.
            with anyio.CancelScope(shield=True):
                try:
                    await anyio.to_thread.run_sync(
                        lambda: runner.join(timeout=_RUNNER_JOIN_TIMEOUT)
                    )
                except RuntimeError:
                    # Threadpool unavailable (e.g. interpreter shutdown) — fall
                    # back to a direct join so the worker still gets reaped.
                    runner.join(timeout=_RUNNER_JOIN_TIMEOUT)

    return StreamingResponse(
        _drain(),
        media_type="text/event-stream",
        headers=_make_headers(extra_headers),
    )
