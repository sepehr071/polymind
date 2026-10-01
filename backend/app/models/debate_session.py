"""
Debate Session Model

Stores debate sessions where multiple AI configs discuss a topic
with a judge that synthesizes the final verdict.
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
    text,
    update,
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

    Legacy doc had top-level ``judge_config_id``, ``current_round``,
    ``final_verdict``. ORM stores debate-specific knobs inside the JSONB
    ``settings`` blob and verdict as a dedicated ``verdict`` column. Re-expose
    the legacy keys on the wire so routes/streams keep reading them.
    """
    if obj is None:
        return None
    out = obj.to_dict()
    settings = out.get('settings') or {}
    out['judge_config_id'] = settings.get('judge_config_id')
    out['current_round'] = settings.get('current_round', 0)
    out['final_verdict'] = out.get('verdict')
    return out


class DebateSessionModel:
    """Model for multi-config debate sessions"""

    collection = 'debate_sessions'

    @staticmethod
    def create(user_id: str, topic: str, config_ids: list, judge_config_id: str,
               rounds: int = 3, max_tokens: int = 2048,
               thinking_type: str = 'balanced', response_length: str = 'balanced') -> dict:
        uid = _coerce_uuid(user_id)
        if uid is None:
            raise ValueError('user_id must coerce to UUID')

        cfgs = [str(c) for c in (config_ids or [])]
        judge = str(judge_config_id) if judge_config_id is not None else None

        settings = {
            'rounds': rounds,
            'max_tokens': max_tokens,
            'thinking_type': thinking_type,
            'response_length': response_length,
            'judge_config_id': judge,
            'current_round': 0,
        }
        obj = DebateSession(
            user_id=uid,
            topic=topic,
            status='pending',
            config_ids=cfgs,
            settings=settings,
            verdict=None,
        )
        db.session.add(obj)
        db.session.commit()
        return _serialize_session(obj)

    @staticmethod
    def find_by_user(user_id: str, page: int = 1, limit: int = 20) -> list:
        uid = _coerce_uuid(user_id)
        if uid is None:
            return []
        skip = max(0, (int(page) - 1)) * int(limit)
        stmt = (
            select(DebateSession)
            .where(DebateSession.user_id == uid)
            .order_by(DebateSession.updated_at.desc())
            .offset(skip)
            .limit(int(limit))
        )
        rows = db.session.execute(stmt).scalars().all()
        return [_serialize_session(r) for r in rows]

    @staticmethod
    def count_by_user(user_id: str) -> int:
        uid = _coerce_uuid(user_id)
        if uid is None:
            return 0
        return int(
            db.session.execute(
                select(func.count()).select_from(DebateSession).where(
                    DebateSession.user_id == uid
                )
            ).scalar()
            or 0
        )

    @staticmethod
    def find_by_id(session_id: str) -> dict:
        sid = _coerce_uuid(session_id)
        if sid is None:
            return None
        obj = db.session.get(DebateSession, sid)
        return _serialize_session(obj) if obj is not None else None

    @staticmethod
    def update_status(session_id: str, status: str, current_round: int = None) -> bool:
        sid = _coerce_uuid(session_id)
        if sid is None:
            return False
        obj = db.session.get(DebateSession, sid)
        if obj is None:
            return False
        obj.status = status
        if current_round is not None:
            settings = dict(obj.settings or {})
            settings['current_round'] = int(current_round)
            obj.settings = settings
            flag_modified(obj, 'settings')
        obj.updated_at = datetime.utcnow()
        db.session.commit()
        return True

    @staticmethod
    def set_verdict(session_id: str, verdict: str) -> bool:
        sid = _coerce_uuid(session_id)
        if sid is None:
            return False
        result = db.session.execute(
            update(DebateSession)
            .where(DebateSession.id == sid)
            .values(
                verdict=verdict,
                status='completed',
                updated_at=datetime.utcnow(),
            )
        )
        db.session.commit()
        return (result.rowcount or 0) > 0

    @staticmethod
    def delete(session_id: str, user_id: str) -> bool:
        sid = _coerce_uuid(session_id)
        uid = _coerce_uuid(user_id)
        if sid is None or uid is None:
            return False
        result = db.session.execute(
            delete(DebateSession).where(
                DebateSession.id == sid,
                DebateSession.user_id == uid,
            )
        )
        db.session.commit()
        return (result.rowcount or 0) > 0


# ---------------------------------------------------------------------------
# Phase 3 — SQLAlchemy 2.0 ORM model.
#
# `config_ids` polymorphic (mix of `quick:*` strings + UUIDs) stored JSONB +
# GIN-indexed. `settings` holds debate config (rounds, judge config, etc).
# ---------------------------------------------------------------------------


class DebateSession(db.Model, SerializableMixin):
    __tablename__ = 'debate_sessions'

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
    settings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    verdict: Mapped[str | None] = mapped_column(db.Text, nullable=True)
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
        # Widened in migration 0002 to cover the full session lifecycle the
        # debate routes/streams actually write.
        CheckConstraint(
            "status IN ('active','pending','in_progress','completed','cancelled','error')",
            name='ck_debate_sessions_status',
        ),
        Index(
            'ix_debate_sessions_config_ids',
            'config_ids',
            postgresql_using='gin',
            postgresql_ops={'config_ids': 'jsonb_path_ops'},
        ),
    )
