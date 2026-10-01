from datetime import datetime
from sqlalchemy import select, update as sa_update, delete as sa_delete, func
from app.extensions import db
from app.utils.ids import to_uuid, maybe_to_uuid
from app.models.workspace_member import ROLE_HIERARCHY


def _pm_to_legacy_dict(m) -> dict | None:
    if m is None:
        return None
    d = m.to_dict()
    # `added_by` did not survive the ORM redesign — keep the key for shape
    # parity but always emit None.
    d.setdefault('added_by', None)
    return d


class ProjectMemberModel:
    """Model for project memberships - links users to projects with a role."""

    collection_name = 'project_members'

    @staticmethod
    def add(project_id, user_id, role: str, added_by) -> dict:
        if role not in ROLE_HIERARCHY:
            raise ValueError(f"Invalid role: {role}")

        from app.models.project_member import ProjectMember
        pid = to_uuid(project_id)
        uid = to_uuid(user_id)
        _added_by_uuid = maybe_to_uuid(added_by)  # not persisted; kept for API parity

        existing = db.session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == pid,
                ProjectMember.user_id == uid,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return _pm_to_legacy_dict(existing)

        m = ProjectMember(
            project_id=pid,
            user_id=uid,
            role=role,
            created_at=datetime.utcnow(),
        )
        db.session.add(m)
        db.session.commit()
        return _pm_to_legacy_dict(m)

    @staticmethod
    def find(project_id, user_id) -> dict:
        from app.models.project_member import ProjectMember
        try:
            pid = to_uuid(project_id)
            uid = to_uuid(user_id)
        except (ValueError, TypeError):
            return None
        m = db.session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == pid,
                ProjectMember.user_id == uid,
            )
        ).scalar_one_or_none()
        return _pm_to_legacy_dict(m)

    @staticmethod
    def find_by_project(project_id) -> list:
        from app.models.project_member import ProjectMember
        try:
            pid = to_uuid(project_id)
        except (ValueError, TypeError):
            return []
        rows = db.session.execute(
            select(ProjectMember).where(ProjectMember.project_id == pid)
        ).scalars().all()
        return [_pm_to_legacy_dict(m) for m in rows]

    @staticmethod
    def find_by_user(user_id) -> list:
        from app.models.project_member import ProjectMember
        try:
            uid = to_uuid(user_id)
        except (ValueError, TypeError):
            return []
        rows = db.session.execute(
            select(ProjectMember).where(ProjectMember.user_id == uid)
        ).scalars().all()
        return [_pm_to_legacy_dict(m) for m in rows]

    @staticmethod
    def update_role(project_id, user_id, role: str) -> bool:
        if role not in ROLE_HIERARCHY:
            raise ValueError(f"Invalid role: {role}")
        from app.models.project_member import ProjectMember
        pid = to_uuid(project_id)
        uid = to_uuid(user_id)
        result = db.session.execute(
            sa_update(ProjectMember)
            .where(
                ProjectMember.project_id == pid,
                ProjectMember.user_id == uid,
            )
            .values(role=role)
        )
        db.session.commit()
        return (result.rowcount or 0) > 0

    @staticmethod
    def remove(project_id, user_id) -> bool:
        from app.models.project_member import ProjectMember
        try:
            pid = to_uuid(project_id)
            uid = to_uuid(user_id)
        except (ValueError, TypeError):
            return False
        result = db.session.execute(
            sa_delete(ProjectMember).where(
                ProjectMember.project_id == pid,
                ProjectMember.user_id == uid,
            )
        )
        db.session.commit()
        return (result.rowcount or 0) > 0

    @staticmethod
    def count_by_project(project_id) -> int:
        from app.models.project_member import ProjectMember
        try:
            pid = to_uuid(project_id)
        except (ValueError, TypeError):
            return 0
        return int(db.session.execute(
            select(func.count())
            .select_from(ProjectMember)
            .where(ProjectMember.project_id == pid)
        ).scalar() or 0)

    @staticmethod
    def count_by_project_role(project_id, role: str) -> int:
        from app.models.project_member import ProjectMember
        try:
            pid = to_uuid(project_id)
        except (ValueError, TypeError):
            return 0
        return int(db.session.execute(
            select(func.count())
            .select_from(ProjectMember)
            .where(
                ProjectMember.project_id == pid,
                ProjectMember.role == role,
            )
        ).scalar() or 0)

    @staticmethod
    def delete_by_project(project_id) -> int:
        from app.models.project_member import ProjectMember
        try:
            pid = to_uuid(project_id)
        except (ValueError, TypeError):
            return 0
        result = db.session.execute(
            sa_delete(ProjectMember).where(ProjectMember.project_id == pid)
        )
        db.session.commit()
        return result.rowcount or 0


# ---------------------------------------------------------------------------
# SQLAlchemy ORM model (Phase 3 strangler-fig).
# ---------------------------------------------------------------------------
import uuid as _uuid  # noqa: E402
from datetime import datetime as _datetime  # noqa: E402

from sqlalchemy import (  # noqa: E402
    CheckConstraint,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import (  # noqa: E402
    TIMESTAMP,
    UUID as PG_UUID,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship  # noqa: E402

from app.models._base import SerializableMixin  # noqa: E402


class ProjectMember(db.Model, SerializableMixin):
    __tablename__ = 'project_members'

    id: Mapped[_uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    project_id: Mapped[_uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('projects.id', ondelete='CASCADE'),
        nullable=False,
    )
    user_id: Mapped[_uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[_datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped['Project'] = relationship(  # noqa: F821
        back_populates='members'
    )

    __table_args__ = (
        UniqueConstraint(
            'project_id', 'user_id', name='uq_project_members_project_user'
        ),
        Index('ix_project_members_user', 'user_id'),
        CheckConstraint(
            "role IN ('owner', 'editor', 'viewer')",
            name='ck_project_members_role',
        ),
    )
