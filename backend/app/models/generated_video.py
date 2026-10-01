"""Generated videos.

Phase 4D: PG-backed via ORM ``GeneratedVideo``. Extra Mongo fields
(``frame_image_id``, ``duration_sec``, ``aspect_ratio``, etc.) are folded
into ``video_metadata`` JSONB; ``local_path`` → ``url`` falls back to
metadata; ``model`` is its own column.
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


class GeneratedVideoModel:
    """Model for AI-generated videos (OpenRouter ``/videos`` endpoint)."""

    _indexes_ensured = True  # PG indexes live on ORM; legacy guard no-op.

    @staticmethod
    def create(
        user_id,
        prompt,
        model,
        local_path,
        video_url,
        openrouter_generation_id,
        frame_image_id=None,
        duration_sec=None,
        resolution=None,
        aspect_ratio=None,
        generate_audio=True,
        seed=None,
        metadata=None,
    ):
        uid = _to_uuid(user_id)
        merged = dict(metadata or {})
        merged.update({
            'local_path': local_path,
            'openrouter_generation_id': openrouter_generation_id,
            'frame_image_id': str(_to_uuid(frame_image_id)) if frame_image_id else None,
            'duration_sec': int(duration_sec) if duration_sec is not None else None,
            'resolution': resolution,
            'aspect_ratio': aspect_ratio,
            'generate_audio': bool(generate_audio),
            'seed': int(seed) if seed is not None else None,
            'is_favorite': False,
        })
        row = GeneratedVideo(
            user_id=uid,
            prompt=prompt,
            model=model,
            url=video_url,
            video_metadata=merged,
        )
        db.session.add(row)
        db.session.commit()
        return _video_to_dict(row)


def _video_to_dict(row: 'GeneratedVideo') -> dict:
    out = row.to_dict()
    out['user_id'] = str(row.user_id) if row.user_id else None
    out['video_url'] = row.url
    out['metadata'] = row.video_metadata or {}
    meta = row.video_metadata or {}
    out['local_path'] = meta.get('local_path')
    out['openrouter_generation_id'] = meta.get('openrouter_generation_id')
    out['frame_image_id'] = meta.get('frame_image_id')
    out['duration_sec'] = meta.get('duration_sec')
    out['resolution'] = meta.get('resolution')
    out['aspect_ratio'] = meta.get('aspect_ratio')
    out['generate_audio'] = meta.get('generate_audio')
    out['seed'] = meta.get('seed')
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


class GeneratedVideo(db.Model, SerializableMixin):
    __tablename__ = 'generated_videos'

    id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid_orm.uuid4
    )
    user_id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_metadata: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, server_default=_sql_text_orm("'{}'::jsonb")
    )
    created_at: Mapped[_dt_orm] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_sql_text_orm('now()')
    )

    __table_args__ = (
        Index('ix_generated_videos_user', 'user_id'),
        Index('ix_generated_videos_created', _sql_text_orm('created_at DESC')),
    )
