"""Integration tests for the team/user budget routes on the projects router.

Covers app/api/routers/projects.py '# Budgets' section:
  - GET    /api/projects/{pid}/budget           (viewer+)
  - PUT    /api/projects/{pid}/budget           (owner)
  - PUT    /api/projects/{pid}/members/{uid}/budget  (owner)

Mirrors tests/api/test_projects.py: real model facades on Postgres, the
flask_ctx bridge, legacy-shaped JSON. Entities are seeded via the model facades
inside ``flask_core.app_context()`` and (where it mirrors production) via the
API. The budget routes themselves do NOT touch OpenRouter / the spend gate, so
no external HTTP and no billing_enforcement flag is needed — spend_rollups rows
are written directly via SpendRollupModel.bump as fixtures.
"""
import uuid

import pytest


# ---------------------------------------------------------------------------
# Seeding helpers — all run inside the Flask app_context.
# ---------------------------------------------------------------------------
def _seed_workspace(flask_core, owner_id, *, role="owner", name="Acme Co"):
    from app.models.workspace import WorkspaceModel
    from app.models.workspace_member import WorkspaceMemberModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name=name, owner_id=owner_id, type="team")
        WorkspaceMemberModel.add(ws["_id"], owner_id, role, status="active")
        return ws


def _seed_project_via_api(client, headers, workspace_id, name="Alpha"):
    resp = client.post("/api/projects/create", headers=headers,
                       json={"workspace_id": str(workspace_id), "name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _make_user(flask_core, *, email, role="user", display_name="Other"):
    from app.models.user import UserModel

    with flask_core.app_context():
        return UserModel.create(email=email, password="TestPassword123!",
                                display_name=display_name, role=role)


def _add_member(flask_core, *, wid, pid, uid, role="editor"):
    """Add a user to the workspace (so project add is legal) + the project."""
    from app.models.workspace_member import WorkspaceMemberModel
    from app.models.project_member import ProjectMemberModel

    with flask_core.app_context():
        WorkspaceMemberModel.add(wid, uid, "viewer", status="active")
        ProjectMemberModel.add(project_id=pid, user_id=uid, role=role, added_by=uid)


def _bump_rollup(flask_core, *, scope_type, scope_id, cost, calls=1):
    """Write a spend_rollups row for the current month via the facade."""
    from app.models.spend_rollup import SpendRollupModel

    with flask_core.app_context():
        month = SpendRollupModel.current_period_month()
        SpendRollupModel.bump(scope_type, scope_id, month, cost, calls=calls, commit=True)


def _headers_for(mint_token, uid, role="user"):
    return {"Authorization": f"Bearer {mint_token(uid, role=role)}",
            "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Auth gating.
# ---------------------------------------------------------------------------
def test_get_budget_no_token_401(client):
    resp = client.get(f"/api/projects/{uuid.uuid4()}/budget")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_put_budget_no_token_401(client):
    resp = client.put(f"/api/projects/{uuid.uuid4()}/budget", json={"amount_usd": 10})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /budget — default empty shape.
# ---------------------------------------------------------------------------
def test_get_budget_empty_default(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    proj = _seed_project_via_api(client, auth_headers, ws["_id"])

    resp = client.get(f"/api/projects/{proj['_id']}/budget", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["team_budget"] is None
    assert body["spend_mtd"] == 0.0
    assert body["remaining"] is None
    assert body["attribution"] == "project_tagged_only"
    # The owner is an explicit project member -> appears in per_user.
    assert isinstance(body["per_user"], list)
    owner_row = next(r for r in body["per_user"] if r["user_id"] == str(test_user["_id"]))
    assert owner_row["role"] == "owner"
    assert owner_row["budget"] is None
    assert owner_row["spend_mtd"] == 0.0
    assert owner_row["remaining"] is None
    assert owner_row["email"] == test_user["email"]


# ---------------------------------------------------------------------------
# PUT /budget — owner sets, GET reflects.
# ---------------------------------------------------------------------------
def test_owner_sets_team_budget_get_reflects(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    proj = _seed_project_via_api(client, auth_headers, ws["_id"])

    put = client.put(f"/api/projects/{proj['_id']}/budget", headers=auth_headers,
                     json={"amount_usd": 50})
    assert put.status_code == 200, put.text
    pbody = put.json()
    assert pbody["team_budget"]["amount_usd"] == 50.0
    assert pbody["team_budget"]["enabled"] is True
    assert pbody["team_budget"]["scope_type"] == "team"
    assert pbody["team_budget"]["scope_id"] == str(proj["_id"])
    # Parent linkage points at the company (workspace).
    assert pbody["team_budget"]["parent_scope_type"] == "company"
    assert pbody["team_budget"]["parent_scope_id"] == str(ws["_id"])
    assert pbody["remaining"] == 50.0

    get = client.get(f"/api/projects/{proj['_id']}/budget", headers=auth_headers)
    assert get.status_code == 200
    assert get.json()["team_budget"]["amount_usd"] == 50.0


def test_team_budget_spend_reflected_in_remaining(client, flask_core, auth_headers,
                                                  test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    proj = _seed_project_via_api(client, auth_headers, ws["_id"])

    client.put(f"/api/projects/{proj['_id']}/budget", headers=auth_headers,
               json={"amount_usd": 100})
    _bump_rollup(flask_core, scope_type="team", scope_id=proj["_id"], cost=30.5)

    get = client.get(f"/api/projects/{proj['_id']}/budget", headers=auth_headers)
    body = get.json()
    assert body["spend_mtd"] == pytest.approx(30.5)
    assert body["remaining"] == pytest.approx(69.5)


def test_put_budget_clear_with_null(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    proj = _seed_project_via_api(client, auth_headers, ws["_id"])

    client.put(f"/api/projects/{proj['_id']}/budget", headers=auth_headers,
               json={"amount_usd": 25})
    cleared = client.put(f"/api/projects/{proj['_id']}/budget", headers=auth_headers,
                         json={"amount_usd": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["team_budget"] is None
    assert cleared.json()["remaining"] is None

    get = client.get(f"/api/projects/{proj['_id']}/budget", headers=auth_headers)
    assert get.json()["team_budget"] is None


def test_put_budget_disabled_remaining_null(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    proj = _seed_project_via_api(client, auth_headers, ws["_id"])

    put = client.put(f"/api/projects/{proj['_id']}/budget", headers=auth_headers,
                     json={"amount_usd": 40, "enabled": False})
    assert put.status_code == 200, put.text
    body = put.json()
    # Disabled budget row is still surfaced (get_any), but remaining is null.
    assert body["team_budget"]["enabled"] is False
    assert body["remaining"] is None


def test_put_budget_negative_400(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    proj = _seed_project_via_api(client, auth_headers, ws["_id"])

    resp = client.put(f"/api/projects/{proj['_id']}/budget", headers=auth_headers,
                      json={"amount_usd": -1})
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"] == "amount_usd must be >= 0"


def test_put_budget_non_numeric_400(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    proj = _seed_project_via_api(client, auth_headers, ws["_id"])

    resp = client.put(f"/api/projects/{proj['_id']}/budget", headers=auth_headers,
                      json={"amount_usd": "lots"})
    assert resp.status_code == 400, resp.text


def test_put_budget_project_not_found_404(client, auth_headers):
    resp = client.put(f"/api/projects/{uuid.uuid4()}/budget", headers=auth_headers,
                      json={"amount_usd": 10})
    # project_role_dep denies before the handler when no project/membership.
    assert resp.status_code in (403, 404), resp.text


# ---------------------------------------------------------------------------
# Role gating — viewer can GET, viewer/editor cannot PUT.
# ---------------------------------------------------------------------------
def test_viewer_can_get_budget(client, flask_core, auth_headers, test_user, mint_token):
    ws = _seed_workspace(flask_core, test_user["_id"])
    proj = _seed_project_via_api(client, auth_headers, ws["_id"])
    viewer = _make_user(flask_core, email="viewer@gmail.com")
    _add_member(flask_core, wid=ws["_id"], pid=proj["_id"], uid=viewer["_id"], role="viewer")

    vheaders = _headers_for(mint_token, viewer["_id"])
    resp = client.get(f"/api/projects/{proj['_id']}/budget", headers=vheaders)
    assert resp.status_code == 200, resp.text


def test_viewer_budget_masks_dollar_fields(client, flask_core, auth_headers,
                                           test_user, mint_token):
    """A non-owner viewer gets the envelope shape but EVERY $ field nulled —
    no member's global cross-company spend / ceilings leak (owner-only policy)."""
    ws = _seed_workspace(flask_core, test_user["_id"])
    proj = _seed_project_via_api(client, auth_headers, ws["_id"])
    viewer = _make_user(flask_core, email="viewer-mask@gmail.com")
    _add_member(flask_core, wid=ws["_id"], pid=proj["_id"], uid=viewer["_id"], role="viewer")

    # Owner sets a team budget + a member budget; spend exists for both scopes.
    client.put(f"/api/projects/{proj['_id']}/budget", headers=auth_headers,
               json={"amount_usd": 100})
    client.put(f"/api/projects/{proj['_id']}/members/{viewer['_id']}/budget",
               headers=auth_headers, json={"amount_usd": 25})
    _bump_rollup(flask_core, scope_type="team", scope_id=proj["_id"], cost=12.0)
    _bump_rollup(flask_core, scope_type="user", scope_id=viewer["_id"], cost=3.5)

    vheaders = _headers_for(mint_token, viewer["_id"])
    body = client.get(f"/api/projects/{proj['_id']}/budget", headers=vheaders).json()

    assert body["cost_visible"] is False
    # Team-level $ fields masked, but the budget row + enabled posture remain.
    assert body["spend_mtd"] is None
    assert body["remaining"] is None
    assert body["team_budget"] is not None
    assert body["team_budget"]["amount_usd"] is None
    assert body["team_budget"]["enabled"] is True
    # Every per_user row masked: no spend / ceiling / remaining leaks.
    for row in body["per_user"]:
        assert row["spend_mtd"] is None
        assert row["remaining"] is None
        if row["budget"] is not None:
            assert row["budget"]["amount_usd"] is None
    # Non-$ facts still present (membership + role).
    assert any(r["user_id"] == str(viewer["_id"]) for r in body["per_user"])


def test_owner_budget_cost_visible_true(client, flask_core, auth_headers, test_user):
    """The project/workspace owner sees real $ values (cost_visible True)."""
    ws = _seed_workspace(flask_core, test_user["_id"])
    proj = _seed_project_via_api(client, auth_headers, ws["_id"])
    client.put(f"/api/projects/{proj['_id']}/budget", headers=auth_headers,
               json={"amount_usd": 80})
    _bump_rollup(flask_core, scope_type="team", scope_id=proj["_id"], cost=20.0)

    body = client.get(f"/api/projects/{proj['_id']}/budget", headers=auth_headers).json()
    assert body["cost_visible"] is True
    assert body["team_budget"]["amount_usd"] == 80.0
    assert body["spend_mtd"] == pytest.approx(20.0)
    assert body["remaining"] == pytest.approx(60.0)


def test_viewer_cannot_put_budget_403(client, flask_core, auth_headers, test_user,
                                      mint_token):
    ws = _seed_workspace(flask_core, test_user["_id"])
    proj = _seed_project_via_api(client, auth_headers, ws["_id"])
    viewer = _make_user(flask_core, email="viewer2@gmail.com")
    _add_member(flask_core, wid=ws["_id"], pid=proj["_id"], uid=viewer["_id"], role="viewer")

    vheaders = _headers_for(mint_token, viewer["_id"])
    resp = client.put(f"/api/projects/{proj['_id']}/budget", headers=vheaders,
                      json={"amount_usd": 10})
    assert resp.status_code == 403, resp.text


def test_editor_cannot_put_budget_403(client, flask_core, auth_headers, test_user,
                                      mint_token):
    ws = _seed_workspace(flask_core, test_user["_id"])
    proj = _seed_project_via_api(client, auth_headers, ws["_id"])
    editor = _make_user(flask_core, email="editor@gmail.com")
    _add_member(flask_core, wid=ws["_id"], pid=proj["_id"], uid=editor["_id"], role="editor")

    eheaders = _headers_for(mint_token, editor["_id"])
    resp = client.put(f"/api/projects/{proj['_id']}/budget", headers=eheaders,
                      json={"amount_usd": 10})
    assert resp.status_code == 403, resp.text


def test_editor_cannot_put_member_budget_403(client, flask_core, auth_headers, test_user,
                                             mint_token):
    ws = _seed_workspace(flask_core, test_user["_id"])
    proj = _seed_project_via_api(client, auth_headers, ws["_id"])
    editor = _make_user(flask_core, email="editor3@gmail.com")
    _add_member(flask_core, wid=ws["_id"], pid=proj["_id"], uid=editor["_id"], role="editor")

    eheaders = _headers_for(mint_token, editor["_id"])
    resp = client.put(
        f"/api/projects/{proj['_id']}/members/{editor['_id']}/budget",
        headers=eheaders, json={"amount_usd": 10})
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# Member budget — set / clear round trip + 404 on non-member.
# ---------------------------------------------------------------------------
def test_member_budget_set_get_clear_roundtrip(client, flask_core, auth_headers,
                                               test_user, mint_token):
    ws = _seed_workspace(flask_core, test_user["_id"])
    proj = _seed_project_via_api(client, auth_headers, ws["_id"])
    member = _make_user(flask_core, email="member@gmail.com", display_name="Mem Ber")
    _add_member(flask_core, wid=ws["_id"], pid=proj["_id"], uid=member["_id"], role="editor")

    # Set the member's global user budget.
    put = client.put(
        f"/api/projects/{proj['_id']}/members/{member['_id']}/budget",
        headers=auth_headers, json={"amount_usd": 20})
    assert put.status_code == 200, put.text
    pbody = put.json()
    assert pbody["user_id"] == str(member["_id"])
    assert pbody["budget"]["amount_usd"] == 20.0
    assert pbody["budget"]["scope_type"] == "user"
    assert pbody["budget"]["scope_id"] == str(member["_id"])
    assert pbody["budget"]["parent_scope_type"] == "team"
    assert pbody["budget"]["parent_scope_id"] == str(proj["_id"])
    assert pbody["remaining"] == 20.0

    # GET reflects it on the per_user row.
    get = client.get(f"/api/projects/{proj['_id']}/budget", headers=auth_headers)
    member_row = next(r for r in get.json()["per_user"]
                      if r["user_id"] == str(member["_id"]))
    assert member_row["budget"]["amount_usd"] == 20.0
    assert member_row["display_name"] == "Mem Ber"

    # Clear via null amount.
    cleared = client.put(
        f"/api/projects/{proj['_id']}/members/{member['_id']}/budget",
        headers=auth_headers, json={"amount_usd": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["budget"] is None
    assert cleared.json()["remaining"] is None

    get2 = client.get(f"/api/projects/{proj['_id']}/budget", headers=auth_headers)
    member_row2 = next(r for r in get2.json()["per_user"]
                       if r["user_id"] == str(member["_id"]))
    assert member_row2["budget"] is None


def test_member_budget_spend_reflected(client, flask_core, auth_headers, test_user,
                                       mint_token):
    ws = _seed_workspace(flask_core, test_user["_id"])
    proj = _seed_project_via_api(client, auth_headers, ws["_id"])
    member = _make_user(flask_core, email="member2@gmail.com")
    _add_member(flask_core, wid=ws["_id"], pid=proj["_id"], uid=member["_id"], role="editor")

    client.put(f"/api/projects/{proj['_id']}/members/{member['_id']}/budget",
               headers=auth_headers, json={"amount_usd": 15})
    _bump_rollup(flask_core, scope_type="user", scope_id=member["_id"], cost=4.25)

    get = client.get(f"/api/projects/{proj['_id']}/budget", headers=auth_headers)
    member_row = next(r for r in get.json()["per_user"]
                      if r["user_id"] == str(member["_id"]))
    assert member_row["spend_mtd"] == pytest.approx(4.25)
    assert member_row["remaining"] == pytest.approx(10.75)


def test_member_budget_non_member_404(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    proj = _seed_project_via_api(client, auth_headers, ws["_id"])
    stranger = _make_user(flask_core, email="stranger@gmail.com")
    # stranger is NOT a project member.

    resp = client.put(
        f"/api/projects/{proj['_id']}/members/{stranger['_id']}/budget",
        headers=auth_headers, json={"amount_usd": 5})
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"] == "Member not found"


def test_member_budget_negative_400(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    proj = _seed_project_via_api(client, auth_headers, ws["_id"])
    member = _make_user(flask_core, email="member3@gmail.com")
    _add_member(flask_core, wid=ws["_id"], pid=proj["_id"], uid=member["_id"], role="editor")

    resp = client.put(
        f"/api/projects/{proj['_id']}/members/{member['_id']}/budget",
        headers=auth_headers, json={"amount_usd": -1})
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"] == "amount_usd must be >= 0"
