"""Integration tests for the holding-admin router (app/api/routers/admin_holding.py).

The platform-admin principal was eliminated; the super-admin (``role=='admin'``)
now owns the holding pool, feature flags, and company-credit transfers. Every
route is mounted at ``/api/admin`` and gated by ``require_admin``.

Mirrors tests/api/test_auth.py: real model facades on Postgres, legacy-shaped
JSON, and the conftest fixtures (client, admin_headers/auth_headers, user
factories, truncate_all autouse). No external HTTP is touched — every route is
pure DB aggregation, so nothing is mocked.

Auth note: the gate is ``require_admin`` (``users.role == 'admin'``). The
``admin_headers`` fixture mints an admin JWT; ``auth_headers`` (a manager) is the
403-negative principal since ``require_admin`` rejects any non-admin.
"""
import uuid


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------
def _seed_company(flask_core, owner, *, name="Acme Co"):
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        return WorkspaceModel.create(name=name, owner_id=owner["_id"], type="team")


# ---------------------------------------------------------------------------
# Feature flags.
# ---------------------------------------------------------------------------
def test_get_features_happy(client, admin_headers):
    resp = client.get("/api/admin/features", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body["features"], dict)
    # Default-features keys must all be present.
    for key in ("arena", "debate", "image_studio", "workflow", "knowledge"):
        assert key in body["features"]
    assert "updated_at" in body
    assert "updated_by" in body


