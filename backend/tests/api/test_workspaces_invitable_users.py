"""Integration tests for GET /api/workspaces/{wid}/invitable-users and the
list_members enrichment (auth_method + last_active_at), plus a guard that the
removed /auth/register route is gone.

Mirrors tests/api/test_workspaces.py: full path through TestClient -> flask_ctx
app_context -> real model facades on Postgres -> legacy-shaped JSON. Entities
are seeded via the model facades inside ``flask_core.app_context()``.
"""
import pytest

from tests.api.conftest import _headers, _mint


# ---------------------------------------------------------------------------
# Seeding helpers (same shape as test_workspaces.py).
# ---------------------------------------------------------------------------
def _make_user(flask_core, *, email, role="user", display_name="User", password="TestPassword123!"):
    from app.models.user import UserModel

    with flask_core.app_context():
        return UserModel.create(
            email=email, password=password, display_name=display_name, role=role
        )


def _make_sso_user(flask_core, *, email, role="user", display_name="SSO User"):
    """A Keycloak-provisioned user has password_hash=None -> auth_method 'sso'."""
    from app.models.user import UserModel

    with flask_core.app_context():
        return UserModel.create(
            email=email, password=None, display_name=display_name, role=role
        )


def _make_workspace(flask_core, *, owner, name="Acme Team", type="team"):
    from app.models.workspace import WorkspaceModel
    from app.models.workspace_member import WorkspaceMemberModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name=name, owner_id=owner["_id"], type=type)
        WorkspaceMemberModel.add(
            ws["_id"], owner["_id"], "owner", invited_by=owner["_id"], status="active"
        )
        return ws


def _add_member(flask_core, *, wid, user, role="editor", status="active"):
    from app.models.workspace_member import WorkspaceMemberModel

    with flask_core.app_context():
        return WorkspaceMemberModel.add(
            wid, user["_id"], role, invited_by=user["_id"], status=status
        )


def _hdr(user, role="user"):
    return _headers(_mint(user["_id"], role=role))


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------
@pytest.fixture
def owner_user(flask_core):
    return _make_user(flask_core, email="iv_owner@gmail.com", role="manager", display_name="Owner")


@pytest.fixture
def owner_headers(owner_user):
    return _hdr(owner_user, role="manager")


@pytest.fixture
def team_ws(flask_core, owner_user):
    return _make_workspace(flask_core, owner=owner_user, name="Invitable Team")


