"""Cross-worker stream-generation state (P0.2) — PG-backed.

Replaces the legacy Mongo ``stream_generation_state`` collection. ``expires_at``
is enforced via a periodic sweep instead of Mongo's TTL index — call
``StreamStateModel.sweep_expired()`` from a scheduled task.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    delete as sa_delete,
    func,
    select,
    text as sa_text,
    update as sa_update,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID as PG_UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models._base import SerializableMixin


class StreamState(db.Model, SerializableMixin):
    __tablename__ = 'stream_generation_state'

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    cancelled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )

    __table_args__ = (
        UniqueConstraint('session_id', name='uq_stream_state_session_id'),
        Index('ix_stream_state_expires', 'expires_at'),
    )


# Reservation rows live until the stream's ``clear``/``on_close`` deletes them.
# Their TTL is the cap's safety net: if a stream outlives the TTL the row is
# sweep-eligible and the active-count would UNDER-count (admitting an over-cap
# stream). So the reservation TTL must exceed the longest a single stream can run
# — the chat/arena/debate wall-clock cap is 1800s and the SSE runner-join cap is
# also 1800s — plus a buffer. 2100s = 1800 wall-clock + 300 buffer.
_RESERVATION_TTL_SECONDS = 2100


def _to_uuid(val):
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except (ValueError, TypeError, AttributeError):
        return None


class StreamStateModel:
    @staticmethod
    def register(session_id: str, ttl_seconds: int = 300, user_id: Optional[str] = None) -> None:
        """Mark a session as active. Resets ``cancelled`` to False on re-register."""
        now = datetime.now(timezone.utc)
        stmt = pg_insert(StreamState).values(
            id=uuid.uuid4(),
            session_id=str(session_id),
            user_id=_to_uuid(user_id),
            cancelled=False,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        ).on_conflict_do_update(
            constraint='uq_stream_state_session_id',
            set_={
                'cancelled': False,
                'user_id': _to_uuid(user_id),
                'created_at': now,
                'expires_at': now + timedelta(seconds=ttl_seconds),
            },
        )
        try:
            db.session.execute(stmt)
            db.session.commit()
        except Exception:
            db.session.rollback()

    @staticmethod
    def try_reserve(
        session_id: str,
        user_id: Optional[str],
        max_active: int,
        ttl_seconds: int = _RESERVATION_TTL_SECONDS,
    ) -> bool:
        """Atomically reserve a stream slot for ``user_id`` (closes the cap TOCTOU).

        Runs count-then-insert in ONE transaction guarded by a per-user
        ``pg_advisory_xact_lock`` so two concurrent opens can't both read
        ``count < max_active`` and both insert (the bug ``count_active`` +
        ``register`` had — the count ran in the handler but the row was written
        later, inside the producer, after the response started). The advisory
        lock is held until the transaction commits, serializing the
        check-and-insert across all workers on the same Postgres.

        Inserts a reservation row (same schema as ``register``, ``cancelled``
        False so ``count_active`` counts it) keyed by ``session_id``
        (= a handler-minted ``reservation_id``) IFF the user is under
        ``max_active``. ``promote`` later swaps the key to the real message_id so
        the cancel-by-message-id path still resolves the row.

        Returns True when the slot was reserved (row inserted), False when the
        user is already at the cap (caller returns 429). A null user_id is never
        capped (returns True without writing — anonymous/system streams aren't
        per-user limited).
        """
        uid = _to_uuid(user_id)
        if uid is None:
            return True
        now = datetime.now(timezone.utc)
        try:
            # Per-user advisory lock — serialize count+insert against other opens
            # for THIS user. hashtext() -> int4 is an acceptable lock-key space
            # (collisions only over-serialize unrelated users, never miscount).
            db.session.execute(
                sa_text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
                {"k": f"stream_cap:{uid}"},
            )
            count = db.session.execute(
                select(func.count())
                .select_from(StreamState)
                .where(
                    StreamState.user_id == uid,
                    StreamState.cancelled.is_(False),
                    StreamState.expires_at > now,
                )
            ).scalar_one_or_none()
            if int(count or 0) >= max_active:
                # Release the advisory lock by ending the txn; no row written.
                db.session.rollback()
                return False
            db.session.execute(
                pg_insert(StreamState).values(
                    id=uuid.uuid4(),
                    session_id=str(session_id),
                    user_id=uid,
                    cancelled=False,
                    created_at=now,
                    expires_at=now + timedelta(seconds=ttl_seconds),
                )
            )
            db.session.commit()
            return True
        except Exception:
            db.session.rollback()
            # Fail-open: a DB hiccup in the speed-bump must not block the stream.
            return True

    @staticmethod
    def promote(reservation_id: str, message_id: str) -> None:
        """Re-key a reserved row from the handler's reservation_id to message_id.

        Lets the producer keep using ``register``/``is_cancelled``/``clear`` and
        the cancel endpoint keep resolving by message_id, while the row that was
        already counted at reserve time is the SAME row (no double-count, no gap).
        ``register(message_id, ...)`` in the producer then refreshes it (TTL bump
        / cancelled reset) via the ``session_id`` unique-constraint upsert.
        """
        try:
            db.session.execute(
                sa_update(StreamState)
                .where(StreamState.session_id == str(reservation_id))
                .values(session_id=str(message_id))
            )
            db.session.commit()
        except Exception:
            db.session.rollback()

    @staticmethod
    def mark_cancelled(session_id: str) -> bool:
        try:
            result = db.session.execute(
                sa_update(StreamState)
                .where(StreamState.session_id == str(session_id))
                .values(cancelled=True)
            )
            db.session.commit()
            return (result.rowcount or 0) > 0
        except Exception:
            db.session.rollback()
            return False

    @staticmethod
    def is_cancelled(session_id: str) -> bool:
        try:
            row = db.session.execute(
                select(StreamState.cancelled).where(StreamState.session_id == str(session_id))
            ).scalar_one_or_none()
            # End the implicit read transaction. On psycopg3 a SELECT with no
            # commit/rollback leaves the connection ``idle in transaction`` for
            # the whole stream — holding xmin and blocking VACUUM. Rollback is
            # the cheapest way to return the connection to plain ``idle``; it
            # cannot lose committed writes done elsewhere in the producer (those
            # open + commit their own transactions).
            db.session.rollback()
            return bool(row)
        except Exception:
            db.session.rollback()
            return False

    @staticmethod
    def clear(session_id: str) -> None:
        try:
            db.session.execute(
                sa_delete(StreamState).where(StreamState.session_id == str(session_id))
            )
            db.session.commit()
        except Exception:
            db.session.rollback()

    @staticmethod
    def count_active(user_id: str) -> int:
        """Count this user's live streams — rows not yet expired and not cancelled.

        Backs the per-user concurrent-stream cap (DoS guard). ``register`` writes
        the row a stream counts against (resetting ``cancelled`` + bumping
        ``expires_at``), and the producer's ``clear`` deletes it on exit, so an
        in-flight stream contributes exactly one row here. A tiny race (two
        opens checking at once) is acceptable for a speed-bump.
        """
        uid = _to_uuid(user_id)
        if uid is None:
            return 0
        now = datetime.now(timezone.utc)
        try:
            count = db.session.execute(
                select(func.count())
                .select_from(StreamState)
                .where(
                    StreamState.user_id == uid,
                    StreamState.cancelled.is_(False),
                    StreamState.expires_at > now,
                )
            ).scalar_one_or_none()
            # End the implicit read transaction (see ``is_cancelled``) so the
            # connection does not linger ``idle in transaction``.
            db.session.rollback()
            return int(count or 0)
        except Exception:
            db.session.rollback()
            return 0

    @staticmethod
    def owner_of(session_id: str) -> Optional[str]:
        try:
            uid = db.session.execute(
                select(StreamState.user_id).where(StreamState.session_id == str(session_id))
            ).scalar_one_or_none()
            # End the implicit read transaction (see ``is_cancelled``) so the
            # connection does not linger ``idle in transaction``.
            db.session.rollback()
            return str(uid) if uid else None
        except Exception:
            db.session.rollback()
            return None

    @staticmethod
    def sweep_expired() -> int:
        """Delete rows whose ``expires_at`` has elapsed. Returns deleted count."""
        now = datetime.now(timezone.utc)
        try:
            result = db.session.execute(
                sa_delete(StreamState).where(StreamState.expires_at < now)
            )
            db.session.commit()
            return result.rowcount or 0
        except Exception:
            db.session.rollback()
            return 0
