"""Integration tests for the workspaces + groups FastAPI router.

Mirrors tests/api/test_auth.py: full path through TestClient -> flask_ctx
app_context -> real model facades on Postgres -> legacy-shaped JSON. Entities
are seeded via the model facades inside ``flask_core.app_context()``.

External HTTP is never hit: ``send_invite_email`` short-circuits to ``False``
when SMTP is unconfigured (the test env), and no LLM/OpenRouter calls are made
by any workspaces/groups route.
"""
import pytest

from tests.api.conftest import _headers, _mint


# ---------------------------------------------------------------------------
# Seeding helpers — all run inside an app_context via the model facades.
# ---------------------------------------------------------------------------
def _make_user(flask_core, *, email, role="user", display_name="User"):
    from app.models.user import UserModel

    with flask_core.app_context():
        return UserModel.create(
            email=email, password="TestPassword123!", display_name=display_name, role=role
        )


def _make_workspace(flask_core, *, owner, name="Acme Team", type="team"):
    """Create a workspace + add owner as an active owner member."""
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
# Fixtures: an owner + their team workspace.
# ---------------------------------------------------------------------------
@pytest.fixture
def owner_user(flask_core):
    return _make_user(flask_core, email="owner@gmail.com", role="manager", display_name="Owner")


@pytest.fixture
def owner_headers(owner_user):
    return _hdr(owner_user, role="manager")


@pytest.fixture
def team_ws(flask_core, owner_user):
    return _make_workspace(flask_core, owner=owner_user, name="Acme Team")


@pytest.fixture
def admin_headers(flask_core):
    """A super-admin caller — the only principal allowed to mint credits."""
    admin = _make_user(flask_core, email="credit_admin@gmail.com", role="admin")
    return _hdr(admin, role="admin")


# ===========================================================================
# /list
# ===========================================================================
def test_list_workspaces_returns_membered(client, owner_headers, team_ws):
    resp = client.get("/api/workspaces/list", headers=owner_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)
    ids = {w["_id"] for w in body}
    assert str(team_ws["_id"]) in ids
    me = next(w for w in body if w["_id"] == str(team_ws["_id"]))
    assert me["member_role"] == "owner"


def test_list_workspaces_no_token_401(client):
    resp = client.get("/api/workspaces/list")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ===========================================================================
