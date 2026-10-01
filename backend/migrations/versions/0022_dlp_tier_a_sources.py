"""dlp_events sources for Tier A studio tools

Adds: research, email_writer, contract, tender, cv_checker

Revision ID: 0022_dlp_tier_a_sources
Revises: 0021_dlp_ocr_source
Create Date: 2026-07-21 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0022_dlp_tier_a_sources"
down_revision: Union[str, Sequence[str], None] = "0021_dlp_ocr_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FULL = (
    "source IN ('chat','arena','workflow','helper','image_prompt',"
    "'meeting','debate','automate','assistant','presentation','agent','ocr',"
    "'research','email_writer','contract','tender','cv_checker')"
)

_PREV = (
    "source IN ('chat','arena','workflow','helper','image_prompt',"
    "'meeting','debate','automate','assistant','presentation','agent','ocr')"
)


def upgrade() -> None:
    op.drop_constraint("ck_dlp_events_source", "dlp_events", type_="check")
    op.create_check_constraint("ck_dlp_events_source", "dlp_events", _FULL)


def downgrade() -> None:
    op.drop_constraint("ck_dlp_events_source", "dlp_events", type_="check")
    op.create_check_constraint("ck_dlp_events_source", "dlp_events", _PREV)
