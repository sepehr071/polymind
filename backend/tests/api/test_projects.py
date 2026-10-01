"""Integration tests for the FastAPI projects router (app/api/routers/projects.py).

Mirrors tests/api/test_auth.py: real model facades on Postgres, the flask_ctx
bridge, legacy-shaped JSON. No external HTTP (the projects routes never call
OpenRouter / upstreams). Entities are seeded via the model facades inside a
``flask_core.app_context()`` and (where it mirrors production) via the API.

Access model recap (utils/permissions.py): a project owner = an explicit
``project_members`` row with role 'owner' OR a workspace 'owner'/'editor' role
on the parent workspace. We seed a workspace + an owner ``workspace_members``
row for the test user, then create projects through the API (which also adds the
explicit project-owner row), so the caller is a full owner.
"""
import uuid

import pytest


# ---------------------------------------------------------------------------
# Seeding helpers — all run inside the Flask app_context.
# ---------------------------------------------------------------------------
def _seed_workspace(flask_core, owner_id, *, role="owner", name="Acme Co"):
    """Create a workspace owned by ``owner_id`` + an active membership row."""
    from app.models.workspace import WorkspaceModel
    from app.models.workspace_member import WorkspaceMemberModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name=name, owner_id=owner_id, type="team")
        WorkspaceMemberModel.add(ws["_id"], owner_id, role, status="active")
        return ws


