import secrets
from datetime import datetime, timedelta
from sqlalchemy import select, update as sa_update, delete as sa_delete
from app.extensions import db
from app.utils.ids import to_uuid, maybe_to_uuid


# Pending workspace invites expire after 7 days.
INVITE_TTL_DAYS = 7


def _invite_to_legacy_dict(i) -> dict | None:
    if i is None:
        return None
    d = i.to_dict()
    d['invited_by'] = str(i.invited_by_user_id) if i.invited_by_user_id else None
    return d


class WorkspaceInviteModel:
    """Pending email invites to join a workspace.

    On Postgres TTL becomes an explicit sweep; the data shape is preserved.
    """

    collection_name = 'workspace_invites'

    @staticmethod
    def create(workspace_id, email: str, role: str, invited_by) -> dict:
        if role not in ('owner', 'editor', 'viewer'):
            raise ValueError(f"Invalid role: {role}")

        from app.models.workspace_invite import WorkspaceInvite

        wid = to_uuid(workspace_id)
        inviter_uuid = maybe_to_uuid(invited_by)

        email_norm = (email or '').strip().lower()
        if not email_norm:
            raise ValueError("email is required")

        now = datetime.utcnow()
        token = secrets.token_urlsafe(24)

        # Drop any existing pending invite (Mongo did `delete_many` to honour
        # the unique index on (workspace, email)).
        db.session.execute(
            sa_delete(WorkspaceInvite).where(
                WorkspaceInvite.workspace_id == wid,
                WorkspaceInvite.email == email_norm,
                WorkspaceInvite.accepted_at.is_(None),
            )
        )

        invite = WorkspaceInvite(
            workspace_id=wid,
            email=email_norm,
            role=role,
            token=token,
            invited_by_user_id=inviter_uuid,
            expires_at=now + timedelta(days=INVITE_TTL_DAYS),
            accepted_at=None,
            created_at=now,
        )
        db.session.add(invite)
        db.session.commit()
        return _invite_to_legacy_dict(invite)

    @staticmethod
    def find_by_token(token: str) -> dict:
        from app.models.workspace_invite import WorkspaceInvite
        if not token:
            return None
        i = db.session.execute(
            select(WorkspaceInvite).where(WorkspaceInvite.token == token)
        ).scalar_one_or_none()
        return _invite_to_legacy_dict(i)

    @staticmethod
    def find_by_workspace(workspace_id, pending_only: bool = True) -> list:
        from app.models.workspace_invite import WorkspaceInvite
        try:
            wid = to_uuid(workspace_id)
        except (ValueError, TypeError):
            return []
        stmt = select(WorkspaceInvite).where(WorkspaceInvite.workspace_id == wid)
        if pending_only:
            stmt = stmt.where(
                WorkspaceInvite.accepted_at.is_(None),
                WorkspaceInvite.expires_at > datetime.utcnow(),
            )
        rows = db.session.execute(stmt).scalars().all()
        return [_invite_to_legacy_dict(i) for i in rows]

    @staticmethod
    def mark_accepted(token: str) -> bool:
        from app.models.workspace_invite import WorkspaceInvite
        if not token:
            return False
        result = db.session.execute(
            sa_update(WorkspaceInvite)
            .where(WorkspaceInvite.token == token)
            .values(accepted_at=datetime.utcnow())
        )
        db.session.commit()
        return (result.rowcount or 0) > 0

    @staticmethod
    def revoke(token: str) -> bool:
        from app.models.workspace_invite import WorkspaceInvite
        if not token:
            return False
        result = db.session.execute(
            sa_delete(WorkspaceInvite).where(WorkspaceInvite.token == token)
        )
        db.session.commit()
        return (result.rowcount or 0) > 0

    @staticmethod
    def refresh(token: str) -> dict:
        """Rotate the token and reset expiry. Compare-and-swap on old token."""
        from app.models.workspace_invite import WorkspaceInvite
        if not token:
            return None
        new_token = secrets.token_urlsafe(24)
        new_expires = datetime.utcnow() + timedelta(days=INVITE_TTL_DAYS)
        # CAS update — only mutate the row whose token still matches.
        stmt = (
            sa_update(WorkspaceInvite)
            .where(WorkspaceInvite.token == token)
            .values(token=new_token, expires_at=new_expires)
            .returning(WorkspaceInvite.id)
        )
        row = db.session.execute(stmt).first()
        db.session.commit()
        if row is None:
            return None
        invite = db.session.execute(
            select(WorkspaceInvite).where(WorkspaceInvite.id == row[0])
        ).scalar_one_or_none()
        return _invite_to_legacy_dict(invite)


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
    func,
    text,
)
from sqlalchemy.dialects.postgresql import (  # noqa: E402
    CITEXT,
    TIMESTAMP,
    UUID as PG_UUID,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship  # noqa: E402

from app.models._base import SerializableMixin  # noqa: E402


class WorkspaceInvite(db.Model, SerializableMixin):
    __tablename__ = 'workspace_invites'

    id: Mapped[_uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    workspace_id: Mapped[_uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('workspaces.id', ondelete='CASCADE'),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    token: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    invited_by_user_id: Mapped[_uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('users.id'),
        nullable=True,
    )
    expires_at: Mapped[_datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    accepted_at: Mapped[_datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    created_at: Mapped[_datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    workspace: Mapped['Workspace'] = relationship(  # noqa: F821
        back_populates='invites'
    )

    __table_args__ = (
        # Partial unique: only one pending invite per (workspace, email).
        Index(
            'uq_workspace_invites_pending',
            'workspace_id',
            'email',
            unique=True,
            postgresql_where=text('accepted_at IS NULL'),
        ),
        CheckConstraint(
            "role IN ('owner', 'editor', 'viewer')",
            name='ck_workspace_invites_role',
        ),
    )
