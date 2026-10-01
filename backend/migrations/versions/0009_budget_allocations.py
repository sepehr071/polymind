"""add budget_allocations — hierarchical spend caps

Phase 1 of the hierarchical-billing build. One configurable spend ceiling per
scope (``holding | company | team | user``) and period (``mtd | absolute``).
Additive + dark-flagged (gated behind the ``billing_enforcement`` feature flag,
default OFF) so applying it is safe on a live DB.

Mirrors the ``BudgetAllocation`` ORM ``__table_args__`` (canonical source for
autogenerate + fresh-DB bootstrap). ``created_by_user_id`` is polymorphic (NO
FK), like ``credit_ledger.created_by_user_id``. The unique index COALESCEs a NULL
``scope_id`` (holding scope) to the zero UUID so the holding row is unique on
(scope_type, period) too.

Revision ID: 0009_budget_allocations
Revises: 0008_usage_cost_detail
Create Date: 2026-06-04 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# NB: kept <=32 chars to fit alembic_version.version_num (varchar(32)).
revision: str = '0009_budget_allocations'
down_revision: Union[str, Sequence[str], None] = '0008_usage_cost_detail'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the ``budget_allocations`` table + its indexes."""

    op.create_table(
        'budget_allocations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('scope_type', sa.Text(), nullable=False),
        sa.Column('scope_id', sa.UUID(), nullable=True),
        sa.Column('period', sa.Text(), server_default=sa.text("'mtd'"), nullable=False),
        sa.Column('amount_usd', sa.Numeric(precision=14, scale=8), nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('parent_scope_type', sa.Text(), nullable=True),
        sa.Column('parent_scope_id', sa.UUID(), nullable=True),
        sa.Column('created_by_user_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "scope_type IN ('holding','company','team','user')",
            name='ck_budget_allocations_scope_type',
        ),
        sa.CheckConstraint(
            "scope_id IS NOT NULL OR scope_type = 'holding'",
            name='ck_budget_allocations_scope_id',
        ),
        sa.CheckConstraint(
            "period IN ('mtd','absolute')",
            name='ck_budget_allocations_period',
        ),
        sa.CheckConstraint(
            'amount_usd >= 0',
            name='ck_budget_allocations_amount',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'uq_budget_alloc_scope_period',
        'budget_allocations',
        [
            'scope_type',
            sa.literal_column(
                "COALESCE(scope_id, '00000000-0000-0000-0000-000000000000'::uuid)"
            ),
            'period',
        ],
        unique=True,
    )
    op.create_index(
        'ix_budget_alloc_scope_enabled',
        'budget_allocations',
        ['scope_type', 'scope_id'],
        unique=False,
        postgresql_where=sa.text('enabled'),
    )


def downgrade() -> None:
    """Drop the ``budget_allocations`` table + its indexes."""

    op.drop_index('ix_budget_alloc_scope_enabled', table_name='budget_allocations')
    op.drop_index('uq_budget_alloc_scope_period', table_name='budget_allocations')
    op.drop_table('budget_allocations')
