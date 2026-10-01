"""image edit threads: image_conversations table + thread cols on generated_images

Conversational image editing groups a series of edits ("make it blue", "now add
a hat") under an ``image_conversations`` row. Each ``generated_images`` row is a
turn; ``conversation_id`` links it to its thread and ``parent_image_id`` records
which prior image it edited (fed back in as the input/edit base). Both columns
are nullable so one-shot generations and all legacy rows stay valid.

Mirrors the ORM in ``app/models/generated_image.py`` (canonical for autogenerate
+ fresh-DB bootstrap).

Revision ID: 0013_image_threads
Revises: 0012_dlp_assistant_source
Create Date: 2026-06-09 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
# NB: kept <=32 chars to fit alembic_version.version_num (varchar(32)).
revision: str = '0013_image_threads'
down_revision: Union[str, Sequence[str], None] = '0012_dlp_assistant_source'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'image_conversations',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('config_id', sa.Text(), nullable=True),
        sa.Column('workspace_id', UUID(as_uuid=True), nullable=True),
        sa.Column('project_id', UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
    )
    op.create_index('ix_image_conversations_user', 'image_conversations', ['user_id'])
    op.create_index('ix_image_conversations_updated', 'image_conversations',
                    [sa.text('updated_at DESC')])

    op.add_column('generated_images',
                  sa.Column('conversation_id', UUID(as_uuid=True), nullable=True))
    op.add_column('generated_images',
                  sa.Column('parent_image_id', UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_generated_images_conversation', 'generated_images',
        'image_conversations', ['conversation_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index('ix_generated_images_conversation', 'generated_images',
                    ['conversation_id'])


def downgrade() -> None:
    op.drop_index('ix_generated_images_conversation', table_name='generated_images')
    op.drop_constraint('fk_generated_images_conversation', 'generated_images',
                       type_='foreignkey')
    op.drop_column('generated_images', 'parent_image_id')
    op.drop_column('generated_images', 'conversation_id')
    op.drop_index('ix_image_conversations_updated', table_name='image_conversations')
    op.drop_index('ix_image_conversations_user', table_name='image_conversations')
    op.drop_table('image_conversations')
