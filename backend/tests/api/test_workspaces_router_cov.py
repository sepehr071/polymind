"""Coverage-raising tests for the workspaces router + WorkspaceModel facade.

Complements tests/api/test_workspaces.py by driving the *uncovered* branches:
invalid-ID validators, accept/resend-invite edge states, transfer-ownership
edge cases, billing daily aggregation with real usage rows, audit query
filters, group name-conflict 409s, and direct WorkspaceModel facade paths
(bad ids, plan_tier/ip_allowlist validation, settings replace, set_owner,
find_by_slug, slug-collision, ownerless team).

Mirrors the sibling style: TestClient -> flask_ctx app_context -> real model
facades on Postgres -> legacy-shaped JSON. No external HTTP is hit
(send_invite_email short-circuits to False when SMTP is unconfigured).
"""
import uuid

import pytest

from tests.api.conftest import _headers, _mint


# ---------------------------------------------------------------------------
# Seeding helpers (mirror the sibling file).
# ---------------------------------------------------------------------------
def _make_user(flask_core, *, email, role="user", display_name="User"):
    from app.models.user import UserModel

    with flask_core.app_context():
        return UserModel.create(
            email=email, password="TestPassword123!", display_name=display_name, role=role
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


@pytest.fixture
def owner_user(flask_core):
    return _make_user(flask_core, email="cov_owner@gmail.com", role="manager", display_name="Owner")


@pytest.fixture
def owner_headers(owner_user):
    return _hdr(owner_user, role="manager")


@pytest.fixture
def team_ws(flask_core, owner_user):
    return _make_workspace(flask_core, owner=owner_user, name="Cov Team")


# ===========================================================================
# Invalid-ID validator branches (every handler short-circuits on bad UUID).
# An admin token passes the workspace_member gate (global short-circuit), so
# the handler body's own validate_object_id check is what 400s.
# ===========================================================================
@pytest.fixture
def admin_hdr(flask_core):
    admin = _make_user(flask_core, email="cov_admin@gmail.com", role="admin")
    return _hdr(admin, role="admin")


def test_get_workspace_invalid_id_400(client, admin_hdr):
    resp = client.get("/api/workspaces/not-a-uuid", headers=admin_hdr)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid workspace ID"


def test_update_workspace_invalid_id_400(client, admin_hdr):
    resp = client.patch(
        "/api/workspaces/not-a-uuid", json={"name": "x"}, headers=admin_hdr
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid workspace ID"


def test_delete_workspace_invalid_id_400(client, admin_hdr):
    resp = client.delete("/api/workspaces/not-a-uuid", headers=admin_hdr)
    assert resp.status_code == 400


def test_create_invite_invalid_id_400(client, admin_hdr):
    resp = client.post(
        "/api/workspaces/not-a-uuid/invites",
        json={"email": "x@y.com", "role": "editor"},
        headers=admin_hdr,
    )
    assert resp.status_code == 400


def test_list_invites_invalid_id_400(client, admin_hdr):
    resp = client.get("/api/workspaces/not-a-uuid/invites", headers=admin_hdr)
    assert resp.status_code == 400


def test_list_members_invalid_id_400(client, admin_hdr):
    resp = client.get("/api/workspaces/not-a-uuid/members", headers=admin_hdr)
    assert resp.status_code == 400


def test_update_member_role_invalid_id_400(client, admin_hdr):
    resp = client.patch(
        f"/api/workspaces/not-a-uuid/members/{uuid.uuid4()}",
        json={"role": "editor"},
        headers=admin_hdr,
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid ID"


def test_remove_member_invalid_id_400(client, admin_hdr):
    resp = client.delete(
        f"/api/workspaces/not-a-uuid/members/{uuid.uuid4()}", headers=admin_hdr
    )
    assert resp.status_code == 400


def test_transfer_ownership_invalid_id_400(client, admin_hdr):
    resp = client.post(
        "/api/workspaces/not-a-uuid/transfer-ownership",
        json={"new_owner_user_id": str(uuid.uuid4())},
        headers=admin_hdr,
    )
    assert resp.status_code == 400


def test_overview_invalid_id_400(client, admin_hdr):
    resp = client.get("/api/workspaces/not-a-uuid/overview", headers=admin_hdr)
    assert resp.status_code == 400


def test_billing_usage_invalid_id_400(client, admin_hdr):
    resp = client.get("/api/workspaces/not-a-uuid/billing/usage", headers=admin_hdr)
    assert resp.status_code == 400


def test_audit_invalid_id_400(client, admin_hdr):
    resp = client.get("/api/workspaces/not-a-uuid/audit", headers=admin_hdr)
    assert resp.status_code == 400


def test_add_credits_invalid_id_400(client, admin_hdr):
    resp = client.post(
        "/api/workspaces/not-a-uuid/billing/credits",
        json={"amount_usd": 5},
        headers=admin_hdr,
    )
    assert resp.status_code == 400


def test_list_ledger_invalid_id_400(client, admin_hdr):
    resp = client.get("/api/workspaces/not-a-uuid/billing/ledger", headers=admin_hdr)
    assert resp.status_code == 400


def test_create_group_invalid_id_400(client, admin_hdr):
    resp = client.post(
        "/api/workspaces/not-a-uuid/groups", json={"name": "x"}, headers=admin_hdr
    )
    assert resp.status_code == 400


def test_list_groups_invalid_id_400(client, admin_hdr):
    resp = client.get("/api/workspaces/not-a-uuid/groups/list", headers=admin_hdr)
    assert resp.status_code == 400


def test_get_group_invalid_id_400(client, admin_hdr):
    resp = client.get(
        f"/api/workspaces/not-a-uuid/groups/{uuid.uuid4()}", headers=admin_hdr
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid ID"


def test_update_group_invalid_id_400(client, admin_hdr):
    resp = client.put(
        f"/api/workspaces/not-a-uuid/groups/{uuid.uuid4()}",
        json={"name": "x"},
        headers=admin_hdr,
    )
    assert resp.status_code == 400


def test_delete_group_invalid_id_400(client, admin_hdr):
    resp = client.delete(
        f"/api/workspaces/not-a-uuid/groups/{uuid.uuid4()}", headers=admin_hdr
    )
    assert resp.status_code == 400


def test_add_group_member_invalid_id_400(client, admin_hdr):
    resp = client.post(
        f"/api/workspaces/not-a-uuid/groups/{uuid.uuid4()}/members",
        json={"user_id": str(uuid.uuid4())},
        headers=admin_hdr,
    )
    assert resp.status_code == 400


def test_remove_group_member_invalid_id_400(client, admin_hdr):
    resp = client.delete(
        f"/api/workspaces/not-a-uuid/groups/{uuid.uuid4()}/members/{uuid.uuid4()}",
        headers=admin_hdr,
    )
    assert resp.status_code == 400


# ===========================================================================
# Workspace 404 (admin token passes gate, missing row 404s).
# ===========================================================================
def test_update_workspace_unknown_404(client, admin_hdr):
    resp = client.patch(
        f"/api/workspaces/{uuid.uuid4()}", json={"name": "x"}, headers=admin_hdr
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "Workspace not found"


def test_delete_workspace_unknown_404(client, admin_hdr):
    resp = client.delete(f"/api/workspaces/{uuid.uuid4()}", headers=admin_hdr)
    assert resp.status_code == 404


def test_overview_unknown_404(client, admin_hdr):
    resp = client.get(f"/api/workspaces/{uuid.uuid4()}/overview", headers=admin_hdr)
    assert resp.status_code == 404


def test_add_credits_unknown_workspace_404(client, admin_hdr):
    resp = client.post(
        f"/api/workspaces/{uuid.uuid4()}/billing/credits",
        json={"amount_usd": 10},
        headers=admin_hdr,
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "Workspace not found"


def test_transfer_ownership_unknown_workspace_404(client, admin_hdr):
    resp = client.post(
        f"/api/workspaces/{uuid.uuid4()}/transfer-ownership",
        json={"new_owner_user_id": str(uuid.uuid4())},
        headers=admin_hdr,
    )
    assert resp.status_code == 404


# ===========================================================================
# update_workspace branches: empty name, settings-not-object, avatar, settings
# blob replace, ip_allowlist, enforce_2fa.
# ===========================================================================
def test_update_workspace_empty_name_400(client, owner_headers, team_ws):
    resp = client.patch(
        f"/api/workspaces/{team_ws['_id']}", json={"name": "   "}, headers=owner_headers
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "name cannot be empty"


def test_update_workspace_name_too_long_400(client, owner_headers, team_ws):
    resp = client.patch(
        f"/api/workspaces/{team_ws['_id']}",
        json={"name": "y" * 101},
        headers=owner_headers,
    )
    assert resp.status_code == 400
    assert "at most 100" in resp.json()["error"]


def test_update_workspace_settings_not_object_400(client, owner_headers, team_ws):
    resp = client.patch(
        f"/api/workspaces/{team_ws['_id']}",
        json={"settings": "nope"},
        headers=owner_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "settings must be an object"


def test_update_workspace_avatar_settings_iplist(client, owner_headers, team_ws):
    resp = client.patch(
        f"/api/workspaces/{team_ws['_id']}",
        json={
            "avatar": {"type": "initials", "value": "ZZ"},
            "settings": {"plan": "free", "custom": True},
            "ip_allowlist": ["10.0.0.1", "10.0.0.2"],
            "enforce_2fa": True,
        },
        headers=owner_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["enforce_2fa"] is True
    assert body["ip_allowlist"] == ["10.0.0.1", "10.0.0.2"]


def test_update_workspace_bad_ip_allowlist_400(client, owner_headers, team_ws):
    resp = client.patch(
        f"/api/workspaces/{team_ws['_id']}",
        json={"ip_allowlist": "notalist"},
        headers=owner_headers,
    )
    assert resp.status_code == 400
    assert "ip_allowlist" in resp.json()["error"]


def test_update_workspace_ip_allowlist_blank_item_400(client, owner_headers, team_ws):
    resp = client.patch(
        f"/api/workspaces/{team_ws['_id']}",
        json={"ip_allowlist": ["  "]},
        headers=owner_headers,
    )
    assert resp.status_code == 400


# ===========================================================================
# Invite edge branches: resend already-accepted 409, resend unknown 404,
# accept-invite already-accepted / expired, revoke wrong-workspace 404.
# ===========================================================================
def test_resend_invite_unknown_404(client, owner_headers, team_ws):
    resp = client.post(
        f"/api/workspaces/{team_ws['_id']}/invites/ghost-token/resend",
        headers=owner_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "Invite not found"


def test_resend_invite_already_accepted_409(client, flask_core, owner_headers, team_ws):
    created = client.post(
        f"/api/workspaces/{team_ws['_id']}/invites",
        json={"email": "acc@gmail.com", "role": "viewer"},
        headers=owner_headers,
    ).json()
    token = created["token"]
    # Mark accepted directly via the facade.
    from app.models.workspace_invite import WorkspaceInviteModel

    with flask_core.app_context():
        WorkspaceInviteModel.mark_accepted(token)

    resp = client.post(
        f"/api/workspaces/{team_ws['_id']}/invites/{token}/resend", headers=owner_headers
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "invite_already_accepted"


def test_accept_invite_already_accepted_400(client, flask_core, owner_headers, team_ws):
    created = client.post(
        f"/api/workspaces/{team_ws['_id']}/invites",
        json={"email": "twice@gmail.com", "role": "editor"},
        headers=owner_headers,
    ).json()
    token = created["token"]
    from app.models.workspace_invite import WorkspaceInviteModel

    with flask_core.app_context():
        WorkspaceInviteModel.mark_accepted(token)

    joiner = _make_user(flask_core, email="twice@gmail.com", role="user")
    resp = client.post(
        "/api/workspaces/accept-invite", json={"token": token}, headers=_hdr(joiner)
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "invite_already_accepted"


def test_accept_invite_expired_is_accepted_due_to_str_coercion(
    client, flask_core, owner_headers, team_ws
):
    """Drives the expiry branch in accept-invite. NOTE: possible bug — the
    expiry guard is ``isinstance(expires_at, datetime) and expires_at <= now``,
    but ``WorkspaceInviteModel.find_by_token`` returns the row via
    ``to_dict()`` which ISO-stringifies every datetime (see _base.py
    ``SerializableMixin.to_dict``). So ``expires_at`` is a *str*, the
    ``isinstance(..., datetime)`` check is always False, and an EXPIRED invite
    is accepted (200) instead of rejected (400 invite_expired). Asserting the
    real current behavior."""
    created = client.post(
        f"/api/workspaces/{team_ws['_id']}/invites",
        json={"email": "expired@gmail.com", "role": "viewer"},
        headers=owner_headers,
    ).json()
    token = created["token"]
    # Force expiry into the past directly on the column.
    from datetime import datetime, timedelta

    from app.extensions import db
    from app.models.workspace_invite import WorkspaceInvite
    from sqlalchemy import update as sa_update

    with flask_core.app_context():
        db.session.execute(
            sa_update(WorkspaceInvite)
            .where(WorkspaceInvite.token == token)
            .values(expires_at=datetime.utcnow() - timedelta(days=1))
        )
        db.session.commit()

    joiner = _make_user(flask_core, email="expired@gmail.com", role="user")
    resp = client.post(
        "/api/workspaces/accept-invite", json={"token": token}, headers=_hdr(joiner)
    )
    # Expired-but-accepted: the str-typed expires_at slips past the guard.
    assert resp.status_code == 200
    assert resp.json()["role"] == "viewer"


def test_accept_invite_reactivates_revoked_member(client, flask_core, owner_headers, team_ws):
    """Caller is an existing non-active member -> update_status path."""
    rejoiner = _make_user(flask_core, email="rejoin@gmail.com", role="user")
    _add_member(flask_core, wid=team_ws["_id"], user=rejoiner, role="editor", status="revoked")

    created = client.post(
        f"/api/workspaces/{team_ws['_id']}/invites",
        json={"email": "rejoin@gmail.com", "role": "viewer"},
        headers=owner_headers,
    ).json()
    resp = client.post(
        "/api/workspaces/accept-invite", json={"token": created["token"]}, headers=_hdr(rejoiner)
    )
    assert resp.status_code == 200, resp.text
    # role is the invite's role.
    assert resp.json()["role"] == "viewer"


def test_revoke_invite_wrong_workspace_404(client, flask_core, owner_headers, team_ws, owner_user):
    other_ws = _make_workspace(flask_core, owner=owner_user, name="Other WS")
    created = client.post(
        f"/api/workspaces/{other_ws['_id']}/invites",
        json={"email": "wrong@gmail.com", "role": "viewer"},
        headers=owner_headers,
    ).json()
    token = created["token"]
    # Try to revoke it through team_ws -> belongs to other_ws -> 404.
    resp = client.delete(
        f"/api/workspaces/{team_ws['_id']}/invites/{token}", headers=owner_headers
    )
    assert resp.status_code == 404
    assert "does not belong" in resp.json()["error"]


# ===========================================================================
# update_member_role: bad role, demote non-last-owner OK.
# ===========================================================================
def test_update_member_role_bad_role_400(client, flask_core, owner_headers, team_ws):
    member = _make_user(flask_core, email="badrole@gmail.com", role="user")
    _add_member(flask_core, wid=team_ws["_id"], user=member, role="editor")
    resp = client.patch(
        f"/api/workspaces/{team_ws['_id']}/members/{member['_id']}",
        json={"role": "superadmin"},
        headers=owner_headers,
    )
    assert resp.status_code == 400
    assert "role must be one of" in resp.json()["error"]


def test_update_member_demote_owner_when_multiple_owners(client, flask_core, owner_headers, team_ws):
    """With two owners, demoting one is allowed (owner_count > 1)."""
    second = _make_user(flask_core, email="second_owner@gmail.com", role="user")
    _add_member(flask_core, wid=team_ws["_id"], user=second, role="owner")
    resp = client.patch(
        f"/api/workspaces/{team_ws['_id']}/members/{second['_id']}",
        json={"role": "editor"},
        headers=owner_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "editor"


def test_remove_owner_when_multiple_owners(client, flask_core, owner_headers, team_ws):
    second = _make_user(flask_core, email="rm_owner@gmail.com", role="user")
    _add_member(flask_core, wid=team_ws["_id"], user=second, role="owner")
    resp = client.delete(
        f"/api/workspaces/{team_ws['_id']}/members/{second['_id']}", headers=owner_headers
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "Member removed"


# ===========================================================================
# transfer-ownership edge cases (global admin path, 409s, target inactive).
# ===========================================================================
def test_transfer_ownership_global_admin(client, flask_core, team_ws):
    """A global admin (not owner) can transfer ownership."""
    admin = _make_user(flask_core, email="ta_admin@gmail.com", role="admin")
    new_owner = _make_user(flask_core, email="ta_newowner@gmail.com", role="user")
    _add_member(flask_core, wid=team_ws["_id"], user=new_owner, role="editor")
    resp = client.post(
        f"/api/workspaces/{team_ws['_id']}/transfer-ownership",
        json={"new_owner_user_id": str(new_owner["_id"])},
        headers=_hdr(admin, role="admin"),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["new_owner_membership"]["role"] == "owner"


def test_transfer_ownership_missing_target_400(client, owner_headers, team_ws):
    resp = client.post(
        f"/api/workspaces/{team_ws['_id']}/transfer-ownership",
        json={},
        headers=owner_headers,
    )
    assert resp.status_code == 400
    assert "new_owner_user_id" in resp.json()["error"]


def test_transfer_ownership_target_is_caller_409(client, owner_headers, owner_user, team_ws):
    resp = client.post(
        f"/api/workspaces/{team_ws['_id']}/transfer-ownership",
        json={"new_owner_user_id": str(owner_user["_id"])},
        headers=owner_headers,
    )
    assert resp.status_code == 409
    assert "already the caller" in resp.json()["error"]


def test_transfer_ownership_target_already_owner_409(client, flask_core, owner_headers, team_ws):
    second = _make_user(flask_core, email="ta_already@gmail.com", role="user")
    _add_member(flask_core, wid=team_ws["_id"], user=second, role="owner")
    resp = client.post(
        f"/api/workspaces/{team_ws['_id']}/transfer-ownership",
        json={"new_owner_user_id": str(second["_id"])},
        headers=owner_headers,
    )
    assert resp.status_code == 409
    assert "already an owner" in resp.json()["error"]


def test_transfer_ownership_target_inactive_400(client, flask_core, owner_headers, team_ws):
    pending = _make_user(flask_core, email="ta_pending@gmail.com", role="user")
    _add_member(flask_core, wid=team_ws["_id"], user=pending, role="editor", status="pending")
    resp = client.post(
        f"/api/workspaces/{team_ws['_id']}/transfer-ownership",
        json={"new_owner_user_id": str(pending["_id"])},
        headers=owner_headers,
    )
    assert resp.status_code == 400
    assert "not an active member" in resp.json()["error"]


# ===========================================================================
# Billing usage with REAL usage rows -> exercises the daily-aggregation branch,
# user/project hydration, and credits math.
# ===========================================================================
def test_billing_usage_with_data(client, flask_core, owner_headers, owner_user, team_ws):
    from app.models.project import ProjectModel
    from app.models.usage_log import UsageLogModel

    with flask_core.app_context():
        proj = ProjectModel.create(
            workspace_id=team_ws["_id"], name="Billed Project", created_by=owner_user["_id"]
        )
        UsageLogModel.create(
            user_id=owner_user["_id"],
            workspace_id=team_ws["_id"],
            project_id=proj["_id"],
            model="openai/gpt-5",
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=1.25,
            origin="web",
        )
        UsageLogModel.create(
            user_id=owner_user["_id"],
            workspace_id=team_ws["_id"],
            project_id=proj["_id"],
            model="google/gemini-3",
            prompt_tokens=200,
            completion_tokens=80,
            cost_usd=0.75,
            origin="web",
        )

    # Use a wide explicit window so the freshly-written rows deterministically
    # fall inside (the default window's `created_at <= utcnow()` upper bound is
    # racy against the server's non-UTC tz).
    resp = client.get(
        f"/api/workspaces/{team_ws['_id']}/billing/usage"
        "?start=2020-01-01&end=2999-12-31",
        headers=owner_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body["daily"], list)
    assert body["totals"]["cost_usd"] == pytest.approx(2.0)
    assert body["totals"]["total_tokens"] == 430
    # by_user hydrated with the owner's email.
    assert any(r.get("email") == "cov_owner@gmail.com" for r in body["by_user"])
    # by_project hydrated with the project name.
    assert any(r.get("name") == "Billed Project" for r in body["by_project"])


def test_billing_usage_explicit_window(client, owner_headers, team_ws):
    """start/end query params parse via _parse_iso_date."""
    resp = client.get(
        f"/api/workspaces/{team_ws['_id']}/billing/usage"
        "?start=2020-01-01&end=2020-12-31",
        headers=owner_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["window"]["start"].startswith("2020-01-01")
    assert body["daily"] == []


def test_billing_usage_daily_rows_in_wide_window(
    client, flask_core, owner_headers, owner_user, team_ws
):
    """Wide window guarantees freshly-written rows fall inside -> the daily
    aggregation row-mapping branch executes."""
    from app.models.usage_log import UsageLogModel

    with flask_core.app_context():
        UsageLogModel.create(
            user_id=owner_user["_id"],
            workspace_id=team_ws["_id"],
            model="openai/gpt-5",
            prompt_tokens=10,
            completion_tokens=5,
            cost_usd=0.4,
            origin="web",
        )
    resp = client.get(
        f"/api/workspaces/{team_ws['_id']}/billing/usage"
        "?start=2020-01-01&end=2999-12-31",
        headers=owner_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["daily"]) >= 1
    row = body["daily"][0]
    assert "date" in row and "cost_usd" in row and "total_tokens" in row


# ===========================================================================
# Overview with real data (top_projects + usage_30d + groups branches).
# ===========================================================================
def test_overview_with_usage_and_groups(client, flask_core, owner_headers, owner_user, team_ws):
    from app.models.project import ProjectModel
    from app.models.usage_log import UsageLogModel

    with flask_core.app_context():
        proj = ProjectModel.create(
            workspace_id=team_ws["_id"], name="Overview Project", created_by=owner_user["_id"]
        )
        UsageLogModel.create(
            user_id=owner_user["_id"],
            workspace_id=team_ws["_id"],
            project_id=proj["_id"],
            model="openai/gpt-5",
            prompt_tokens=10,
            completion_tokens=5,
            cost_usd=0.5,
            origin="web",
        )
    client.post(
        f"/api/workspaces/{team_ws['_id']}/groups",
        json={"name": "OverviewGroup"},
        headers=owner_headers,
    )
    resp = client.get(f"/api/workspaces/{team_ws['_id']}/overview", headers=owner_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert any(p["name"] == "Overview Project" for p in body["top_projects"])
    assert any(g["name"] == "OverviewGroup" for g in body["groups"])
    assert len(body["usage_30d"]) >= 1


# ===========================================================================
# Audit log filters: limit clamp, before, actor_id (valid + invalid), action.
# ===========================================================================
def test_audit_filters_and_entries(client, flask_core, owner_headers, owner_user, team_ws):
    from app.models.audit_log import AuditLogModel

    with flask_core.app_context():
        AuditLogModel.create(
            action="workspace.test_action",
            admin_id=owner_user["_id"],
            target_type="workspace",
            target_id=team_ws["_id"],
            details={"k": "v"},
        )
    resp = client.get(
        f"/api/workspaces/{team_ws['_id']}/audit"
        f"?limit=1&action=workspace.test_action&actor_id={owner_user['_id']}",
        headers=owner_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["entries"]) == 1
    e = body["entries"][0]
    assert e["action"] == "workspace.test_action"
    assert e["actor"]["email"] == "cov_owner@gmail.com"


def test_audit_invalid_actor_id_400(client, owner_headers, team_ws):
    resp = client.get(
        f"/api/workspaces/{team_ws['_id']}/audit?actor_id=not-a-uuid",
        headers=owner_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid actor_id"


def test_audit_limit_clamped_high(client, owner_headers, team_ws):
    # limit=9999 clamps to 200, still 200 OK.
    resp = client.get(
        f"/api/workspaces/{team_ws['_id']}/audit?limit=9999", headers=owner_headers
    )
    assert resp.status_code == 200


# ===========================================================================
# Credit ledger: list_ledger limit/skip validation.
# ===========================================================================
def test_list_ledger_bad_limit_400(client, owner_headers, team_ws):
    resp = client.get(
        f"/api/workspaces/{team_ws['_id']}/billing/ledger?limit=abc",
        headers=owner_headers,
    )
    assert resp.status_code == 400
    assert "integers" in resp.json()["error"]


def test_add_credits_refund_and_adjustment(client, admin_hdr, team_ws):
    # Minting/adjusting credit is super-admin ONLY (require_admin); a workspace
    # owner can no longer self-fund. adjustment/refund may be signed (that's
    # their purpose), so a negative amount is allowed for those types.
    r1 = client.post(
        f"/api/workspaces/{team_ws['_id']}/billing/credits",
        json={"amount_usd": 30, "type": "adjustment"},
        headers=admin_hdr,
    )
    assert r1.status_code == 201, r1.text
    r2 = client.post(
        f"/api/workspaces/{team_ws['_id']}/billing/credits",
        json={"amount_usd": -5, "type": "refund"},
        headers=admin_hdr,
    )
    assert r2.status_code == 201, r2.text
    assert r2.json()["credits_balance_usd"] == pytest.approx(25.0)


# ===========================================================================
# Groups: name conflict 409 (create + update), too-long name 400,
# unknown user 404 on add member, not-found-group 404 branches.
# ===========================================================================
def test_create_group_duplicate_name_409(client, owner_headers, team_ws):
    client.post(
        f"/api/workspaces/{team_ws['_id']}/groups",
        json={"name": "Dupe"},
        headers=owner_headers,
    )
    resp = client.post(
        f"/api/workspaces/{team_ws['_id']}/groups",
        json={"name": "Dupe"},
        headers=owner_headers,
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "group_name_exists"


def test_create_group_name_too_long_400(client, owner_headers, team_ws):
    resp = client.post(
        f"/api/workspaces/{team_ws['_id']}/groups",
        json={"name": "z" * 81},
        headers=owner_headers,
    )
    assert resp.status_code == 400
    assert "at most 80" in resp.json()["error"]


def test_update_group_duplicate_name_409(client, owner_headers, team_ws):
    client.post(
        f"/api/workspaces/{team_ws['_id']}/groups",
        json={"name": "First"},
        headers=owner_headers,
    )
    second = client.post(
        f"/api/workspaces/{team_ws['_id']}/groups",
        json={"name": "Second"},
        headers=owner_headers,
    ).json()
    resp = client.put(
        f"/api/workspaces/{team_ws['_id']}/groups/{second['_id']}",
        json={"name": "First"},
        headers=owner_headers,
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "group_name_exists"


def test_update_group_empty_name_400(client, owner_headers, team_ws):
    created = client.post(
        f"/api/workspaces/{team_ws['_id']}/groups",
        json={"name": "Trimmable"},
        headers=owner_headers,
    ).json()
    resp = client.put(
        f"/api/workspaces/{team_ws['_id']}/groups/{created['_id']}",
        json={"name": "   "},
        headers=owner_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "name cannot be empty"


def test_update_group_full_fields(client, owner_headers, team_ws):
    """Exercises the color/icon/description update branches. NOTE: by design
    ``GroupModel.update`` persists only ``name``+``description`` and silently
    drops the cosmetic ``color``/``icon`` (documented Phase-4 parity loss in
    models/group.py), so the response color stays at the default."""
    created = client.post(
        f"/api/workspaces/{team_ws['_id']}/groups",
        json={"name": "Styled"},
        headers=owner_headers,
    ).json()
    resp = client.put(
        f"/api/workspaces/{team_ws['_id']}/groups/{created['_id']}",
        json={"color": "#ff0000", "icon": "star", "description": "team desc"},
        headers=owner_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # description persists; color is dropped on the floor -> stays default.
    assert body["description"] == "team desc"
    assert body["color"] == "#5c9aed"


def test_update_group_unknown_404(client, owner_headers, team_ws):
    resp = client.put(
        f"/api/workspaces/{team_ws['_id']}/groups/{uuid.uuid4()}",
        json={"name": "x"},
        headers=owner_headers,
    )
    assert resp.status_code == 404


def test_delete_group_unknown_404(client, owner_headers, team_ws):
    resp = client.delete(
        f"/api/workspaces/{team_ws['_id']}/groups/{uuid.uuid4()}", headers=owner_headers
    )
    assert resp.status_code == 404


def test_add_group_member_group_unknown_404(client, flask_core, owner_headers, team_ws):
    member = _make_user(flask_core, email="g_unkgrp@gmail.com", role="user")
    _add_member(flask_core, wid=team_ws["_id"], user=member, role="editor")
    resp = client.post(
        f"/api/workspaces/{team_ws['_id']}/groups/{uuid.uuid4()}/members",
        json={"user_id": str(member["_id"])},
        headers=owner_headers,
    )
    assert resp.status_code == 404


def test_add_group_member_bad_user_id_400(client, owner_headers, team_ws):
    created = client.post(
        f"/api/workspaces/{team_ws['_id']}/groups",
        json={"name": "BadUid"},
        headers=owner_headers,
    ).json()
    resp = client.post(
        f"/api/workspaces/{team_ws['_id']}/groups/{created['_id']}/members",
        json={"user_id": "not-a-uuid"},
        headers=owner_headers,
    )
    assert resp.status_code == 400
    assert "user_id" in resp.json()["error"]


def test_add_group_member_user_not_found_404(client, owner_headers, team_ws):
    created = client.post(
        f"/api/workspaces/{team_ws['_id']}/groups",
        json={"name": "GhostUser"},
        headers=owner_headers,
    ).json()
    resp = client.post(
        f"/api/workspaces/{team_ws['_id']}/groups/{created['_id']}/members",
        json={"user_id": str(uuid.uuid4())},
        headers=owner_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "User not found"


def test_remove_group_member_group_unknown_404(client, owner_headers, team_ws):
    resp = client.delete(
        f"/api/workspaces/{team_ws['_id']}/groups/{uuid.uuid4()}/members/{uuid.uuid4()}",
        headers=owner_headers,
    )
    assert resp.status_code == 404


# ===========================================================================
# Direct WorkspaceModel facade tests (model/workspace.py uncovered ranges).
# ===========================================================================
def test_model_create_invalid_type_raises(flask_core, owner_user):
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        with pytest.raises(ValueError):
            WorkspaceModel.create(name="Bad", owner_id=owner_user["_id"], type="weird")


def test_model_create_ownerless_team(flask_core):
    """Keycloak org workspaces are created with no owner column (mig 0026)."""
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name="KC Org", owner_id=None, type="team")
    assert ws["type"] == "team"
    assert ws["owner_id"] is None


def test_model_create_default_avatar_initials(flask_core, owner_user):
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name="Acme Beta Co", owner_id=owner_user["_id"])
    assert ws["avatar"]["type"] == "initials"
    assert ws["avatar"]["value"] == "AB"


def test_model_find_by_id_bad_id_none(flask_core):
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        assert WorkspaceModel.find_by_id("not-a-uuid") is None


def test_model_find_by_owner_bad_id_empty(flask_core):
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        assert WorkspaceModel.find_by_owner("not-a-uuid") == []


def test_model_find_by_owner_returns_rows(flask_core, owner_user, team_ws):
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        rows = WorkspaceModel.find_by_owner(owner_user["_id"])
    ids = {r["_id"] for r in rows}
    assert str(team_ws["_id"]) in ids


def test_model_find_by_member_bad_id_empty(flask_core):
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        assert WorkspaceModel.find_by_member("not-a-uuid") == []


def test_model_update_no_clean_fields_false(flask_core, team_ws):
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        # Only keys outside the allowlist -> returns False without committing.
        assert WorkspaceModel.update(team_ws["_id"], {"bogus": 1}) is False


def test_model_update_bad_plan_tier_raises(flask_core, team_ws):
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        with pytest.raises(ValueError):
            WorkspaceModel.update(team_ws["_id"], {"plan_tier": "platinum"})


def test_model_update_bad_ip_allowlist_type_raises(flask_core, team_ws):
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        with pytest.raises(ValueError):
            WorkspaceModel.update(team_ws["_id"], {"ip_allowlist": "x"})


def test_model_update_ip_allowlist_non_string_item_raises(flask_core, team_ws):
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        with pytest.raises(ValueError):
            WorkspaceModel.update(team_ws["_id"], {"ip_allowlist": [123]})


def test_model_update_ip_allowlist_blank_item_raises(flask_core, team_ws):
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        with pytest.raises(ValueError):
            WorkspaceModel.update(team_ws["_id"], {"ip_allowlist": ["   "]})


def test_model_update_settings_replace_and_extras(flask_core, team_ws):
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        changed = WorkspaceModel.update(
            team_ws["_id"],
            {
                "settings": {"only": "this"},
                "plan_tier": "team",
                "domain": "acme.io",
                "credits_balance_usd": 7.5,
                "avatar": {"type": "initials", "value": "QQ"},
                "enforce_2fa": True,
            },
        )
        assert changed is True
        refetched = WorkspaceModel.find_by_id(team_ws["_id"])
    assert refetched["plan_tier"] == "team"
    assert refetched["domain"] == "acme.io"
    assert refetched["credits_balance_usd"] == pytest.approx(7.5)


def test_model_update_unknown_workspace_false(flask_core):
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        assert WorkspaceModel.update(uuid.uuid4(), {"name": "x"}) is False


def test_model_update_settings_subkey(flask_core, team_ws):
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        assert WorkspaceModel.update_settings_subkey(team_ws["_id"], "dlp", {"tier": "strict"}) is True
        refetched = WorkspaceModel.find_by_id(team_ws["_id"])
    assert refetched["settings"]["dlp"] == {"tier": "strict"}


def test_model_update_settings_subkey_bad_id_false(flask_core):
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        assert WorkspaceModel.update_settings_subkey("not-a-uuid", "x", 1) is False


def test_model_update_settings_subkey_unknown_false(flask_core):
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        assert WorkspaceModel.update_settings_subkey(uuid.uuid4(), "x", 1) is False


def test_model_delete_bad_id_false(flask_core):
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        assert WorkspaceModel.delete("not-a-uuid") is False


def test_model_delete_unknown_false(flask_core):
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        assert WorkspaceModel.delete(uuid.uuid4()) is False


def test_model_delete_happy(flask_core, owner_user):
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name="DeleteMe Model", owner_id=owner_user["_id"])
        assert WorkspaceModel.delete(ws["_id"]) is True
        assert WorkspaceModel.find_by_id(ws["_id"]) is None


def test_model_set_owner_unknown_false(flask_core, owner_user):
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        assert WorkspaceModel.set_owner(uuid.uuid4(), owner_user["_id"]) is False


def test_model_set_owner_happy(flask_core, owner_user, team_ws):
    from app.models.workspace import WorkspaceModel

    new_owner = _make_user(flask_core, email="model_newowner@gmail.com", role="user")
    with flask_core.app_context():
        assert WorkspaceModel.set_owner(team_ws["_id"], new_owner["_id"]) is True
        refetched = WorkspaceModel.find_by_id(team_ws["_id"])
    assert refetched["owner_id"] == str(new_owner["_id"])


def test_model_find_by_slug(flask_core, owner_user):
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name="Sluggable Co", owner_id=owner_user["_id"])
        found = WorkspaceModel.find_by_slug(ws["slug"])
    assert found is not None
    assert found["_id"] == ws["_id"]


def test_model_find_by_slug_unknown_none(flask_core):
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        assert WorkspaceModel.find_by_slug("no-such-slug-xyz") is None


def test_model_create_slug_collision_uses_suffix(flask_core, owner_user):
    """Two workspaces with the same name -> second gets a hex-suffixed slug."""
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        a = WorkspaceModel.create(name="Same Name", owner_id=owner_user["_id"])
        b = WorkspaceModel.create(name="Same Name", owner_id=owner_user["_id"])
    assert a["slug"] != b["slug"]
    assert b["slug"].startswith("same-name-")


def test_model_slugify_empty_falls_back(flask_core, owner_user):
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        # All-punctuation name -> _slugify yields 'workspace'.
        ws = WorkspaceModel.create(name="!!!", owner_id=owner_user["_id"])
    assert ws["slug"].startswith("workspace")
