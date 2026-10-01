"""add thumb_b64 column to generated_images

True downscaled thumbnails for generated images. History grids render this
small WebP ``data:`` URI (~5-15 KB, max 256px) straight from the list payload
instead of lazy-fetching each tile's full base64 image by id.

A single nullable column on the existing ``generated_images`` table:

  * ``thumb_b64`` — ``data:image/webp;base64,...`` (NULL for un-backfilled
    rows; the frontend falls back to the lazy full-by-id fetch when NULL).

Mirrors the ``GeneratedImage`` ORM ``mapped_column`` addition (canonical source
for autogenerate + fresh-DB bootstrap).

Revision ID: 0007_add_image_thumb
Revises: 0006_dlp_review_fields
Create Date: 2026-06-02 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# NB: kept <=32 chars to fit alembic_version.version_num (varchar(32)).
revision: str = '0007_add_image_thumb'
down_revision: Union[str, Sequence[str], None] = '0006_dlp_review_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the nullable ``thumb_b64`` column to ``generated_images``."""

    op.add_column(
        'generated_images',
        sa.Column('thumb_b64', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Drop the ``thumb_b64`` column."""

    op.drop_column('generated_images', 'thumb_b64')
