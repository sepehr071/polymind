"""dlp_events source for shop assistant

Adds: shop

Revision ID: 0024_dlp_shop_source
Revises: 0023_meeting_summary_memo
Create Date: 2026-07-22 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0024_dlp_shop_source"
down_revision: Union[str, Sequence[str], None] = "0023_meeting_summary_memo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FULL = (
    "source IN ('chat','arena','workflow','helper','image_prompt',"
    "'meeting','debate','automate','assistant','presentation','agent','ocr',"
    "'research','email_writer','contract','tender','cv_checker','shop')"
)

_PREV = (
    "source IN ('chat','arena','workflow','helper','image_prompt',"
    "'meeting','debate','automate','assistant','presentation','agent','ocr',"
    "'research','email_writer','contract','tender','cv_checker')"
)


def upgrade() -> None:
    op.drop_constraint("ck_dlp_events_source", "dlp_events", type_="check")
    op.create_check_constraint("ck_dlp_events_source", "dlp_events", _FULL)


def downgrade() -> None:
    op.drop_constraint("ck_dlp_events_source", "dlp_events", type_="check")
    op.create_check_constraint("ck_dlp_events_source", "dlp_events", _PREV)
