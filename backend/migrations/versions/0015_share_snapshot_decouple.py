"""decouple link snapshots from the source conversation

A link share is a self-contained FROZEN snapshot: anyone signed in can open it
and save their OWN independent copy. So the snapshot must OUTLIVE the original
conversation — deleting the source chat must not break the link or anyone's
saved copy. Switch ``conversation_shares.conversation_id`` from NOT NULL + ON
DELETE CASCADE to nullable + ON DELETE SET NULL.

Team grants (share_type='team') are live access and are hard-deleted in the
conversation-delete handler instead (see routers/conversations.py).

Revision ID: 0015_share_snapshot_decouple
Revises: 0014_conversation_shares
Create Date: 2026-06-10 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = '0015_share_snapshot_decouple'
down_revision: Union[str, Sequence[str], None] = '0014_conversation_shares'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FK = 'conversation_shares_conversation_id_fkey'


def upgrade() -> None:
    op.drop_constraint(_FK, 'conversation_shares', type_='foreignkey')
    op.alter_column('conversation_shares', 'conversation_id',
                    existing_type=UUID(as_uuid=True), nullable=True)
    op.create_foreign_key(
        _FK, 'conversation_shares', 'conversations',
        ['conversation_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(_FK, 'conversation_shares', type_='foreignkey')
    # Orphaned snapshots (conversation already deleted) would violate NOT NULL.
    op.execute("DELETE FROM conversation_shares WHERE conversation_id IS NULL")
    op.alter_column('conversation_shares', 'conversation_id',
                    existing_type=UUID(as_uuid=True), nullable=False)
    op.create_foreign_key(
        _FK, 'conversation_shares', 'conversations',
        ['conversation_id'], ['id'], ondelete='CASCADE',
    )
