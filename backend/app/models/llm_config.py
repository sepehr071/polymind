import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    or_,
    func,
    select,
    text,
    update as sa_update,
    delete as sa_delete,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm.attributes import flag_modified

from app.extensions import db
from app.models._base import SerializableMixin
from bson import ObjectId


def _as_uuid(v):
    """Coerce str / UUID / ObjectId to ``uuid.UUID`` or ``None``."""
    if v is None:
        return None
    if isinstance(v, uuid.UUID):
        return v
    if isinstance(v, ObjectId):
        return None
    try:
        return uuid.UUID(str(v))
    except (ValueError, AttributeError):
        return None


class LLMConfig(db.Model, SerializableMixin):
    """SQLAlchemy ORM model for ``llm_configs`` (personas / saved configs)."""

    __tablename__ = 'llm_configs'

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=True,
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('workspaces.id', ondelete='CASCADE'),
        nullable=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('projects.id', ondelete='SET NULL'),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(db.Text, nullable=False)
    description: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    provider: Mapped[str] = mapped_column(db.Text, nullable=False)
    model: Mapped[str] = mapped_column(db.Text, nullable=False)
    system_prompt: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    parameters: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    avatar: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    stats: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    tags: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    visibility: Mapped[str] = mapped_column(
        db.Text, nullable=False, server_default=text("'private'")
    )
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
            "visibility IN ('private','public','template','project')",
            name='ck_llm_configs_visibility',
        ),
        Index('ix_llm_configs_owner', 'owner_user_id'),
        Index('ix_llm_configs_visibility', 'visibility'),
        Index(
            'ix_llm_configs_project_created',
            'project_id',
            text('created_at DESC'),
        ),
        Index(
            'ix_llm_configs_name_trgm',
            'name',
            postgresql_using='gin',
            postgresql_ops={'name': 'gin_trgm_ops'},
        ),
        Index(
            'ix_llm_configs_description_trgm',
            'description',
            postgresql_using='gin',
            postgresql_ops={'description': 'gin_trgm_ops'},
        ),
    )


def _row_to_legacy_dict(row: LLMConfig) -> dict:
    """Emit the legacy Mongo-shaped doc that route layer + frontend expect.

    Legacy keys ``owner_id`` / ``model_id`` / ``model_name`` are aliases for
    ``owner_user_id`` / ``model`` / a denormalised display name. We don't
    have a separate ``model_name`` column — surface ``model`` for both keys.
    """
    d = row.to_dict()
    d['owner_id'] = d.get('owner_user_id')
    d['model_id'] = d.get('model')
    d['model_name'] = d.get('model')
    return d


