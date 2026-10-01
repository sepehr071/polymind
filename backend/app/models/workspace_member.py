from datetime import datetime
from sqlalchemy import select, update as sa_update, delete as sa_delete, func
from app.extensions import db
from app.utils.ids import to_uuid, maybe_to_uuid


# Role hierarchy used to evaluate permissions: higher number == more access.
ROLE_HIERARCHY = {
    'viewer': 1,
    'editor': 2,
    'owner': 3,
}

# Set of valid role strings — useful for input validation.
VALID_ROLES = set(ROLE_HIERARCHY.keys())

# Mongo accepted `revoked`; the Postgres check-constraint uses `removed`.
# Translate at the boundary so callers stay untouched.
_STATUS_IN = {'pending', 'active', 'revoked'}
_STATUS_DB = {'pending': 'pending', 'active': 'active', 'revoked': 'removed'}


def _member_to_legacy_dict(m) -> dict | None:
    if m is None:
        return None
    d = m.to_dict()
    d['invited_by'] = str(m.invited_by_user_id) if m.invited_by_user_id else None
    # The Mongo doc carried `invited_email`; ORM has no column → keep `None`.
    d.setdefault('invited_email', None)
    # Translate DB `removed` back to legacy `revoked`.
    if m.status == 'removed':
        d['status'] = 'revoked'
    return d


