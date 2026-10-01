"""Uploads — user-uploaded files (images / documents).

The ``uploads`` table replaces the legacy Mongo ``uploads`` collection.
This was overlooked in Phase 3's inventory; added under Phase 6.5.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    Text,
    delete as sa_delete,
    func,
    select,
    text as sa_text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models._base import SerializableMixin
from app.utils.ids import to_uuid


class Upload(db.Model, SerializableMixin):
    __tablename__ = 'uploads'

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    original_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    type: Mapped[str] = mapped_column(Text, nullable=False, default='file')
    thumbnail_filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    force_attachment: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # Extracted document text (markitdown → Markdown) for chat attachments.
    # ``extraction_status`` ∈ {'ok','truncated','error','unavailable','na'};
    # NULL for images / non-extractable types.
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_chars: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sa_text('0')
    )
    extraction_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index('ix_uploads_user_created', 'user_id', 'created_at'),
    )


class UploadModel:
    """Façade for the uploads table."""

    @staticmethod
    def create(*, user_id, filename, original_name, mime_type, size, type,
               thumbnail_filename=None, force_attachment=False,
               extracted_text=None, extracted_chars=0, extraction_status=None):
        row = Upload(
            id=uuid.uuid4(),
            user_id=to_uuid(user_id),
            filename=filename,
            original_name=original_name,
            mime_type=mime_type,
            size=int(size or 0),
            type=type,
            thumbnail_filename=thumbnail_filename,
            force_attachment=bool(force_attachment),
            extracted_text=extracted_text,
            extracted_chars=int(extracted_chars or 0),
            extraction_status=extraction_status,
            created_at=datetime.utcnow(),
        )
        db.session.add(row)
        db.session.commit()
        return row.to_dict()

    @staticmethod
    def find_by_id(upload_id):
        try:
            uid = to_uuid(upload_id)
        except (ValueError, TypeError):
            return None
        row = db.session.execute(
            select(Upload).where(Upload.id == uid)
        ).scalar_one_or_none()
        return row.to_dict() if row else None

    @staticmethod
    def find_by_id_for_user(upload_id, user_id):
        """Owner-scoped variant of :meth:`find_by_id`.

        Resolves the upload ONLY when it belongs to ``user_id``. Returns
        ``None`` on a malformed id, a missing row, OR a cross-user mismatch —
        the cross-tenant IDOR guard for every path that inlines upload bytes
        into a chat/data turn from a client-supplied ``upload_id``.
        """
        try:
            uid = to_uuid(upload_id)
            owner = to_uuid(user_id)
        except (ValueError, TypeError):
            return None
        row = db.session.execute(
            select(Upload).where(Upload.id == uid, Upload.user_id == owner)
        ).scalar_one_or_none()
        return row.to_dict() if row else None

    @staticmethod
    def get_extracted_text(upload_id):
        """Narrow lookup of just the extraction fields (no full-row hydration).

        Returns ``{'extracted_text','extracted_chars','extraction_status'}`` or
        ``None`` if the upload id is malformed / not found.
        """
        try:
            uid = to_uuid(upload_id)
        except (ValueError, TypeError):
            return None
        row = db.session.execute(
            select(
                Upload.extracted_text,
                Upload.extracted_chars,
                Upload.extraction_status,
            ).where(Upload.id == uid)
        ).one_or_none()
        if row is None:
            return None
        return {
            'extracted_text': row.extracted_text,
            'extracted_chars': row.extracted_chars,
            'extraction_status': row.extraction_status,
        }

    @staticmethod
    def get_extracted_text_for_user(upload_id, user_id):
        """Owner-scoped variant of :meth:`get_extracted_text`.

        Returns the extraction fields ONLY when the upload belongs to
        ``user_id``; ``None`` on malformed id / missing row / cross-user
        mismatch. Used by the attachment-inlining path so a client cannot
        replay another user's extracted document text into the model context.
        """
        try:
            uid = to_uuid(upload_id)
            owner = to_uuid(user_id)
        except (ValueError, TypeError):
            return None
        row = db.session.execute(
            select(
                Upload.extracted_text,
                Upload.extracted_chars,
                Upload.extraction_status,
            ).where(Upload.id == uid, Upload.user_id == owner)
        ).one_or_none()
        if row is None:
            return None
        return {
            'extracted_text': row.extracted_text,
            'extracted_chars': row.extracted_chars,
            'extraction_status': row.extraction_status,
        }

    @staticmethod
    def set_extracted_text(upload_id, user_id, text, chars, status):
        """Owner-scoped write-back of the extraction fields.

        Used by the Data Analyzer ingestion path to cache a PDF/image
        transcription on the upload row so a follow-up turn (or a re-attach of
        the same file) reuses it instead of re-running the paid OCR call. The
        ``user_id`` guard mirrors the read-side ``*_for_user`` lookups: a foreign
        upload id resolves to zero rows and returns ``False``. Returns whether a
        row was updated.
        """
        try:
            uid = to_uuid(upload_id)
            owner = to_uuid(user_id)
        except (ValueError, TypeError):
            return False
        result = db.session.execute(
            db.update(Upload)
            .where(Upload.id == uid, Upload.user_id == owner)
            .values(
                extracted_text=text,
                extracted_chars=int(chars or 0),
                extraction_status=status,
            )
        )
        db.session.commit()
        return bool(result.rowcount)

    @staticmethod
    def delete(upload_id):
        try:
            uid = to_uuid(upload_id)
        except (ValueError, TypeError):
            return 0
        result = db.session.execute(
            sa_delete(Upload).where(Upload.id == uid)
        )
        db.session.commit()
        return result.rowcount or 0

    @staticmethod
    def find_by_user(user_id, skip=0, limit=20):
        try:
            uid = to_uuid(user_id)
        except (ValueError, TypeError):
            return []
        rows = db.session.execute(
            select(Upload)
            .where(Upload.user_id == uid)
            .order_by(Upload.created_at.desc())
            .offset(skip)
            .limit(limit)
        ).scalars().all()
        return [r.to_dict() for r in rows]

    @staticmethod
    def count_by_user(user_id):
        try:
            uid = to_uuid(user_id)
        except (ValueError, TypeError):
            return 0
        return int(db.session.execute(
            select(func.count())
            .select_from(Upload)
            .where(Upload.user_id == uid)
        ).scalar() or 0)
