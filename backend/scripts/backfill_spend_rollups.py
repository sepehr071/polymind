"""Backfill ``spend_rollups`` from the historical ``usage_logs`` ledger.

Phase 1 of the hierarchical-billing build. The metering write path
(``OpenRouterService._record_usage``) maintains ``spend_rollups`` incrementally
for NEW usage, but rows that predate the rollup table need a one-off aggregate.

This script recomputes every rollup from scratch:

  * company per-month   — GROUP BY (workspace_id, month)
  * company LIFETIME     — GROUP BY (workspace_id)        -> period_month 1970-01-01
  * team per-month      — GROUP BY (project_id,   month)
  * user per-month      — GROUP BY (user_id,      month)
  * member per-month    — GROUP BY (workspace_id, user_id, month) -> scope id
                          ``member_scope_id(workspace_id, user_id)``

``month`` = ``date_trunc('month', created_at AT TIME ZONE 'utc')::date`` — the
DB session is pinned UTC, but the explicit cast keeps the bucket boundaries
correct regardless. Rows with a NULL scope id are skipped (no scope to attribute
spend to).

Idempotent: it DELETEs all existing ``spend_rollups`` rows first, then inserts
fresh aggregates — re-running converges to the same state. Safe to run anytime.

Usage (loads the dev DSN from backend/.env, like seed.py):
    ./.venv-uv/Scripts/python.exe scripts/backfill_spend_rollups.py

Or target another DB explicitly:
    SQLALCHEMY_DATABASE_URI=postgresql+psycopg://... \
        ./.venv-uv/Scripts/python.exe scripts/backfill_spend_rollups.py
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import date, datetime, timezone

# Load backend/.env BEFORE importing the app package — Config reads
# SQLALCHEMY_DATABASE_URI at class-def time (mirrors scripts/seed.py /
# scripts/backfill_image_thumbs.py). An explicit SQLALCHEMY_DATABASE_URI already
# in the environment wins (override=False only fills gaps it doesn't set).
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, '.env'), override=False)
except Exception:  # noqa: BLE001 — dotenv optional; env may already be set.
    pass

from sqlalchemy import delete, insert, text  # noqa: E402

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models.budget_allocation import member_scope_id  # noqa: E402
from app.models.spend_rollup import SpendRollup, SpendRollupModel  # noqa: E402

_LIFETIME = SpendRollupModel.LIFETIME  # date(1970, 1, 1)


# Per-(scope_type, scope column) per-month aggregate. ``cost_usd``/``count`` are
# summed; NULL scope ids are filtered out (no scope to attribute to).
_PER_MONTH_SQL = """
    SELECT
        {col} AS scope_id,
        date_trunc('month', created_at AT TIME ZONE 'utc')::date AS period_month,
        COALESCE(SUM(cost_usd), 0) AS spent_usd,
        COUNT(*) AS calls
    FROM usage_logs
    WHERE {col} IS NOT NULL
    GROUP BY 1, 2
"""

# Member (user inside one org) per-month — scope id derived in Python.
_MEMBER_MONTH_SQL = """
    SELECT
        workspace_id,
        user_id,
        date_trunc('month', created_at AT TIME ZONE 'utc')::date AS period_month,
        COALESCE(SUM(cost_usd), 0) AS spent_usd,
        COUNT(*) AS calls
    FROM usage_logs
    WHERE workspace_id IS NOT NULL AND user_id IS NOT NULL
    GROUP BY 1, 2, 3
"""

# Company LIFETIME sentinel — all-time per-workspace spend, period_month pinned
# to the 1970 sentinel.
_LIFETIME_SQL = """
    SELECT
        workspace_id AS scope_id,
        COALESCE(SUM(cost_usd), 0) AS spent_usd,
        COUNT(*) AS calls
    FROM usage_logs
    WHERE workspace_id IS NOT NULL
    GROUP BY 1
"""


def _insert_rows(rows: list[dict]) -> int:
    """Bulk-insert prepared rollup dicts. Returns the inserted row count."""
    if not rows:
        return 0
    db.session.execute(insert(SpendRollup), rows)
    return len(rows)


def backfill() -> dict:
    """Recompute all spend_rollups from usage_logs. Returns a counts dict."""
    now = datetime.now(timezone.utc)
    counts = {
        'company_month': 0, 'company_lifetime': 0, 'team_month': 0,
        'user_month': 0, 'member_month': 0,
    }

    # Wipe — idempotent recompute.
    db.session.execute(delete(SpendRollup))

    # company / team / user per-month.
    scope_cols = [
        ('company', 'workspace_id', 'company_month'),
        ('team', 'project_id', 'team_month'),
        ('user', 'user_id', 'user_month'),
    ]
    for scope_type, col, key in scope_cols:
        sql = _PER_MONTH_SQL.format(col=col)
        result = db.session.execute(text(sql)).all()
        rows = [
            {
                'id': uuid.uuid4(),
                'scope_type': scope_type,
                'scope_id': r.scope_id,
                'period_month': r.period_month,
                'spent_usd': float(r.spent_usd or 0),
                'calls': int(r.calls or 0),
                'updated_at': now,
            }
            for r in result
        ]
        counts[key] = _insert_rows(rows)

    member_rows = [
        {
            'id': uuid.uuid4(),
            'scope_type': 'member',
            'scope_id': member_scope_id(r.workspace_id, r.user_id),
            'period_month': r.period_month,
            'spent_usd': float(r.spent_usd or 0),
            'calls': int(r.calls or 0),
            'updated_at': now,
        }
        for r in db.session.execute(text(_MEMBER_MONTH_SQL)).all()
    ]
    counts['member_month'] = _insert_rows(member_rows)

    # company LIFETIME sentinel.
    lifetime_result = db.session.execute(text(_LIFETIME_SQL)).all()
    lifetime_rows = [
        {
            'id': uuid.uuid4(),
            'scope_type': 'company',
            'scope_id': r.scope_id,
            'period_month': _LIFETIME,
            'spent_usd': float(r.spent_usd or 0),
            'calls': int(r.calls or 0),
            'updated_at': now,
        }
        for r in lifetime_result
    ]
    counts['company_lifetime'] = _insert_rows(lifetime_rows)

    db.session.commit()
    return counts


def main() -> int:
    app = create_app()
    with app.app_context():
        url = db.engine.url
        print(f'backfill_spend_rollups: DB={url.database!r} host={url.host!r}', flush=True)
        counts = backfill()
    total = sum(counts.values())
    print(
        'backfill_spend_rollups: DONE — '
        f'company_month={counts["company_month"]} '
        f'company_lifetime={counts["company_lifetime"]} '
        f'team_month={counts["team_month"]} '
        f'user_month={counts["user_month"]} '
        f'member_month={counts["member_month"]} (total={total})',
        flush=True,
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
