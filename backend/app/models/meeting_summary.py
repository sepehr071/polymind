"""
MeetingSummaryModel — generated summary artifacts for a meeting.

Phase 4D: backed by Postgres (ORM `MeetingSummary`).

Columns drop the `_json` suffix per `_serialize_summary` frontend contract:
    Mongo: action_items_json / decisions_json / minutes_json / qa_json /
           open_questions_json
    PG   : action_items     / decisions     / minutes     / qa     /
           open_questions
Façade accepts EITHER suffixed (legacy) or unsuffixed kwargs in ``data``.
"""

import uuid


VALID_EMAIL_TONES = {'formal', 'casual'}


def _to_uuid(val):
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except Exception:
        return None


class MeetingSummaryModel:
    collection_name = 'meeting_summaries'

    # ------------------------------------------------------------------
    # CRUD — PG-backed
    # ------------------------------------------------------------------

    @staticmethod
    def create(meeting_id: str, data: dict) -> str:
        """Insert a new summary row. Returns the inserted _id (UUID string)."""
        mid = _to_uuid(meeting_id)
        if mid is None:
            raise ValueError(f"Invalid meeting_id: {meeting_id!r}")

        email_tone = data.get('email_tone')
        if email_tone is not None and email_tone not in VALID_EMAIL_TONES:
            raise ValueError(f"Invalid email_tone: {email_tone}")

        # Accept both suffixed (legacy) + unsuffixed kwargs.
        action_items = data.get('action_items', data.get('action_items_json')) or []
        decisions = data.get('decisions', data.get('decisions_json')) or []
        minutes = data.get('minutes', data.get('minutes_json')) or []
        qa = data.get('qa', data.get('qa_json')) or []
        open_questions = data.get('open_questions', data.get('open_questions_json')) or []
        speaker_names = data.get('speaker_names') or []

        model_used = data.get('model_used') or data.get('model')
        if not model_used:
            raise KeyError('model')

        row = MeetingSummary(
            meeting_id=mid,
            exec_summary=data.get('exec_summary', ''),
            action_items=action_items,
            decisions=decisions,
            minutes=minutes,
            qa=qa,
            open_questions=open_questions,
            speaker_names=speaker_names,
            email_draft=data.get('email_draft'),
            tone=email_tone or data.get('tone'),
            model_used=model_used,
            memo=data.get('memo'),
        )
        db.session.add(row)
        db.session.commit()
        return str(row.id)

    @staticmethod
    def find_by_id(summary_id) -> dict | None:
        sid = _to_uuid(summary_id)
        if sid is None:
            return None
        row = db.session.get(MeetingSummary, sid)
        return _summary_to_dict(row) if row else None

    @staticmethod
    def find_latest_for_meeting(meeting_id: str) -> dict | None:
        return MeetingSummaryModel.latest_for_meeting(meeting_id)

    @staticmethod
    def latest_for_meeting(meeting_id: str) -> dict | None:
        mid = _to_uuid(meeting_id)
        if mid is None:
            return None
        row = db.session.execute(
            select(MeetingSummary)
            .where(MeetingSummary.meeting_id == mid)
            .order_by(MeetingSummary.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        return _summary_to_dict(row) if row else None

    @staticmethod
    def delete(summary_id) -> bool:
        sid = _to_uuid(summary_id)
        if sid is None:
            return False
        result = db.session.execute(
            delete(MeetingSummary).where(MeetingSummary.id == sid)
        )
        db.session.commit()
        return result.rowcount > 0

    @staticmethod
    def delete_for_meeting(meeting_id: str) -> int:
        mid = _to_uuid(meeting_id)
        if mid is None:
            return 0
        result = db.session.execute(
            delete(MeetingSummary).where(MeetingSummary.meeting_id == mid)
        )
        db.session.commit()
        return result.rowcount


def _summary_to_dict(row: 'MeetingSummary') -> dict:
    out = row.to_dict()
    # Backwards-compat alias: callers + `_serialize_summary` accept either form.
    out['meeting_id'] = str(row.meeting_id) if row.meeting_id else None
    out['email_tone'] = row.tone
    out['model'] = row.model_used
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
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models._base import SerializableMixin


class MeetingSummary(db.Model, SerializableMixin):
    __tablename__ = 'meeting_summaries'

    id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid_orm.uuid4
    )
    meeting_id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('meetings.id', ondelete='CASCADE'),
        nullable=False,
    )
    exec_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_draft: Mapped[str | None] = mapped_column(Text, nullable=True)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_items: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=_sql_text_orm("'[]'::jsonb")
    )
    decisions: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=_sql_text_orm("'[]'::jsonb")
    )
    qa: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=_sql_text_orm("'[]'::jsonb")
    )
    open_questions: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=_sql_text_orm("'[]'::jsonb")
    )
    minutes: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=_sql_text_orm("'[]'::jsonb")
    )
    speaker_names: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=_sql_text_orm("'[]'::jsonb")
    )
    model_used: Mapped[str | None] = mapped_column(Text, nullable=True)
    tone: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[_dt_orm] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_sql_text_orm('now()')
    )

    __table_args__ = (
        CheckConstraint(
            "tone IS NULL OR tone IN ('formal','casual')",
            name='ck_meeting_summaries_tone',
        ),
        Index(
            'ix_meeting_summaries_meeting_created',
            'meeting_id',
            _sql_text_orm('created_at DESC'),
        ),
    )
