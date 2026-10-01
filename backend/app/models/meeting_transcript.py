"""
MeetingTranscriptModel — diarized transcript for a meeting.

Phase 4D: backed by Postgres (ORM `MeetingTranscript`). Mongo dict-shape
preserved on read. 1:1 with meetings via UNIQUE(meeting_id) constraint.
"""

import uuid


def _to_uuid(val):
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except Exception:
        return None


class MeetingTranscriptModel:
    collection_name = 'meeting_transcripts'

    # ------------------------------------------------------------------
    # CRUD — PG-backed
    # ------------------------------------------------------------------

    @staticmethod
    def create(meeting_id: str, data: dict) -> str:
        """Upsert a transcript row keyed by meeting_id. Returns meeting_id."""
        mid = _to_uuid(meeting_id)
        if mid is None:
            raise ValueError(f"Invalid meeting_id: {meeting_id!r}")

        raw_json = data.get('raw_json', {})
        plain_text = data.get('plain_text', '')
        words_json = data.get('words_json', [])
        language_code = data.get('language_code', 'fas')

        stmt = pg_insert(MeetingTranscript).values(
            meeting_id=mid,
            raw_text=plain_text,
            raw_json=raw_json,
            words_json=words_json,
            language_code=language_code,
        ).on_conflict_do_update(
            index_elements=['meeting_id'],
            set_=dict(
                raw_text=plain_text,
                raw_json=raw_json,
                words_json=words_json,
                language_code=language_code,
            ),
        )
        db.session.execute(stmt)
        db.session.commit()
        return str(mid)

    @staticmethod
    def find_by_id(meeting_id: str) -> dict | None:
        """Mongo `_id` was the meeting_id itself, so this is meeting-keyed lookup."""
        return MeetingTranscriptModel.find_by_meeting(meeting_id)

    @staticmethod
    def find_by_meeting(meeting_id: str) -> dict | None:
        mid = _to_uuid(meeting_id)
        if mid is None:
            return None
        row = db.session.execute(
            select(MeetingTranscript).where(MeetingTranscript.meeting_id == mid)
        ).scalar_one_or_none()
        return _transcript_to_dict(row) if row else None

    @staticmethod
    def update(meeting_id: str, data: dict) -> bool:
        if not data:
            return False
        mid = _to_uuid(meeting_id)
        if mid is None:
            return False
        translated: dict = {}
        for k, v in data.items():
            if k == 'plain_text':
                translated['raw_text'] = v
            elif k in ('raw_json', 'words_json', 'language_code', 'raw_text'):
                translated[k] = v
        if not translated:
            return False
        result = db.session.execute(
            update(MeetingTranscript)
            .where(MeetingTranscript.meeting_id == mid)
            .values(**translated)
        )
        db.session.commit()
        return result.rowcount > 0

    @staticmethod
    def delete(meeting_id: str) -> bool:
        mid = _to_uuid(meeting_id)
        if mid is None:
            return False
        result = db.session.execute(
            delete(MeetingTranscript).where(MeetingTranscript.meeting_id == mid)
        )
        db.session.commit()
        return result.rowcount > 0


def _transcript_to_dict(row: 'MeetingTranscript') -> dict:
    out = row.to_dict()
    # Legacy alias: callers expect `plain_text` (Mongo field name).
    out['plain_text'] = row.raw_text
    out['meeting_id'] = str(row.meeting_id) if row.meeting_id else None
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
    update,
    delete,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models._base import SerializableMixin


class MeetingTranscript(db.Model, SerializableMixin):
    __tablename__ = 'meeting_transcripts'

    id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid_orm.uuid4
    )
    meeting_id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('meetings.id', ondelete='CASCADE'),
        nullable=False,
    )
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, server_default=_sql_text_orm("'{}'::jsonb")
    )
    words_json: Mapped[list | None] = mapped_column(
        JSONB, nullable=True, server_default=_sql_text_orm("'[]'::jsonb")
    )
    language_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[_dt_orm] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_sql_text_orm('now()')
    )

    __table_args__ = (
        UniqueConstraint('meeting_id', name='uq_meeting_transcripts_meeting_id'),
    )