def test_set_feature_single_toggle(client, admin_headers, admin_user):
    resp = client.put("/api/admin/features",
                      json={"feature": "arena", "enabled": True}, headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["features"]["arena"] is True
    # arena defaults False -> this is a real change.
    assert {"name": "arena", "old": False, "new": True} in body["changes"]
    # updated_by is hydrated to the acting super-admin's users.id.
    assert body["updated_by"]["id"] == str(admin_user["_id"])

    # The change is persisted: a subsequent GET reflects it.
    again = client.get("/api/admin/features", headers=admin_headers)
    assert again.json()["features"]["arena"] is True


def test_set_features_bulk(client, admin_headers):
    resp = client.put("/api/admin/features",
                      json={"features": {"arena": True, "debate": True}}, headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["features"]["arena"] is True
    assert body["features"]["debate"] is True


def test_set_feature_unknown_400(client, admin_headers):
    resp = client.put("/api/admin/features",
                      json={"feature": "does_not_exist", "enabled": True}, headers=admin_headers)
    assert resp.status_code == 400
    assert "allowed" in resp.json()


def test_set_feature_missing_enabled_400(client, admin_headers):
    resp = client.put("/api/admin/features",
                      json={"feature": "arena"}, headers=admin_headers)
    assert resp.status_code == 400
    assert "`enabled`" in resp.json()["error"]


def test_set_features_empty_object_400(client, admin_headers):
    resp = client.put("/api/admin/features",
                      json={"features": {}}, headers=admin_headers)
    assert resp.status_code == 400


def test_set_features_no_keys_400(client, admin_headers):
    resp = client.put("/api/admin/features", json={"nonsense": 1}, headers=admin_headers)
    assert resp.status_code == 400
    assert "Must provide either" in resp.json()["error"]


def test_set_features_requires_admin(client, auth_headers):
    # A manager JWT (role='manager') is rejected by require_admin.
    resp = client.put("/api/admin/features",
                      json={"feature": "arena", "enabled": True}, headers=auth_headers)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Holding overview.
# ---------------------------------------------------------------------------
def test_holding_overview_happy(client, admin_headers):
    resp = client.get("/api/admin/holding/overview", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "workspaces_count" in body
    assert "totals" in body
    assert "holding_credits" in body
    # Back-compat alias collapsed from totals.cost_usd.
    assert body["usage_30d_cost_usd"] == body["totals"]["cost_usd"]


# ---------------------------------------------------------------------------
# Credit charging — company-scoped.
# ---------------------------------------------------------------------------
def test_charge_company_happy(client, flask_core, admin_headers):
    # Owner can be any user; the admin acts on the company. Use a fresh user.
    from app.models.user import UserModel

    with flask_core.app_context():
        owner = UserModel.create(email="owner-umbrella@gmail.com",
                                 password="TestPassword123!",
                                 display_name="Owner", role="user")
    ws = _seed_company(flask_core, owner, name="Umbrella")
    resp = client.post(f"/api/admin/companies/{ws['_id']}/credits",
                       json={"amount_usd": 25.0, "type": "top_up", "note": "seed"},
                       headers=admin_headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # Ledger entry carries the Mongo _id alias.
    assert "_id" in body["entry"]
    assert body["entry"]["amount_usd"] == 25.0
    assert body["credits_balance_usd"] == 25.0

    # The charge wrote a company_credits_added audit row under category='holding'.
    with flask_core.app_context():
        from app.models.audit_log import AuditLogModel
        rows = AuditLogModel.find_all(action="company_credits_added")
        assert any(r.get("category") == "holding" for r in rows)


def test_charge_company_invalid_id_400(client, admin_headers):
    resp = client.post("/api/admin/companies/not-a-uuid/credits",
                       json={"amount_usd": 5.0}, headers=admin_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid id"


def test_charge_company_missing_amount_400(client, flask_core, admin_headers, admin_user):
    ws = _seed_company(flask_core, admin_user)
    resp = client.post(f"/api/admin/companies/{ws['_id']}/credits",
                       json={"note": "no amount"}, headers=admin_headers)
    assert resp.status_code == 400
    assert "amount_usd" in resp.json()["error"]


def test_charge_company_zero_amount_400(client, flask_core, admin_headers, admin_user):
    ws = _seed_company(flask_core, admin_user)
    resp = client.post(f"/api/admin/companies/{ws['_id']}/credits",
                       json={"amount_usd": 0}, headers=admin_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "amount_usd must be non-zero"


def test_charge_company_bad_type_400(client, flask_core, admin_headers, admin_user):
    ws = _seed_company(flask_core, admin_user)
    resp = client.post(f"/api/admin/companies/{ws['_id']}/credits",
                       json={"amount_usd": 5.0, "type": "bogus"},
                       headers=admin_headers)
    assert resp.status_code == 400
    assert "type must be one of" in resp.json()["error"]


def test_charge_company_workspace_not_found_404(client, admin_headers):
    resp = client.post(f"/api/admin/companies/{uuid.uuid4()}/credits",
                       json={"amount_usd": 5.0}, headers=admin_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Workspace not found"


def test_charge_company_requires_admin(client, flask_core, auth_headers, admin_user):
    ws = _seed_company(flask_core, admin_user)
    resp = client.post(f"/api/admin/companies/{ws['_id']}/credits",
                       json={"amount_usd": 5.0}, headers=auth_headers)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Credit charging — holding-scoped (top-up the pool).
# ---------------------------------------------------------------------------
def test_charge_holding_happy(client, admin_headers, admin_user):
    resp = client.post("/api/admin/holding/credits",
                       json={"amount_usd": 100.0, "type": "top_up", "note": "pool"},
                       headers=admin_headers)
    assert resp.status_code == 201, resp.text
    assert resp.json()["lifetime_topups_usd"] == 100.0

    # The holding ledger lists the movement.
    ledger = client.get("/api/admin/holding/ledger", headers=admin_headers)
    assert ledger.status_code == 200
    body = ledger.json()
    assert body["total"] == 1
    entry = body["entries"][0]
    assert entry["amount_usd"] == 100.0
    # added_by is hydrated from the acting super-admin's users.id.
    assert entry["added_by"]["id"] == str(admin_user["_id"])


def test_charge_holding_missing_amount_400(client, admin_headers):
    resp = client.post("/api/admin/holding/credits",
                       json={"note": "x"}, headers=admin_headers)
    assert resp.status_code == 400
    assert "amount_usd" in resp.json()["error"]


def test_holding_ledger_empty(client, admin_headers):
    resp = client.get("/api/admin/holding/ledger", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["entries"] == []
    assert body["total"] == 0


def test_holding_ledger_requires_admin(client, auth_headers):
    resp = client.get("/api/admin/holding/ledger", headers=auth_headers)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Holding -> company transfer (source='holding').
# ---------------------------------------------------------------------------
def test_holding_transfer_happy(client, flask_core, admin_headers, admin_user):
    # Seed the holding pool through the production route, then transfer.
    fund = client.post("/api/admin/holding/credits",
                       json={"amount_usd": 100.0, "type": "top_up", "note": "pool"},
                       headers=admin_headers)
    assert fund.status_code == 201, fund.text

    ws = _seed_company(flask_core, admin_user, name="Globex")
    resp = client.post(f"/api/admin/companies/{ws['_id']}/credits",
                       json={"amount_usd": 30.0, "source": "holding"},
                       headers=admin_headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["source"] == "holding"
    assert body["holding_pool_remaining_usd"] == 70.0  # 100 - 30


def test_holding_transfer_overdraw_402(client, flask_core, admin_headers, admin_user):
    # Pool funded with 100; transferring more than that 402s (scope=holding).
    fund = client.post("/api/admin/holding/credits",
                       json={"amount_usd": 100.0, "type": "top_up", "note": "pool"},
                       headers=admin_headers)
    assert fund.status_code == 201, fund.text

    ws = _seed_company(flask_core, admin_user, name="Soylent")
    resp = client.post(f"/api/admin/companies/{ws['_id']}/credits",
                       json={"amount_usd": 250.0, "source": "holding"},
                       headers=admin_headers)
    assert resp.status_code == 402, resp.text
    assert resp.json()["scope"] == "holding"


# ---------------------------------------------------------------------------
# Route-registration smoke.
# ---------------------------------------------------------------------------
def test_admin_holding_routes_registered(app):
    paths = {getattr(r, "path", None) for r in app.routes}
    for p in (
        "/api/admin/features",
        "/api/admin/holding/overview",
        "/api/admin/holding/ledger",
        "/api/admin/holding/credits",
        "/api/admin/companies/{wid}/credits",
    ):
        assert p in paths
    # The platform-operator router is gone entirely.
    assert not any((p or "").startswith("/api/platform") for p in paths)
