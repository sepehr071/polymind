"""conversation kind 'agent' + dlp_events source 'agent'

All-in-one router agent reuses conversations with kind='agent' (separate from
chat/data rails) and logs DLP events with source='agent'.

Revision ID: 0020_agent_kind_dlp
Revises: 0019_dlp_presentation_source
Create Date: 2026-07-18 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = '0020_agent_kind_dlp'
down_revision: Union[str, Sequence[str], None] = '0019_dlp_presentation_source'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('ck_conversations_kind', 'conversations', type_='check')
    op.create_check_constraint(
        'ck_conversations_kind',
        'conversations',
        "kind IN ('chat','data','agent')",
    )

    op.drop_constraint('ck_dlp_events_source', 'dlp_events', type_='check')
    op.create_check_constraint(
        'ck_dlp_events_source',
        'dlp_events',
        "source IN ('chat','arena','workflow','helper','image_prompt',"
        "'meeting','debate','automate','assistant','presentation','agent')",
    )


def downgrade() -> None:
    op.drop_constraint('ck_dlp_events_source', 'dlp_events', type_='check')
    op.create_check_constraint(
        'ck_dlp_events_source',
        'dlp_events',
        "source IN ('chat','arena','workflow','helper','image_prompt',"
        "'meeting','debate','automate','assistant','presentation')",
    )

    # Rows with kind='agent' must be removed or re-tagged before narrowing.
    op.execute("UPDATE conversations SET kind = 'chat' WHERE kind = 'agent'")
    op.drop_constraint('ck_conversations_kind', 'conversations', type_='check')
    op.create_check_constraint(
        'ck_conversations_kind',
        'conversations',
        "kind IN ('chat','data')",
    )
