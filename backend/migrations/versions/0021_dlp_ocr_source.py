"""dlp_events source 'ocr'

OCR assistant logs DLP events with source='ocr'.

Revision ID: 0021_dlp_ocr_source
Revises: 0020_agent_kind_dlp
Create Date: 2026-07-21 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0021_dlp_ocr_source"
down_revision: Union[str, Sequence[str], None] = "0020_agent_kind_dlp"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_dlp_events_source", "dlp_events", type_="check")
    op.create_check_constraint(
        "ck_dlp_events_source",
        "dlp_events",
        "source IN ('chat','arena','workflow','helper','image_prompt',"
        "'meeting','debate','automate','assistant','presentation','agent','ocr')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_dlp_events_source", "dlp_events", type_="check")
    op.create_check_constraint(
        "ck_dlp_events_source",
        "dlp_events",
        "source IN ('chat','arena','workflow','helper','image_prompt',"
        "'meeting','debate','automate','assistant','presentation','agent')",
    )
