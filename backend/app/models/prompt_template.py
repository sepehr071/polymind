import uuid
from datetime import datetime

from sqlalchemy import (
    func,
    select,
    text,
    update as sa_update,
    delete as sa_delete,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models._base import SerializableMixin
from bson import ObjectId


def _as_uuid(v):
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


class PromptTemplate(db.Model, SerializableMixin):
    """SQLAlchemy ORM model for ``prompt_templates`` (image-gen prompt
    library + future seeded chat prompts)."""

    __tablename__ = 'prompt_templates'

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    category: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    title: Mapped[str] = mapped_column(db.Text, nullable=False)
    body: Mapped[str] = mapped_column(db.Text, nullable=False)
    variables: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    usage_count: Mapped[int] = mapped_column(
        db.Integer, nullable=False, server_default=text('0')
    )
    is_seed: Mapped[bool] = mapped_column(
        db.Boolean, nullable=False, server_default=text('false')
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


def _row_to_legacy_dict(row: PromptTemplate) -> dict:
    """Emit the legacy Mongo-shaped doc with ``name`` / ``template_text``
    aliases. The ORM model collapsed these to ``title`` / ``body`` but the
    route layer + seed scripts still address them by the old names.
    """
    d = row.to_dict()
    d['name'] = d.get('title')
    d['template_text'] = d.get('body')
    d.setdefault('is_active', True)
    return d


class PromptTemplateModel:
    """Façade ported to SQLAlchemy (Phase 4-C).

    Legacy data carried ``is_active`` (soft-delete flag); the new schema
    doesn't — soft delete becomes a real delete. Frontend treats both the
    same (route layer never surfaces inactive rows).
    """

    @staticmethod
    def create(name, category, template_text, variables=None, description='', created_by=None):
        """Create a new prompt template.

        ``description`` and ``created_by`` are not first-class columns on the
        ORM model — kept in the signature for back-compat (silently dropped).
        """
        row = PromptTemplate(
            id=uuid.uuid4(),
            category=category,
            title=name,
            body=template_text,
            variables=variables or [],
            usage_count=0,
            is_seed=False,
        )
        db.session.add(row)
        db.session.commit()
        return _row_to_legacy_dict(row)

    @staticmethod
    def find_by_id(template_id):
        """Find template by ID."""
        tid = _as_uuid(template_id)
        if tid is None:
            return None
        row = db.session.execute(
            select(PromptTemplate).where(PromptTemplate.id == tid)
        ).scalar_one_or_none()
        return _row_to_legacy_dict(row) if row else None

    @staticmethod
    def find_all_active():
        """Find all active templates (no inactive concept post-cutover)."""
        rows = db.session.execute(
            select(PromptTemplate).order_by(
                PromptTemplate.category.asc().nulls_last(),
                PromptTemplate.title.asc(),
            )
        ).scalars().all()
        return [_row_to_legacy_dict(r) for r in rows]

    @staticmethod
    def find_by_category(category):
        """Find all templates in a category."""
        rows = db.session.execute(
            select(PromptTemplate)
            .where(PromptTemplate.category == category)
            .order_by(PromptTemplate.title.asc())
        ).scalars().all()
        return [_row_to_legacy_dict(r) for r in rows]

    @staticmethod
    def get_categories():
        """Get list of all categories with counts."""
        rows = db.session.execute(
            select(PromptTemplate.category, func.count().label('count'))
            .group_by(PromptTemplate.category)
            .order_by(PromptTemplate.category.asc())
        ).all()
        return [{'category': r.category, 'count': int(r.count)} for r in rows]

    @staticmethod
    def update(template_id, updates):
        """Update a template."""
        tid = _as_uuid(template_id)
        if tid is None:
            return False
        # Map legacy aliases.
        clean = dict(updates or {})
        if 'name' in clean:
            clean['title'] = clean.pop('name')
        if 'template_text' in clean:
            clean['body'] = clean.pop('template_text')
        clean.pop('is_active', None)  # column doesn't exist in PG schema
        clean.pop('description', None)
        column_names = {c.name for c in PromptTemplate.__table__.columns}
        clean = {k: v for k, v in clean.items() if k in column_names and k not in ('id', 'created_at')}
        if not clean:
            return False
        clean['updated_at'] = datetime.utcnow()
        result = db.session.execute(
            sa_update(PromptTemplate).where(PromptTemplate.id == tid).values(**clean)
        )
        db.session.commit()
        return (result.rowcount or 0) > 0

    @staticmethod
    def delete(template_id):
        """Hard-delete a template (the ORM model has no ``is_active`` column)."""
        tid = _as_uuid(template_id)
        if tid is None:
            return False
        result = db.session.execute(
            sa_delete(PromptTemplate).where(PromptTemplate.id == tid)
        )
        db.session.commit()
        return (result.rowcount or 0) > 0

    @staticmethod
    def increment_usage(template_id):
        """Increment usage_count atomically via ``UPDATE … SET col = col + 1``."""
        tid = _as_uuid(template_id)
        if tid is None:
            return None
        db.session.execute(
            sa_update(PromptTemplate)
            .where(PromptTemplate.id == tid)
            .values(usage_count=PromptTemplate.usage_count + 1)
        )
        db.session.commit()
        return None

    # Alternate spelling used by the task description.
    increment_usage_count = increment_usage
