"""
MeetingModel — top-level meeting document.

Phase 4D: backed by Postgres (SQLAlchemy ORM `Meeting`). Public API
signatures preserved verbatim; return shape stays the Mongo dict with
``_id`` as string (via `to_dict()`). `bson`/`mongo` imports retained per
Phase 7 cleanup contract.

Original Mongo doc schema (kept here for reference; not used at runtime):
  _id                 str   (UUID4)
  owner_id            ObjectId
  title               str | None
  status              'uploaded' | 'transcribing' | 'summarizing' | 'done' | 'failed'
  original_filename   str
  audio_path          str
  language            str   default 'fas'
  duration_s          float | None
  num_speakers        int | None
  meeting_brief       str | None
  series_id           str | None
  error_message       str | None
  speakers            list[{speaker_id, display_name}]
  latest_summary_id   ObjectId | None
  created_at, updated_at
"""

import uuid
from datetime import datetime, timezone


MEETING_STATUS = {
    'UPLOADED': 'uploaded',
    'TRANSCRIBING': 'transcribing',
    'SUMMARIZING': 'summarizing',
    'DONE': 'done',
    'FAILED': 'failed',
    'CANCELLED': 'cancelled',
}

VALID_MEETING_STATUSES = set(MEETING_STATUS.values())

DEFAULT_LANGUAGE = 'fas'


def _to_uuid(val):
    """Accept either a UUID instance or a string and return a UUID. None -> None."""
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except Exception:
        return None


