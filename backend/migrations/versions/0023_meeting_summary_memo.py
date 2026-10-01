"""meeting_summaries.memo for action pack

Revision ID: 0023_meeting_summary_memo
Revises: 0022_dlp_tier_a_sources
Create Date: 2026-07-21 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023_meeting_summary_memo"
down_revision: Union[str, Sequence[str], None] = "0022_dlp_tier_a_sources"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "meeting_summaries",
        sa.Column("memo", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("meeting_summaries", "memo")
