"""conversation sharing: conversation_shares table + messages.sender_user_id

Two share modes in one table (``conversation_shares``):
  * ``share_type='link'`` — random ``token`` + frozen ``snapshot`` (JSONB); any
    logged-in user can open the read-only snapshot at ``/api/share/{token}``.
  * ``share_type='team'`` — one row per ``project_id`` (team) granted live
    read+contribute access to the conversation.

``messages.sender_user_id`` records the human author of a USER turn in a
collaborative (team-shared) chat; NULL on assistant rows and legacy/owner turns.

Mirrors the ORM in ``app/models/conversation_share.py`` + the new column on
``app/models/message.py`` (canonical for autogenerate + fresh-DB bootstrap).

Revision ID: 0014_conversation_shares
Revises: 0013_image_threads
Create Date: 2026-06-10 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
# NB: kept <=32 chars to fit alembic_version.version_num (varchar(32)).
revision: str = '0014_conversation_shares'
down_revision: Union[str, Sequence[str], None] = '0013_image_threads'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'conversation_shares',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('conversation_id', UUID(as_uuid=True),
                  sa.ForeignKey('conversations.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('share_type', sa.Text(), nullable=False),
        sa.Column('created_by', UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token', sa.Text(), nullable=True),
        sa.Column('snapshot', JSONB(), nullable=True),
        sa.Column('project_id', UUID(as_uuid=True),
                  sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("share_type IN ('link','team')",
                           name='ck_conversation_shares_type'),
        sa.UniqueConstraint('conversation_id', 'project_id',
                            name='uq_conversation_shares_conv_project'),
    )
    op.create_index('ix_conversation_shares_conversation', 'conversation_shares',
                    ['conversation_id'])
    op.create_index('ix_conversation_shares_project', 'conversation_shares',
                    ['project_id'])
    # Partial unique: only link rows carry a token; team rows leave it NULL.
    op.create_index('ix_conversation_shares_token', 'conversation_shares',
                    ['token'], unique=True,
                    postgresql_where=sa.text('token IS NOT NULL'))

    op.add_column('messages',
                  sa.Column('sender_user_id', UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_messages_sender_user', 'messages', 'users',
        ['sender_user_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index('ix_messages_sender_user', 'messages', ['sender_user_id'])


def downgrade() -> None:
    op.drop_index('ix_messages_sender_user', table_name='messages')
    op.drop_constraint('fk_messages_sender_user', 'messages', type_='foreignkey')
    op.drop_column('messages', 'sender_user_id')
    op.drop_index('ix_conversation_shares_token', table_name='conversation_shares')
    op.drop_index('ix_conversation_shares_project', table_name='conversation_shares')
    op.drop_index('ix_conversation_shares_conversation',
                  table_name='conversation_shares')
    op.drop_table('conversation_shares')
