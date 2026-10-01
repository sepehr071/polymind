"""presentations table — AI presentation generator records

Backs the AI presentation generator. One row per generated deck, tracked
through its lifecycle via the ``status`` column (CHECK-constrained to the same
set as ``models/presentation.py:VALID_STATUS``). ``options``/``outline`` are
JSONB blobs (render config + the generated outline); ``pptx_upload_id`` is an
FK-free reference into ``uploads`` for the rendered file. Indexed on
``user_id``/``workspace_id``/``project_id`` for scoped list queries plus a
composite ``(user_id, created_at)`` for the per-user reverse-chronological list.

``downgrade`` simply drops the table (the indexes/CHECK go with it).

Revision ID: 0018_presentations
Revises: 0017_merge_platform_into_admin
Create Date: 2026-06-30 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID

# revision identifiers, used by Alembic.
# NB: kept <=32 chars to fit alembic_version.version_num (varchar(32)).
revision: str = '0018_presentations'
down_revision: Union[str, Sequence[str], None] = '0017_merge_platform_into_admin'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'presentations',
        sa.Column('id', UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), nullable=False),
        sa.Column('workspace_id', UUID(as_uuid=True), nullable=True),
        sa.Column('project_id', UUID(as_uuid=True), nullable=True),
        sa.Column('title', sa.Text(), nullable=False, server_default=''),
        sa.Column('status', sa.Text(), nullable=False, server_default='draft'),
        sa.Column('language', sa.Text(), nullable=False, server_default='fa'),
        sa.Column('theme', sa.Text(), nullable=False, server_default='polymind'),
        sa.Column(
            'options', JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            'outline', JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column('pptx_upload_id', UUID(as_uuid=True), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column(
            'created_at',
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.Column(
            'updated_at',
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.CheckConstraint(
            "status IN ('draft','outlining','outline_ready','rendering','ready','failed')",
            name='ck_presentations_status',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_presentations_user_id', 'presentations', ['user_id'])
    op.create_index('ix_presentations_workspace_id', 'presentations', ['workspace_id'])
    op.create_index('ix_presentations_project_id', 'presentations', ['project_id'])
    op.create_index(
        'ix_presentations_user_created', 'presentations', ['user_id', 'created_at']
    )


def downgrade() -> None:
    op.drop_table('presentations')
