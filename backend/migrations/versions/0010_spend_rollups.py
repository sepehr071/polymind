"""add spend_rollups — per-scope/month spend counters

Phase 1 of the hierarchical-billing build. Incrementally-maintained
``spent_usd`` + ``calls`` per ``(scope_type, scope_id, period_month)`` so the
spend-gate avoids a ``SUM(usage_logs)`` scan on the hot path. ``period_month ==
1970-01-01`` is the LIFETIME sentinel (company scope only). Additive + populated
by the metering write path + an idempotent backfill script — safe on a live DB.

Mirrors the ``SpendRollup`` ORM ``__table_args__`` (canonical source for
autogenerate + fresh-DB bootstrap). Surrogate UUID PK; the upsert target is the
``uq_spend_rollups_scope_period`` unique constraint.

Revision ID: 0010_spend_rollups
Revises: 0009_budget_allocations
Create Date: 2026-06-04 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# NB: kept <=32 chars to fit alembic_version.version_num (varchar(32)).
revision: str = '0010_spend_rollups'
down_revision: Union[str, Sequence[str], None] = '0009_budget_allocations'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the ``spend_rollups`` table + its indexes."""

    op.create_table(
        'spend_rollups',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('scope_type', sa.Text(), nullable=False),
        sa.Column('scope_id', sa.UUID(), nullable=False),
        sa.Column('period_month', sa.Date(), nullable=False),
        sa.Column('spent_usd', sa.Numeric(precision=14, scale=8), server_default=sa.text('0'), nullable=False),
        sa.Column('calls', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "scope_type IN ('company','team','user')",
            name='ck_spend_rollups_scope_type',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'scope_type', 'scope_id', 'period_month',
            name='uq_spend_rollups_scope_period',
        ),
    )
    op.create_index(
        'ix_spend_rollups_scope',
        'spend_rollups',
        ['scope_type', 'scope_id'],
        unique=False,
    )


def downgrade() -> None:
    """Drop the ``spend_rollups`` table + its index."""

    op.drop_index('ix_spend_rollups_scope', table_name='spend_rollups')
    op.drop_table('spend_rollups')
