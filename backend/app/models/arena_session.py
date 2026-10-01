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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm.attributes import flag_modified

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


def _serialize_session(obj) -> dict:
    """Bridge Mongo wire shape.

    - ``topic`` (ORM) aliased back to ``title`` so the route layer's
      ``session['title']`` keeps working.
    - ``session_metadata`` (ORM) aliased back to ``metadata``.
    """
    if obj is None:
        return None
    out = obj.to_dict()
    out['title'] = out.get('topic')
    out['metadata'] = out.pop('session_metadata', {}) or {}
    return out


class ArenaSessionModel:
    """Model for multi-config arena sessions"""

    @staticmethod
    def create(user_id, config_ids, title='Arena Session'):
        uid = _coerce_uuid(user_id)
        if uid is None:
            raise ValueError('user_id must coerce to UUID')

        # config_ids stays polymorphic (quick:* + UUID strings) in JSONB array.
        cfgs = [str(c) for c in (config_ids or [])]

        obj = ArenaSession(
            user_id=uid,
            topic=title,
            status='active',
            config_ids=cfgs,
            session_metadata={},
        )
        db.session.add(obj)
        db.session.commit()
        return _serialize_session(obj)

    @staticmethod
    def find_by_id(session_id):
        sid = _coerce_uuid(session_id)
        if sid is None:
            return None
        obj = db.session.get(ArenaSession, sid)
        return _serialize_session(obj) if obj is not None else None

    @staticmethod
    def find_by_user(user_id, skip=0, limit=20):
        uid = _coerce_uuid(user_id)
        if uid is None:
            return []
        stmt = (
            select(ArenaSession)
            .where(ArenaSession.user_id == uid)
            .order_by(ArenaSession.updated_at.desc())
            .offset(skip)
            .limit(limit)
        )
        rows = db.session.execute(stmt).scalars().all()
        return [_serialize_session(r) for r in rows]

    @staticmethod
    def count_by_user(user_id):
        uid = _coerce_uuid(user_id)
        if uid is None:
            return 0
        return int(
            db.session.execute(
                select(func.count()).select_from(ArenaSession).where(
                    ArenaSession.user_id == uid
                )
            ).scalar()
            or 0
        )

    @staticmethod
    def update(session_id, updates):
        """Generic $set; routes pass ``title`` / ``project_id`` / etc.

        Maps legacy ``title`` → ORM ``topic``. Ignores fields the ORM doesn't
        have (e.g. ``project_id`` — arena_sessions are personal-scope in ORM).
        """
        sid = _coerce_uuid(session_id)
        if sid is None:
            return None
        obj = db.session.get(ArenaSession, sid)
        if obj is None:
            return None
        for k, v in (updates or {}).items():
            if k == 'title':
                obj.topic = v
                continue
            if k == 'metadata':
                obj.session_metadata = v or {}
                flag_modified(obj, 'session_metadata')
                continue
            if hasattr(obj, k):
                setattr(obj, k, v)
        obj.updated_at = datetime.utcnow()
        db.session.commit()
        return obj

    @staticmethod
    def delete(session_id):
        sid = _coerce_uuid(session_id)
        if sid is None:
            return False
        result = db.session.execute(
            delete(ArenaSession).where(ArenaSession.id == sid)
        )
        db.session.commit()
        return (result.rowcount or 0) > 0


# ---------------------------------------------------------------------------
# Phase 3 — SQLAlchemy 2.0 ORM model.
#
# `config_ids` is polymorphic (mix of `quick:*` synthetic strings and real
# UUID strings); stored as JSONB array w/ GIN index. No FK.
# `metadata` is reserved on SQLAlchemy; column is named `session_metadata`.
# ---------------------------------------------------------------------------


class ArenaSession(db.Model, SerializableMixin):
    __tablename__ = 'arena_sessions'

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    topic: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    status: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    config_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    session_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
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
        CheckConstraint(
            "status IN ('active','completed','error')",
            name='ck_arena_sessions_status',
        ),
        Index(
            'ix_arena_sessions_config_ids',
            'config_ids',
            postgresql_using='gin',
            postgresql_ops={'config_ids': 'jsonb_path_ops'},
        ),
    )
