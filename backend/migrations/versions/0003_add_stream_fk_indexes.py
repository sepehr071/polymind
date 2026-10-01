"""add FK indexes for hot arena/debate/DLP read paths

Perf fix: three foreign-key columns on high-traffic child tables had no
supporting index, forcing sequential scans on hot paths:

  1. ``arena_messages (session_id, order_idx)`` — covers find_by_session
     ordering and the ``MAX(order_idx)`` next-index probe on every insert.
  2. ``debate_messages (session_id, order_idx)`` — covers find_by_session /
     find_by_session_and_round range scans and the insert-time reads.
  3. ``dlp_event_matches (event_id)`` — covers the matches->events join in the
     DLP stats rollups (top_rules) and the per-event match hydration.

These mirror the ``Index`` entries added to each model's ``__table_args__``
(canonical source for autogenerate + fresh-DB bootstrap).

Revision ID: 0003_add_stream_fk_indexes
Revises: 0002_widen_checks_retarget_fks
Create Date: 2026-05-31 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
# NB: kept <=32 chars to fit alembic_version.version_num (varchar(32)).
revision: str = '0003_add_stream_fk_indexes'
down_revision: Union[str, Sequence[str], None] = '0002_widen_checks_retarget_fks'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the three missing FK-supporting indexes."""

    # 1. arena_messages — find_by_session ordering + MAX(order_idx) probe.
    op.create_index(
        'ix_arena_messages_session_order',
        'arena_messages',
        ['session_id', 'order_idx'],
    )

    # 2. debate_messages — find_by_session / find_by_session_and_round.
    op.create_index(
        'ix_debate_messages_session_order',
        'debate_messages',
        ['session_id', 'order_idx'],
    )

    # 3. dlp_event_matches — matches->events join + per-event hydration.
    op.create_index(
        'ix_dlp_event_matches_event',
        'dlp_event_matches',
        ['event_id'],
    )


def downgrade() -> None:
    """Drop the three indexes (reverse order)."""

    op.drop_index('ix_dlp_event_matches_event', table_name='dlp_event_matches')
    op.drop_index('ix_debate_messages_session_order', table_name='debate_messages')
    op.drop_index('ix_arena_messages_session_order', table_name='arena_messages')
