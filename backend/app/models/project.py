import re
import secrets
from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.attributes import flag_modified
from app.extensions import db
from app.utils.ids import to_uuid


def _project_to_legacy_dict(p) -> dict | None:
    if p is None:
        return None
    d = p.to_dict()
    settings = p.settings or {}
    d['color'] = settings.get('color') or '#5c9aed'
    d['icon'] = settings.get('icon')
    d['pinned'] = bool(settings.get('pinned') or False)
    d['default_model'] = settings.get('default_model')
    d['default_temperature'] = settings.get('default_temperature')
    d['last_activity_at'] = settings.get('last_activity_at')
    d['created_by'] = str(p.owner_user_id) if p.owner_user_id else None
    return d


class ProjectModel:
    """Model for Projects - workspace-scoped containers for folders/conversations."""

    collection_name = 'projects'

    @staticmethod
    def _slugify(name: str) -> str:
        s = (name or '').lower()
        s = re.sub(r'[^a-z0-9]+', '-', s)
        s = re.sub(r'-+', '-', s).strip('-')
        return s or 'project'

    @staticmethod
    def create(workspace_id, name: str, created_by, color: str = '#5c9aed',
               icon: str = None, description: str = None) -> dict:
        from app.models.project import Project
        wid = to_uuid(workspace_id)
        creator_uuid = to_uuid(created_by)

        base_slug = ProjectModel._slugify(name)
        now = datetime.utcnow()
        slug = base_slug

        for _attempt in range(6):
            settings = {
                'color': color,
                'icon': icon,
                'pinned': False,
                'default_model': None,
                'default_temperature': None,
                'last_activity_at': now.isoformat(),
            }
            p = Project(
                workspace_id=wid,
                slug=slug,
                name=name,
                description=description,
                owner_user_id=creator_uuid,
                archived=False,
                tags=[],
                settings=settings,
                created_at=now,
                updated_at=now,
            )
            db.session.add(p)
            try:
                db.session.commit()
                return _project_to_legacy_dict(p)
            except IntegrityError:
                db.session.rollback()
                slug = f"{base_slug}-{secrets.token_hex(3)}"

        raise RuntimeError(f"Could not generate unique slug for project '{name}'")

    @staticmethod
    def find_by_id(project_id) -> dict:
        from app.models.project import Project
        try:
            pid = to_uuid(project_id)
        except (ValueError, TypeError):
            return None
        p = db.session.execute(
            select(Project).where(Project.id == pid)
        ).scalar_one_or_none()
        return _project_to_legacy_dict(p)

    @staticmethod
    def find_by_workspace(workspace_id, archived: bool = False) -> list:
        from app.models.project import Project
        try:
            wid = to_uuid(workspace_id)
        except (ValueError, TypeError):
            return []
        rows = db.session.execute(
            select(Project)
            .where(Project.workspace_id == wid, Project.archived == archived)
            .order_by(Project.archived.asc(), Project.name.asc())
        ).scalars().all()
        return [_project_to_legacy_dict(p) for p in rows]

    @staticmethod
    def update(project_id, update_data: dict) -> bool:
        from app.models.project import Project
        pid = to_uuid(project_id)

        allowed_fields = {
            'name', 'color', 'icon', 'description', 'archived',
            'pinned', 'tags', 'last_activity_at',
            'default_model', 'default_temperature',
        }
        clean = {k: v for k, v in (update_data or {}).items() if k in allowed_fields}
        if not clean:
            return False

        if 'default_temperature' in clean and clean['default_temperature'] is not None:
            try:
                temp = float(clean['default_temperature'])
            except (TypeError, ValueError):
                raise ValueError('default_temperature must be a number')
            if temp < 0.0 or temp > 2.0:
                raise ValueError('default_temperature must be between 0.0 and 2.0')
            clean['default_temperature'] = temp

        p = db.session.execute(
            select(Project).where(Project.id == pid)
        ).scalar_one_or_none()
        if p is None:
            return False

        changed = False
        settings = dict(p.settings or {})
        for k, v in clean.items():
            if k == 'name':
                p.name = v
                changed = True
            elif k == 'description':
                p.description = v
                changed = True
            elif k == 'archived':
                p.archived = bool(v)
                changed = True
            elif k == 'tags':
                if not isinstance(v, list):
                    raise ValueError('tags must be a list')
                cleaned = [str(t).strip() for t in v if str(t).strip()]
                p.tags = cleaned
                flag_modified(p, 'tags')
                changed = True
            elif k == 'last_activity_at':
                settings['last_activity_at'] = (
                    v.isoformat() if isinstance(v, datetime) else v
                )
                changed = True
            else:
                settings[k] = v
                changed = True

        p.settings = settings
        flag_modified(p, 'settings')
        p.updated_at = datetime.utcnow()
        db.session.commit()
        return changed

    @staticmethod
    def delete(project_id) -> bool:
        from app.models.project import Project
        try:
            pid = to_uuid(project_id)
        except (ValueError, TypeError):
            return False
        p = db.session.execute(
            select(Project).where(Project.id == pid)
        ).scalar_one_or_none()
        if p is None:
            return False
        db.session.delete(p)
        db.session.commit()
        return True

    @staticmethod
    def find_by_ids(project_ids) -> list:
        """Bulk fetch projects by ID. Returns legacy dicts in arbitrary order."""
        from app.models.project import Project
        uids = []
        for v in project_ids or []:
            try:
                uids.append(to_uuid(v))
            except (ValueError, TypeError):
                continue
        if not uids:
            return []
        rows = db.session.execute(
            select(Project).where(Project.id.in_(uids))
        ).scalars().all()
        return [_project_to_legacy_dict(p) for p in rows]

    @staticmethod
    def accessible_ids_for_user(user_id) -> set:
        """Every project id (``uuid.UUID``) the user can currently view.

        Company membership alone does NOT open a team. Set is:
            * explicit ``project_members`` rows for the user
            * non-empty group grants via ``project_group_access`` × ``group_members``
        Super-admin bypass stays at callers (``check_project_access`` path).
        """
        from app.models.project_member import ProjectMember
        from app.models.project_group_access import ProjectGroupAccess
        from app.models.group_member import GroupMember

        try:
            uid = to_uuid(user_id)
        except (ValueError, TypeError):
            return set()

        explicit = select(ProjectMember.project_id).where(
            ProjectMember.user_id == uid
        )
        via_group = (
            select(ProjectGroupAccess.project_id)
            .join(GroupMember, GroupMember.group_id == ProjectGroupAccess.group_id)
            .where(GroupMember.user_id == uid)
        )
        rows = db.session.execute(explicit.union(via_group)).all()
        return {r[0] for r in rows}

    @staticmethod
    def find_ids_by_workspaces(workspace_ids) -> list:
        """Return all project IDs (as ``uuid.UUID`` objects) that belong to
        any of *workspace_ids*. Used to derive an accessible-project set
        from a user's workspace memberships."""
        from app.models.project import Project
        wids = []
        for w in workspace_ids or []:
            try:
                wids.append(to_uuid(w))
            except (ValueError, TypeError):
                continue
        if not wids:
            return []
        rows = db.session.execute(
            select(Project.id).where(Project.workspace_id.in_(wids))
        ).all()
        return [r[0] for r in rows]

    @staticmethod
    def count_by_workspace(workspace_id, archived: bool = False) -> int:
        from app.models.project import Project
        try:
            wid = to_uuid(workspace_id)
        except (ValueError, TypeError):
            return 0
        return int(db.session.execute(
            select(func.count())
            .select_from(Project)
            .where(Project.workspace_id == wid, Project.archived == archived)
        ).scalar() or 0)

    @staticmethod
    def pin(project_id, value: bool) -> bool:
        return ProjectModel.update(project_id, {'pinned': bool(value)})

    @staticmethod
    def set_tags(project_id, tags: list) -> bool:
        if not isinstance(tags, list):
            raise ValueError('tags must be a list')
        cleaned = [str(t).strip() for t in tags if str(t).strip()]
        return ProjectModel.update(project_id, {'tags': cleaned})


