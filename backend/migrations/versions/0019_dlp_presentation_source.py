"""widen dlp_events.source CHECK to admit the 'presentation' source

AI presentation generation is DLP-gated (the outline topic + assembled source
material), logging ``dlp_events`` rows with ``source='presentation'``. PG
enforces the ``ck_dlp_events_source`` CHECK constraint, so the new legal value
needs a constraint widen here (mirrors the ORM ``CheckConstraint`` in
``app/models/dlp_event.py`` + the ``VALID_SOURCES`` set — canonical for
autogenerate + fresh-DB bootstrap). Same drop+recreate pattern as
``0012_dlp_assistant_source``.

Revision ID: 0019_dlp_presentation_source
Revises: 0018_presentations
Create Date: 2026-06-30 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
# NB: kept <=32 chars to fit alembic_version.version_num (varchar(32)).
revision: str = '0019_dlp_presentation_source'
down_revision: Union[str, Sequence[str], None] = '0018_presentations'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add 'presentation' to the dlp_events.source CHECK constraint."""
    op.drop_constraint('ck_dlp_events_source', 'dlp_events', type_='check')
    op.create_check_constraint(
        'ck_dlp_events_source',
        'dlp_events',
        "source IN ('chat','arena','workflow','helper','image_prompt',"
        "'meeting','debate','automate','assistant','presentation')",
    )


def downgrade() -> None:
    """Reverse: restore the narrower source set (sans 'presentation')."""
    op.drop_constraint('ck_dlp_events_source', 'dlp_events', type_='check')
    op.create_check_constraint(
        'ck_dlp_events_source',
        'dlp_events',
        "source IN ('chat','arena','workflow','helper','image_prompt',"
        "'meeting','debate','automate','assistant')",
    )
