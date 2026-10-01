"""OCR assistant job history.

One row per extract run. ``files`` JSONB holds per-upload status + markdown.
List projection strips ``content`` so the rail stays light.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import CheckConstraint, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models._base import SerializableMixin

VALID_STATUS = ('running', 'done', 'failed', 'cancelled')


def _to_uuid(val):
    if val in (None, '', b''):
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except (ValueError, TypeError, AttributeError):
        return None


def job_title(prompt: str = '', files: list | None = None) -> str:
    for f in files or []:
        name = (f.get('original_name') or '').strip()
        if name:
            extra = max(len(files) - 1, 0)
            return f"{name} +{extra}" if extra else name[:80]
    p = (prompt or '').strip()
    return p[:80] if p else 'OCR'


def _list_files(files) -> list:
    out = []
    for f in files or []:
        out.append({
            'upload_id': f.get('upload_id'),
            'original_name': f.get('original_name'),
            'status': f.get('status'),
        })
    return out


class OcrJob(db.Model, SerializableMixin):
    __tablename__ = 'ocr_jobs'

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default='')
    title: Mapped[str] = mapped_column(Text, nullable=False, default='OCR')
    status: Mapped[str] = mapped_column(Text, nullable=False, default='running')
    files: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
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
            "status IN ('running','done','failed','cancelled')",
            name='ck_ocr_jobs_status',
        ),
        Index('ix_ocr_jobs_user_created', 'user_id', 'created_at'),
    )

    def to_dict(self) -> dict:
        out = super().to_dict()
        out['files'] = list(self.files or [])
        return out

    def to_list_dict(self) -> dict:
        out = self.to_dict()
        out['files'] = _list_files(out.get('files'))
        return out


class OcrJobModel:
    @staticmethod
    def create(*, user_id, workspace_id=None, prompt='', files=None, status='running') -> dict:
        stubs = list(files or [])
        row = OcrJob(
            user_id=_to_uuid(user_id),
            workspace_id=_to_uuid(workspace_id),
            prompt=prompt or '',
            title=job_title(prompt, stubs),
            status=status,
            files=stubs,
        )
        db.session.add(row)
        db.session.commit()
        return row.to_dict()

    @staticmethod
    def find_by_id_for_user(job_id, user_id) -> Optional[dict]:
        row = db.session.get(OcrJob, _to_uuid(job_id))
        if not row or str(row.user_id) != str(user_id):
            return None
        return row.to_dict()

    @staticmethod
    def list_for_user(user_id, *, limit=50) -> list[dict]:
        uid = _to_uuid(user_id)
        if uid is None:
            return []
        rows = (
            db.session.query(OcrJob)
            .filter(OcrJob.user_id == uid)
            .order_by(OcrJob.created_at.desc())
            .limit(min(int(limit or 50), 100))
            .all()
        )
        return [r.to_list_dict() for r in rows]

    @staticmethod
    def update(job_id, **fields) -> Optional[dict]:
        row = db.session.get(OcrJob, _to_uuid(job_id))
        if not row:
            return None
        if 'workspace_id' in fields and isinstance(fields['workspace_id'], str):
            fields['workspace_id'] = _to_uuid(fields['workspace_id'])
        for k, v in fields.items():
            if hasattr(row, k):
                setattr(row, k, v)
        if 'files' in fields or 'prompt' in fields:
            row.title = job_title(row.prompt, row.files)
        row.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        return row.to_dict()

    @staticmethod
    def patch_file(job_id, upload_id, **fields) -> Optional[dict]:
        row = db.session.get(OcrJob, _to_uuid(job_id))
        if not row:
            return None
        files = [dict(f) for f in (row.files or [])]
        found = False
        for i, f in enumerate(files):
            if str(f.get('upload_id')) == str(upload_id):
                files[i] = {**f, **fields}
                found = True
                break
        if not found:
            files.append({'upload_id': upload_id, **fields})
        row.files = files
        row.title = job_title(row.prompt, files)
        row.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        return row.to_dict()

    @staticmethod
    def delete_for_user(job_id, user_id) -> bool:
        row = db.session.get(OcrJob, _to_uuid(job_id))
        if not row or str(row.user_id) != str(user_id):
            return False
        db.session.delete(row)
        db.session.commit()
        return True