# /create  (manager_or_admin gate)
# ===========================================================================
def test_create_workspace_happy(client, owner_headers):
    resp = client.post("/api/workspaces/create", json={"name": "New Team"}, headers=owner_headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["_id"]
    assert body["name"] == "New Team"
    assert body["type"] == "team"


def test_create_workspace_requires_manager_or_admin(client, plain_headers):
    resp = client.post("/api/workspaces/create", json={"name": "Nope"}, headers=plain_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Manager or admin access required"


def test_create_workspace_missing_name_400(client, owner_headers):
    resp = client.post("/api/workspaces/create", json={}, headers=owner_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "name is required"


def test_create_workspace_name_too_long_400(client, owner_headers):
    resp = client.post(
        "/api/workspaces/create", json={"name": "x" * 101}, headers=owner_headers
    )
    assert resp.status_code == 400
    assert "at most 100" in resp.json()["error"]


def test_create_workspace_no_token_401(client):
    resp = client.post("/api/workspaces/create", json={"name": "x"})
    assert resp.status_code == 401


# ===========================================================================
# GET /<wid>
# ===========================================================================
def test_get_workspace_happy(client, owner_headers, team_ws):
    resp = client.get(f"/api/workspaces/{team_ws['_id']}", headers=owner_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["_id"] == str(team_ws["_id"])
    assert body["member_role"] == "owner"


def test_get_workspace_non_member_403(client, flask_core, team_ws):
    outsider = _make_user(flask_core, email="outsider@gmail.com", role="user")
    resp = client.get(f"/api/workspaces/{team_ws['_id']}", headers=_hdr(outsider))
    assert resp.status_code == 403
    assert resp.json()["error"] == "Workspace access denied"


def test_get_workspace_unknown_404(client, owner_headers, flask_core, owner_user):
    # A syntactically-valid UUID the caller is a super-admin-less non-member of:
    # use an admin token so the workspace_member gate passes, then 404 on missing row.
    import uuid

    admin = _make_user(flask_core, email="ga@gmail.com", role="admin")
    missing = str(uuid.uuid4())
    resp = client.get(f"/api/workspaces/{missing}", headers=_hdr(admin, role="admin"))
    assert resp.status_code == 404
    assert resp.json()["error"] == "Workspace not found"


# ===========================================================================
# PATCH /<wid>  (owner gate)
# ===========================================================================
def test_update_workspace_happy(client, owner_headers, team_ws):
    resp = client.patch(
        f"/api/workspaces/{team_ws['_id']}", json={"name": "Renamed"}, headers=owner_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Renamed"


def test_update_workspace_no_fields_400(client, owner_headers, team_ws):
    resp = client.patch(
        f"/api/workspaces/{team_ws['_id']}", json={}, headers=owner_headers
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "No valid fields to update"


def test_update_workspace_bad_plan_tier_400(client, owner_headers, team_ws):
    resp = client.patch(
        f"/api/workspaces/{team_ws['_id']}",
        json={"plan_tier": "platinum"},
        headers=owner_headers,
    )
    assert resp.status_code == 400


def test_update_workspace_editor_forbidden_403(client, flask_core, team_ws):
    editor = _make_user(flask_core, email="editor@gmail.com", role="user")
    _add_member(flask_core, wid=team_ws["_id"], user=editor, role="editor")
    resp = client.patch(
        f"/api/workspaces/{team_ws['_id']}", json={"name": "x"}, headers=_hdr(editor)
    )
    assert resp.status_code == 403


# ===========================================================================
# DELETE /<wid>
# ===========================================================================
def test_delete_team_workspace(client, owner_headers, team_ws):
    resp = client.delete(f"/api/workspaces/{team_ws['_id']}", headers=owner_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["message"] == "Workspace deleted"
    assert "cascade" in resp.json()


def test_delete_workspace_deletes_its_conversations(client, flask_core, owner_user, team_ws):
    """Chats stamped into an org go with it (conversations.workspace_id CASCADE)."""
    from app.models.conversation import ConversationModel

    with flask_core.app_context():
        conv = ConversationModel.create(
            user_id=owner_user["_id"], config_id="quick:x", workspace_id=team_ws["_id"],
        )
    resp = client.delete(
        f"/api/workspaces/{team_ws['_id']}", headers=_hdr(owner_user, role="manager")
    )
    assert resp.status_code == 200, resp.text
    with flask_core.app_context():
        assert ConversationModel.find_by_id(conv["_id"]) is None


# ===========================================================================
# Invites
# ===========================================================================
def test_create_invite_happy(client, owner_headers, team_ws):
    resp = client.post(
        f"/api/workspaces/{team_ws['_id']}/invites",
        json={"email": "invitee@gmail.com", "role": "editor"},
        headers=owner_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["_id"]
    assert body["invite_url"].startswith("/invite/")
    # No SMTP configured in tests -> email_sent is False.
    assert body["email_sent"] is False


def test_create_invite_bad_role_400(client, owner_headers, team_ws):
    resp = client.post(
        f"/api/workspaces/{team_ws['_id']}/invites",
        json={"email": "x@y.com", "role": "superuser"},
        headers=owner_headers,
    )
    assert resp.status_code == 400
    assert "role must be one of" in resp.json()["error"]


def test_create_invite_bad_email_400(client, owner_headers, team_ws):
    resp = client.post(
        f"/api/workspaces/{team_ws['_id']}/invites",
        json={"email": "notanemail", "role": "editor"},
        headers=owner_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "Valid email is required"


def test_list_invites_owner_only(client, owner_headers, team_ws):
    client.post(
        f"/api/workspaces/{team_ws['_id']}/invites",
        json={"email": "p@gmail.com", "role": "viewer"},
        headers=owner_headers,
    )
    resp = client.get(f"/api/workspaces/{team_ws['_id']}/invites", headers=owner_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert any(i["email"] == "p@gmail.com" for i in body)


def test_revoke_invite_unknown_404(client, owner_headers, team_ws):
    resp = client.delete(
        f"/api/workspaces/{team_ws['_id']}/invites/nonexistent-token", headers=owner_headers
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "Invite not found"


def test_revoke_invite_happy(client, owner_headers, team_ws):
    created = client.post(
        f"/api/workspaces/{team_ws['_id']}/invites",
        json={"email": "rev@gmail.com", "role": "viewer"},
        headers=owner_headers,
    ).json()
    token = created["token"]
    resp = client.delete(
        f"/api/workspaces/{team_ws['_id']}/invites/{token}", headers=owner_headers
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "Invite revoked"


# ---------------------------------------------------------------------------
# accept-invite
# ---------------------------------------------------------------------------
def test_accept_invite_happy(client, flask_core, owner_headers, team_ws):
    created = client.post(
        f"/api/workspaces/{team_ws['_id']}/invites",
        json={"email": "joiner@gmail.com", "role": "editor"},
        headers=owner_headers,
    ).json()
    token = created["token"]

    joiner = _make_user(flask_core, email="joiner@gmail.com", role="user")
    resp = client.post(
        "/api/workspaces/accept-invite", json={"token": token}, headers=_hdr(joiner)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["workspace_id"] == str(team_ws["_id"])
    assert body["role"] == "editor"


def test_accept_invite_email_mismatch_403(client, flask_core, owner_headers, team_ws):
    created = client.post(
        f"/api/workspaces/{team_ws['_id']}/invites",
        json={"email": "expected@gmail.com", "role": "viewer"},
        headers=owner_headers,
    ).json()
    other = _make_user(flask_core, email="different@gmail.com", role="user")
    resp = client.post(
        "/api/workspaces/accept-invite", json={"token": created["token"]}, headers=_hdr(other)
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "invite_email_mismatch"


def test_accept_invite_missing_token_400(client, plain_headers):
    resp = client.post("/api/workspaces/accept-invite", json={}, headers=plain_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "token is required"


def test_accept_invite_unknown_token_404(client, plain_headers):
    resp = client.post(
        "/api/workspaces/accept-invite", json={"token": "ghost"}, headers=plain_headers
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "invite_not_found"


# ---------------------------------------------------------------------------
# resend invite
# ---------------------------------------------------------------------------
def test_resend_invite_rotates_token(client, owner_headers, team_ws):
    created = client.post(
        f"/api/workspaces/{team_ws['_id']}/invites",
        json={"email": "resend@gmail.com", "role": "viewer"},
        headers=owner_headers,
    ).json()
    old_token = created["token"]
    resp = client.post(
        f"/api/workspaces/{team_ws['_id']}/invites/{old_token}/resend", headers=owner_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["invite"]["token"] != old_token
    assert body["accept_url"].startswith("/invite/")


# ===========================================================================
# Members
# ===========================================================================
def test_list_members_hydrated(client, flask_core, owner_headers, owner_user, team_ws):
    editor = _make_user(flask_core, email="m_editor@gmail.com", role="user")
    _add_member(flask_core, wid=team_ws["_id"], user=editor, role="editor")

    resp = client.get(f"/api/workspaces/{team_ws['_id']}/members", headers=owner_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    emails = {m["user"]["email"] for m in body}
    assert "owner@gmail.com" in emails
    assert "m_editor@gmail.com" in emails
    for m in body:
        assert "_id" in m


def test_update_member_role_happy(client, flask_core, owner_headers, team_ws):
    editor = _make_user(flask_core, email="promote@gmail.com", role="user")
    _add_member(flask_core, wid=team_ws["_id"], user=editor, role="viewer")
    resp = client.patch(
        f"/api/workspaces/{team_ws['_id']}/members/{editor['_id']}",
        json={"role": "editor"},
        headers=owner_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "editor"


def test_update_member_role_unknown_member_404(client, flask_core, owner_headers, team_ws):
    import uuid

    resp = client.patch(
        f"/api/workspaces/{team_ws['_id']}/members/{uuid.uuid4()}",
        json={"role": "editor"},
        headers=owner_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "Member not found"


def test_update_member_role_last_owner_protected_400(
    client, owner_headers, owner_user, team_ws
):
    # Demoting the sole owner must be refused.
    resp = client.patch(
        f"/api/workspaces/{team_ws['_id']}/members/{owner_user['_id']}",
        json={"role": "editor"},
        headers=owner_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "last_owner_protected"


def test_remove_member_happy(client, flask_core, owner_headers, team_ws):
    member = _make_user(flask_core, email="remove@gmail.com", role="user")
    _add_member(flask_core, wid=team_ws["_id"], user=member, role="editor")
    resp = client.delete(
        f"/api/workspaces/{team_ws['_id']}/members/{member['_id']}", headers=owner_headers
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "Member removed"


def test_remove_last_owner_protected_400(client, owner_headers, owner_user, team_ws):
    resp = client.delete(
        f"/api/workspaces/{team_ws['_id']}/members/{owner_user['_id']}", headers=owner_headers
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "last_owner_protected"


# ===========================================================================
# transfer-ownership
# ===========================================================================
def test_transfer_ownership_happy(client, flask_core, owner_headers, team_ws):
    new_owner = _make_user(flask_core, email="newowner@gmail.com", role="user")
    _add_member(flask_core, wid=team_ws["_id"], user=new_owner, role="editor")
    resp = client.post(
        f"/api/workspaces/{team_ws['_id']}/transfer-ownership",
        json={"new_owner_user_id": str(new_owner["_id"])},
        headers=owner_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["new_owner_membership"]["role"] == "owner"
    assert body["previous_owner_membership"]["role"] == "editor"


def test_transfer_ownership_non_owner_403(client, flask_core, team_ws):
    stranger = _make_user(flask_core, email="stranger@gmail.com", role="user")
    resp = client.post(
        f"/api/workspaces/{team_ws['_id']}/transfer-ownership",
        json={"new_owner_user_id": str(stranger["_id"])},
        headers=_hdr(stranger),
    )
    assert resp.status_code == 403


def test_transfer_ownership_target_not_member_400(client, owner_headers, flask_core, team_ws):
    outsider = _make_user(flask_core, email="ext@gmail.com", role="user")
    resp = client.post(
        f"/api/workspaces/{team_ws['_id']}/transfer-ownership",
        json={"new_owner_user_id": str(outsider["_id"])},
        headers=owner_headers,
    )
    assert resp.status_code == 400


# ===========================================================================
# Overview + billing
# ===========================================================================
def test_overview_happy(client, owner_headers, team_ws):
    resp = client.get(f"/api/workspaces/{team_ws['_id']}/overview", headers=owner_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["workspace"]["_id"] == str(team_ws["_id"])
    assert "billing" in body
    assert "stats" in body
    assert body["stats"]["members_active"] >= 1


def test_billing_usage_owner_only(client, owner_headers, team_ws):
    resp = client.get(
        f"/api/workspaces/{team_ws['_id']}/billing/usage", headers=owner_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "by_user" in body
    assert "credits" in body
    assert "remaining_usd" in body["credits"]


def test_billing_usage_editor_forbidden_403(client, flask_core, team_ws):
    editor = _make_user(flask_core, email="bill_editor@gmail.com", role="user")
    _add_member(flask_core, wid=team_ws["_id"], user=editor, role="editor")
    resp = client.get(
        f"/api/workspaces/{team_ws['_id']}/billing/usage", headers=_hdr(editor)
    )
    assert resp.status_code == 403


def test_add_credits_happy(client, admin_headers, team_ws):
    # Minting credit is now super-admin ONLY (require_admin) — a workspace owner
    # may no longer self-fund their wallet.
    resp = client.post(
        f"/api/workspaces/{team_ws['_id']}/billing/credits",
        json={"amount_usd": 50, "type": "top_up", "note": "seed"},
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["credits_balance_usd"] == 50.0
    assert body["entry"]["_id"]


def test_add_credits_non_admin_owner_403(client, owner_headers, team_ws):
    """Regression lock (#1): a non-admin workspace owner is REFUSED — the
    member-owner gate that let any account self-mint unlimited credit (and
    defeat prepaid enforcement) is gone; funding is super-admin only."""
    resp = client.post(
        f"/api/workspaces/{team_ws['_id']}/billing/credits",
        json={"amount_usd": 50, "type": "top_up"},
        headers=owner_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "Admin access required"


def test_add_credits_bad_amount_400(client, admin_headers, team_ws):
    resp = client.post(
        f"/api/workspaces/{team_ws['_id']}/billing/credits",
        json={"type": "top_up"},
        headers=admin_headers,
    )
    assert resp.status_code == 400
    assert "amount_usd" in resp.json()["error"]


def test_add_credits_bad_type_400(client, admin_headers, team_ws):
    resp = client.post(
        f"/api/workspaces/{team_ws['_id']}/billing/credits",
        json={"amount_usd": 10, "type": "bonus"},
        headers=admin_headers,
    )
    assert resp.status_code == 400


def test_add_credits_nonpositive_top_up_400(client, admin_headers, team_ws):
    """Regression lock (#1): a zero/negative ``top_up`` is rejected so a funding
    call can't be repurposed to silently drain a wallet."""
    resp = client.post(
        f"/api/workspaces/{team_ws['_id']}/billing/credits",
        json={"amount_usd": 0, "type": "top_up"},
        headers=admin_headers,
    )
    assert resp.status_code == 400
    assert "amount_usd" in resp.json()["error"]


def test_list_ledger_after_credit(client, admin_headers, owner_headers, team_ws):
    # Seed the credit as the super-admin (POST is admin-gated)...
    client.post(
        f"/api/workspaces/{team_ws['_id']}/billing/credits",
        json={"amount_usd": 25, "type": "top_up"},
        headers=admin_headers,
    )
    # ...but the ledger GET stays owner-scoped (read-only).
    resp = client.get(
        f"/api/workspaces/{team_ws['_id']}/billing/ledger", headers=owner_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_credits_usd"] == 25.0
    assert len(body["entries"]) == 1
    assert body["entries"][0]["added_by_user"]["email"] == "credit_admin@gmail.com"


# ===========================================================================
# Audit
# ===========================================================================
def test_audit_happy(client, owner_headers, team_ws):
    resp = client.get(f"/api/workspaces/{team_ws['_id']}/audit", headers=owner_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "entries" in body
    assert "next_before" in body


def test_audit_bad_limit_400(client, owner_headers, team_ws):
    resp = client.get(
        f"/api/workspaces/{team_ws['_id']}/audit?limit=notanint", headers=owner_headers
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "limit must be an integer"


# ===========================================================================
# Groups (same /api/workspaces prefix; admin gate -> owner via legacy map)
# ===========================================================================
def test_create_group_happy(client, owner_headers, team_ws):
    resp = client.post(
        f"/api/workspaces/{team_ws['_id']}/groups",
        json={"name": "Engineers"},
        headers=owner_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["_id"]
    assert body["name"] == "Engineers"
    assert body["member_count"] == 0


def test_create_group_missing_name_400(client, owner_headers, team_ws):
    resp = client.post(
        f"/api/workspaces/{team_ws['_id']}/groups", json={}, headers=owner_headers
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "name is required"


def test_create_group_editor_forbidden_403(client, flask_core, team_ws):
    # 'admin' min_role maps to 'owner' — an editor must be refused.
    editor = _make_user(flask_core, email="g_editor@gmail.com", role="user")
    _add_member(flask_core, wid=team_ws["_id"], user=editor, role="editor")
    resp = client.post(
        f"/api/workspaces/{team_ws['_id']}/groups",
        json={"name": "X"},
        headers=_hdr(editor),
    )
    assert resp.status_code == 403


def test_list_groups_viewer_ok(client, flask_core, owner_headers, team_ws):
    client.post(
        f"/api/workspaces/{team_ws['_id']}/groups",
        json={"name": "Designers"},
        headers=owner_headers,
    )
    viewer = _make_user(flask_core, email="g_viewer@gmail.com", role="user")
    _add_member(flask_core, wid=team_ws["_id"], user=viewer, role="viewer")
    resp = client.get(
        f"/api/workspaces/{team_ws['_id']}/groups/list", headers=_hdr(viewer)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "groups" in body
    assert any(g["name"] == "Designers" for g in body["groups"])


def test_get_group_with_members(client, owner_headers, team_ws):
    created = client.post(
        f"/api/workspaces/{team_ws['_id']}/groups",
        json={"name": "Detail"},
        headers=owner_headers,
    ).json()
    gid = created["_id"]
    resp = client.get(
        f"/api/workspaces/{team_ws['_id']}/groups/{gid}", headers=owner_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["_id"] == gid
    assert body["members"] == []


def test_get_group_unknown_404(client, owner_headers, team_ws):
    import uuid

    resp = client.get(
        f"/api/workspaces/{team_ws['_id']}/groups/{uuid.uuid4()}", headers=owner_headers
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "Group not found"


def test_update_group_happy(client, owner_headers, team_ws):
    created = client.post(
        f"/api/workspaces/{team_ws['_id']}/groups",
        json={"name": "Old"},
        headers=owner_headers,
    ).json()
    gid = created["_id"]
    resp = client.put(
        f"/api/workspaces/{team_ws['_id']}/groups/{gid}",
        json={"name": "Renamed"},
        headers=owner_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Renamed"


def test_update_group_no_fields_400(client, owner_headers, team_ws):
    created = client.post(
        f"/api/workspaces/{team_ws['_id']}/groups",
        json={"name": "Empty"},
        headers=owner_headers,
    ).json()
    gid = created["_id"]
    resp = client.put(
        f"/api/workspaces/{team_ws['_id']}/groups/{gid}", json={}, headers=owner_headers
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "No valid fields to update"


def test_delete_group_happy(client, owner_headers, team_ws):
    created = client.post(
        f"/api/workspaces/{team_ws['_id']}/groups",
        json={"name": "DeleteMe"},
        headers=owner_headers,
    ).json()
    gid = created["_id"]
    resp = client.delete(
        f"/api/workspaces/{team_ws['_id']}/groups/{gid}", headers=owner_headers
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "Group deleted"


def test_add_group_member_happy(client, flask_core, owner_headers, team_ws):
    member = _make_user(flask_core, email="g_member@gmail.com", role="user")
    _add_member(flask_core, wid=team_ws["_id"], user=member, role="editor")
    created = client.post(
        f"/api/workspaces/{team_ws['_id']}/groups",
        json={"name": "WithMembers"},
        headers=owner_headers,
    ).json()
    gid = created["_id"]
    resp = client.post(
        f"/api/workspaces/{team_ws['_id']}/groups/{gid}/members",
        json={"user_id": str(member["_id"])},
        headers=owner_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["_id"]


def test_add_group_member_not_in_workspace_400(client, flask_core, owner_headers, team_ws):
    outsider = _make_user(flask_core, email="g_outsider@gmail.com", role="user")
    created = client.post(
        f"/api/workspaces/{team_ws['_id']}/groups",
        json={"name": "Guarded"},
        headers=owner_headers,
    ).json()
    gid = created["_id"]
    resp = client.post(
        f"/api/workspaces/{team_ws['_id']}/groups/{gid}/members",
        json={"user_id": str(outsider["_id"])},
        headers=owner_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "not_in_workspace"


def test_remove_group_member_happy(client, flask_core, owner_headers, team_ws):
    member = _make_user(flask_core, email="g_rm@gmail.com", role="user")
    _add_member(flask_core, wid=team_ws["_id"], user=member, role="editor")
    created = client.post(
        f"/api/workspaces/{team_ws['_id']}/groups",
        json={"name": "RmMember"},
        headers=owner_headers,
    ).json()
    gid = created["_id"]
    client.post(
        f"/api/workspaces/{team_ws['_id']}/groups/{gid}/members",
        json={"user_id": str(member["_id"])},
        headers=owner_headers,
    )
    resp = client.delete(
        f"/api/workspaces/{team_ws['_id']}/groups/{gid}/members/{member['_id']}",
        headers=owner_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "Member removed"


def test_remove_group_member_not_member_404(client, flask_core, owner_headers, team_ws):
    member = _make_user(flask_core, email="g_notmember@gmail.com", role="user")
    _add_member(flask_core, wid=team_ws["_id"], user=member, role="editor")
    created = client.post(
        f"/api/workspaces/{team_ws['_id']}/groups",
        json={"name": "Empty404"},
        headers=owner_headers,
    ).json()
    gid = created["_id"]
    resp = client.delete(
        f"/api/workspaces/{team_ws['_id']}/groups/{gid}/members/{member['_id']}",
        headers=owner_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "Member not found"


# ===========================================================================
# Route-registration smoke (does not touch the DB).
# ===========================================================================
def test_workspaces_routes_registered(app):
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/workspaces/list" in paths
    assert "/api/workspaces/create" in paths
    assert "/api/workspaces/{wid}" in paths
    assert "/api/workspaces/accept-invite" in paths
    assert "/api/workspaces/{wid}/members/{uid}" in paths
    assert "/api/workspaces/{wid}/transfer-ownership" in paths
    assert "/api/workspaces/{wid}/billing/usage" in paths
    assert "/api/workspaces/{wid}/groups" in paths
    assert "/api/workspaces/{wid}/groups/list" in paths
    assert "/api/workspaces/{wid}/groups/{gid}/members/{uid}" in paths
