"""widen dlp_events CHECK constraints for the redact action

DLP "redact mode" adds a new event outcome where sensitive spans are spliced
out (replaced with typed placeholders) and the scrubbed text proceeds to the
LLM. This needs two new legal values on ``dlp_events``:

  * ``highest_action`` gains ``'redact'``
  * ``status`` gains ``'redacted'`` (the outcome enum). The review-workflow
    values (``open|reviewed|dismissed|escalated``) are also admitted here so
    the column tolerates either family — mirrors the ORM CheckConstraint widen.

The per-match ``dlp_event_matches.action`` constraint is intentionally LEFT
UNCHANGED — individual matches keep their rule-level action
(block/require_confirm/warn); ``redact`` is an event-level outcome only.

Mirrors the ORM ``CheckConstraint`` widen in ``app/models/dlp_event.py``
(canonical source for autogenerate + fresh-DB bootstrap).

Revision ID: 0005_dlp_redact_action
Revises: 0004_upload_extracted_text
Create Date: 2026-06-01 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
# NB: kept <=32 chars to fit alembic_version.version_num (varchar(32)).
revision: str = '0005_dlp_redact_action'
down_revision: Union[str, Sequence[str], None] = '0004_upload_extracted_text'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Widen the two dlp_events CHECK constraints to admit redact / redacted."""

    # 1. dlp_events.highest_action — add 'redact'.
    op.drop_constraint(
        'ck_dlp_events_highest_action', 'dlp_events', type_='check'
    )
    op.create_check_constraint(
        'ck_dlp_events_highest_action',
        'dlp_events',
        "highest_action IN ('block','require_confirm','warn','allow','redact')",
    )

    # 2. dlp_events.status — add 'redacted' (plus the review-workflow enum).
    op.drop_constraint(
        'ck_dlp_events_status', 'dlp_events', type_='check'
    )
    op.create_check_constraint(
        'ck_dlp_events_status',
        'dlp_events',
        "status IN ('blocked','confirmed','warned','allowed','redacted',"
        "'open','reviewed','dismissed','escalated')",
    )


def downgrade() -> None:
    """Reverse: restore the narrower CHECK constraints."""

    # 2. dlp_events.status — restore the narrow outcome enum.
    op.drop_constraint(
        'ck_dlp_events_status', 'dlp_events', type_='check'
    )
    op.create_check_constraint(
        'ck_dlp_events_status',
        'dlp_events',
        "status IN ('blocked','confirmed','warned','allowed')",
    )

    # 1. dlp_events.highest_action — restore the narrow action set.
    op.drop_constraint(
        'ck_dlp_events_highest_action', 'dlp_events', type_='check'
    )
    op.create_check_constraint(
        'ck_dlp_events_highest_action',
        'dlp_events',
        "highest_action IN ('block','require_confirm','warn','allow')",
    )