# ---------------------------------------------------------------------------
# SQLAlchemy ORM model (Phase 3 strangler-fig).
# ---------------------------------------------------------------------------
import uuid as _uuid  # noqa: E402
from datetime import datetime as _datetime  # noqa: E402

from sqlalchemy import (  # noqa: E402
    Boolean,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import (  # noqa: E402
    JSONB,
    TIMESTAMP,
    UUID as PG_UUID,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship  # noqa: E402

from app.models._base import SerializableMixin  # noqa: E402


class Project(db.Model, SerializableMixin):
    __tablename__ = 'projects'

    id: Mapped[_uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    workspace_id: Mapped[_uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('workspaces.id', ondelete='CASCADE'),
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_user_id: Mapped[_uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('users.id'),
        nullable=True,
    )
    archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text('false')
    )
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, server_default='[]')
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default='{}')
    created_at: Mapped[_datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[_datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    workspace: Mapped['Workspace'] = relationship(  # noqa: F821
        back_populates='projects'
    )
    members: Mapped[list['ProjectMember']] = relationship(  # noqa: F821
        back_populates='project', cascade='all, delete-orphan'
    )
    group_access: Mapped[list['ProjectGroupAccess']] = relationship(  # noqa: F821
        back_populates='project', cascade='all, delete-orphan'
    )
    webhooks: Mapped[list['ProjectWebhook']] = relationship(  # noqa: F821
        back_populates='project', cascade='all, delete-orphan'
    )

    __table_args__ = (
        UniqueConstraint('workspace_id', 'slug', name='uq_projects_ws_slug'),
        Index('ix_projects_ws_archived', 'workspace_id', 'archived'),
    )
