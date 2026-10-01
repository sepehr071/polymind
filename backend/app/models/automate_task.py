"""Automate-agent tasks.

Phase 4D: PG-backed via ORM ``AutomateTask``. Mongo fields ``task_text``,
``model``, ``session_id``, ``live_url``, ``output``, ``error``,
``message_count`` are folded into the ``result`` JSONB column (with
``task_text`` aliased to the ``prompt`` column). ``external_task_id``
carries the upstream session_id.
"""

import uuid
from datetime import datetime, timezone
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


class AutomateTaskModel:
    @classmethod
    def create(cls, user_id: str, task_text: str, model: str) -> str:
        uid = _to_uuid(user_id)
        if uid is None:
            raise ValueError(f"Invalid user_id: {user_id!r}")
        row = AutomateTask(
            user_id=uid,
            prompt=task_text,
            status='pending',
            external_task_id=None,
            result={
                'model': model,
                'task_text': task_text,
                'session_id': None,
                'live_url': None,
                'output': None,
                'error': None,
                'message_count': 0,
            },
        )
        db.session.add(row)
        db.session.commit()
        return str(row.id)

    @classmethod
    def find_by_id(cls, task_id: str) -> Optional[dict]:
        tid = _to_uuid(task_id)
        if tid is None:
            return None
        row = db.session.get(AutomateTask, tid)
        return _task_to_dict(row) if row else None

    @classmethod
    def find_by_user(cls, user_id: str, limit: int = 50, skip: int = 0) -> list:
        uid = _to_uuid(user_id)
        if uid is None:
            return []
        rows = db.session.execute(
            select(AutomateTask)
            .where(AutomateTask.user_id == uid)
            .order_by(AutomateTask.created_at.desc())
            .offset(skip)
            .limit(limit)
        ).scalars().all()
        return [_task_to_dict(r) for r in rows]

    @classmethod
    def count_by_user(cls, user_id: str) -> int:
        uid = _to_uuid(user_id)
        if uid is None:
            return 0
        return int(
            db.session.execute(
                select(func.count(AutomateTask.id)).where(AutomateTask.user_id == uid)
            ).scalar() or 0
        )

    @classmethod
    def count_active_by_user(cls, user_id: str) -> int:
        """Count pending+running tasks for a user — concurrent-cap gate."""
        uid = _to_uuid(user_id)
        if uid is None:
            return 0
        return int(
            db.session.execute(
                select(func.count(AutomateTask.id)).where(
                    AutomateTask.user_id == uid,
                    AutomateTask.status.in_(['pending', 'running']),
                )
            ).scalar() or 0
        )

    @classmethod
    def count_created_since(cls, user_id: str, since) -> int:
        """Count tasks created on/after *since* — daily-quota gate."""
        uid = _to_uuid(user_id)
        if uid is None:
            return 0
        return int(
            db.session.execute(
                select(func.count(AutomateTask.id)).where(
                    AutomateTask.user_id == uid,
                    AutomateTask.created_at >= since,
                )
            ).scalar() or 0
        )

    @classmethod
    def find_expired_running(cls, now=None) -> list:
        """Find rows whose deadline_at has elapsed; used by the sweeper."""
        if now is None:
            now = datetime.now(timezone.utc)
        # deadline_at lives in `result` blob.
        rows = db.session.execute(
            select(AutomateTask).where(
                AutomateTask.status.in_(['pending', 'running']),
                AutomateTask.result['deadline_at'].astext != None,  # noqa: E711
            )
        ).scalars().all()
        out = []
        for r in rows:
            deadline_str = (r.result or {}).get('deadline_at')
            if not deadline_str:
                continue
            try:
                if isinstance(deadline_str, str):
                    deadline = datetime.fromisoformat(deadline_str.replace('Z', '+00:00'))
                else:
                    deadline = deadline_str
                if deadline <= now:
                    out.append(_task_to_dict(r))
            except (ValueError, TypeError):
                continue
        return out

    @classmethod
    def update(cls, task_id: str, updates: dict) -> bool:
        tid = _to_uuid(task_id)
        if tid is None or not updates:
            return False
        row = db.session.get(AutomateTask, tid)
        if row is None:
            return False
        result_blob = dict(row.result or {})
        column_changes: dict = {'updated_at': datetime.now(timezone.utc)}
        for k, v in updates.items():
            if k == 'status':
                column_changes['status'] = v
            elif k == 'session_id':
                # Promote to top-level external_task_id, AND keep on result blob.
                column_changes['external_task_id'] = v
                result_blob['session_id'] = v
            elif k == 'task_text':
                column_changes['prompt'] = v
                result_blob['task_text'] = v
            else:
                # All other legacy fields (live_url, output, error, message_count, model, ...)
                # stay in the JSONB result blob.
                result_blob[k] = v
        column_changes['result'] = result_blob
        for col, val in column_changes.items():
            setattr(row, col, val)
        flag_modified(row, 'result')
        db.session.commit()
        return True

    @classmethod
    def delete(cls, task_id: str, user_id: str) -> bool:
        tid = _to_uuid(task_id)
        uid = _to_uuid(user_id)
        if tid is None or uid is None:
            return False
        # Cascade delete via FK (automate_messages.task_id ON DELETE CASCADE)
        # already covers child rows — no manual cascade needed.
        result = db.session.execute(
            delete(AutomateTask).where(
                AutomateTask.id == tid,
                AutomateTask.user_id == uid,
            )
        )
        db.session.commit()
        return result.rowcount > 0

    @classmethod
    def set_session(cls, task_id: str, session_id: str, live_url: Optional[str]) -> bool:
        return cls.update(task_id, {"session_id": session_id, "live_url": live_url})

    @classmethod
    def set_status(
        cls,
        task_id: str,
        status: str,
        error: Optional[str] = None,
        output: Optional[str] = None,
    ) -> bool:
        updates: dict = {"status": status}
        if error is not None:
            updates["error"] = error
        if output is not None:
            updates["output"] = output
        return cls.update(task_id, updates)

    @classmethod
    def increment_message_count(cls, task_id: str, delta: int = 1) -> bool:
        # TODO: phase 7 — no message_count column on the new schema. Phase 5
        # callers should COUNT(*) FROM automate_messages WHERE task_id = ?
        # at read time instead of maintaining a denormalised counter.
        return False