class WorkspaceMemberModel:
    """Model for workspace memberships - links users to workspaces with a role."""

    collection_name = 'workspace_members'

    @staticmethod
    def add(workspace_id, user_id, role: str, invited_by=None,
            invited_email: str = None, status: str = 'active') -> dict:
        if role not in ROLE_HIERARCHY:
            raise ValueError(f"Invalid role: {role}")
        if status not in _STATUS_IN:
            raise ValueError(f"Invalid status: {status}")

        from app.models.workspace_member import WorkspaceMember
        wid = to_uuid(workspace_id)
        uid = to_uuid(user_id)
        inviter_uuid = maybe_to_uuid(invited_by)

        existing = db.session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == wid,
                WorkspaceMember.user_id == uid,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return _member_to_legacy_dict(existing)

        now = datetime.utcnow()
        m = WorkspaceMember(
            workspace_id=wid,
            user_id=uid,
            role=role,
            status=_STATUS_DB[status],
            invited_by_user_id=inviter_uuid,
            joined_at=now if status == 'active' else None,
            created_at=now,
        )
        db.session.add(m)
        db.session.commit()
        return _member_to_legacy_dict(m)

    @staticmethod
    def find(workspace_id, user_id) -> dict:
        from app.models.workspace_member import WorkspaceMember
        try:
            wid = to_uuid(workspace_id)
            uid = to_uuid(user_id)
        except (ValueError, TypeError):
            return None
        m = db.session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == wid,
                WorkspaceMember.user_id == uid,
            )
        ).scalar_one_or_none()
        return _member_to_legacy_dict(m)

    @staticmethod
    def find_by_workspace(workspace_id, status='active') -> list:
        from app.models.workspace_member import WorkspaceMember
        try:
            wid = to_uuid(workspace_id)
        except (ValueError, TypeError):
            return []
        if isinstance(status, (list, tuple, set)):
            db_statuses = [_STATUS_DB.get(s, s) for s in status]
            stmt = select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == wid,
                WorkspaceMember.status.in_(db_statuses),
            )
        else:
            stmt = select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == wid,
                WorkspaceMember.status == _STATUS_DB.get(status, status),
            )
        rows = db.session.execute(stmt).scalars().all()
        return [_member_to_legacy_dict(m) for m in rows]

    @staticmethod
    def find_by_user(user_id, status: str = 'active') -> list:
        from app.models.workspace_member import WorkspaceMember
        try:
            uid = to_uuid(user_id)
        except (ValueError, TypeError):
            return []
        rows = db.session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.user_id == uid,
                WorkspaceMember.status == _STATUS_DB.get(status, status),
            )
        ).scalars().all()
        # Mongo callers iterate `m['workspace_id']` as an ObjectId; emit a
        # UUID instance so str(...) works the same way and ORM joins keep
        # functioning when callers feed it back through `to_uuid`.
        out = []
        for m in rows:
            d = _member_to_legacy_dict(m)
            d['workspace_id'] = m.workspace_id  # raw UUID (was ObjectId)
            out.append(d)
        return out

    @staticmethod
    def update_role(workspace_id, user_id, role: str) -> bool:
        if role not in ROLE_HIERARCHY:
            raise ValueError(f"Invalid role: {role}")
        from app.models.workspace_member import WorkspaceMember
        wid = to_uuid(workspace_id)
        uid = to_uuid(user_id)
        result = db.session.execute(
            sa_update(WorkspaceMember)
            .where(
                WorkspaceMember.workspace_id == wid,
                WorkspaceMember.user_id == uid,
            )
            .values(role=role)
        )
        db.session.commit()
        return (result.rowcount or 0) > 0

    @staticmethod
    def update_status(workspace_id, user_id, status: str) -> bool:
        if status not in _STATUS_IN:
            raise ValueError(f"Invalid status: {status}")
        from app.models.workspace_member import WorkspaceMember
        wid = to_uuid(workspace_id)
        uid = to_uuid(user_id)
        values = {'status': _STATUS_DB[status]}
        if status == 'active':
            values['joined_at'] = datetime.utcnow()
        result = db.session.execute(
            sa_update(WorkspaceMember)
            .where(
                WorkspaceMember.workspace_id == wid,
                WorkspaceMember.user_id == uid,
            )
            .values(**values)
        )
        db.session.commit()
        return (result.rowcount or 0) > 0

    @staticmethod
    def remove(workspace_id, user_id) -> bool:
        from app.models.workspace_member import WorkspaceMember
        try:
            wid = to_uuid(workspace_id)
            uid = to_uuid(user_id)
        except (ValueError, TypeError):
            return False
        result = db.session.execute(
            sa_delete(WorkspaceMember).where(
                WorkspaceMember.workspace_id == wid,
                WorkspaceMember.user_id == uid,
            )
        )
        db.session.commit()
        return (result.rowcount or 0) > 0

    @staticmethod
    def count_active(workspace_id) -> int:
        """Count active memberships — seats-used gate."""
        from app.models.workspace_member import WorkspaceMember
        try:
            wid = to_uuid(workspace_id)
        except (ValueError, TypeError):
            return 0
        return int(db.session.execute(
            select(func.count())
            .select_from(WorkspaceMember)
            .where(
                WorkspaceMember.workspace_id == wid,
                WorkspaceMember.status == 'active',
            )
        ).scalar() or 0)

    @staticmethod
    def count_owners(workspace_id) -> int:
        from app.models.workspace_member import WorkspaceMember
        try:
            wid = to_uuid(workspace_id)
        except (ValueError, TypeError):
            return 0
        return int(db.session.execute(
            select(func.count())
            .select_from(WorkspaceMember)
            .where(
                WorkspaceMember.workspace_id == wid,
                WorkspaceMember.role == 'owner',
                WorkspaceMember.status == 'active',
            )
        ).scalar() or 0)


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


class WorkspaceMember(db.Model, SerializableMixin):
    __tablename__ = 'workspace_members'

    id: Mapped[_uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    workspace_id: Mapped[_uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('workspaces.id', ondelete='CASCADE'),
        nullable=False,
    )
    user_id: Mapped[_uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    invited_by_user_id: Mapped[_uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('users.id'),
        nullable=True,
    )
    joined_at: Mapped[_datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    created_at: Mapped[_datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    workspace: Mapped['Workspace'] = relationship(  # noqa: F821
        back_populates='members',
        foreign_keys=[workspace_id],
    )

    __table_args__ = (
        UniqueConstraint(
            'workspace_id', 'user_id', name='uq_workspace_members_ws_user'
        ),
        Index('ix_workspace_members_user_status', 'user_id', 'status'),
        CheckConstraint(
            "role IN ('owner', 'editor', 'viewer')",
            name='ck_workspace_members_role',
        ),
        CheckConstraint(
            "status IN ('active', 'pending', 'removed')",
            name='ck_workspace_members_status',
        ),
    )
