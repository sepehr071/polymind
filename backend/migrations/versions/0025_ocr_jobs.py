"""ocr_jobs table — OCR assistant extract history

One row per extract run. files JSONB = per-upload status + markdown.
List queries use (user_id, created_at). CHECK mirrors models/ocr_job.py:VALID_STATUS.

Revision ID: 0025_ocr_jobs
Revises: 0024_dlp_shop_source
Create Date: 2026-09-19 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID

revision: str = '0025_ocr_jobs'
down_revision: Union[str, Sequence[str], None] = '0024_dlp_shop_source'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ocr_jobs',
        sa.Column('id', UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), nullable=False),
        sa.Column('workspace_id', UUID(as_uuid=True), nullable=True),
        sa.Column('prompt', sa.Text(), nullable=False, server_default=''),
        sa.Column('title', sa.Text(), nullable=False, server_default='OCR'),
        sa.Column('status', sa.Text(), nullable=False, server_default='running'),
        sa.Column(
            'files', JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
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
            "status IN ('running','done','failed','cancelled')",
            name='ck_ocr_jobs_status',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ocr_jobs_user_id', 'ocr_jobs', ['user_id'])
    op.create_index('ix_ocr_jobs_workspace_id', 'ocr_jobs', ['workspace_id'])
    op.create_index('ix_ocr_jobs_user_created', 'ocr_jobs', ['user_id', 'created_at'])


def downgrade() -> None:
    op.drop_table('ocr_jobs')
