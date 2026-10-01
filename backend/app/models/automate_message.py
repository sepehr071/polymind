"""Automate-agent message replay log.

Phase 4D: PG-backed via ORM ``AutomateMessage``. Legacy Mongo fields
``role``, ``type``, ``summary``, ``screenshot_url`` are folded into the
``data`` JSONB column. The ``(task_id, cursor_id)`` unique constraint
dedupes replays via ``ON CONFLICT DO NOTHING``.
"""

import uuid
from typing import Optional


def _to_uuid(val):
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except Exception:
        return None


class AutomateMessageModel:

    @classmethod
    def create(
        cls,
        task_id: str,
        cursor_id: str,
        role: str,
        type: str,
        summary: Optional[str],
        data: Optional[dict],
        screenshot_url: Optional[str],
    ) -> str:
        """Idempotent insert keyed on (task_id, cursor_id)."""
        tid = _to_uuid(task_id)
        if tid is None:
            raise ValueError(f"Invalid task_id: {task_id!r}")
        blob = dict(data or {})
        blob.update({
            'role': role,
            'type': type,
            'summary': summary,
            'screenshot_url': screenshot_url,
        })
        new_id = uuid.uuid4()
        stmt = pg_insert(AutomateMessage).values(
            id=new_id,
            task_id=tid,
            cursor_id=cursor_id,
            data=blob,
        ).on_conflict_do_nothing(index_elements=['task_id', 'cursor_id'])
        db.session.execute(stmt)
        db.session.commit()
        # Resolve the row that exists (may be the just-inserted one OR a prior).
        existing = db.session.execute(
            select(AutomateMessage.id).where(
                AutomateMessage.task_id == tid,
                AutomateMessage.cursor_id == cursor_id,
            )
        ).scalar_one_or_none()
        return str(existing) if existing else str(new_id)

    @classmethod
    def find_by_task(cls, task_id: str, limit: int = 500) -> list:
        tid = _to_uuid(task_id)
        if tid is None:
            return []
        rows = db.session.execute(
            select(AutomateMessage)
            .where(AutomateMessage.task_id == tid)
            .order_by(AutomateMessage.created_at.asc())
            .limit(limit)
        ).scalars().all()
        return [_msg_to_dict(r) for r in rows]

    @classmethod
    def delete_by_task(cls, task_id: str) -> int:
        tid = _to_uuid(task_id)
        if tid is None:
            return 0
        result = db.session.execute(
            delete(AutomateMessage).where(AutomateMessage.task_id == tid)
        )
        db.session.commit()
        return result.rowcount


def _msg_to_dict(row: 'AutomateMessage') -> dict:
    out = row.to_dict()
    out['task_id'] = str(row.task_id) if row.task_id else None
    # Surface legacy aliases from data blob.
    blob = row.data or {}
    out['role'] = blob.get('role')
    out['type'] = blob.get('type')
    out['summary'] = blob.get('summary')
    out['screenshot_url'] = blob.get('screenshot_url')
    return out


# ======================================================================
# Phase 3 — SQLAlchemy 2.0 ORM model
# ======================================================================

import uuid as _uuid_orm
from datetime import datetime as _dt_orm

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    text as _sql_text_orm,
    select,
    delete,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models._base import SerializableMixin


class AutomateMessage(db.Model, SerializableMixin):
    __tablename__ = 'automate_messages'

    id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid_orm.uuid4
    )
    task_id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('automate_tasks.id', ondelete='CASCADE'),
        nullable=False,
    )
    cursor_id: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, server_default=_sql_text_orm("'{}'::jsonb")
    )
    created_at: Mapped[_dt_orm] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_sql_text_orm('now()')
    )

    __table_args__ = (
        UniqueConstraint('task_id', 'cursor_id', name='uq_automate_messages_task_cursor'),
    )
