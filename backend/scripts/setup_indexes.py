"""Apply database schema (Alembic-based).

Phase 6: replaces the Mongo ``XxxModel.create_indexes()`` collection-by-collection
walk with a thin wrapper around ``alembic upgrade head``. Run from the
backend directory so ``alembic.ini`` resolves.

Usage:
    cd backend
    ./.venv-uv/Scripts/python.exe scripts/setup_indexes.py
"""
import subprocess
import sys


def main() -> int:
    cmd = [sys.executable, '-m', 'alembic', '--config', 'alembic.ini', 'upgrade', 'head']
    return subprocess.call(cmd, cwd='.')


if __name__ == '__main__':
    sys.exit(main())
