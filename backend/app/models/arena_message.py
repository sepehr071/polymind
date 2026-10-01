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


def _serialize_message(obj) -> dict:
    if obj is None:
        return None
    out = obj.to_dict()
    out['metadata'] = out.pop('message_metadata', {}) or {}
    # ``session_id`` already serialized as UUID-string by SerializableMixin.
    return out


class ArenaMessageModel:
    """Model for arena chat messages"""

    @staticmethod
    def create(session_id, role, content, config_id=None, metadata=None):
        sid = _coerce_uuid(session_id)
        if sid is None:
            raise ValueError('session_id must coerce to UUID')

        # Allocate next order_idx within this session.
        next_idx = db.session.execute(
            select(func.coalesce(func.max(ArenaMessage.order_idx), -1) + 1).where(
                ArenaMessage.session_id == sid
            )
        ).scalar()
        next_idx = int(next_idx or 0)

        obj = ArenaMessage(
            session_id=sid,
            role=role,
            content=content,
            # config_id stays a string (polymorphic quick:* + UUID).
            config_id=str(config_id) if config_id is not None else None,
            message_metadata=metadata or {},
            order_idx=next_idx,
        )
        db.session.add(obj)
        db.session.commit()
        return _serialize_message(obj)

    @staticmethod
    def find_by_session(session_id):
        sid = _coerce_uuid(session_id)
        if sid is None:
            return []
        stmt = (
            select(ArenaMessage)
            .where(ArenaMessage.session_id == sid)
            .order_by(ArenaMessage.order_idx.asc(), ArenaMessage.created_at.asc())
        )
        rows = db.session.execute(stmt).scalars().all()
        return [_serialize_message(r) for r in rows]

    @staticmethod
    def update_content_and_metadata(message_id, content, metadata):
        """Atomic content + metadata replacement for stream finalization."""
        from sqlalchemy import update as _sa_update
        mid = _coerce_uuid(message_id)
        if mid is None:
            return None
        result = db.session.execute(
            _sa_update(ArenaMessage)
            .where(ArenaMessage.id == mid)
            .values(content=content, message_metadata=metadata or {})
        )
        db.session.commit()
        return result

    @staticmethod
    def delete_by_session(session_id):
        sid = _coerce_uuid(session_id)
        if sid is None:
            return 0
        result = db.session.execute(
            delete(ArenaMessage).where(ArenaMessage.session_id == sid)
        )
        db.session.commit()
        return int(result.rowcount or 0)


# ---------------------------------------------------------------------------
# Phase 3 — SQLAlchemy 2.0 ORM model.
# ---------------------------------------------------------------------------


class ArenaMessage(db.Model, SerializableMixin):
    __tablename__ = 'arena_messages'

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('arena_sessions.id', ondelete='CASCADE'),
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
            "role IN ('user','assistant','system','tool')",
            name='ck_arena_messages_role',
        ),
        # Covers find_by_session ordering + the MAX(order_idx) probe on insert.
        Index(
            'ix_arena_messages_session_order',
            'session_id',
            'order_idx',
        ),
    )
