"""add review-workflow fields to dlp_events

DLP review round-2 persists the admin triage workflow. Previously
``DLPEventModel.update_review`` was a no-op because ``dlp_events`` had no
review columns (only the outcome ``status`` enum). Four columns capture the
review state distinctly from the outcome:

  * ``review_status``        — {'open','reviewed','dismissed','escalated'},
    NOT NULL default 'open'.
  * ``review_note``          — free-text reviewer note (nullable, capped at
    1000 chars by the model).
  * ``reviewed_by_user_id``  — FK users.id (ON DELETE SET NULL), nullable.
  * ``reviewed_at``          — timestamptz, nullable.

Mirrors the ``DLPEvent`` ORM ``mapped_column`` + ``CheckConstraint`` additions
(canonical source for autogenerate + fresh-DB bootstrap).

Revision ID: 0006_dlp_review_fields
Revises: 0005_dlp_redact_action
Create Date: 2026-06-01 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
# NB: kept <=32 chars to fit alembic_version.version_num (varchar(32)).
revision: str = '0006_dlp_review_fields'
down_revision: Union[str, Sequence[str], None] = '0005_dlp_redact_action'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the four review-workflow columns + the review_status CHECK."""

    op.add_column(
        'dlp_events',
        sa.Column(
            'review_status',
            sa.Text(),
            server_default=sa.text("'open'"),
            nullable=False,
        ),
    )
    op.add_column('dlp_events', sa.Column('review_note', sa.Text(), nullable=True))
    op.add_column(
        'dlp_events',
        sa.Column(
            'reviewed_by_user_id',
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        'dlp_events',
        sa.Column(
            'reviewed_at',
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )

    op.create_foreign_key(
        'fk_dlp_events_reviewed_by_user_id',
        'dlp_events',
        'users',
        ['reviewed_by_user_id'],
        ['id'],
        ondelete='SET NULL',
    )

    op.create_check_constraint(
        'ck_dlp_events_review_status',
        'dlp_events',
        "review_status IN ('open','reviewed','dismissed','escalated')",
    )


def downgrade() -> None:
    """Reverse: drop the CHECK, the FK, then the four columns."""

    op.drop_constraint('ck_dlp_events_review_status', 'dlp_events', type_='check')
    op.drop_constraint(
        'fk_dlp_events_reviewed_by_user_id', 'dlp_events', type_='foreignkey'
    )
    op.drop_column('dlp_events', 'reviewed_at')
    op.drop_column('dlp_events', 'reviewed_by_user_id')
    op.drop_column('dlp_events', 'review_note')
    op.drop_column('dlp_events', 'review_status')