# ===========================================================================
# GET /{wid}/invitable-users
# ===========================================================================
def test_invitable_users_non_owner_403(client, flask_core, team_ws):
    editor = _make_user(flask_core, email="iv_editor@gmail.com", role="user")
    _add_member(flask_core, wid=team_ws["_id"], user=editor, role="editor")
    resp = client.get(
        f"/api/workspaces/{team_ws['_id']}/invitable-users?q=zoe", headers=_hdr(editor)
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "Workspace access denied"


def test_invitable_users_short_query_empty_list(client, owner_headers, team_ws):
    # < 2 chars -> [] without touching the DB search.
    resp = client.get(
        f"/api/workspaces/{team_ws['_id']}/invitable-users?q=z", headers=owner_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


def test_invitable_users_empty_query_empty_list(client, owner_headers, team_ws):
    resp = client.get(
        f"/api/workspaces/{team_ws['_id']}/invitable-users", headers=owner_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


def test_invitable_users_matches_by_email(client, flask_core, owner_headers, team_ws):
    candidate = _make_user(
        flask_core, email="zoe.candidate@gmail.com", role="user", display_name="Zoe Q"
    )
    resp = client.get(
        f"/api/workspaces/{team_ws['_id']}/invitable-users?q=zoe.candidate",
        headers=owner_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)
    ids = {u["id"] for u in body}
    assert str(candidate["_id"]) in ids
    hit = next(u for u in body if u["id"] == str(candidate["_id"]))
    assert hit["email"] == "zoe.candidate@gmail.com"
    assert hit["display_name"] == "Zoe Q"
    assert "avatar_url" in hit


def test_invitable_users_matches_by_display_name(client, flask_core, owner_headers, team_ws):
    candidate = _make_user(
        flask_core, email="quentin@gmail.com", role="user", display_name="Quirky Quokka"
    )
    resp = client.get(
        f"/api/workspaces/{team_ws['_id']}/invitable-users?q=quirky",
        headers=owner_headers,
    )
    assert resp.status_code == 200, resp.text
    ids = {u["id"] for u in resp.json()}
    assert str(candidate["_id"]) in ids


def test_invitable_users_excludes_active_member(client, flask_core, owner_headers, team_ws):
    member = _make_user(
        flask_core, email="zoe.member@gmail.com", role="user", display_name="Zoe Member"
    )
    _add_member(flask_core, wid=team_ws["_id"], user=member, role="editor")
    resp = client.get(
        f"/api/workspaces/{team_ws['_id']}/invitable-users?q=zoe.member",
        headers=owner_headers,
    )
    assert resp.status_code == 200, resp.text
    ids = {u["id"] for u in resp.json()}
    assert str(member["_id"]) not in ids


def test_invitable_users_excludes_owner_self(client, owner_user, owner_headers, team_ws):
    # The owner is an active member -> excluded from their own typeahead.
    resp = client.get(
        f"/api/workspaces/{team_ws['_id']}/invitable-users?q=iv_owner",
        headers=owner_headers,
    )
    assert resp.status_code == 200, resp.text
    ids = {u["id"] for u in resp.json()}
    assert str(owner_user["_id"]) not in ids


def test_invitable_users_excludes_pending_invite_email(
    client, flask_core, owner_headers, team_ws
):
    candidate = _make_user(
        flask_core, email="zoe.pending@gmail.com", role="user", display_name="Zoe Pending"
    )
    # Create a pending invite for this email via the real route.
    created = client.post(
        f"/api/workspaces/{team_ws['_id']}/invites",
        json={"email": "zoe.pending@gmail.com", "role": "editor"},
        headers=owner_headers,
    )
    assert created.status_code == 201, created.text

    resp = client.get(
        f"/api/workspaces/{team_ws['_id']}/invitable-users?q=zoe.pending",
        headers=owner_headers,
    )
    assert resp.status_code == 200, resp.text
    ids = {u["id"] for u in resp.json()}
    assert str(candidate["_id"]) not in ids


def test_invitable_users_invalid_wid_400_or_403(client, owner_headers):
    # A non-UUID wid fails the workspace_member gate before the handler body.
    resp = client.get(
        "/api/workspaces/not-a-uuid/invitable-users?q=zoe", headers=owner_headers
    )
    assert resp.status_code in (400, 403)


# ===========================================================================
# list_members enrichment: auth_method + last_active_at
# ===========================================================================
def test_list_members_includes_auth_method_and_last_active(
    client, flask_core, owner_headers, owner_user, team_ws
):
    sso_member = _make_sso_user(flask_core, email="sso.member@gmail.com")
    _add_member(flask_core, wid=team_ws["_id"], user=sso_member, role="editor")

    resp = client.get(f"/api/workspaces/{team_ws['_id']}/members", headers=owner_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    by_email = {}
    for m in body:
        # Every member row now carries the two new fields.
        assert "auth_method" in m
        assert "last_active_at" in m
        by_email[m["user"]["email"]] = m

    # Owner was created with a password -> auth_method 'password'.
    owner_row = by_email["iv_owner@gmail.com"]
    assert owner_row["auth_method"] == "password"
    # last_active is seeded at user creation -> ISO string, not None.
    assert owner_row["last_active_at"] is not None

    # SSO-provisioned user has no password -> auth_method 'sso'.
    sso_row = by_email["sso.member@gmail.com"]
    assert sso_row["auth_method"] == "sso"


# ===========================================================================
# /auth/register removal guard.
# ===========================================================================
def test_register_route_removed(client):
    resp = client.post(
        "/api/auth/register",
        json={"email": "x@gmail.com", "password": "ValidPass123!", "display_name": "X"},
    )
    assert resp.status_code not in (200, 201)
    assert resp.status_code in (404, 405)
