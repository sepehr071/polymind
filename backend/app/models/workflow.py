import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, func, select, text, update as sa_update
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models._base import SerializableMixin


# Sentinel string the route layer translates `?project_id=null` into. Mirrors
# the conversation / folder convention.
NULL_PROJECT_SENTINEL = '__null__'


def _as_uuid(v):
    """Coerce str / ObjectId / UUID to ``uuid.UUID`` or ``None``."""
    if v is None:
        return None
    if isinstance(v, uuid.UUID):
        return v
    try:
        return uuid.UUID(str(v))
    except (ValueError, AttributeError):
        return None


class Workflow(db.Model, SerializableMixin):
    """SQLAlchemy ORM model for ``workflows`` (Phase 3 strangler-fig).

    Mirrors the Mongo document shape one-to-one so route-layer callers can
    keep using ``WorkflowModel`` until Phase 4 cuts the façade over. Hot
    fields are real columns; React Flow ``nodes``/``edges`` + ``tags`` stay
    JSONB.
    """

    __tablename__ = 'workflows'

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
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
    nodes: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    edges: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    is_template: Mapped[bool] = mapped_column(
        db.Boolean, nullable=False, server_default=text('false')
    )
    category: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    tags: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    visibility: Mapped[str] = mapped_column(
        db.Text, nullable=False, server_default=text("'private'")
    )
    version: Mapped[int] = mapped_column(
        db.Integer, nullable=False, server_default=text('0')
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
            name='ck_workflows_visibility',
        ),
        Index(
            'ix_workflows_user_updated',
            'user_id',
            text('updated_at DESC'),
        ),
        Index(
            'ix_workflows_project_updated',
            'project_id',
            text('updated_at DESC'),
        ),
        Index('ix_workflows_is_template', 'is_template'),
        Index('ix_workflows_category', 'category'),
    )


