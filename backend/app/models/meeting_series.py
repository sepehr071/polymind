"""
Meeting-series models — recurring meeting groups + glossary + speaker memory.

Phase 4D: backed by Postgres. Three ORM classes in this file:
    MeetingSeries, MeetingSeriesKeyterm, MeetingSeriesSpeakerName.
Mongo dict-shape preserved on read. ``_id`` is UUID4 string (matches v1).
"""

import uuid
from datetime import datetime, timezone


VALID_EMAIL_TONES = {'formal', 'casual'}
VALID_KEYTERM_SOURCES = {'manual', 'suggested', 'accepted'}


def _to_uuid(val):
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except Exception:
        return None


# ======================================================================
# MeetingSeriesModel
# ======================================================================
class MeetingSeriesModel:
    collection_name = 'meeting_series'

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    @staticmethod
    def create(owner_id: str, data: dict) -> str:
        email_tone = data.get('email_tone', 'formal')
        if email_tone not in VALID_EMAIL_TONES:
            raise ValueError(f"Invalid email_tone: {email_tone}")

        sid = _to_uuid(data.get('_id')) or uuid.uuid4()
        oid = _to_uuid(owner_id)

        row = MeetingSeries(
            id=sid,
            owner_user_id=oid,
            name=data['name'],
            description=data.get('description'),
            email_tone_preference=email_tone,
        )
        db.session.add(row)
        db.session.commit()
        return str(sid)

    @staticmethod
    def find_by_id(series_id: str) -> dict | None:
        sid = _to_uuid(series_id)
        if sid is None:
            return None
        row = db.session.get(MeetingSeries, sid)
        return _series_to_dict(row) if row else None

    @staticmethod
    def find_owned(series_id: str, owner_id: str) -> dict | None:
        sid = _to_uuid(series_id)
        oid = _to_uuid(owner_id)
        if sid is None or oid is None:
            return None
        row = db.session.execute(
            select(MeetingSeries).where(
                MeetingSeries.id == sid,
                MeetingSeries.owner_user_id == oid,
            )
        ).scalar_one_or_none()
        return _series_to_dict(row) if row else None

    @staticmethod
    def list_for_user(owner_id: str, skip: int = 0, limit: int = 200) -> list:
        oid = _to_uuid(owner_id)
        if oid is None:
            return []
        rows = db.session.execute(
            select(MeetingSeries)
            .where(MeetingSeries.owner_user_id == oid)
            .order_by(MeetingSeries.updated_at.desc())
            .offset(skip)
            .limit(limit)
        ).scalars().all()
        return [_series_to_dict(r) for r in rows]

    @staticmethod
    def update(series_id: str, owner_id: str, data: dict) -> bool:
        if not data:
            return False
        if 'email_tone' in data and data['email_tone'] not in VALID_EMAIL_TONES:
            raise ValueError(f"Invalid email_tone: {data['email_tone']}")
        sid = _to_uuid(series_id)
        oid = _to_uuid(owner_id)
        if sid is None or oid is None:
            return False
        translated: dict = {}
        for k, v in data.items():
            if k == 'email_tone':
                translated['email_tone_preference'] = v
            elif k in ('name', 'description'):
                translated[k] = v
        translated['updated_at'] = datetime.now(timezone.utc)
        result = db.session.execute(
            update(MeetingSeries)
            .where(MeetingSeries.id == sid, MeetingSeries.owner_user_id == oid)
            .values(**translated)
        )
        db.session.commit()
        return result.rowcount > 0

    @staticmethod
    def delete(series_id: str, owner_id: str) -> bool:
        sid = _to_uuid(series_id)
        oid = _to_uuid(owner_id)
        if sid is None or oid is None:
            return False
        result = db.session.execute(
            delete(MeetingSeries).where(
                MeetingSeries.id == sid,
                MeetingSeries.owner_user_id == oid,
            )
        )
        db.session.commit()
        return result.rowcount > 0



def _series_to_dict(row: 'MeetingSeries') -> dict:
    out = row.to_dict()
    out['owner_id'] = str(row.owner_user_id) if row.owner_user_id else None
    out['email_tone'] = row.email_tone_preference
    return out


