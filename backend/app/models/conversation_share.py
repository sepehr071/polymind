"""Conversation sharing — link snapshots + live team grants.

Two share modes share ONE table (``conversation_shares``):

* ``share_type='link'`` — a single row carrying a random URL-safe ``token`` and a
  frozen ``snapshot`` (JSONB) of the conversation at share time. Any logged-in
  user who opens ``GET /api/share/{token}`` sees that snapshot, read-only;
  messages added after sharing do NOT change it.
* ``share_type='team'`` — one row per team (``project_id``) the owner shares
  into. Every member of that team can read AND contribute to the *live*
  conversation (collaborative chat). No token, no snapshot — reads hit the live
  messages.

Revocation = a soft ``revoked_at`` stamp (link) / a hard row delete (team diff).
``user_can_access`` is the single source of truth both the conversations router
and the chat router consult to widen the strict owner check. ``ConversationShare``
rows cascade-delete with their conversation.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    UniqueConstraint,
    delete as sa_delete,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models._base import SerializableMixin
from app.utils.ids import maybe_to_uuid, to_uuid


def _serialize_share(obj) -> dict | None:
    if obj is None:
        return None
    return obj.to_dict()


class ConversationShareModel:
    collection_name = 'conversation_shares'

    # ------------------------------------------------------------------ link
    @staticmethod
    def create_link(conversation_id, created_by, snapshot) -> dict | None:
        """Mint (or replace) the single link share for a conversation.

        A conversation has at most one link share. Any prior link rows are
        hard-deleted first so the URL always reflects the latest 'current
        state' the owner chose to publish.
        """
        cid = to_uuid(conversation_id)
        uid = to_uuid(created_by)
        db.session.execute(
            sa_delete(ConversationShare).where(
                ConversationShare.conversation_id == cid,
                ConversationShare.share_type == 'link',
            )
        )
        row = ConversationShare(
            conversation_id=cid,
            share_type='link',
            created_by=uid,
            token=secrets.token_urlsafe(24),
            snapshot=snapshot or {},
            project_id=None,
        )
        db.session.add(row)
        db.session.commit()
        return _serialize_share(row)

    @staticmethod
    def get_link(conversation_id) -> dict | None:
        """The active (non-revoked) link share for a conversation, or None."""
        cid = maybe_to_uuid(conversation_id)
        if cid is None:
            return None
        row = db.session.execute(
            select(ConversationShare).where(
                ConversationShare.conversation_id == cid,
                ConversationShare.share_type == 'link',
                ConversationShare.revoked_at.is_(None),
            )
        ).scalar_one_or_none()
        return _serialize_share(row)

    @staticmethod
    def get_by_token(token) -> dict | None:
        """Resolve an active link share by token (public snapshot view)."""
        if not token:
            return None
        row = db.session.execute(
            select(ConversationShare).where(
                ConversationShare.token == token,
                ConversationShare.share_type == 'link',
                ConversationShare.revoked_at.is_(None),
            )
        ).scalar_one_or_none()
        return _serialize_share(row)

    @staticmethod
    def revoke_link(conversation_id) -> bool:
        """Revoke the conversation's link share by HARD-deleting the row.

        A soft ``revoked_at`` stamp left the full-content ``snapshot`` JSONB blob
        resident forever (a data-erasure gap — revoked content stopped being
        servable but never stopped residing). Deleting the row drops the blob too;
        the read path already 404s on a missing token, so revocation behavior is
        unchanged.
        """
        cid = maybe_to_uuid(conversation_id)
        if cid is None:
            return False
        result = db.session.execute(
            sa_delete(ConversationShare).where(
                ConversationShare.conversation_id == cid,
                ConversationShare.share_type == 'link',
            )
        )
        db.session.commit()
        return (result.rowcount or 0) > 0

    # ------------------------------------------------------------------ team
    @staticmethod
    def team_project_ids(conversation_id) -> list[str]:
        """Active team-share target project ids for a conversation."""
        cid = maybe_to_uuid(conversation_id)
        if cid is None:
            return []
        rows = db.session.execute(
            select(ConversationShare.project_id).where(
                ConversationShare.conversation_id == cid,
                ConversationShare.share_type == 'team',
                ConversationShare.revoked_at.is_(None),
            )
        ).all()
        return [str(r[0]) for r in rows if r[0] is not None]

    @staticmethod
    def delete_for_conversation(conversation_id) -> int:
        """Hard-delete EVERY share row (link + team) for a conversation.

        Used on conversation delete: previously only team grants were removed and
        the link row was orphaned (its ``conversation_id`` FK SET NULL) — keeping
        the full-content ``snapshot`` blob resident forever (erasure gap). Hard
        deletion drops the blob with the chat. The read path 404s on the now-gone
        token, so any outstanding link stops being servable AND stops residing.
        """
        cid = maybe_to_uuid(conversation_id)
        if cid is None:
            return 0
        result = db.session.execute(
            sa_delete(ConversationShare).where(
                ConversationShare.conversation_id == cid,
            )
        )
        db.session.commit()
        return result.rowcount or 0

    @staticmethod
    def set_team_shares(conversation_id, created_by, project_ids) -> list[str]:
        """Diff the team-share set to exactly *project_ids*.

        Rows for teams no longer in the set are hard-deleted; missing ones are
        inserted; a previously-revoked row for a still-desired team is
        reactivated. Returns the resulting active project-id list (strings).
        """
        cid = to_uuid(conversation_id)
        uid = to_uuid(created_by)

        desired = set()
        for p in (project_ids or []):
            pu = maybe_to_uuid(p)
            if pu is not None:
                desired.add(pu)

        existing = db.session.execute(
            select(ConversationShare).where(
                ConversationShare.conversation_id == cid,
                ConversationShare.share_type == 'team',
            )
        ).scalars().all()
        by_pid = {r.project_id: r for r in existing}

        for pid, row in by_pid.items():
            if pid not in desired:
                db.session.delete(row)

        for pid in desired:
            row = by_pid.get(pid)
            if row is None:
                db.session.add(ConversationShare(
                    conversation_id=cid,
                    share_type='team',
                    created_by=uid,
                    project_id=pid,
                    token=None,
                    snapshot=None,
                ))
            elif row.revoked_at is not None:
                row.revoked_at = None

        db.session.commit()
        return [str(p) for p in desired]

    # ----------------------------------------------------------------- query
    @staticmethod
    def user_can_access(conversation_id, user_id) -> bool:
        """True iff *user_id* is a member of any team this conversation is
        actively shared into. The owner check is the caller's responsibility —
        this widens it, it does not replace it.
        """
        from app.utils.permissions import check_project_access
        for pid in ConversationShareModel.team_project_ids(conversation_id):
            if check_project_access(user_id, pid, 'viewer'):
                return True
        return False

    @staticmethod
    def summary_for(conversation_id) -> dict:
        """Compact share state for a single conversation payload."""
        return ConversationShareModel.summary_for_many(
            [conversation_id]
        ).get(str(conversation_id), _empty_summary())

    @staticmethod
    def summary_for_many(conversation_ids) -> dict:
        """Batch share-state lookup: ``{conversation_id_str -> summary}``.

        Summary shape: ``{is_shared, via_link, teams: [project_id_str, ...]}``.
        One query for the whole page — no per-row N+1.
        """
        ids = [maybe_to_uuid(c) for c in (conversation_ids or [])]
        ids = [i for i in ids if i is not None]
        if not ids:
            return {}
        rows = db.session.execute(
            select(
                ConversationShare.conversation_id,
                ConversationShare.share_type,
                ConversationShare.project_id,
            ).where(
                ConversationShare.conversation_id.in_(ids),
                ConversationShare.revoked_at.is_(None),
            )
        ).all()
        bucket: dict = {}
        for cid, share_type, pid in rows:
            summary = bucket.setdefault(str(cid), _empty_summary())
            if share_type == 'team' and pid is not None:
                summary['teams'].append(str(pid))
                summary['is_shared'] = True
            elif share_type == 'link':
                summary['via_link'] = True
                summary['is_shared'] = True
        return bucket


def _empty_summary() -> dict:
    return {'is_shared': False, 'via_link': False, 'teams': []}


# ---------------------------------------------------------------------------
# SQLAlchemy 2.0 ORM model (Postgres).
# ---------------------------------------------------------------------------
class ConversationShare(db.Model, SerializableMixin):
    __tablename__ = 'conversation_shares'

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Nullable + SET NULL: a link snapshot is self-contained and OUTLIVES the
    # source conversation (deleting the original must not break the link or any
    # saved copy). Team grants are hard-deleted on conversation delete instead.
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('conversations.id', ondelete='SET NULL'),
        nullable=True,
    )
    share_type: Mapped[str] = mapped_column(db.Text, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    # Link-only: random URL-safe token addressing the public snapshot view.
    token: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    # Link-only: frozen conversation snapshot at share time.
    snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Team-only: the team (project) granted live read+contribute access.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('projects.id', ondelete='CASCADE'),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "share_type IN ('link','team')",
            name='ck_conversation_shares_type',
        ),
        # Team rows are unique per (conversation, team); link rows carry a NULL
        # project_id (NULLs are distinct in PG) so they never collide here.
        UniqueConstraint(
            'conversation_id', 'project_id',
            name='uq_conversation_shares_conv_project',
        ),
        Index('ix_conversation_shares_conversation', 'conversation_id'),
        Index('ix_conversation_shares_project', 'project_id'),
        Index(
            'ix_conversation_shares_token', 'token',
            unique=True, postgresql_where=text('token IS NOT NULL'),
        ),
    )