class WorkflowModel:
    """Façade — internals ported to SQLAlchemy (Phase 4-C)."""

    @classmethod
    def create(cls, user_id, name, description, nodes, edges, is_template=False,
               project_id=None, workspace_id=None, category=None):
        """Create a new workflow."""
        row = Workflow(
            id=uuid.uuid4(),
            user_id=_as_uuid(user_id),
            name=name,
            description=description or '',
            nodes=nodes or [],
            edges=edges or [],
            is_template=bool(is_template),
            project_id=_as_uuid(project_id),
            workspace_id=_as_uuid(workspace_id),
            category=category,
        )
        db.session.add(row)
        db.session.commit()
        return str(row.id)

    @classmethod
    def find_by_id(cls, workflow_id):
        """Get workflow by ID, no ACL filter. Returns dict or None."""
        wid = _as_uuid(workflow_id)
        if wid is None:
            return None
        row = db.session.execute(
            select(Workflow).where(Workflow.id == wid)
        ).scalar_one_or_none()
        return row.to_dict() if row else None

    @classmethod
    def get_version(cls, workflow_id):
        """Return current row's optimistic-concurrency version, or 0 if missing.

        ``version`` is tracked in the row's JSONB-mirrored dict shape for
        legacy back-compat — there is no dedicated SQL column. Returns 0
        when the row exists but no version is set.
        """
        doc = cls.find_by_id(workflow_id)
        if doc is None:
            return None
        return int(doc.get('version') or 0)

    @classmethod
    def delete_unchecked(cls, workflow_id):
        """Delete workflow without owner check. Used when a project-owner
        gate already authorised the operation."""
        from sqlalchemy import delete as sa_delete
        wid = _as_uuid(workflow_id)
        if wid is None:
            return False
        result = db.session.execute(
            sa_delete(Workflow).where(Workflow.id == wid)
        )
        db.session.commit()
        return (result.rowcount or 0) > 0

    @classmethod
    def get_by_id(cls, workflow_id, user_id=None):
        """Get workflow by ID. If ``user_id`` is provided, restrict to owner
        or template."""
        wid = _as_uuid(workflow_id)
        if wid is None:
            return None
        stmt = select(Workflow).where(Workflow.id == wid)
        if user_id:
            uid = _as_uuid(user_id)
            stmt = stmt.where((Workflow.user_id == uid) | (Workflow.is_template.is_(True)))
        row = db.session.execute(stmt).scalar_one_or_none()
        return row.to_dict() if row else None

    @classmethod
    def get_by_user(cls, user_id):
        """Get all workflows for a user (newest first)."""
        uid = _as_uuid(user_id)
        rows = db.session.execute(
            select(Workflow).where(Workflow.user_id == uid).order_by(Workflow.updated_at.desc())
        ).scalars().all()
        return [r.to_dict() for r in rows]

    @staticmethod
    def find_by_project(project_id, skip=0, limit=50):
        """List workflows scoped to a project, newest first."""
        pid = _as_uuid(project_id)
        rows = db.session.execute(
            select(Workflow)
            .where(Workflow.project_id == pid)
            .order_by(Workflow.updated_at.desc())
            .offset(skip)
            .limit(limit)
        ).scalars().all()
        return [r.to_dict() for r in rows]

    @staticmethod
    def find_by_user(user_id, project_id=None, skip=0, limit=100):
        """Tri-state project filter (mirrors Phase B conversation contract).

        project_id semantics:
            None                                -> no project filter
            NULL_PROJECT_SENTINEL ('__null__')  -> rows with project_id IS NULL
            'null'                              -> alias of the sentinel
            UUID / str                          -> exact match
        """
        uid = _as_uuid(user_id)
        stmt = select(Workflow).where(Workflow.user_id == uid)
        if project_id == NULL_PROJECT_SENTINEL or project_id == 'null':
            stmt = stmt.where(Workflow.project_id.is_(None))
        elif project_id is not None:
            stmt = stmt.where(Workflow.project_id == _as_uuid(project_id))
        rows = db.session.execute(
            stmt.order_by(Workflow.updated_at.desc()).offset(skip).limit(limit)
        ).scalars().all()
        return [r.to_dict() for r in rows]

    @staticmethod
    def find_visible_to(user_id, project_id=None, skip=0, limit=100):
        """Caller's own + project-scoped if project_id."""
        uid = _as_uuid(user_id)
        conds = [Workflow.user_id == uid]
        if project_id:
            pid = _as_uuid(project_id)
            if pid is not None:
                conds.append(Workflow.project_id == pid)
        from sqlalchemy import or_
        rows = db.session.execute(
            select(Workflow)
            .where(or_(*conds))
            .order_by(Workflow.updated_at.desc())
            .offset(skip)
            .limit(limit)
        ).scalars().all()
        return [r.to_dict() for r in rows]

    @classmethod
    def update(cls, workflow_id, user_id, updates):
        """Update workflow with ownership check.

        Returns True on success.
        """
        wid = _as_uuid(workflow_id)
        uid = _as_uuid(user_id)
        if wid is None or uid is None:
            return False

        # Filter to columns that actually exist on Workflow.
        column_names = {c.name for c in Workflow.__table__.columns}
        clean = {k: v for k, v in (updates or {}).items() if k in column_names and k not in ('id', 'created_at')}
        if 'project_id' in clean and clean['project_id'] is not None:
            clean['project_id'] = _as_uuid(clean['project_id'])
        if 'workspace_id' in clean and clean['workspace_id'] is not None:
            clean['workspace_id'] = _as_uuid(clean['workspace_id'])
        if not clean:
            return False

        clean['updated_at'] = datetime.utcnow()
        result = db.session.execute(
            sa_update(Workflow)
            .where(Workflow.id == wid, Workflow.user_id == uid)
            .values(**clean)
        )
        db.session.commit()
        return (result.rowcount or 0) > 0

    @classmethod
    def delete(cls, workflow_id, user_id):
        """Delete workflow with ownership check."""
        wid = _as_uuid(workflow_id)
        uid = _as_uuid(user_id)
        if wid is None or uid is None:
            return False
        from sqlalchemy import delete as sa_delete
        result = db.session.execute(
            sa_delete(Workflow).where(Workflow.id == wid, Workflow.user_id == uid)
        )
        db.session.commit()
        return (result.rowcount or 0) > 0

    @classmethod
    def get_templates(cls):
        """Get all system templates."""
        rows = db.session.execute(
            select(Workflow).where(Workflow.is_template.is_(True)).order_by(Workflow.name.asc())
        ).scalars().all()
        return [r.to_dict() for r in rows]

    @classmethod
    def duplicate(cls, workflow_id, user_id, new_name=None):
        """Duplicate a workflow for a user."""
        original = cls.get_by_id(workflow_id, user_id)
        if not original:
            return None

        return cls.create(
            user_id=user_id,
            name=new_name or f"{original['name']} (Copy)",
            description=original.get('description', ''),
            nodes=original.get('nodes', []),
            edges=original.get('edges', []),
            is_template=False
        )
