"""add extracted-text columns to uploads (chat attachments)

Chat attachments extract document text (markitdown → Markdown) at upload time
so it can be threaded into prompts. Three nullable/defaulted columns hold the
result on the existing ``uploads`` table:

  * ``extracted_text``     — the extracted Markdown (NULL for images / native
    PDF / non-extractable types).
  * ``extracted_chars``    — character count of the extracted text (default 0).
  * ``extraction_status``  — {'ok','truncated','error','unavailable','na'} or
    NULL when extraction did not apply.

Mirrors the ``Upload`` ORM ``mapped_column`` additions (canonical source for
autogenerate + fresh-DB bootstrap).

Revision ID: 0004_upload_extracted_text
Revises: 0003_add_stream_fk_indexes
Create Date: 2026-05-31 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# NB: kept <=32 chars to fit alembic_version.version_num (varchar(32)).
revision: str = '0004_upload_extracted_text'
down_revision: Union[str, Sequence[str], None] = '0003_add_stream_fk_indexes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the three extracted-text columns to ``uploads``."""

    op.add_column('uploads', sa.Column('extracted_text', sa.Text(), nullable=True))
    op.add_column(
        'uploads',
        sa.Column(
            'extracted_chars',
            sa.Integer(),
            server_default=sa.text('0'),
            nullable=False,
        ),
    )
    op.add_column('uploads', sa.Column('extraction_status', sa.Text(), nullable=True))


def downgrade() -> None:
    """Drop the three columns (reverse order)."""

    op.drop_column('uploads', 'extraction_status')
    op.drop_column('uploads', 'extracted_chars')
    op.drop_column('uploads', 'extracted_text')
