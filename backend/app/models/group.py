"""Group model — workspace-scoped collection of users for project access grants."""

from datetime import datetime
from sqlalchemy import select, func
from app.extensions import db
from app.utils.ids import to_uuid


def _group_to_legacy_dict(g, *, member_count: int | None = None) -> dict | None:
    if g is None:
        return None
    d = g.to_dict()
    # The ORM table dropped the cosmetic + denormalised fields the Mongo
    # body carried — re-emit defaults so the route layer keeps working.
    d.setdefault('color', '#5c9aed')
    d.setdefault('icon', None)
    d.setdefault('created_by', None)
    d['member_count'] = (
        int(member_count) if member_count is not None
        else GroupModel.count_members(g.id)
    )
    return d


class GroupModel:
    """Model for groups - workspace-scoped roster used by project access grants."""

    collection_name = 'groups'

    @staticmethod
    def create(workspace_id, name: str, created_by, color: str = '#5c9aed',
               icon: str = None, description: str = None) -> dict:
        from app.models.group import Group
        wid = to_uuid(workspace_id)
        _creator = to_uuid(created_by)  # not persisted; kept for API parity
        # `color`/`icon` have no columns — drop silently.

        now = datetime.utcnow()
        g = Group(
            workspace_id=wid,
            name=name,
            description=description,
            created_at=now,
            updated_at=now,
        )
        db.session.add(g)
        db.session.commit()
        return _group_to_legacy_dict(g, member_count=0)

    @staticmethod
    def find_by_id(group_id) -> dict:
        from app.models.group import Group
        try:
            gid = to_uuid(group_id)
        except (ValueError, TypeError):
            return None
        g = db.session.execute(
            select(Group).where(Group.id == gid)
        ).scalar_one_or_none()
        return _group_to_legacy_dict(g)

    @staticmethod
    def find_by_workspace(workspace_id) -> list:
        from app.models.group import Group
        try:
            wid = to_uuid(workspace_id)
        except (ValueError, TypeError):
            return []
        rows = db.session.execute(
            select(Group)
            .where(Group.workspace_id == wid)
            .order_by(Group.name.asc())
        ).scalars().all()
        return [_group_to_legacy_dict(g) for g in rows]

    @staticmethod
    def update(group_id, update_data: dict) -> bool:
        from app.models.group import Group
        gid = to_uuid(group_id)

        allowed_fields = {'name', 'color', 'icon', 'description'}
        clean = {k: v for k, v in (update_data or {}).items() if k in allowed_fields}
        if not clean:
            return False

        g = db.session.execute(
            select(Group).where(Group.id == gid)
        ).scalar_one_or_none()
        if g is None:
            return False

        # Only `name` + `description` survive on the ORM; the cosmetic
        # extras get dropped on the floor (parity loss documented in the
        # Phase-4 summary).
        if 'name' in clean:
            g.name = clean['name']
        if 'description' in clean:
            g.description = clean['description']
        g.updated_at = datetime.utcnow()
        db.session.commit()
        return True

    @staticmethod
    def delete(group_id) -> bool:
        from app.models.group import Group
        try:
            gid = to_uuid(group_id)
        except (ValueError, TypeError):
            return False
        g = db.session.execute(
            select(Group).where(Group.id == gid)
        ).scalar_one_or_none()
        if g is None:
            return False
        db.session.delete(g)
        db.session.commit()
        return True

    @staticmethod
    def count_members(group_id) -> int:
        from app.models.group_member import GroupMember
        try:
            gid = to_uuid(group_id)
        except (ValueError, TypeError):
            return 0
        return int(db.session.execute(
            select(func.count())
            .select_from(GroupMember)
            .where(GroupMember.group_id == gid)
        ).scalar() or 0)

    @staticmethod
    def recompute_member_count(group_id) -> int:
        """No-op besides the count: ORM doesn't store ``member_count`` —
        callers should read it via :meth:`count_members` instead.
        """
        return GroupModel.count_members(group_id)


# ---------------------------------------------------------------------------
# SQLAlchemy ORM model (Phase 3 strangler-fig).
# ---------------------------------------------------------------------------
import uuid as _uuid  # noqa: E402
from datetime import datetime as _datetime  # noqa: E402

from sqlalchemy import (  # noqa: E402
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


class Group(db.Model, SerializableMixin):
    __tablename__ = 'groups'

    id: Mapped[_uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    workspace_id: Mapped[_uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('workspaces.id', ondelete='CASCADE'),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[_datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[_datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    workspace: Mapped['Workspace'] = relationship(  # noqa: F821
        back_populates='groups'
    )
    members: Mapped[list['GroupMember']] = relationship(  # noqa: F821
        back_populates='group', cascade='all, delete-orphan'
    )

    __table_args__ = (
        UniqueConstraint('workspace_id', 'name', name='uq_groups_ws_name'),
        Index('ix_groups_workspace', 'workspace_id'),
    )
