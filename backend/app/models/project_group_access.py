"""ProjectGroupAccess — grants a group a role on a specific project."""

from datetime import datetime
from sqlalchemy import select, delete as sa_delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.extensions import db
from app.utils.ids import to_uuid, maybe_to_uuid


def _pga_to_legacy_dict(row) -> dict | None:
    if row is None:
        return None
    d = row.to_dict()
    # Legacy fields the route layer still touches.
    d.setdefault('expires_at', None)
    d.setdefault('created_by', None)
    d.setdefault('updated_at', None)
    return d


class ProjectGroupAccessModel:
    """Grant rows mapping (project, group) -> role with optional expiry."""

    collection_name = 'project_group_access'

    @staticmethod
    def set(project_id, group_id, role: str, expires_at=None, created_by=None) -> dict:
        from app.models.project_group_access import ProjectGroupAccess
        pid = to_uuid(project_id)
        gid = to_uuid(group_id)
        _creator = maybe_to_uuid(created_by)  # not persisted; kept for API parity
        # NOTE: `expires_at` has no column on this ORM table — drop silently
        # (will be added in a follow-up migration if/when scheduling lands).

        stmt = (
            pg_insert(ProjectGroupAccess)
            .values(
                project_id=pid,
                group_id=gid,
                role=role,
                created_at=datetime.utcnow(),
            )
            .on_conflict_do_update(
                constraint='uq_project_group_access_project_group',
                set_={'role': role},
            )
        )
        db.session.execute(stmt)
        db.session.commit()
        row = db.session.execute(
            select(ProjectGroupAccess).where(
                ProjectGroupAccess.project_id == pid,
                ProjectGroupAccess.group_id == gid,
            )
        ).scalar_one_or_none()
        return _pga_to_legacy_dict(row)

    @staticmethod
    def remove(project_id, group_id) -> bool:
        from app.models.project_group_access import ProjectGroupAccess
        try:
            pid = to_uuid(project_id)
            gid = to_uuid(group_id)
        except (ValueError, TypeError):
            return False
        result = db.session.execute(
            sa_delete(ProjectGroupAccess).where(
                ProjectGroupAccess.project_id == pid,
                ProjectGroupAccess.group_id == gid,
            )
        )
        db.session.commit()
        return (result.rowcount or 0) > 0

    @staticmethod
    def delete_by_group(group_id) -> int:
        """Cascade-delete every project-grant referencing *group_id*."""
        from app.models.project_group_access import ProjectGroupAccess
        try:
            gid = to_uuid(group_id)
        except (ValueError, TypeError):
            return 0
        result = db.session.execute(
            sa_delete(ProjectGroupAccess).where(ProjectGroupAccess.group_id == gid)
        )
        db.session.commit()
        return result.rowcount or 0

    @staticmethod
    def find_by_project(project_id) -> list:
        from app.models.project_group_access import ProjectGroupAccess
        try:
            pid = to_uuid(project_id)
        except (ValueError, TypeError):
            return []
        rows = db.session.execute(
            select(ProjectGroupAccess).where(ProjectGroupAccess.project_id == pid)
        ).scalars().all()
        out = []
        for r in rows:
            d = _pga_to_legacy_dict(r)
            d['group_id'] = r.group_id  # raw UUID for caller's set-membership math
            out.append(d)
        return out

    @staticmethod
    def find_groups_with_access(project_id, user_id) -> list:
        """Groups this user belongs to that have an active access grant on this project."""
        from app.models.project_group_access import ProjectGroupAccess
        from app.models.group_member import GroupMember
        from app.models.group import GroupModel

        try:
            pid = to_uuid(project_id)
            uid = to_uuid(user_id)
        except (ValueError, TypeError):
            return []

        # Single join: grant rows on this project whose group the user belongs to.
        rows = db.session.execute(
            select(ProjectGroupAccess)
            .join(GroupMember, GroupMember.group_id == ProjectGroupAccess.group_id)
            .where(
                ProjectGroupAccess.project_id == pid,
                GroupMember.user_id == uid,
            )
        ).scalars().all()

        out = []
        for r in rows:
            group = GroupModel.find_by_id(r.group_id)
            if not group:
                continue
            out.append({
                'group': group,
                'role': r.role,
                'expires_at': None,
            })
        return out


# ---------------------------------------------------------------------------
# SQLAlchemy ORM model (Phase 3 strangler-fig).
# ---------------------------------------------------------------------------
import uuid as _uuid  # noqa: E402
from datetime import datetime as _datetime  # noqa: E402

from sqlalchemy import (  # noqa: E402
    CheckConstraint,
    ForeignKey,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import (  # noqa: E402
    TIMESTAMP,
    UUID as PG_UUID,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship  # noqa: E402

from app.models._base import SerializableMixin  # noqa: E402


class ProjectGroupAccess(db.Model, SerializableMixin):
    __tablename__ = 'project_group_access'

    id: Mapped[_uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    project_id: Mapped[_uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('projects.id', ondelete='CASCADE'),
        nullable=False,
    )
    group_id: Mapped[_uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('groups.id', ondelete='CASCADE'),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[_datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped['Project'] = relationship(  # noqa: F821
        back_populates='group_access'
    )

    __table_args__ = (
        UniqueConstraint(
            'project_id', 'group_id', name='uq_project_group_access_project_group'
        ),
        CheckConstraint(
            "role IN ('owner', 'editor', 'viewer')",
            name='ck_project_group_access_role',
        ),
    )