def _task_to_dict(row: 'AutomateTask') -> dict:
    out = row.to_dict()
    out['user_id'] = str(row.user_id) if row.user_id else None
    # Legacy field aliases — surface from the result blob.
    blob = row.result or {}
    out['task_text'] = blob.get('task_text', row.prompt)
    out['model'] = blob.get('model')
    out['session_id'] = blob.get('session_id') or row.external_task_id
    out['live_url'] = blob.get('live_url')
    out['output'] = blob.get('output')
    out['error'] = blob.get('error')
    out['message_count'] = int(blob.get('message_count') or 0)
    return out


# ======================================================================
# Phase 3 — SQLAlchemy 2.0 ORM model
# ======================================================================

import uuid as _uuid_orm
from datetime import datetime as _dt_orm

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    text as _sql_text_orm,
    select,
    delete,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm.attributes import flag_modified

from app.extensions import db
from app.models._base import SerializableMixin


class AutomateTask(db.Model, SerializableMixin):
    __tablename__ = 'automate_tasks'

    id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid_orm.uuid4
    )
    user_id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    external_task_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, server_default=_sql_text_orm("'{}'::jsonb")
    )
    created_at: Mapped[_dt_orm] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_sql_text_orm('now()')
    )
    updated_at: Mapped[_dt_orm] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_sql_text_orm('now()')
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','completed','failed','cancelled','stopped','error','timed_out')",
            name='ck_automate_tasks_status',
        ),
        Index(
            'ix_automate_tasks_user_created',
            'user_id',
            _sql_text_orm('created_at DESC'),
        ),
    )