class MeetingModel:
    collection_name = 'meetings'

    # ------------------------------------------------------------------
    # CRUD — PG-backed
    # ------------------------------------------------------------------

    @staticmethod
    def create(owner_id: str, data: dict) -> str:
        """Insert a new meeting row. Returns the inserted _id (UUID string)."""
        status = data.get('status', MEETING_STATUS['UPLOADED'])
        if status not in VALID_MEETING_STATUSES:
            raise ValueError(f"Invalid meeting status: {status}")

        meeting_uuid = _to_uuid(data.get('_id')) or uuid.uuid4()
        owner_uuid = _to_uuid(owner_id)
        series_uuid = _to_uuid(data.get('series_id'))

        m = Meeting(
            id=meeting_uuid,
            owner_user_id=owner_uuid,
            series_id=series_uuid,
            title=data.get('title'),
            status=status,
            audio_path=data.get('audio_path'),
            audio_url=data.get('audio_url'),
            duration_s=int(data['duration_s']) if data.get('duration_s') is not None else None,
            transcript_language=data.get('language', DEFAULT_LANGUAGE),
            email_tone=data.get('email_tone'),
            error=data.get('error_message'),
        )
        db.session.add(m)
        db.session.commit()

        # Optional embedded-speaker bootstrap (mirrors legacy `speakers` arg).
        speakers = data.get('speakers') or []
        for idx, s in enumerate(speakers):
            db.session.add(MeetingSpeaker(
                meeting_id=meeting_uuid,
                speaker_label=s['speaker_id'],
                display_name=s.get('display_name'),
                order_idx=idx,
            ))
        if speakers:
            db.session.commit()

        return str(meeting_uuid)

    @staticmethod
    def find_by_id(meeting_id: str) -> dict | None:
        mid = _to_uuid(meeting_id)
        if mid is None:
            return None
        row = db.session.get(Meeting, mid)
        return _meeting_to_dict(row) if row else None

    @staticmethod
    def find_owned(meeting_id: str, owner_id: str) -> dict | None:
        mid = _to_uuid(meeting_id)
        oid = _to_uuid(owner_id)
        if mid is None or oid is None:
            return None
        row = db.session.execute(
            select(Meeting).where(Meeting.id == mid, Meeting.owner_user_id == oid)
        ).scalar_one_or_none()
        return _meeting_to_dict(row) if row else None

    @staticmethod
    def list_for_user(
        owner_id: str,
        series_id: str | None = None,
        q: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list:
        oid = _to_uuid(owner_id)
        if oid is None:
            return []
        stmt = select(Meeting).where(Meeting.owner_user_id == oid)
        sid = _to_uuid(series_id) if series_id else None
        if sid is not None:
            stmt = stmt.where(Meeting.series_id == sid)
        if q:
            stmt = stmt.where(Meeting.title.ilike(f'%{q}%'))
        stmt = stmt.order_by(Meeting.created_at.desc()).offset(skip).limit(limit)
        rows = db.session.execute(stmt).scalars().all()
        # Batch-load speakers for the whole page in ONE query to avoid an N+1
        # (was one MeetingSpeaker SELECT per row via _meeting_to_dict).
        speakers_map = _speakers_for_meetings([r.id for r in rows])
        return [_meeting_to_dict(r, speakers_map=speakers_map) for r in rows]

    @staticmethod
    def update(meeting_id: str, owner_id: str, data: dict) -> bool:
        if not data:
            return False
        if 'status' in data and data['status'] not in VALID_MEETING_STATUSES:
            raise ValueError(f"Invalid meeting status: {data['status']}")
        mid = _to_uuid(meeting_id)
        oid = _to_uuid(owner_id)
        if mid is None or oid is None:
            return False

        # Translate legacy field names → ORM column names.
        translated: dict = {}
        for k, v in data.items():
            if k == 'error_message':
                translated['error'] = v
            elif k == 'language':
                translated['transcript_language'] = v
            elif k == 'series_id':
                translated['series_id'] = _to_uuid(v)
            elif k in ('latest_summary_id', 'speakers', 'num_speakers', 'meeting_brief'):
                # Not modelled on the ORM table (latest_summary derives from
                # meeting_summaries.created_at; speakers live in meeting_speakers).
                continue
            else:
                translated[k] = v
        translated['updated_at'] = datetime.now(timezone.utc)

        result = db.session.execute(
            update(Meeting)
            .where(Meeting.id == mid, Meeting.owner_user_id == oid)
            .values(**translated)
        )
        db.session.commit()
        return result.rowcount > 0

    @staticmethod
    def count_for_series(owner_id: str, series_id: str) -> int:
        """Count meetings belonging to *owner_id* that point at *series_id*."""
        oid = _to_uuid(owner_id)
        sid = _to_uuid(series_id)
        if oid is None or sid is None:
            return 0
        return int(db.session.execute(
            select(func.count()).select_from(Meeting).where(
                Meeting.owner_user_id == oid,
                Meeting.series_id == sid,
            )
        ).scalar() or 0)

    @staticmethod
    def count_by_series_for_owner(owner_id: str, series_ids=None) -> dict:
        """Return ``{series_id_str: count}`` for an owner in ONE grouped query.

        Replaces the per-series N+1 (`count_for_series` in a loop). When
        *series_ids* is supplied, scopes the GROUP BY to that list; otherwise
        counts every non-NULL series for the owner. NULL-series meetings are
        excluded (they belong to no series).
        """
        oid = _to_uuid(owner_id)
        if oid is None:
            return {}
        stmt = (
            select(Meeting.series_id, func.count().label('cnt'))
            .where(Meeting.owner_user_id == oid, Meeting.series_id.isnot(None))
            .group_by(Meeting.series_id)
        )
        if series_ids is not None:
            sids = [s for s in (_to_uuid(x) for x in series_ids) if s is not None]
            if not sids:
                return {}
            stmt = stmt.where(Meeting.series_id.in_(sids))
        rows = db.session.execute(stmt).all()
        return {str(r.series_id): int(r.cnt or 0) for r in rows}

    @staticmethod
    def null_series_for_owner(owner_id: str, series_id: str) -> int:
        """Reset ``series_id`` to NULL on all *owner_id* meetings pointing
        at *series_id*. Used during series delete cascade."""
        oid = _to_uuid(owner_id)
        sid = _to_uuid(series_id)
        if oid is None or sid is None:
            return 0
        result = db.session.execute(
            update(Meeting).where(
                Meeting.owner_user_id == oid,
                Meeting.series_id == sid,
            ).values(
                series_id=None,
                updated_at=datetime.now(timezone.utc),
            )
        )
        db.session.commit()
        return result.rowcount or 0

    @staticmethod
    def set_status(
        meeting_id: str,
        status: str,
        error_message: str | None = None,
    ) -> bool:
        if status not in VALID_MEETING_STATUSES:
            raise ValueError(f"Invalid meeting status: {status}")
        mid = _to_uuid(meeting_id)
        if mid is None:
            return False
        values: dict = {'status': status, 'updated_at': datetime.now(timezone.utc)}
        if error_message is not None:
            values['error'] = error_message
        result = db.session.execute(
            update(Meeting).where(Meeting.id == mid).values(**values)
        )
        db.session.commit()
        return result.rowcount > 0

    @staticmethod
    def set_language(meeting_id: str, language: str) -> bool:
        """Set ``transcript_language`` on a meeting without an owner check.

        Used from the background transcription pipeline, where ownership
        was already verified by the route that scheduled the thread.
        """
        if not language:
            return False
        mid = _to_uuid(meeting_id)
        if mid is None:
            return False
        result = db.session.execute(
            update(Meeting).where(Meeting.id == mid).values(
                transcript_language=language,
                updated_at=datetime.now(timezone.utc),
            )
        )
        db.session.commit()
        return result.rowcount > 0

    @staticmethod
    def set_latest_summary(meeting_id: str, summary_id) -> bool:
        """No-op on PG — "latest summary" is derived via ORDER BY created_at DESC
        on `meeting_summaries`. Kept as a no-op so legacy callers don't crash."""
        mid = _to_uuid(meeting_id)
        if mid is None:
            return False
        result = db.session.execute(
            update(Meeting).where(Meeting.id == mid).values(
                updated_at=datetime.now(timezone.utc)
            )
        )
        db.session.commit()
        return result.rowcount > 0

    @staticmethod
    def upsert_speakers(meeting_id: str, speakers: list[dict]) -> bool:
        """Replace the speakers list for a meeting. Mirrors Mongo `$set speakers`."""
        mid = _to_uuid(meeting_id)
        if mid is None:
            return False
        # Wipe + re-add (small N — typically <10 per meeting).
        db.session.execute(
            delete(MeetingSpeaker).where(MeetingSpeaker.meeting_id == mid)
        )
        for idx, s in enumerate(speakers or []):
            db.session.add(MeetingSpeaker(
                meeting_id=mid,
                speaker_label=s['speaker_id'],
                display_name=s.get('display_name'),
                order_idx=idx,
            ))
        db.session.execute(
            update(Meeting).where(Meeting.id == mid).values(
                updated_at=datetime.now(timezone.utc)
            )
        )
        db.session.commit()
        return True

    @staticmethod
    def add_speaker(meeting_id: str, label: str, display_name: str | None = None) -> bool:
        """Append a new speaker row with order_idx = MAX+1."""
        mid = _to_uuid(meeting_id)
        if mid is None:
            return False
        next_idx_row = db.session.execute(
            select(func.coalesce(func.max(MeetingSpeaker.order_idx), -1) + 1)
            .where(MeetingSpeaker.meeting_id == mid)
        ).scalar()
        next_idx = int(next_idx_row or 0)
        db.session.add(MeetingSpeaker(
            meeting_id=mid,
            speaker_label=label,
            display_name=display_name,
            order_idx=next_idx,
        ))
        db.session.commit()
        return True

    @staticmethod
    def update_speaker_display_name(meeting_id: str, label: str, new_name: str | None) -> bool:
        mid = _to_uuid(meeting_id)
        if mid is None:
            return False
        result = db.session.execute(
            update(MeetingSpeaker)
            .where(MeetingSpeaker.meeting_id == mid,
                   MeetingSpeaker.speaker_label == label)
            .values(display_name=new_name, updated_at=datetime.now(timezone.utc))
        )
        db.session.commit()
        return result.rowcount > 0

    @staticmethod
    def set_speaker_name(meeting_id: str, speaker_id: str, display_name: str | None) -> bool:
        """Legacy positional-`$` mirror — update if present, else add."""
        ok = MeetingModel.update_speaker_display_name(meeting_id, speaker_id, display_name)
        if ok:
            return True
        return MeetingModel.add_speaker(meeting_id, speaker_id, display_name)

    @staticmethod
    def cancel(meeting_id: str) -> bool:
        """Flip cancel_requested + status='cancelled'. Used by the cancel route."""
        mid = _to_uuid(meeting_id)
        if mid is None:
            return False
        result = db.session.execute(
            update(Meeting).where(Meeting.id == mid).values(
                cancel_requested=True,
                status='cancelled',
                updated_at=datetime.now(timezone.utc),
            )
        )
        db.session.commit()
        return result.rowcount > 0

    @staticmethod
    def search_by_title(owner_id: str, q: str, limit: int = 25) -> list:
        oid = _to_uuid(owner_id)
        if oid is None or not q or not q.strip():
            return []
        stmt = (
            select(Meeting)
            .where(Meeting.owner_user_id == oid, Meeting.title.ilike(f'%{q.strip()}%'))
            .order_by(Meeting.created_at.desc())
            .limit(limit)
        )
        rows = db.session.execute(stmt).scalars().all()
        speakers_map = _speakers_for_meetings([r.id for r in rows])
        return [_meeting_to_dict(r, speakers_map=speakers_map) for r in rows]

    @staticmethod
    def delete(meeting_id: str, owner_id: str) -> bool:
        mid = _to_uuid(meeting_id)
        oid = _to_uuid(owner_id)
        if mid is None or oid is None:
            return False
        result = db.session.execute(
            delete(Meeting).where(Meeting.id == mid, Meeting.owner_user_id == oid)
        )
        db.session.commit()
        return result.rowcount > 0


def _speakers_for_meetings(meeting_ids) -> dict:
    """Batch-fetch speakers for a list of meetings in ONE query.

    Returns ``{meeting_id (uuid): [ {speaker_id, display_name}, ... ]}`` ordered
    by ``order_idx``. Used by the list/search paths to avoid an N+1 (one
    MeetingSpeaker SELECT per meeting via `_meeting_to_dict`).
    """
    ids = [m for m in (meeting_ids or []) if m is not None]
    if not ids:
        return {}
    out: dict = {}
    try:
        rows = db.session.execute(
            select(MeetingSpeaker)
            .where(MeetingSpeaker.meeting_id.in_(ids))
            .order_by(MeetingSpeaker.meeting_id.asc(), MeetingSpeaker.order_idx.asc())
        ).scalars().all()
        for s in rows:
            out.setdefault(s.meeting_id, []).append(
                {'speaker_id': s.speaker_label, 'display_name': s.display_name}
            )
    except Exception:
        return {}
    return out


def _meeting_to_dict(row: 'Meeting', speakers_map: dict | None = None) -> dict:
    """Mongo-compatible payload: includes legacy alias fields the routes / pipeline
    still read (`owner_id`, `language`, `error_message`, `speakers[]`).

    When *speakers_map* is provided (built by `_speakers_for_meetings`), the
    embedded speakers list is read from it instead of issuing a per-row query —
    this is how the list/search paths avoid an N+1. The single-meeting path
    (map omitted) falls back to its own SELECT.
    """
    out = row.to_dict()
    # Legacy aliases the rest of the app still reads on the dict shape.
    out['owner_id'] = str(row.owner_user_id) if row.owner_user_id else None
    out['language'] = row.transcript_language
    out['error_message'] = row.error
    out['series_id'] = str(row.series_id) if row.series_id else None
    # Embedded speakers list — derived from meeting_speakers join.
    if speakers_map is not None:
        out['speakers'] = speakers_map.get(row.id, [])
        return out
    try:
        spkrs = db.session.execute(
            select(MeetingSpeaker)
            .where(MeetingSpeaker.meeting_id == row.id)
            .order_by(MeetingSpeaker.order_idx.asc())
        ).scalars().all()
        out['speakers'] = [
            {'speaker_id': s.speaker_label, 'display_name': s.display_name}
            for s in spkrs
        ]
    except Exception:
        out['speakers'] = []
    return out


# ======================================================================
# Phase 3 — SQLAlchemy 2.0 ORM models
# ======================================================================

import uuid as _uuid_orm
from datetime import datetime as _dt_orm

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text as _sql_text_orm,
    select,
    update,
    delete,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID  # noqa: F401
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models._base import SerializableMixin


VALID_MEETING_STATUSES_PG = (
    'uploaded',
    'transcribing',
    'summarizing',
    'done',
    'failed',
    'cancelled',
)

VALID_EMAIL_TONES_PG = ('formal', 'casual')


class Meeting(db.Model, SerializableMixin):
    __tablename__ = 'meetings'

    id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid_orm.uuid4
    )
    owner_user_id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    series_id: Mapped[_uuid_orm.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('meeting_series.id', ondelete='SET NULL'),
        nullable=True,
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    audio_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transcript_language: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_tone: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(
        db.Boolean, nullable=False, server_default=_sql_text_orm('false')
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[_dt_orm] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_sql_text_orm('now()')
    )
    updated_at: Mapped[_dt_orm] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_sql_text_orm('now()')
    )
    completed_at: Mapped[_dt_orm | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            f"status IN {VALID_MEETING_STATUSES_PG}",
            name='ck_meetings_status',
        ),
        CheckConstraint(
            f"email_tone IS NULL OR email_tone IN {VALID_EMAIL_TONES_PG}",
            name='ck_meetings_email_tone',
        ),
        Index(
            'ix_meetings_owner_created',
            'owner_user_id',
            _sql_text_orm('created_at DESC'),
        ),
        Index('ix_meetings_owner_series', 'owner_user_id', 'series_id'),
        Index('ix_meetings_owner_status', 'owner_user_id', 'status'),
        Index(
            'ix_meetings_title_trgm',
            'title',
            postgresql_using='gin',
            postgresql_ops={'title': 'gin_trgm_ops'},
        ),
    )


class MeetingSpeaker(db.Model, SerializableMixin):
    __tablename__ = 'meeting_speakers'

    id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid_orm.uuid4
    )
    meeting_id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('meetings.id', ondelete='CASCADE'),
        nullable=False,
    )
    speaker_label: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[_dt_orm] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_sql_text_orm('now()')
    )
    updated_at: Mapped[_dt_orm] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_sql_text_orm('now()')
    )

    __table_args__ = (
        UniqueConstraint('meeting_id', 'speaker_label', name='uq_meeting_speaker_label'),
    )
