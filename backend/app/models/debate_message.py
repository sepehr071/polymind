"""
Debate Message Model

Stores individual messages from debaters and the judge
within a debate session.
"""

from datetime import datetime
import uuid

from bson import ObjectId
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    delete,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models._base import SerializableMixin


def _coerce_uuid(value):
    if value in (None, '', b''):
        return None
    if isinstance(value, uuid.UUID):
        return value
    if isinstance(value, ObjectId):
        return None
    if isinstance(value, (bytes, bytearray)):
        value = value.decode('utf-8', 'replace')
    if isinstance(value, str):
        try:
            return uuid.UUID(value)
        except (ValueError, AttributeError):
            return None
    return None


# Pack (round_num, order_in_round) into a single monotonically-growing
# ``order_idx`` so we can sort & filter by round without an extra column.
# Round-step of 10_000 keeps room for many turns per round while staying
# inside Postgres int range.
_ROUND_STEP = 10_000


def _pack_order_idx(round_num: int, order_in_round: int) -> int:
    return int(round_num) * _ROUND_STEP + int(order_in_round)


def _unpack_round(order_idx: int) -> tuple[int, int]:
    return divmod(int(order_idx), _ROUND_STEP)


def _serialize_message(obj) -> dict:
    if obj is None:
        return None
    out = obj.to_dict()
    raw_meta = out.pop('message_metadata', {}) or {}
    rnum, oin = _unpack_round(out.get('order_idx', 0))
    # Re-expose legacy top-level fields the route layer expects.
    out['round'] = raw_meta.pop('round', rnum)
    out['order_in_round'] = raw_meta.pop('order_in_round', oin)
    out['metadata'] = raw_meta
    return out


class DebateMessageModel:
    """Model for debate messages"""

    collection = 'debate_messages'

    @staticmethod
    def create(session_id: str, round_num: int, config_id: str, role: str,
               content: str, order_in_round: int, metadata: dict = None) -> dict:
        sid = _coerce_uuid(session_id)
        if sid is None:
            raise ValueError('session_id must coerce to UUID')

        # Stash legacy ``round`` / ``order_in_round`` inside metadata so we
        # don't lose them on re-read, and pack into the ORM's ``order_idx``.
        meta = dict(metadata or {})
        meta['round'] = int(round_num)
        meta['order_in_round'] = int(order_in_round)

        obj = DebateMessage(
            session_id=sid,
            role=role,
            content=content,
            config_id=str(config_id) if config_id is not None else None,
            message_metadata=meta,
            order_idx=_pack_order_idx(round_num, order_in_round),
        )
        db.session.add(obj)
        db.session.commit()
        return _serialize_message(obj)

    @staticmethod
    def find_by_session(session_id: str) -> list:
        sid = _coerce_uuid(session_id)
        if sid is None:
            return []
        stmt = (
            select(DebateMessage)
            .where(DebateMessage.session_id == sid)
            .order_by(DebateMessage.order_idx.asc(), DebateMessage.created_at.asc())
        )
        rows = db.session.execute(stmt).scalars().all()
        return [_serialize_message(r) for r in rows]

    @staticmethod
    def delete_by_session(session_id: str) -> int:
        sid = _coerce_uuid(session_id)
        if sid is None:
            return 0
        result = db.session.execute(
            delete(DebateMessage).where(DebateMessage.session_id == sid)
        )
        db.session.commit()
        return int(result.rowcount or 0)


# ---------------------------------------------------------------------------
# Phase 3 — SQLAlchemy 2.0 ORM model.
# ---------------------------------------------------------------------------


class DebateMessage(db.Model, SerializableMixin):
    __tablename__ = 'debate_messages'

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('debate_sessions.id', ondelete='CASCADE'),
        nullable=False,
    )
    # Polymorphic (quick:* string or UUID-as-string); no FK.
    config_id: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    role: Mapped[str] = mapped_column(db.Text, nullable=False)
    content: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    message_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    order_idx: Mapped[int] = mapped_column(db.Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('user','assistant','system','tool','debater','judge')",
            name='ck_debate_messages_role',
        ),
        # Covers find_by_session / find_by_session_and_round range scans
        # (packed round/order_in_round) + the insert-time ordering reads.
        Index(
            'ix_debate_messages_session_order',
            'session_id',
            'order_idx',
        ),
    )
