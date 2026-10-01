"""widen dlp_events.source CHECK to admit the 'assistant' source

Custom-assistant persona prompts are now DLP-gated at save (configs create /
update + enhance-prompt), logging ``dlp_events`` rows with ``source='assistant'``.
PG enforces the ``ck_dlp_events_source`` CHECK constraint that Mongo never did,
so the new legal value needs a constraint widen here (mirrors the ORM
``CheckConstraint`` in ``app/models/dlp_event.py`` — canonical for autogenerate +
fresh-DB bootstrap).

Revision ID: 0012_dlp_assistant_source
Revises: 0011_revoked_tokens_no_fk
Create Date: 2026-06-09 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
# NB: kept <=32 chars to fit alembic_version.version_num (varchar(32)).
revision: str = '0012_dlp_assistant_source'
down_revision: Union[str, Sequence[str], None] = '0011_revoked_tokens_no_fk'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add 'assistant' to the dlp_events.source CHECK constraint."""
    op.drop_constraint('ck_dlp_events_source', 'dlp_events', type_='check')
    op.create_check_constraint(
        'ck_dlp_events_source',
        'dlp_events',
        "source IN ('chat','arena','workflow','helper','image_prompt',"
        "'meeting','debate','automate','assistant')",
    )


def downgrade() -> None:
    """Reverse: restore the narrower source set (sans 'assistant')."""
    op.drop_constraint('ck_dlp_events_source', 'dlp_events', type_='check')
    op.create_check_constraint(
        'ck_dlp_events_source',
        'dlp_events',
        "source IN ('chat','arena','workflow','helper','image_prompt',"
        "'meeting','debate','automate')",
    )
