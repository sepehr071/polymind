"""Backfill ``thumb_b64`` thumbnails for existing generated images.

New images get a small downscaled WebP thumbnail at create-time (see
``GeneratedImageModel.create`` / ``_make_thumb_data_uri``). This one-off,
idempotent, re-runnable script populates ``thumb_b64`` for rows that predate
that change: it iterates rows where ``thumb_b64 IS NULL AND b64_payload IS NOT
NULL``, generates a thumbnail from the full base64 payload, and commits in
batches.

Rows whose payload can't be decoded into a raster image leave ``thumb_b64``
NULL (the frontend falls back to the lazy full-by-id fetch for those tiles);
they're counted as ``skipped`` and re-attempted on the next run.

Usage (loads the dev DSN from backend/.env, like seed.py):
    ./.venv-uv/Scripts/python.exe scripts/backfill_image_thumbs.py
    ./.venv-uv/Scripts/python.exe scripts/backfill_image_thumbs.py --batch 200 --limit 1000

Or target another DB explicitly:
    SQLALCHEMY_DATABASE_URI=postgresql+psycopg://... \
        ./.venv-uv/Scripts/python.exe scripts/backfill_image_thumbs.py
"""
from __future__ import annotations

import argparse
import os
import sys

# Load backend/.env BEFORE importing the app package — Config reads
# SQLALCHEMY_DATABASE_URI at class-def time (mirrors scripts/seed.py). An
# explicit SQLALCHEMY_DATABASE_URI already in the environment wins (override
# only fills the gaps it doesn't set).
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, '.env'), override=False)
except Exception:  # noqa: BLE001 — dotenv optional; env may already be set.
    pass

from sqlalchemy import select  # noqa: E402

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models.generated_image import GeneratedImage, _make_thumb_data_uri  # noqa: E402


def backfill(batch_size: int = 100, limit: int | None = None) -> dict:
    """Populate ``thumb_b64`` for rows missing it. Returns a counts dict."""
    generated = 0
    skipped = 0
    scanned = 0

    while True:
        remaining = batch_size
        if limit is not None:
            remaining = min(batch_size, limit - scanned)
            if remaining <= 0:
                break
        # Re-query each batch from the top: skipped rows still match
        # (thumb_b64 stays NULL), so an OFFSET would walk past them. Generated
        # rows fall out of the predicate, so the window naturally advances.
        stmt = (
            select(GeneratedImage)
            .where(
                GeneratedImage.thumb_b64.is_(None),
                GeneratedImage.b64_payload.is_not(None),
            )
            .order_by(GeneratedImage.created_at.asc())
            .limit(remaining)
        )
        rows = db.session.execute(stmt).scalars().all()
        if not rows:
            break

        batch_generated = 0
        for row in rows:
            scanned += 1
            thumb = _make_thumb_data_uri(row.b64_payload)
            if thumb:
                row.thumb_b64 = thumb
                generated += 1
                batch_generated += 1
            else:
                skipped += 1

        db.session.commit()
        print(
            f'  batch: scanned={len(rows)} generated={batch_generated} '
            f'(total generated={generated} skipped={skipped})',
            flush=True,
        )

        # If a whole batch produced no thumbnails, every remaining matching row
        # is un-decodable — the predicate would loop forever. Stop.
        if batch_generated == 0:
            print('  no thumbnails generated this batch (remaining rows '
                  'un-decodable); stopping.', flush=True)
            break

    return {'generated': generated, 'skipped': skipped, 'scanned': scanned}


def main() -> int:
    parser = argparse.ArgumentParser(description='Backfill generated-image thumbnails.')
    parser.add_argument('--batch', type=int, default=100, help='rows per commit (default 100)')
    parser.add_argument('--limit', type=int, default=None, help='max rows to scan (default: all)')
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        url = db.engine.url
        print(f'backfill_image_thumbs: DB={url.database!r} host={url.host!r}', flush=True)
        counts = backfill(batch_size=max(1, args.batch), limit=args.limit)

    print(
        f'backfill_image_thumbs: DONE — generated={counts["generated"]} '
        f'skipped={counts["skipped"]} scanned={counts["scanned"]}',
        flush=True,
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
