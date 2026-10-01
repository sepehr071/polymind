"""Fresh Postgres test harness for the FastAPI bridge (tests/api/**).

Independent of the legacy Mongo harness in tests/conftest.py. Env MUST be set
at module top — BEFORE any ``from app ...`` import — so Config reads the *_test
DB URL + the right secrets, and the SPA catch-all stays unregistered.
"""
import os

os.environ.setdefault(
    "SQLALCHEMY_DATABASE_URI",
    "postgresql+psycopg://postgres:postgres@localhost:5432/unichat_test",
)
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-0123456789abcdefXYZ")
os.environ.setdefault("SECRET_KEY", "test-secret-0123456789abcdefXYZ")
os.environ["SERVE_SPA"] = "0"

import uuid as _uuid  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

import jwt as pyjwt  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

_TEST_DB_NAME_SUFFIX = "_test"
_JWT_SECRET = os.environ["JWT_SECRET_KEY"]


# ---------------------------------------------------------------------------
# Neutralize the pytest-flask autouse fixtures. They key off the fixture named
# ``app`` and assume it is a Flask app (``app.response_class``,
# ``app.test_request_context()``, ``app.config``). Here ``app`` is a FastAPI
# instance, so we override each as a no-op for the tests/api package.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _monkeypatch_response_class():
    yield


@pytest.fixture(autouse=True)
def _push_request_context():
    yield


@pytest.fixture(autouse=True)
def _configure_application():
    yield


# ---------------------------------------------------------------------------
# Postgres engine — reuse the guard from tests/conftest.py:79-113. Schema is
# already bootstrapped on unichat_test (do NOT re-run alembic), just connect.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def _pg_engine():
    url = os.environ["SQLALCHEMY_DATABASE_URI"]
    engine = create_engine(url, future=True)
    if not (engine.url.database or "").endswith(_TEST_DB_NAME_SUFFIX):
        raise RuntimeError(
            f"REFUSING TO RUN PG TESTS: database name {engine.url.database!r} "
            f"does not end in '_test'. Set SQLALCHEMY_DATABASE_URI to a *_test DB."
        )
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.skip(f"Postgres unreachable at {url}: {exc.orig}")
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def flask_core(_pg_engine):
    from app.api.core import flask_core as core

    return core


@pytest.fixture(scope="session")
def app(_pg_engine):
    """The FastAPI app under test."""
    import app.asgi as asgi_module

    return asgi_module.app


@pytest.fixture(scope="function")
def client(app):
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Per-test truncation. Re-assert the _test guard before wiping.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="function", autouse=True)
def truncate_all(flask_core):
    from app.api.core import db

    yield
    with flask_core.app_context():
        engine = db.engine
        if not (engine.url.database or "").endswith(_TEST_DB_NAME_SUFFIX):
            raise RuntimeError(
                f"REFUSING TO TRUNCATE: database name {engine.url.database!r} "
                f"does not end in '_test'."
            )
        # Release this test's ORM session so it isn't itself holding a lock.
        db.session.remove()
        # Use a fresh AUTOCOMMIT connection for cleanup. A test that opened an
        # SSE stream (client.stream) and didn't fully drain it leaves the
        # generator suspended inside `with flask_core.app_context()`, holding an
        # 'idle in transaction' read lock — which would deadlock the TRUNCATE's
        # ACCESS EXCLUSIVE lock. Terminate any such leaked backend on THIS
        # *_test DB first, then truncate under a lock_timeout safety net.
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid() "
                "AND state IN ('idle in transaction', "
                "'idle in transaction (aborted)')"
            ))
            conn.execute(text("SET lock_timeout = '5s'"))
            tables = conn.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
                )
            ).scalars().all()
            if tables:
                joined = ", ".join(f'"{t}"' for t in tables)
                conn.execute(text(f"TRUNCATE {joined} RESTART IDENTITY CASCADE"))


# ---------------------------------------------------------------------------
# Token minting (HS256, PyJWT) — matches what resolve_user_from_token accepts.
# ---------------------------------------------------------------------------
def _mint(user_id, *, role="user", token_type="access", expired=False, jti=None):
    now = datetime.now(timezone.utc)
    exp = now - timedelta(minutes=5) if expired else now + timedelta(hours=1)
    payload = {
        "sub": str(user_id),
        "jti": jti or str(_uuid.uuid4()),
        "type": token_type,
        "fresh": False,
        "iat": now,
        "nbf": now,
        "exp": exp,
        "role": role,
    }
    return pyjwt.encode(payload, _JWT_SECRET, algorithm="HS256")


def _headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture
def mint_token():
    """Expose the token minter to tests (expired / revoked helpers)."""
    return _mint


# ---------------------------------------------------------------------------
# User factories — created via the real model facades inside an app_context.
# ---------------------------------------------------------------------------
TEST_ORG_SLUG = "test-org"


def _test_org_id():
    """The shared "Test Org" team workspace (created lazily per test).

    Mirrors a Keycloak org workspace: no ``owner_user_id``; ownership is the
    ``owner`` membership role. Callers must already be in an app_context.
    """
    from app.models.workspace import WorkspaceModel

    ws = WorkspaceModel.find_by_slug(TEST_ORG_SLUG)
    if ws is None:
        ws = WorkspaceModel.create(name="Test Org", owner_id=None, type="team")
    return str(ws["_id"])


def _make_user(flask_core, *, email, password, display_name, role):
    """Create a user inside the shared "Test Org" (membership + active ws).

    Personal workspaces no longer exist (mig 0026); like a Keycloak org sync,
    manager/admin join as ``owner`` and plain users as ``viewer``.
    """
    from app.models.user import UserModel
    from app.models.workspace_member import WorkspaceMemberModel

    with flask_core.app_context():
        user = UserModel.create(
            email=email, password=password, display_name=display_name, role=role
        )
        wid = _test_org_id()
        member_role = "owner" if role in ("manager", "admin") else "viewer"
        WorkspaceMemberModel.add(wid, user["_id"], member_role, status="active")
        UserModel.set_active_workspace(user["_id"], wid)
        return UserModel.find_by_id(user["_id"])


@pytest.fixture
def test_user(flask_core):
    return _make_user(flask_core, email="test@gmail.com", password="TestPassword123!",
                      display_name="Test User", role="manager")


@pytest.fixture
def plain_user(flask_core):
    return _make_user(flask_core, email="plain@gmail.com", password="TestPassword123!",
                      display_name="Plain User", role="user")


@pytest.fixture
def admin_user(flask_core):
    return _make_user(flask_core, email="admin@gmail.com", password="AdminPassword123!",
                      display_name="Admin User", role="admin")


@pytest.fixture
def banned_user(flask_core):
    from app.models.user import UserModel

    user = _make_user(flask_core, email="banned@gmail.com", password="TestPassword123!",
                      display_name="Banned User", role="user")
    with flask_core.app_context():
        UserModel.ban_user(user["_id"], "policy violation", admin_id=None)
    # Re-fetch the post-ban legacy dict.
    with flask_core.app_context():
        return UserModel.find_by_id(user["_id"])


# ---------------------------------------------------------------------------
# Auth headers.
# ---------------------------------------------------------------------------
@pytest.fixture
def auth_headers(test_user):
    return _headers(_mint(test_user["_id"], role="manager"))


@pytest.fixture
def admin_headers(admin_user):
    return _headers(_mint(admin_user["_id"], role="admin"))


@pytest.fixture
def plain_headers(plain_user):
    return _headers(_mint(plain_user["_id"], role="user"))
