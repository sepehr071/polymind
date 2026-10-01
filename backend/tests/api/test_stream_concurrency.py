"""Reserve-before-response per-user cap + per-worker stream semaphore.

Covers the SSE pool-DoS hardening (perf+sec backlog):

* ``stream_state.reserve`` is TOCTOU-safe and admits exactly ``max_active``
  concurrent reservations per user (the 4th at cap=3 is rejected).
* A handler exception AFTER a successful reserve must ``clear`` the reservation
  row so the slot is not leaked (the next stream is admitted).
* The per-worker ``stream_concurrency`` BoundedSemaphore admits up to its ceiling
  and returns False at ceiling+1, then recovers after a release; over-release
  raises (the leak alarm).
* ``StreamPreflight`` composes both releases through one ``on_close`` that fires
  exactly once.

These exercise the model/service layer directly inside an app_context (no SSE
handler / OpenRouter round-trip needed). DB-backed reserve/promote/clear reuse
the shared ``flask_core`` + per-test TRUNCATE harness in conftest.
"""
from __future__ import annotations

import importlib
import uuid

import pytest

from app.services import stream_state


# ---------------------------------------------------------------------------
# Per-user reservation cap (DB-backed).
# ---------------------------------------------------------------------------
def test_reserve_admits_up_to_cap_then_rejects(flask_core, test_user):
    """The (max_active+1)-th concurrent reservation for one user is rejected."""
    uid = str(test_user["_id"])
    with flask_core.app_context():
        rids = [str(uuid.uuid4()) for _ in range(4)]
        # First 3 reservations fit under the cap.
        assert stream_state.reserve(rids[0], uid, 3) is True
        assert stream_state.reserve(rids[1], uid, 3) is True
        assert stream_state.reserve(rids[2], uid, 3) is True
        # The 4th must be rejected (cap reached) and write no row.
        assert stream_state.reserve(rids[3], uid, 3) is False
        assert stream_state.count_active(uid) == 3
        # Releasing one slot re-admits.
        stream_state.clear(rids[0])
        assert stream_state.count_active(uid) == 2
        assert stream_state.reserve(rids[3], uid, 3) is True
        assert stream_state.count_active(uid) == 3


def test_reservation_is_per_user(flask_core, test_user, plain_user):
    """One user's reservations never count against another's cap."""
    u1, u2 = str(test_user["_id"]), str(plain_user["_id"])
    with flask_core.app_context():
        for _ in range(3):
            assert stream_state.reserve(str(uuid.uuid4()), u1, 3) is True
        # u1 is at cap, but u2 starts empty.
        assert stream_state.reserve(str(uuid.uuid4()), u1, 3) is False
        assert stream_state.reserve(str(uuid.uuid4()), u2, 3) is True


def test_handler_exception_after_reserve_clears_row(flask_core, test_user):
    """A pre-stream failure after reserve must release the slot (no leak).

    Mirrors the handler wiring: ``StreamPreflight`` reserves, then a gate raises;
    ``with preflight:`` / ``preflight.release()`` clears the reservation so the
    NEXT stream is admitted.
    """
    from app.services import stream_concurrency

    uid = str(test_user["_id"])
    with flask_core.app_context():
        # Fill to cap-1, then a reservation that "fails" mid-handler.
        assert stream_state.reserve(str(uuid.uuid4()), uid, 3) is True
        assert stream_state.reserve(str(uuid.uuid4()), uid, 3) is True

        preflight = stream_concurrency.StreamPreflight(uid, 3)
        assert preflight.reserve() is True
        assert stream_state.count_active(uid) == 3  # now at cap

        # Simulate a DLP/spend gate raising after the reserve.
        try:
            with preflight:
                raise RuntimeError("simulated pre-stream gate failure")
        except RuntimeError:
            pass

        # The failed reservation was cleared -> back under cap, next admitted.
        assert stream_state.count_active(uid) == 2
        assert stream_state.reserve(str(uuid.uuid4()), uid, 3) is True


def test_promote_rekeys_reserved_row(flask_core, test_user):
    """promote swaps the reservation_id key to the message_id (no double-count)."""
    uid = str(test_user["_id"])
    with flask_core.app_context():
        rid = str(uuid.uuid4())
        msg_id = str(uuid.uuid4())
        assert stream_state.reserve(rid, uid, 3) is True
        assert stream_state.count_active(uid) == 1
        stream_state.promote(rid, msg_id)
        # Same row, re-keyed: still exactly one active stream, now owned by msg_id.
        assert stream_state.count_active(uid) == 1
        assert stream_state.owner_of(msg_id) == uid
        assert stream_state.owner_of(rid) is None


# ---------------------------------------------------------------------------
# Per-worker global stream semaphore (in-process, no DB).
# ---------------------------------------------------------------------------
@pytest.fixture
def low_ceiling_concurrency(monkeypatch):
    """Re-import stream_concurrency with a tiny ceiling for deterministic tests."""
    monkeypatch.setenv("MAX_CONCURRENT_STREAMS_PER_WORKER", "2")
    import app.services.stream_concurrency as sc

    sc = importlib.reload(sc)
    try:
        yield sc
    finally:
        # Restore the module-level semaphore to the default ceiling for any other
        # test that imports it after this one.
        monkeypatch.delenv("MAX_CONCURRENT_STREAMS_PER_WORKER", raising=False)
        importlib.reload(sc)


def test_global_semaphore_503_at_ceiling_then_recovers(low_ceiling_concurrency):
    sc = low_ceiling_concurrency
    assert sc.available() == 2
    assert sc.try_acquire() is True
    assert sc.try_acquire() is True
    # ceiling+1 is refused (handler returns 503).
    assert sc.try_acquire() is False
    # Releasing one permit re-admits the next stream.
    sc.release()
    assert sc.try_acquire() is True
    sc.release()
    sc.release()
    assert sc.available() == 2


def test_global_semaphore_over_release_raises(low_ceiling_concurrency):
    """BoundedSemaphore raises on over-release — the double-release/leak alarm."""
    sc = low_ceiling_concurrency
    with pytest.raises(ValueError):
        sc.release()  # nothing was acquired


def test_preflight_on_close_releases_both_once(low_ceiling_concurrency, flask_core, test_user):
    """on_close drops the reservation row AND returns the permit, exactly once."""
    sc = low_ceiling_concurrency
    uid = str(test_user["_id"])
    with flask_core.app_context():
        preflight = sc.StreamPreflight(uid, 3)
        assert preflight.reserve() is True
        assert preflight.acquire_global() is True
        assert sc.available() == 1
        assert stream_state.count_active(uid) == 1

        preflight.hand_off()  # ownership -> on_close
        # __exit__ must NOT release after hand_off.
        with preflight:
            pass
        assert sc.available() == 1
        assert stream_state.count_active(uid) == 1

        # on_close releases both.
        preflight.on_close()
        assert sc.available() == 2
        assert stream_state.count_active(uid) == 0

        # A second on_close must not over-release the permit (guarded).
        preflight.on_close()
        assert sc.available() == 2