def _seed_project_via_api(client, headers, workspace_id, name="Alpha"):
    """Create a project through the API (mirrors production owner-grant path)."""
    resp = client.post("/api/projects/create", headers=headers,
                       json={"workspace_id": str(workspace_id), "name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _other_user(flask_core, *, email):
    from app.models.user import UserModel

    with flask_core.app_context():
        return UserModel.create(email=email, password="TestPassword123!",
                                display_name="Other", role="user")


# ---------------------------------------------------------------------------
# Auth gating — no token everywhere.
# ---------------------------------------------------------------------------
def test_list_no_token_401_token_missing(client):
    resp = client.get("/api/projects/list?workspace_id=" + str(uuid.uuid4()))
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_create_no_token_401(client):
    resp = client.post("/api/projects/create", json={"name": "x"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_get_project_no_token_401(client):
    resp = client.get(f"/api/projects/{uuid.uuid4()}")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_banned_user_403(client, banned_user, mint_token):
    token = mint_token(banned_user["_id"], role="user")
    resp = client.get("/api/projects/list?workspace_id=" + str(uuid.uuid4()),
                      headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
    assert resp.json()["error"] == "Account has been suspended"


# ---------------------------------------------------------------------------
# /list
# ---------------------------------------------------------------------------
def test_list_missing_workspace_id_400(client, auth_headers):
    resp = client.get("/api/projects/list", headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "workspace_id query param is required"


def test_list_invalid_workspace_id_400(client, auth_headers):
    resp = client.get("/api/projects/list?workspace_id=not-a-uuid", headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid workspace_id"


def test_list_workspace_not_found_404(client, auth_headers):
    resp = client.get(f"/api/projects/list?workspace_id={uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Workspace not found"


def test_list_workspace_access_denied_403(client, flask_core, auth_headers,
                                          test_user, plain_user, mint_token):
    # Workspace owned by test_user; plain_user has no membership.
    ws = _seed_workspace(flask_core, test_user["_id"])
    plain_headers = {"Authorization": f"Bearer {mint_token(plain_user['_id'], role='user')}"}
    resp = client.get(f"/api/projects/list?workspace_id={ws['_id']}", headers=plain_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Workspace access denied"


def test_list_happy_path(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    p1 = _seed_project_via_api(client, auth_headers, ws["_id"], name="Alpha")
    p2 = _seed_project_via_api(client, auth_headers, ws["_id"], name="Beta")

    resp = client.get(f"/api/projects/list?workspace_id={ws['_id']}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)
    ids = {row["_id"] for row in body}
    assert {p1["_id"], p2["_id"]} <= ids
    # Caller is the project owner -> member_role surfaced.
    for row in body:
        assert "_id" in row
        assert row["member_role"] == "owner"


# ---------------------------------------------------------------------------
# /create
# ---------------------------------------------------------------------------
def test_create_missing_workspace_id_400(client, auth_headers):
    resp = client.post("/api/projects/create", headers=auth_headers, json={"name": "x"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "workspace_id is required"


def test_create_invalid_workspace_id_400(client, auth_headers):
    resp = client.post("/api/projects/create", headers=auth_headers,
                      json={"workspace_id": "nope", "name": "x"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid workspace_id"


def test_create_workspace_not_found_404(client, auth_headers):
    resp = client.post("/api/projects/create", headers=auth_headers,
                      json={"workspace_id": str(uuid.uuid4()), "name": "x"})
    assert resp.status_code == 404
    assert resp.json()["error"] == "Workspace not found"


def test_create_workspace_viewer_denied_403(client, flask_core, test_user,
                                            plain_user, mint_token):
    # plain_user is only a 'viewer' on the workspace -> create needs 'editor'.
    from app.models.workspace_member import WorkspaceMemberModel

    ws = _seed_workspace(flask_core, test_user["_id"])
    with flask_core.app_context():
        WorkspaceMemberModel.add(ws["_id"], plain_user["_id"], "viewer", status="active")
    headers = {"Authorization": f"Bearer {mint_token(plain_user['_id'], role='user')}"}
    resp = client.post("/api/projects/create", headers=headers,
                      json={"workspace_id": str(ws["_id"]), "name": "x"})
    assert resp.status_code == 403
    assert resp.json()["error"] == "Manager or admin access required"


def test_create_empty_name_400(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    resp = client.post("/api/projects/create", headers=auth_headers,
                      json={"workspace_id": str(ws["_id"]), "name": "   "})
    assert resp.status_code == 400
    assert resp.json()["error"] == "name is required"


def test_create_name_too_long_400(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    resp = client.post("/api/projects/create", headers=auth_headers,
                      json={"workspace_id": str(ws["_id"]), "name": "a" * 101})
    assert resp.status_code == 400
    assert resp.json()["error"] == "name must be at most 100 characters"


def test_create_happy_path(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    resp = client.post("/api/projects/create", headers=auth_headers,
                      json={"workspace_id": str(ws["_id"]), "name": "Gamma",
                            "color": "#abcdef", "description": "hi"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "_id" in body  # legacy alias preserved
    assert body["name"] == "Gamma"
    assert body["color"] == "#abcdef"

    # The creator is now an explicit project owner.
    from app.models.project_member import ProjectMemberModel

    with flask_core.app_context():
        member = ProjectMemberModel.find(body["_id"], test_user["_id"])
        assert member is not None
        assert member["role"] == "owner"


# ---------------------------------------------------------------------------
# GET /{pid}
# ---------------------------------------------------------------------------
def test_get_project_happy_path(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"], name="Solo")

    resp = client.get(f"/api/projects/{project['_id']}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["_id"] == project["_id"]
    assert body["member_role"] == "owner"


def test_get_project_access_denied_403(client, flask_core, auth_headers,
                                       test_user, plain_user, mint_token):
    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    headers = {"Authorization": f"Bearer {mint_token(plain_user['_id'], role='user')}"}
    resp = client.get(f"/api/projects/{project['_id']}", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Project access denied"


def test_get_project_not_found_403(client, auth_headers):
    # No project -> project_role_dep denies before the handler (Flask parity:
    # the gate runs first and returns 403, not 404).
    resp = client.get(f"/api/projects/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Project access denied"


# ---------------------------------------------------------------------------
# PATCH /{pid}
# ---------------------------------------------------------------------------
def test_update_project_happy_path(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])

    resp = client.patch(f"/api/projects/{project['_id']}", headers=auth_headers,
                       json={"name": "Renamed", "archived": True})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Renamed"
    assert body["archived"] is True
    assert body["_id"] == project["_id"]


def test_update_project_no_fields_400(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    resp = client.patch(f"/api/projects/{project['_id']}", headers=auth_headers, json={})
    assert resp.status_code == 400
    assert resp.json()["error"] == "No valid fields to update"


def test_update_project_bad_archived_400(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    resp = client.patch(f"/api/projects/{project['_id']}", headers=auth_headers,
                       json={"archived": "yes"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "archived must be a boolean"


def test_update_project_owner_only_403(client, flask_core, auth_headers,
                                       test_user, plain_user, mint_token):
    # plain_user is a workspace 'viewer' -> not project owner.
    from app.models.workspace_member import WorkspaceMemberModel

    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    with flask_core.app_context():
        WorkspaceMemberModel.add(ws["_id"], plain_user["_id"], "viewer", status="active")
    headers = {"Authorization": f"Bearer {mint_token(plain_user['_id'], role='user')}"}
    resp = client.patch(f"/api/projects/{project['_id']}", headers=headers,
                       json={"name": "Nope"})
    assert resp.status_code == 403
    assert resp.json()["error"] == "Project access denied"


# ---------------------------------------------------------------------------
# DELETE /{pid}
# ---------------------------------------------------------------------------
def test_delete_project_happy_path(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])

    resp = client.delete(f"/api/projects/{project['_id']}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["message"] == "Project deleted"

    from app.models.project import ProjectModel

    with flask_core.app_context():
        assert ProjectModel.find_by_id(project["_id"]) is None


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------
def test_list_members_happy_path(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])

    resp = client.get(f"/api/projects/{project['_id']}/members", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)
    # Creator is the lone explicit owner.
    assert len(body) == 1
    row = body[0]
    assert "_id" in row
    assert row["role"] == "owner"
    assert row["user"]["id"] == str(test_user["_id"])
    assert row["user"]["email"] == "test@gmail.com"


def test_add_member_happy_path(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    # Target must already be in the parent workspace.
    target = _other_user(flask_core, email="member@gmail.com")
    from app.models.workspace_member import WorkspaceMemberModel

    with flask_core.app_context():
        WorkspaceMemberModel.add(ws["_id"], target["_id"], "viewer", status="active")

    resp = client.post(f"/api/projects/{project['_id']}/members", headers=auth_headers,
                      json={"user_id": str(target["_id"]), "role": "editor"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "_id" in body
    assert body["role"] == "editor"


def test_add_member_bad_role_400(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    target = _other_user(flask_core, email="member2@gmail.com")
    resp = client.post(f"/api/projects/{project['_id']}/members", headers=auth_headers,
                      json={"user_id": str(target["_id"]), "role": "owner"})
    assert resp.status_code == 400
    assert "role must be one of" in resp.json()["error"]


def test_add_member_user_not_found_404(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    resp = client.post(f"/api/projects/{project['_id']}/members", headers=auth_headers,
                      json={"user_id": str(uuid.uuid4()), "role": "editor"})
    assert resp.status_code == 404
    assert resp.json()["error"] == "User not found"


def test_add_member_not_in_workspace_400(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    # Exists, but NOT a member of the parent workspace.
    target = _other_user(flask_core, email="outsider@gmail.com")
    resp = client.post(f"/api/projects/{project['_id']}/members", headers=auth_headers,
                      json={"user_id": str(target["_id"]), "role": "editor"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "not_in_workspace"


def test_update_member_role_happy_path(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    target = _other_user(flask_core, email="promote@gmail.com")
    from app.models.workspace_member import WorkspaceMemberModel
    from app.models.project_member import ProjectMemberModel

    with flask_core.app_context():
        WorkspaceMemberModel.add(ws["_id"], target["_id"], "viewer", status="active")
        ProjectMemberModel.add(project["_id"], target["_id"], "viewer", added_by=test_user["_id"])

    resp = client.patch(f"/api/projects/{project['_id']}/members/{target['_id']}",
                       headers=auth_headers, json={"role": "editor"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "editor"


def test_update_member_not_found_404(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    resp = client.patch(f"/api/projects/{project['_id']}/members/{uuid.uuid4()}",
                       headers=auth_headers, json={"role": "editor"})
    assert resp.status_code == 404
    assert resp.json()["error"] == "Member not found"


def test_remove_last_owner_protected_400(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    # The creator is the lone explicit owner; removing must be refused.
    resp = client.delete(f"/api/projects/{project['_id']}/members/{test_user['_id']}",
                        headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["code"] == "last_owner_protected"


def test_remove_member_happy_path(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    target = _other_user(flask_core, email="removeme@gmail.com")
    from app.models.workspace_member import WorkspaceMemberModel
    from app.models.project_member import ProjectMemberModel

    with flask_core.app_context():
        WorkspaceMemberModel.add(ws["_id"], target["_id"], "viewer", status="active")
        ProjectMemberModel.add(project["_id"], target["_id"], "editor", added_by=test_user["_id"])

    resp = client.delete(f"/api/projects/{project['_id']}/members/{target['_id']}",
                        headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["message"] == "Member removed"


# ---------------------------------------------------------------------------
# pin / tags (editor min role)
# ---------------------------------------------------------------------------
def test_patch_pin_happy_path(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    resp = client.patch(f"/api/projects/{project['_id']}/pin", headers=auth_headers,
                       json={"pinned": True})
    assert resp.status_code == 200, resp.text
    assert resp.json()["pinned"] is True


def test_patch_pin_bad_payload_400(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    resp = client.patch(f"/api/projects/{project['_id']}/pin", headers=auth_headers,
                       json={"pinned": "true"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "pinned (boolean) is required"


def test_patch_tags_happy_path(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    resp = client.patch(f"/api/projects/{project['_id']}/tags", headers=auth_headers,
                       json={"tags": ["a", "b"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["tags"] == ["a", "b"]


def test_patch_tags_not_list_400(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    resp = client.patch(f"/api/projects/{project['_id']}/tags", headers=auth_headers,
                       json={"tags": "a"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "tags must be a list of strings"


def test_patch_tags_too_many_400(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    resp = client.patch(f"/api/projects/{project['_id']}/tags", headers=auth_headers,
                       json={"tags": [str(i) for i in range(21)]})
    assert resp.status_code == 400
    assert resp.json()["error"] == "a project may have at most 20 tags"


# ---------------------------------------------------------------------------
# Access page (groups + direct members)
# ---------------------------------------------------------------------------
def test_get_access_happy_path(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    resp = client.get(f"/api/projects/{project['_id']}/access", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "groups" in body
    assert "direct_members" in body
    assert isinstance(body["groups"], list)
    # The creator is a direct member.
    assert any(m["user_id"] == str(test_user["_id"]) for m in body["direct_members"])


def test_upsert_group_access_bad_role_400(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    # Seed a real group so we reach the role validation.
    from app.models.group import GroupModel

    with flask_core.app_context():
        group = GroupModel.create(workspace_id=ws["_id"], name="Team A",
                                  created_by=test_user["_id"])
    resp = client.post(f"/api/projects/{project['_id']}/access/groups", headers=auth_headers,
                      json={"group_id": str(group["_id"]), "role": "owner"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_role"


def test_upsert_group_access_happy_path(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    from app.models.group import GroupModel

    with flask_core.app_context():
        group = GroupModel.create(workspace_id=ws["_id"], name="Team B",
                                  created_by=test_user["_id"])
    resp = client.post(f"/api/projects/{project['_id']}/access/groups", headers=auth_headers,
                      json={"group_id": str(group["_id"]), "role": "viewer"})
    assert resp.status_code == 201, resp.text
    assert "_id" in resp.json()


def test_remove_group_access_not_found_404(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    resp = client.delete(
        f"/api/projects/{project['_id']}/access/groups/{uuid.uuid4()}",
        headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Access entry not found"


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------
def test_create_webhook_returns_secret_once(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    resp = client.post(f"/api/projects/{project['_id']}/webhooks", headers=auth_headers,
                      json={"name": "hook", "url": "https://example.com/hook",
                            "events": ["project.updated"]})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "_id" in body
    assert body.get("secret")  # secret present on creation


def test_create_webhook_missing_name_400(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    resp = client.post(f"/api/projects/{project['_id']}/webhooks", headers=auth_headers,
                      json={"url": "https://example.com/hook"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "name is required"


def test_list_webhooks_omits_secret(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    client.post(f"/api/projects/{project['_id']}/webhooks", headers=auth_headers,
               json={"name": "hook", "url": "https://example.com/hook"})
    resp = client.get(f"/api/projects/{project['_id']}/webhooks", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert "secret" not in body[0]
    assert "_id" in body[0]


def test_webhook_update_then_rotate_secret(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    created = client.post(f"/api/projects/{project['_id']}/webhooks", headers=auth_headers,
                         json={"name": "hook", "url": "https://example.com/hook"}).json()
    whid = created["_id"]
    original_secret = created["secret"]

    upd = client.put(f"/api/projects/{project['_id']}/webhooks/{whid}", headers=auth_headers,
                    json={"name": "renamed"})
    assert upd.status_code == 200, upd.text
    # `name` is a phantom legacy field with no ORM column: it is exposed once on
    # create but never persisted, so any read-after-update returns name=None.
    # (Matches original Flask update_webhook: update() drops name, find_by_id()
    #  re-emits it as None via setdefault.)
    assert upd.json()["name"] is None
    assert "secret" not in upd.json()  # secret omitted on update

    rot = client.post(f"/api/projects/{project['_id']}/webhooks/{whid}/rotate-secret",
                     headers=auth_headers)
    assert rot.status_code == 200, rot.text
    assert rot.json()["secret"]
    assert rot.json()["secret"] != original_secret


def test_webhook_not_found_404(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    resp = client.delete(
        f"/api/projects/{project['_id']}/webhooks/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Webhook not found"


# ---------------------------------------------------------------------------
# Route-registration smoke.
# ---------------------------------------------------------------------------
def test_projects_routes_registered(app):
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/projects/list" in paths
    assert "/api/projects/create" in paths
    assert "/api/projects/{pid}" in paths
    assert "/api/projects/{pid}/members" in paths
    assert "/api/projects/{pid}/members/{uid}" in paths
    assert "/api/projects/{pid}/pin" in paths
    assert "/api/projects/{pid}/tags" in paths
    assert "/api/projects/{pid}/access" in paths
    assert "/api/projects/{pid}/access/groups" in paths
    assert "/api/projects/{pid}/webhooks" in paths
    assert "/api/projects/{pid}/webhooks/{whid}" in paths
    assert "/api/projects/{pid}/webhooks/{whid}/rotate-secret" in paths
