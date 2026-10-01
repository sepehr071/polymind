"""Manual cutover smoke test — confirms the SQLAlchemy engine + Postgres reach.

Usage:
    ./.venv-uv/Scripts/python.exe scripts/check_pg.py

Exits 0 on success, 1 on failure. Prints the scalar result of ``SELECT 1``.
"""
from __future__ import annotations

import sys

from sqlalchemy import text

from app import create_app
from app.extensions import db


def main() -> int:
    app = create_app()
    with app.app_context():
        try:
            result = db.session.execute(text('SELECT 1')).scalar()
        except Exception as exc:  # noqa: BLE001 — smoke test surfaces every cause
            print(f'check_pg: FAIL — {type(exc).__name__}: {exc}', file=sys.stderr)
            return 1
        print(f'check_pg: OK — SELECT 1 = {result}')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
