"""
HelperConversationModel — persistent rolling history for the in-app Helper guide.

One row per user (unique constraint on user_id). Messages are stored in the
child ``helper_messages`` table; older turns aren't trimmed at write time —
``rolling_window`` slices the tail for prompt builds so callers control the
context size cheaply without rewriting the whole history.
"""
from datetime import datetime
import uuid
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    UniqueConstraint,
    delete,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import (
    JSONB,
    TIMESTAMP,
    UUID as PG_UUID,
    insert as pg_insert,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models._base import SerializableMixin


def _coerce_uuid(value):
    if value in (None, '', b''):
        return None
    if isinstance(value, uuid.UUID):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode('utf-8', 'replace')
    if isinstance(value, str):
        try:
            return uuid.UUID(value)
        except (ValueError, AttributeError):
            return None
    return None


def _serialize_message_row(row: 'HelperMessage') -> dict:
    """Re-emit child-row in the legacy embedded-message dict shape.

    Legacy doc: ``{role, content, page_context, deep_links, created_at}``.
    The ORM stores ``page_context`` / ``deep_links`` inside the parent
    ``context`` column when set on the FIRST message; for per-message
    storage they ride along in metadata-less child rows (not modelled in
    Phase 3 ORM). We surface ``None`` for those two so callers don't crash
    if they expect the keys.
    """
    return {
        'role': row.role,
        'content': row.content,
        'page_context': None,
        'deep_links': None,
        'created_at': row.created_at.isoformat() if row.created_at else None,
    }


class HelperConversationModel:
    collection_name = 'helper_conversations'

    @staticmethod
    def _coerce_user_id(user_id):
        # Kept for callers that import this helper directly.
        return _coerce_uuid(user_id)

    @staticmethod
    def _get_or_create_parent(user_id_uuid: uuid.UUID) -> 'HelperConversation':
        """Get-or-create the parent row. Single-statement upsert via PG insert."""
        now = datetime.utcnow()
        stmt = (
            pg_insert(HelperConversation)
            .values(
                user_id=user_id_uuid,
                context=None,
                last_message_at=now,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=['user_id'],
                set_={'updated_at': now, 'last_message_at': now},
            )
            .returning(HelperConversation.id)
        )
        result = db.session.execute(stmt).first()
        db.session.flush()
        if result is None:
            # Fallback (shouldn't fire because RETURNING is always emitted on
            # PG ON CONFLICT DO UPDATE).
            return db.session.execute(
                select(HelperConversation).where(
                    HelperConversation.user_id == user_id_uuid
                )
            ).scalar_one()
        return db.session.execute(
            select(HelperConversation).where(
                HelperConversation.id == result[0]
            )
        ).scalar_one()

    @staticmethod
    def append_message(
        user_id,
        role: str,
        content: str,
        page_context: Optional[dict] = None,
        deep_links: Optional[list] = None,
    ) -> bool:
        """Atomically append a message to the user's helper conversation.

        Upserts the parent row, then INSERTs a child ``helper_messages`` row
        with monotonically-allocated ``order_idx``.
        """
        uid = _coerce_uuid(user_id)
        if uid is None:
            return False

        parent = HelperConversationModel._get_or_create_parent(uid)

        # Compute next order_idx within this conversation.
        next_idx = db.session.execute(
            select(func.coalesce(func.max(HelperMessage.order_idx), -1) + 1).where(
                HelperMessage.helper_conversation_id == parent.id
            )
        ).scalar()
        next_idx = int(next_idx or 0)

        msg = HelperMessage(
            helper_conversation_id=parent.id,
            role=role,
            content=content,
            order_idx=next_idx,
        )
        db.session.add(msg)
        db.session.commit()
        return True

    @staticmethod
    def clear(user_id) -> bool:
        """Delete the user's helper conversation. Next append recreates it.

        Cascades to child ``helper_messages`` rows via FK ondelete='CASCADE'.
        """
        uid = _coerce_uuid(user_id)
        if uid is None:
            return False
        result = db.session.execute(
            delete(HelperConversation).where(HelperConversation.user_id == uid)
        )
        db.session.commit()
        return (result.rowcount or 0) > 0

    @staticmethod
    def rolling_window(user_id, n: int = 30) -> list:
        """Return the last ``n`` messages (chronological) for prompt building."""
        uid = _coerce_uuid(user_id)
        if uid is None or n <= 0:
            return []
        parent = db.session.execute(
            select(HelperConversation).where(HelperConversation.user_id == uid)
        ).scalar_one_or_none()
        if parent is None:
            return []

        # Tail N: DESC + LIMIT + reverse.
        rows = db.session.execute(
            select(HelperMessage)
            .where(HelperMessage.helper_conversation_id == parent.id)
            .order_by(HelperMessage.order_idx.desc())
            .limit(int(n))
        ).scalars().all()
        rows = list(rows)
        rows.reverse()
        return [_serialize_message_row(r) for r in rows]

    @staticmethod
    def get_history(user_id) -> list:
        """Return the full message list for the /history endpoint."""
        uid = _coerce_uuid(user_id)
        if uid is None:
            return []
        parent = db.session.execute(
            select(HelperConversation).where(HelperConversation.user_id == uid)
        ).scalar_one_or_none()
        if parent is None:
            return []
        rows = db.session.execute(
            select(HelperMessage)
            .where(HelperMessage.helper_conversation_id == parent.id)
            .order_by(HelperMessage.order_idx.asc())
        ).scalars().all()
        return [_serialize_message_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Phase 3 — SQLAlchemy 2.0 ORM models.
#
# Mongo doc embedded ``messages[]`` array (atomic $push). Normalized into
# child table ``helper_messages`` for relational + indexability.
# ---------------------------------------------------------------------------


class HelperConversation(db.Model, SerializableMixin):
    __tablename__ = 'helper_conversations'

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # UNIQUE so 1 helper conversation per user (Mongo enforced via unique index).
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint('user_id', name='uq_helper_conversations_user'),
    )


class HelperMessage(db.Model, SerializableMixin):
    __tablename__ = 'helper_messages'

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    helper_conversation_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('helper_conversations.id', ondelete='CASCADE'),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(db.Text, nullable=False)
    content: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    order_idx: Mapped[int] = mapped_column(db.BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('user','assistant','system')",
            name='ck_helper_messages_role',
        ),
        UniqueConstraint(
            'helper_conversation_id', 'order_idx',
            name='uq_helper_messages_conv_order',
        ),
    )
