"""Migration 0026_conv_ws_drop_personal — data outcome on a scratch DB.

Runs alembic in a SUBPROCESS against a dedicated ``*_mig0026_test`` database
(created + dropped here) so the shared ``unichat_test`` schema is untouched.
Seeds a 0025-shaped dataset with a personal workspace, then upgrades and
checks: no-team chats deleted, team chats kept + stamped, active workspace
re-pointed, user assets detached (not cascaded), personal ws gone,
usage history kept, CHECKs accept ``member``.
"""
import os
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _alembic(url: str, *args: str) -> None:
    env = {**os.environ, "SQLALCHEMY_DATABASE_URI": url}
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND, env=env, capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]


@pytest.fixture
def mig_db(_pg_engine):
    base = make_url(os.environ["SQLALCHEMY_DATABASE_URI"])
    name = f"{base.database}_mig0026_test"
    assert name.endswith("_test")
    admin = create_engine(
        base.set(database="postgres"), isolation_level="AUTOCOMMIT", future=True,
    )
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{name}"'))
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"cannot create scratch DB: {exc}")
    url = base.set(database=name).render_as_string(hide_password=False)
    try:
        yield url
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def test_migration_0026_drops_personal_data(mig_db):
    _alembic(mig_db, "upgrade", "0025_ocr_jobs")
    ids = {k: uuid.uuid4() for k in (
        "u1", "u2", "p1", "t1", "pp", "tp", "c_personal", "c_team", "c_pws",
        "k1", "w1", "kf_old", "kf_moved", "share",
    )}
    engine = create_engine(mig_db, future=True)
    with engine.begin() as conn:
        seed = """
            INSERT INTO users (id, email, role) VALUES
              (:u1, 'u1@x.io', 'user'), (:u2, 'u2@x.io', 'user');
            INSERT INTO workspaces (id, slug, is_personal, owner_user_id, display_name) VALUES
              (:p1, 'p1', true, :u1, 'U1 Space'), (:t1, 't1', false, NULL, 'Acme');
            UPDATE users SET active_workspace_id = :p1 WHERE id = :u1;
            INSERT INTO workspace_members (id, workspace_id, user_id, role, status) VALUES
              (gen_random_uuid(), :p1, :u1, 'owner', 'active'),
              (gen_random_uuid(), :t1, :u1, 'viewer', 'active'),
              (gen_random_uuid(), :t1, :u2, 'viewer', 'active');
            INSERT INTO projects (id, workspace_id, slug, name) VALUES
              (:pp, :p1, 'pp', 'Personal proj'), (:tp, :t1, 'tp', 'Team proj');
            INSERT INTO conversations (id, user_id, project_id, title) VALUES
              (:c_personal, :u1, NULL, 'no team'),
              (:c_team, :u1, :tp, 'team'),
              (:c_pws, :u1, :pp, 'in personal project');
            INSERT INTO messages (id, conversation_id, role, seq) VALUES
              (gen_random_uuid(), :c_personal, 'user', 1),
              (gen_random_uuid(), :c_team, 'user', 1);
            INSERT INTO conversation_shares (id, conversation_id, share_type, created_by, token)
              VALUES (:share, :c_personal, 'link', :u1, 'tok');
            INSERT INTO knowledge_items (id, user_id, workspace_id, project_id) VALUES
              (:k1, :u1, :p1, :pp);
            INSERT INTO workflows (id, user_id, name, workspace_id, project_id, visibility) VALUES
              (:w1, :u1, 'wf', :p1, :pp, 'project');
            INSERT INTO knowledge_folders (id, user_id, name, scope_key) VALUES
              (:kf_old, :u1, 'Docs', 'u:' || CAST(:u1 AS text));
            INSERT INTO knowledge_folders (id, user_id, workspace_id, project_id, name, scope_key)
              VALUES (:kf_moved, :u1, :p1, :pp, 'Docs', 'p:' || CAST(:pp AS text));
            INSERT INTO usage_logs (id, user_id, workspace_id, model, cost_usd) VALUES
              (gen_random_uuid(), :u1, :p1, 'a/m', 1.5);
            INSERT INTO credit_ledger (id, workspace_id, kind, delta_micro_usd) VALUES
              (gen_random_uuid(), :p1, 'topup', 1000000);
            INSERT INTO spend_rollups (id, scope_type, scope_id, period_month, spent_usd) VALUES
              (gen_random_uuid(), 'company', :p1, '1970-01-01', 1.5);
        """
        # psycopg3 binds params per statement — run them one at a time.
        for stmt in filter(None, (x.strip() for x in seed.split(";"))):
            conn.execute(text(stmt), ids)

    _alembic(mig_db, "upgrade", "0026_conv_ws_drop_personal")

    with engine.begin() as conn:
        one = lambda sql: conn.execute(text(sql), ids).scalar()  # noqa: E731
        assert one("SELECT count(*) FROM conversations") == 1
        assert one("SELECT workspace_id FROM conversations WHERE id = :c_team") == ids["t1"]
        assert one("SELECT count(*) FROM messages") == 1
        assert one("SELECT count(*) FROM conversation_shares") == 0
        assert one("SELECT count(*) FROM workspaces WHERE is_personal") == 0
        assert one("SELECT count(*) FROM projects") == 1
        assert one("SELECT active_workspace_id FROM users WHERE id = :u1") == ids["t1"]
        assert one("SELECT active_workspace_id FROM users WHERE id = :u2") == ids["t1"]
        assert one(
            "SELECT count(*) FROM knowledge_items WHERE id = :k1 "
            "AND workspace_id IS NULL AND project_id IS NULL"
        ) == 1
        assert one(
            "SELECT visibility FROM workflows WHERE id = :w1 AND workspace_id IS NULL"
        ) == "private"
        moved = conn.execute(
            text("SELECT name, scope_key FROM knowledge_folders WHERE id = :kf_moved"), ids,
        ).one()
        assert moved.scope_key == f"u:{ids['u1']}" and moved.name.startswith("Docs (")
        assert one("SELECT count(*) FROM usage_logs WHERE workspace_id IS NULL") == 1
        assert one("SELECT count(*) FROM credit_ledger") == 0
        assert one("SELECT count(*) FROM spend_rollups") == 0
        conn.execute(text(
            "INSERT INTO spend_rollups (id, scope_type, scope_id, period_month) "
            "VALUES (gen_random_uuid(), 'member', gen_random_uuid(), '2026-09-01')"
        ))
        conn.execute(text(
            "INSERT INTO budget_allocations (id, scope_type, scope_id, amount_usd) "
            "VALUES (gen_random_uuid(), 'member', gen_random_uuid(), 1)"
        ))
    engine.dispose()

    _alembic(mig_db, "downgrade", "0025_ocr_jobs")
