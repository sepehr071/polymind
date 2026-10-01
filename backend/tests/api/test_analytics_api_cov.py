"""P1 — unified usage-analytics API coverage.

Drives ``GET /api/admin/analytics/usage`` (require_admin) through the FastAPI
TestClient. Asserts the envelope shape per scope, the children kind at each
drilldown level, granularity passthrough, the legacy ``{error,status}`` 400 on
bad input, and the auth boundaries (403 for non-admin).

The math is covered at the service layer in test_analytics_service_cov.py;
here we verify the HTTP wiring, auth gates, and that NO FastAPI response_model
strips the legacy dict (cost_visible/scope_id/by_model all survive).

NB: the old platform-operator tier (``GET /api/platform/analytics/usage``) was
removed with the platform-admin principal; only the super-admin tier remains.
"""
from datetime import datetime, timedelta, timezone

from tests.api.conftest import _headers, _make_user, _mint


# ---------------------------------------------------------------------------
# Seeding helpers.
# ---------------------------------------------------------------------------
def _user(flask_core, *, email, role="user", display_name="User"):
    return _make_user(flask_core, email=email, password="TestPassword123!",
                      display_name=display_name, role=role)


def _workspace(flask_core, *, owner, name="Acme Co"):
    from app.models.workspace import WorkspaceModel
    from app.models.workspace_member import WorkspaceMemberModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name=name, owner_id=owner["_id"], type="team")
        WorkspaceMemberModel.add(
            ws["_id"], owner["_id"], "owner", invited_by=owner["_id"], status="active"
        )
        return ws


def _project(flask_core, *, wid, owner, name="Team A"):
    from app.models.project import ProjectModel

    with flask_core.app_context():
        return ProjectModel.create(workspace_id=wid, name=name, created_by=owner["_id"])


def _seed_usage(flask_core, *, wid, pid, uid, model="openai/gpt-5", cost=1.0):
    from app.models.usage_log import UsageLog, UsageLogModel
    from app.extensions import db

    when = datetime.now(timezone.utc) - timedelta(days=2)
    with flask_core.app_context():
        row = UsageLogModel.create(
            user_id=uid, workspace_id=wid, project_id=pid, model=model,
            prompt_tokens=10, completion_tokens=5, total_tokens=15,
            cost_usd=cost, origin="web",
        )
        obj = db.session.get(UsageLog, row["_id"])
        obj.created_at = when
        db.session.commit()
        return row


import pytest


@pytest.fixture
def seeded(flask_core):
    """One company / team / two users with usage, plus a super-admin."""
    admin = _user(flask_core, email="superadmin@gmail.com", role="admin",
                  display_name="Super Admin")
    ws = _workspace(flask_core, owner=admin, name="Initech")
    proj = _project(flask_core, wid=ws["_id"], owner=admin, name="Backend Team")
    alice = _user(flask_core, email="a@gmail.com", display_name="Alice")
    bob = _user(flask_core, email="b@gmail.com", display_name="Bob")
    _seed_usage(flask_core, wid=ws["_id"], pid=proj["_id"], uid=alice["_id"],
                model="openai/gpt-5", cost=8.0)
    _seed_usage(flask_core, wid=ws["_id"], pid=proj["_id"], uid=bob["_id"],
                model="google/gemini-3", cost=2.0)
    return {"admin": admin, "ws": ws, "proj": proj, "alice": alice, "bob": bob}


def _admin_hdr(admin):
    return _headers(_mint(admin["_id"], role="admin"))


# ===========================================================================
# Admin tier — scope drilldown + envelope shape.
# ===========================================================================
def test_admin_holding_default_scope(client, seeded):
    resp = client.get("/api/admin/analytics/usage", headers=_admin_hdr(seeded["admin"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Default scope is holding, default granularity day.
    assert body["scope"] == "holding"
    assert body["granularity"] == "day"
    assert body["cost_visible"] is True
    assert "series" in body and "totals" in body and "previous" in body
    assert "deltas" in body
    children = body["breakdown"]["children"]
    assert any(c["id"] == str(seeded["ws"]["_id"]) for c in children)


def test_admin_company_scope_children_teams(client, seeded):
    resp = client.get(
        f"/api/admin/analytics/usage?scope=company&id={seeded['ws']['_id']}",
        headers=_admin_hdr(seeded["admin"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scope"] == "company"
    assert body["scope_id"] == str(seeded["ws"]["_id"])
    team_ids = {c["id"] for c in body["breakdown"]["children"]}
    assert str(seeded["proj"]["_id"]) in team_ids


def test_admin_team_scope_children_users(client, seeded):
    resp = client.get(
        f"/api/admin/analytics/usage?scope=team&id={seeded['proj']['_id']}",
        headers=_admin_hdr(seeded["admin"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scope"] == "team"
    user_ids = {c["id"] for c in body["breakdown"]["children"]}
    assert {str(seeded["alice"]["_id"]), str(seeded["bob"]["_id"])} <= user_ids


def test_admin_user_scope_leaf_by_model(client, seeded):
    resp = client.get(
        f"/api/admin/analytics/usage?scope=user&id={seeded['alice']['_id']}",
        headers=_admin_hdr(seeded["admin"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scope"] == "user"
    assert body["breakdown"]["children"] is None
    keys = {m["key"] for m in body["breakdown"]["by_model"]}
    assert "openai/gpt-5" in keys


def test_admin_granularity_passthrough(client, seeded):
    resp = client.get(
        "/api/admin/analytics/usage?granularity=month",
        headers=_admin_hdr(seeded["admin"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["granularity"] == "month"


def test_admin_bad_scope_400_legacy_shape(client, seeded):
    resp = client.get(
        "/api/admin/analytics/usage?scope=nonsense",
        headers=_admin_hdr(seeded["admin"]),
    )
    assert resp.status_code == 400
    body = resp.json()
    # Legacy {error,status} shape — NOT FastAPI's {detail}.
    assert "error" in body
    assert body["status"] == 400


def test_admin_bad_granularity_400(client, seeded):
    resp = client.get(
        "/api/admin/analytics/usage?granularity=hour",
        headers=_admin_hdr(seeded["admin"]),
    )
    assert resp.status_code == 400
    assert "error" in resp.json()


# ===========================================================================
# Auth boundaries.
# ===========================================================================
def test_admin_endpoint_rejects_non_admin(client, plain_headers):
    resp = client.get("/api/admin/analytics/usage", headers=plain_headers)
    assert resp.status_code == 403


def test_admin_endpoint_requires_token(client):
    resp = client.get("/api/admin/analytics/usage")
    assert resp.status_code == 401
