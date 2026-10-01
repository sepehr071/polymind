"""GroupMember model — links users to groups."""

from datetime import datetime
from sqlalchemy import select, delete as sa_delete
from app.extensions import db
from app.utils.ids import to_uuid, maybe_to_uuid


def _gm_to_legacy_dict(gm) -> dict | None:
    if gm is None:
        return None
    d = gm.to_dict()
    # `added_by` did not survive the ORM redesign.
    d.setdefault('added_by', None)
    return d


class GroupMemberModel:
    """Model for group memberships - links users to a workspace group."""

    collection_name = 'group_members'

    @staticmethod
    def add(group_id, user_id, added_by) -> dict:
        from app.models.group_member import GroupMember
        gid = to_uuid(group_id)
        uid = to_uuid(user_id)
        _added_by = maybe_to_uuid(added_by)  # not persisted; kept for API parity

        existing = db.session.execute(
            select(GroupMember).where(
                GroupMember.group_id == gid,
                GroupMember.user_id == uid,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return _gm_to_legacy_dict(existing)

        gm = GroupMember(
            group_id=gid,
            user_id=uid,
            created_at=datetime.utcnow(),
        )
        db.session.add(gm)
        db.session.commit()
        return _gm_to_legacy_dict(gm)

    @staticmethod
    def remove(group_id, user_id) -> bool:
        from app.models.group_member import GroupMember
        try:
            gid = to_uuid(group_id)
            uid = to_uuid(user_id)
        except (ValueError, TypeError):
            return False
        result = db.session.execute(
            sa_delete(GroupMember).where(
                GroupMember.group_id == gid,
                GroupMember.user_id == uid,
            )
        )
        db.session.commit()
        return (result.rowcount or 0) > 0

    @staticmethod
    def find_by_group(group_id) -> list:
        from app.models.group_member import GroupMember
        try:
            gid = to_uuid(group_id)
        except (ValueError, TypeError):
            return []
        rows = db.session.execute(
            select(GroupMember).where(GroupMember.group_id == gid)
        ).scalars().all()
        return [_gm_to_legacy_dict(gm) for gm in rows]

    @staticmethod
    def delete_by_group(group_id) -> int:
        """Cascade-delete every membership for *group_id*. Used at group delete."""
        from app.models.group_member import GroupMember
        try:
            gid = to_uuid(group_id)
        except (ValueError, TypeError):
            return 0
        result = db.session.execute(
            sa_delete(GroupMember).where(GroupMember.group_id == gid)
        )
        db.session.commit()
        return result.rowcount or 0

    @staticmethod
    def is_member(group_id, user_id) -> bool:
        from app.models.group_member import GroupMember
        try:
            gid = to_uuid(group_id)
            uid = to_uuid(user_id)
        except (ValueError, TypeError):
            return False
        row = db.session.execute(
            select(GroupMember).where(
                GroupMember.group_id == gid,
                GroupMember.user_id == uid,
            )
        ).scalar_one_or_none()
        return row is not None


# ---------------------------------------------------------------------------
# SQLAlchemy ORM model (Phase 3 strangler-fig).
# ---------------------------------------------------------------------------
import uuid as _uuid  # noqa: E402
from datetime import datetime as _datetime  # noqa: E402

from sqlalchemy import (  # noqa: E402
    ForeignKey,
    Index,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import (  # noqa: E402
    TIMESTAMP,
    UUID as PG_UUID,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship  # noqa: E402

from app.models._base import SerializableMixin  # noqa: E402


class GroupMember(db.Model, SerializableMixin):
    __tablename__ = 'group_members'

    id: Mapped[_uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    group_id: Mapped[_uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('groups.id', ondelete='CASCADE'),
        nullable=False,
    )
    user_id: Mapped[_uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    created_at: Mapped[_datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    group: Mapped['Group'] = relationship(  # noqa: F821
        back_populates='members'
    )

    __table_args__ = (
        UniqueConstraint('group_id', 'user_id', name='uq_group_members_group_user'),
        Index('ix_group_members_user', 'user_id'),
    )