# ======================================================================
# KeytermModel
# ======================================================================
class KeytermModel:
    collection_name = 'meeting_series_keyterms'

    @staticmethod
    def upsert_term(series_id: str, term: str, source: str = 'manual') -> dict:
        if source not in VALID_KEYTERM_SOURCES:
            raise ValueError(f"Invalid keyterm source: {source}")
        sid = _to_uuid(series_id)
        if sid is None:
            raise ValueError(f"Invalid series_id: {series_id!r}")
        now = datetime.now(timezone.utc)
        new_id = uuid.uuid4()
        # ON CONFLICT: only promote suggested -> manual; never demote.
        stmt = pg_insert(MeetingSeriesKeyterm).values(
            id=new_id,
            series_id=sid,
            term=term,
            source=source,
        )
        # We want: if existing.source = 'suggested' AND new.source = 'manual',
        # promote to 'manual'. Otherwise leave source untouched.
        from sqlalchemy import case
        stmt = stmt.on_conflict_do_update(
            index_elements=['series_id', 'term'],
            set_={
                'source': case(
                    (
                        (MeetingSeriesKeyterm.source == 'suggested')
                        & (stmt.excluded.source == 'manual'),
                        'manual',
                    ),
                    else_=MeetingSeriesKeyterm.source,
                ),
                'updated_at': now,
            },
        )
        db.session.execute(stmt)
        db.session.commit()
        existing = db.session.execute(
            select(MeetingSeriesKeyterm).where(
                MeetingSeriesKeyterm.series_id == sid,
                MeetingSeriesKeyterm.term == term,
            )
        ).scalar_one_or_none()
        return _keyterm_to_dict(existing) if existing else {}

    @staticmethod
    def find_by_id(term_id: str) -> dict | None:
        tid = _to_uuid(term_id)
        if tid is None:
            return None
        row = db.session.get(MeetingSeriesKeyterm, tid)
        return _keyterm_to_dict(row) if row else None

    @staticmethod
    def list_for_series(series_id: str, source: str | None = None) -> list:
        sid = _to_uuid(series_id)
        if sid is None:
            return []
        stmt = select(MeetingSeriesKeyterm).where(MeetingSeriesKeyterm.series_id == sid)
        if source is not None:
            if source not in VALID_KEYTERM_SOURCES:
                raise ValueError(f"Invalid keyterm source filter: {source}")
            stmt = stmt.where(MeetingSeriesKeyterm.source == source)
        stmt = stmt.order_by(MeetingSeriesKeyterm.created_at.asc())
        rows = db.session.execute(stmt).scalars().all()
        return [_keyterm_to_dict(r) for r in rows]

    @staticmethod
    def set_source(term_id: str, source: str) -> bool:
        if source not in VALID_KEYTERM_SOURCES:
            raise ValueError(f"Invalid keyterm source: {source}")
        tid = _to_uuid(term_id)
        if tid is None:
            return False
        result = db.session.execute(
            update(MeetingSeriesKeyterm)
            .where(MeetingSeriesKeyterm.id == tid)
            .values(source=source, updated_at=datetime.now(timezone.utc))
        )
        db.session.commit()
        return result.rowcount > 0

    @staticmethod
    def delete(term_id: str) -> bool:
        tid = _to_uuid(term_id)
        if tid is None:
            return False
        result = db.session.execute(
            delete(MeetingSeriesKeyterm).where(MeetingSeriesKeyterm.id == tid)
        )
        db.session.commit()
        return result.rowcount > 0

    @staticmethod
    def delete_for_series(series_id: str) -> int:
        sid = _to_uuid(series_id)
        if sid is None:
            return 0
        result = db.session.execute(
            delete(MeetingSeriesKeyterm).where(MeetingSeriesKeyterm.series_id == sid)
        )
        db.session.commit()
        return result.rowcount


def _keyterm_to_dict(row: 'MeetingSeriesKeyterm') -> dict:
    out = row.to_dict()
    out['series_id'] = str(row.series_id) if row.series_id else None
    return out