class LLMConfigModel:
    """Façade ported to SQLAlchemy (Phase 4-C)."""

    collection_name = 'llm_configs'

    @staticmethod
    def create(name, model_id, model_name, owner_id=None, description='',
               system_prompt='', visibility='private', avatar=None,
               parameters=None, tags=None, project_id=None, workspace_id=None,
               provider='openrouter'):
        """Create a new LLM config."""
        default_parameters = {
            'temperature': 0.7,
            'max_tokens': 2048,
            'top_p': 1.0,
            'frequency_penalty': 0.0,
            'presence_penalty': 0.0,
        }
        if parameters:
            default_parameters.update(parameters)

        default_avatar = {
            'type': 'initials',
            'value': name[:2].upper() if name else 'AI',
        }

        row = LLMConfig(
            id=uuid.uuid4(),
            owner_user_id=_as_uuid(owner_id) if owner_id else None,
            workspace_id=_as_uuid(workspace_id) if workspace_id else None,
            project_id=_as_uuid(project_id) if project_id else None,
            name=name,
            description=description,
            provider=provider,
            model=model_id,
            system_prompt=system_prompt,
            parameters=default_parameters,
            avatar=avatar or default_avatar,
            stats={
                'uses_count': 0,
                'saves_count': 0,
                'avg_rating': 0.0,
            },
            tags=tags or [],
            visibility=visibility,
        )
        db.session.add(row)
        db.session.commit()
        return _row_to_legacy_dict(row)

    @staticmethod
    def find_by_id(config_id):
        """Find config by ID."""
        cid = _as_uuid(config_id)
        if cid is None:
            return None
        row = db.session.execute(
            select(LLMConfig).where(LLMConfig.id == cid)
        ).scalar_one_or_none()
        return _row_to_legacy_dict(row) if row else None

    @staticmethod
    def find_by_ids(config_ids):
        """Find multiple configs by IDs in a single query."""
        if not config_ids:
            return []
        uuids = [_as_uuid(c) for c in config_ids]
        uuids = [u for u in uuids if u is not None]
        if not uuids:
            return []
        rows = db.session.execute(
            select(LLMConfig).where(LLMConfig.id.in_(uuids))
        ).scalars().all()
        return [_row_to_legacy_dict(r) for r in rows]

    @staticmethod
    def find_by_owner(owner_id, skip=0, limit=50):
        """Find configs owned by a user."""
        uid = _as_uuid(owner_id)
        if uid is None:
            return []
        rows = db.session.execute(
            select(LLMConfig)
            .where(LLMConfig.owner_user_id == uid)
            .order_by(LLMConfig.created_at.desc())
            .offset(skip)
            .limit(limit)
        ).scalars().all()
        return [_row_to_legacy_dict(r) for r in rows]

    @staticmethod
    def find_templates(skip=0, limit=50):
        """Find admin-created templates."""
        order_col = LLMConfig.stats['uses_count'].astext.cast(db.Numeric)
        rows = db.session.execute(
            select(LLMConfig)
            .where(LLMConfig.visibility == 'template')
            .order_by(order_col.desc().nulls_last())
            .offset(skip)
            .limit(limit)
        ).scalars().all()
        return [_row_to_legacy_dict(r) for r in rows]

    @staticmethod
    def find_visible_to(user_id, project_id=None, skip=0, limit=100):
        """Caller's own + project-scoped (if project_id) + public + templates."""
        uid = _as_uuid(user_id)
        conds = [
            LLMConfig.owner_user_id == uid,
            LLMConfig.visibility.in_(('public', 'template')),
        ]
        if project_id:
            pid = _as_uuid(project_id)
            if pid is not None:
                conds.append(LLMConfig.project_id == pid)
        rows = db.session.execute(
            select(LLMConfig)
            .where(or_(*conds))
            .order_by(LLMConfig.created_at.desc())
            .offset(skip)
            .limit(limit)
        ).scalars().all()
        return [_row_to_legacy_dict(r) for r in rows]

    @staticmethod
    def update(config_id, update_data):
        """Update config. Returns a result-like object with rowcount-shaped
        ``modified_count`` for legacy callers."""
        cid = _as_uuid(config_id)
        if cid is None:
            class _NoOp:
                modified_count = 0
            return _NoOp()
        clean = {k: v for k, v in (update_data or {}).items() if k not in ('id', '_id', 'created_at')}
        # Map legacy aliases.
        if 'owner_id' in clean:
            clean['owner_user_id'] = _as_uuid(clean.pop('owner_id'))
        if 'model_id' in clean:
            clean['model'] = clean.pop('model_id')
        clean.pop('model_name', None)
        if 'project_id' in clean and clean['project_id'] is not None:
            clean['project_id'] = _as_uuid(clean['project_id'])
        if 'workspace_id' in clean and clean['workspace_id'] is not None:
            clean['workspace_id'] = _as_uuid(clean['workspace_id'])
        clean['updated_at'] = datetime.utcnow()
        # Only keep columns that exist on the model.
        column_names = {c.name for c in LLMConfig.__table__.columns}
        clean = {k: v for k, v in clean.items() if k in column_names}
        result = db.session.execute(
            sa_update(LLMConfig).where(LLMConfig.id == cid).values(**clean)
        )
        db.session.commit()

        class _ResultShim:
            modified_count = result.rowcount or 0
        return _ResultShim()

    @staticmethod
    def increment_uses(config_id):
        """Increment ``stats.uses_count`` and refresh ``last_used_at``.

        JSONB scalar mutation: fetch row, mutate Python dict, flag_modified.
        """
        cid = _as_uuid(config_id)
        if cid is None:
            class _NoOp:
                modified_count = 0
            return _NoOp()
        row = db.session.execute(
            select(LLMConfig).where(LLMConfig.id == cid)
        ).scalar_one_or_none()
        if row is None:
            class _NoOp:
                modified_count = 0
            return _NoOp()
        stats = dict(row.stats or {})
        stats['uses_count'] = int(stats.get('uses_count', 0)) + 1
        stats['last_used_at'] = datetime.utcnow().isoformat()
        row.stats = stats
        flag_modified(row, 'stats')
        db.session.commit()

        class _ResultShim:
            modified_count = 1
        return _ResultShim()

    @staticmethod
    def increment_saves(config_id):
        """Increment ``stats.saves_count`` (same JSONB mutation pattern)."""
        cid = _as_uuid(config_id)
        if cid is None:
            class _NoOp:
                modified_count = 0
            return _NoOp()
        row = db.session.execute(
            select(LLMConfig).where(LLMConfig.id == cid)
        ).scalar_one_or_none()
        if row is None:
            class _NoOp:
                modified_count = 0
            return _NoOp()
        stats = dict(row.stats or {})
        stats['saves_count'] = int(stats.get('saves_count', 0)) + 1
        row.stats = stats
        flag_modified(row, 'stats')
        db.session.commit()

        class _ResultShim:
            modified_count = 1
        return _ResultShim()

    @staticmethod
    def set_visibility(config_id, visibility):
        """Change config visibility."""
        return LLMConfigModel.update(config_id, {'visibility': visibility})

    @staticmethod
    def delete(config_id):
        """Delete a config."""
        cid = _as_uuid(config_id)
        if cid is None:
            class _NoOp:
                deleted_count = 0
            return _NoOp()
        result = db.session.execute(
            sa_delete(LLMConfig).where(LLMConfig.id == cid)
        )
        db.session.commit()

        class _ResultShim:
            deleted_count = result.rowcount or 0
        return _ResultShim()

    @staticmethod
    def duplicate(config_id, new_owner_id, new_name=None, project_id=None, workspace_id=None):
        """Duplicate a config for a new owner, propagating active scope."""
        original = LLMConfigModel.find_by_id(config_id)
        if not original:
            return None
        return LLMConfigModel.create(
            name=new_name or f"{original['name']} (copy)",
            model_id=original.get('model_id') or original.get('model'),
            model_name=original.get('model_name') or original.get('model'),
            owner_id=new_owner_id,
            description=original.get('description', ''),
            system_prompt=original.get('system_prompt', ''),
            visibility='private',
            avatar=original.get('avatar'),
            parameters=original.get('parameters'),
            tags=original.get('tags'),
            project_id=project_id,
            workspace_id=workspace_id,
        )

    @staticmethod
    def count_by_owner(owner_id):
        """Count configs owned by user."""
        uid = _as_uuid(owner_id)
        if uid is None:
            return 0
        return int(db.session.execute(
            select(func.count()).select_from(LLMConfig)
            .where(LLMConfig.owner_user_id == uid)
        ).scalar_one() or 0)

    @staticmethod
    def count_public():
        """Count public configs."""
        return int(db.session.execute(
            select(func.count()).select_from(LLMConfig)
            .where(LLMConfig.visibility == 'public')
        ).scalar_one() or 0)
