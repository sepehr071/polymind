"""add upstream_cost_usd + cache_write_tokens to usage_logs

Cost-detail columns the write path (``OpenRouterService._record_usage`` ->
``UsageLogModel.create``) already computes but had nowhere to land:

  * ``upstream_cost_usd`` — ``Numeric(14, 8)`` NULL: OpenRouter's reported
    upstream (provider) cost, distinct from the billed ``cost_usd``.
  * ``cache_write_tokens`` — ``Integer`` NULL: prompt-cache *write* tokens
    (``prompt_tokens_details.cache_write_tokens``), the write-side counterpart
    of the existing ``cached_tokens`` (cache *read*).

Both nullable (no backfill — historical rows simply have NULL). Mirrors the
``UsageLog`` ORM ``mapped_column`` additions (canonical source for autogenerate
+ fresh-DB bootstrap).

Revision ID: 0008_usage_cost_detail
Revises: 0007_add_image_thumb
Create Date: 2026-06-03 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# NB: kept <=32 chars to fit alembic_version.version_num (varchar(32)).
revision: str = '0008_usage_cost_detail'
down_revision: Union[str, Sequence[str], None] = '0007_add_image_thumb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the nullable cost-detail columns to ``usage_logs``."""

    op.add_column(
        'usage_logs',
        sa.Column('upstream_cost_usd', sa.Numeric(14, 8), nullable=True),
    )
    op.add_column(
        'usage_logs',
        sa.Column('cache_write_tokens', sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    """Drop the cost-detail columns."""

    op.drop_column('usage_logs', 'cache_write_tokens')
    op.drop_column('usage_logs', 'upstream_cost_usd')