# ======================================================================
# SpeakerNameModel
# ======================================================================
class SpeakerNameModel:
    collection_name = 'meeting_series_speaker_names'

    @staticmethod
    def upsert(series_id: str, display_name: str) -> dict:
        """Touch (insert-or-update last_used_at) for a series-scoped display_name."""
        sid = _to_uuid(series_id)
        if sid is None:
            raise ValueError(f"Invalid series_id: {series_id!r}")
        now = datetime.now(timezone.utc)
        new_id = uuid.uuid4()
        stmt = pg_insert(MeetingSeriesSpeakerName).values(
            id=new_id,
            series_id=sid,
            display_name=display_name,
            last_used_at=now,
        ).on_conflict_do_update(
            index_elements=['series_id', 'display_name'],
            set_={'last_used_at': now},
        )
        db.session.execute(stmt)
        db.session.commit()
        row = db.session.execute(
            select(MeetingSeriesSpeakerName).where(
                MeetingSeriesSpeakerName.series_id == sid,
                MeetingSeriesSpeakerName.display_name == display_name,
            )
        ).scalar_one_or_none()
        return _speaker_to_dict(row) if row else {}

    @staticmethod
    def list_for_series(series_id: str, limit: int = 100) -> list:
        sid = _to_uuid(series_id)
        if sid is None:
            return []
        rows = db.session.execute(
            select(MeetingSeriesSpeakerName)
            .where(MeetingSeriesSpeakerName.series_id == sid)
            .order_by(MeetingSeriesSpeakerName.last_used_at.desc().nullslast())
            .limit(limit)
        ).scalars().all()
        return [_speaker_to_dict(r) for r in rows]

    @staticmethod
    def delete(name_id: str) -> bool:
        nid = _to_uuid(name_id)
        if nid is None:
            return False
        result = db.session.execute(
            delete(MeetingSeriesSpeakerName).where(MeetingSeriesSpeakerName.id == nid)
        )
        db.session.commit()
        return result.rowcount > 0

    @staticmethod
    def delete_for_series(series_id: str) -> int:
        sid = _to_uuid(series_id)
        if sid is None:
            return 0
        result = db.session.execute(
            delete(MeetingSeriesSpeakerName).where(MeetingSeriesSpeakerName.series_id == sid)
        )
        db.session.commit()
        return result.rowcount


def _speaker_to_dict(row: 'MeetingSeriesSpeakerName') -> dict:
    out = row.to_dict()
    out['series_id'] = str(row.series_id) if row.series_id else None
    return out


# ======================================================================
# Phase 3 — SQLAlchemy 2.0 ORM models (3 tables)
# ======================================================================

import uuid as _uuid_orm
from datetime import datetime as _dt_orm

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    text as _sql_text_orm,
    select,
    update,
    delete,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models._base import SerializableMixin


class MeetingSeries(db.Model, SerializableMixin):
    __tablename__ = 'meeting_series'

    id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid_orm.uuid4
    )
    owner_user_id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_tone_preference: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[_dt_orm] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_sql_text_orm('now()')
    )
    updated_at: Mapped[_dt_orm] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_sql_text_orm('now()')
    )

    __table_args__ = (
        UniqueConstraint('owner_user_id', 'name', name='uq_meeting_series_owner_name'),
        Index(
            'ix_meeting_series_owner_updated',
            'owner_user_id',
            _sql_text_orm('updated_at DESC'),
        ),
    )


class MeetingSeriesKeyterm(db.Model, SerializableMixin):
    __tablename__ = 'meeting_series_keyterms'

    id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid_orm.uuid4
    )
    series_id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('meeting_series.id', ondelete='CASCADE'),
        nullable=False,
    )
    term: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[_dt_orm] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_sql_text_orm('now()')
    )
    updated_at: Mapped[_dt_orm] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_sql_text_orm('now()')
    )

    __table_args__ = (
        CheckConstraint('length(term) <= 50', name='ck_meeting_series_keyterm_len'),
        CheckConstraint(
            "source IN ('manual','suggested','accepted')",
            name='ck_meeting_series_keyterm_source',
        ),
        UniqueConstraint('series_id', 'term', name='uq_meeting_series_keyterm'),
        Index('ix_meeting_series_keyterm_series_source', 'series_id', 'source'),
    )


class MeetingSeriesSpeakerName(db.Model, SerializableMixin):
    __tablename__ = 'meeting_series_speaker_names'

    id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid_orm.uuid4
    )
    series_id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('meeting_series.id', ondelete='CASCADE'),
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    last_used_at: Mapped[_dt_orm | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[_dt_orm] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_sql_text_orm('now()')
    )

    __table_args__ = (
        UniqueConstraint(
            'series_id', 'display_name', name='uq_meeting_series_speaker_name'
        ),
        Index(
            'ix_meeting_series_speaker_last_used',
            'series_id',
            _sql_text_orm('last_used_at DESC NULLS LAST'),
        ),
    )
