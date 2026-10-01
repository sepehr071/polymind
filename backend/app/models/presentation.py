"""AI presentation generator records.

A ``presentations`` row tracks one generated deck through its lifecycle
(``draft`` -> ``outlining`` -> ``outline_ready`` -> ``rendering`` -> ``ready``
or ``failed``). The outline + render options live in JSONB; the rendered PPTX
is stored as an ``uploads`` row referenced by ``pptx_upload_id`` (FK-free, like
the other polymorphic-ish refs in this codebase). The ``XxxModel`` façade
returns the legacy ``_id``-keyed dict shape via ``SerializableMixin``.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Index,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models._base import SerializableMixin

# Lifecycle states. Mirror the CHECK constraint in migration 0018 and the
# frontend status map — a new value needs all three updated + a migration.
VALID_STATUS = (
    'draft',
    'outlining',
    'outline_ready',
    'rendering',
    'ready',
    'failed',
)


def _to_uuid(val):
    """Coerce id input (str/UUID) to UUID; None on falsy."""
    if val in (None, '', b''):
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except (ValueError, TypeError, AttributeError):
        return None


class Presentation(db.Model, SerializableMixin):
    __tablename__ = 'presentations'

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False, default='')
    status: Mapped[str] = mapped_column(Text, nullable=False, default='draft')
    language: Mapped[str] = mapped_column(Text, nullable=False, default='fa')
    theme: Mapped[str] = mapped_column(Text, nullable=False, default='polymind')
    options: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    outline: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    pptx_upload_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
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
            "status IN ('draft','outlining','outline_ready','rendering','ready','failed')",
            name='ck_presentations_status',
        ),
        Index('ix_presentations_user_created', 'user_id', 'created_at'),
    )

    def to_dict(self) -> dict:
        # SerializableMixin emits every column + the `_id` alias and stringifies
        # UUIDs/datetimes; just normalize the JSONB blobs to {} when NULL.
        out = super().to_dict()
        out['options'] = self.options or {}
        out['outline'] = self.outline or {}
        return out


class PresentationModel:
    @staticmethod
    def create(*, user_id, workspace_id=None, project_id=None, title='',
               language='fa', theme='polymind', options=None, outline=None,
               status='draft') -> dict:
        row = Presentation(
            user_id=_to_uuid(user_id),
            workspace_id=_to_uuid(workspace_id),
            project_id=_to_uuid(project_id),
            title=title,
            language=language,
            theme=theme,
            options=options or {},
            outline=outline or {},
            status=status,
        )
        db.session.add(row)
        # session_scope()/request dep remove WITHOUT committing — a bare flush()
        # would be rolled back. Commit (flushes first) so the write persists.
        db.session.commit()
        return row.to_dict()

    @staticmethod
    def find_by_id(pid) -> Optional[dict]:
        row = db.session.get(Presentation, _to_uuid(pid))
        return row.to_dict() if row else None

    @staticmethod
    def find_by_id_for_user(pid, user_id) -> Optional[dict]:
        row = db.session.get(Presentation, _to_uuid(pid))
        if not row or str(row.user_id) != str(user_id):
            return None
        return row.to_dict()

    @staticmethod
    def list_for_user(user_id, *, project_id=None, limit=50) -> list[dict]:
        q = db.session.query(Presentation).filter(
            Presentation.user_id == _to_uuid(user_id)
        )
        if project_id:
            q = q.filter(Presentation.project_id == _to_uuid(project_id))
        rows = q.order_by(Presentation.created_at.desc()).limit(limit).all()
        return [r.to_dict() for r in rows]

    @staticmethod
    def update(pid, **fields) -> Optional[dict]:
        row = db.session.get(Presentation, _to_uuid(pid))
        if not row:
            return None
        # Coerce id-bearing fields to UUID so a string id doesn't rely on the
        # dialect adapter's luck (mirrors ConversationModel.update).
        _ID_FIELDS = ('user_id', 'workspace_id', 'project_id', 'pptx_upload_id')
        for k, v in fields.items():
            if k in _ID_FIELDS and isinstance(v, str):
                v = _to_uuid(v)
            if hasattr(row, k):
                setattr(row, k, v)
        db.session.commit()
        return row.to_dict()

    @staticmethod
    def delete(pid) -> bool:
        row = db.session.get(Presentation, _to_uuid(pid))
        if row:
            db.session.delete(row)
            db.session.commit()
        return bool(row)
