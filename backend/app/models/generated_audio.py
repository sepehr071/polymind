"""Generated TTS audio clips.

Phase 4D: PG-backed via ORM ``GeneratedAudio``. Extra Mongo fields
(``speed``, ``mime``, ``duration_ms``) are stored in ``audio_metadata`` JSONB.
The data URI lands on ``url`` (which here doubles as the data URI carrier).
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


class GeneratedAudioModel:
    """Model for AI-generated speech clips (TTS)."""

    _indexes_ensured = True

    @staticmethod
    def create(
        user_id,
        text,
        model,
        voice,
        speed,
        mime,
        audio_data_uri,
        duration_ms=None,
        metadata=None,
    ):
        uid = _to_uuid(user_id)
        merged = dict(metadata or {})
        merged.update({
            'speed': float(speed) if speed is not None else 1.0,
            'mime': mime,
            'duration_ms': int(duration_ms) if duration_ms is not None else None,
            'is_favorite': False,
        })
        row = GeneratedAudio(
            user_id=uid,
            text=text,
            voice=voice,
            model=model,
            url=audio_data_uri,
            audio_metadata=merged,
        )
        db.session.add(row)
        db.session.commit()
        return _audio_to_dict(row)


def _audio_to_dict(row: 'GeneratedAudio', include_payload: bool = True) -> dict:
    """Serialize a row to the legacy dict shape.

    ``include_payload=False`` omits the heavy base64 ``audio_data_uri`` (the full
    TTS data URI on ``url``, often MBs) while keeping all metadata — for any list
    route that doesn't need to play audio inline. Default ``True`` = unchanged.
    """
    out = row.to_dict()
    out['user_id'] = str(row.user_id) if row.user_id else None
    if include_payload:
        out['audio_data_uri'] = row.url
    else:
        # Drop both the alias and the deferred raw column so the response carries
        # zero base64. Consumers fetch the full clip by id when needed.
        out.pop('audio_data_uri', None)
        out.pop('url', None)
    out['metadata'] = row.audio_metadata or {}
    meta = row.audio_metadata or {}
    out['speed'] = float(meta.get('speed') or 1.0)
    out['mime'] = meta.get('mime')
    out['duration_ms'] = meta.get('duration_ms')
    out['is_favorite'] = bool(meta.get('is_favorite', False))
    return out


# ======================================================================
# Phase 3 — SQLAlchemy 2.0 ORM model
# ======================================================================

import uuid as _uuid_orm
from datetime import datetime as _dt_orm

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Text,
    text as _sql_text_orm,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models._base import SerializableMixin


class GeneratedAudio(db.Model, SerializableMixin):
    __tablename__ = 'generated_audio'

    id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid_orm.uuid4
    )
    user_id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    voice: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_metadata: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, server_default=_sql_text_orm("'{}'::jsonb")
    )
    created_at: Mapped[_dt_orm] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_sql_text_orm('now()')
    )

    __table_args__ = (
        Index('ix_generated_audio_user', 'user_id'),
        Index('ix_generated_audio_created', _sql_text_orm('created_at DESC')),
    )
