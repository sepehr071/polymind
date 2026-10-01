"""conversation kind discriminator: conversations.kind ('chat' | 'data')

Separates Data-Analyzer conversations (``kind='data'``) from normal chat
(``kind='chat'``, the default) so the chat sidebar can filter them out and the
dedicated Data-Analyzer page lists only its own. A single TEXT column on the
existing ``conversations`` table:

  * ``kind`` — NOT NULL, server_default ``'chat'``; CHECK restricts to the two
    known values. Existing rows backfill to ``'chat'`` via the server default.

A composite index ``(user_id, kind, last_message_at DESC NULLS LAST)`` backs the
new ``?kind=`` filtered list query the same way the existing
``ix_conversations_user_last_message_at`` backs the unfiltered one.

Mirrors the ``Conversation`` ORM ``mapped_column`` + ``__table_args__`` additions
(canonical source for autogenerate + fresh-DB bootstrap).

Revision ID: 0016_conversation_kind
Revises: 0015_share_snapshot_decouple
Create Date: 2026-06-11 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# NB: kept <=32 chars to fit alembic_version.version_num (varchar(32)).
revision: str = '0016_conversation_kind'
down_revision: Union[str, Sequence[str], None] = '0015_share_snapshot_decouple'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'conversations',
        sa.Column('kind', sa.Text(), nullable=False, server_default=sa.text("'chat'")),
    )
    op.create_check_constraint(
        'ck_conversations_kind',
        'conversations',
        "kind IN ('chat','data')",
    )
    op.create_index(
        'ix_conversations_user_kind_last_message_at',
        'conversations',
        ['user_id', 'kind', sa.text('last_message_at DESC NULLS LAST')],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_conversations_user_kind_last_message_at', table_name='conversations'
    )
    op.drop_constraint('ck_conversations_kind', 'conversations', type_='check')
    op.drop_column('conversations', 'kind')
