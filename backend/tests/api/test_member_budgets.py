"""Org-only workspaces (mig 0026): member budgets, org-scoped chats + usage.

Covers:
  * ``PUT  /api/admin/users/{uid}/budget``   — per-user monthly budget in ONE org
  * ``POST /api/admin/users/budget/bulk``    — partial success
  * retired ``/admin/users/{id}/credits`` + ``/users/credits/bulk`` -> 410
  * ``GET  /api/admin/users?workspace_id=``  — org members + ``org_budget``
  * spend gate step 1b (``member`` scope, reported as ``scope='user'``)
  * ``GET  /api/conversations`` / ``/search`` / ``/api/agent`` org scoping
  * send/stream 403 on a chat stamped into an org the caller left
  * ``GET  /api/usage/me?workspace_id=`` org filter + member ``my_budget``
"""
import uuid

import pytest


def _h(mint_token, user, role):
    return {
        "Authorization": f"Bearer {mint_token(user['_id'], role=role)}",
        "Content-Type": "application/json",
    }


def _other_org(flask_core, *members):
    """A second team workspace; ``members`` = [(user, role), ...]."""
    from app.models.workspace import WorkspaceModel
    from app.models.workspace_member import WorkspaceMemberModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name="Other Org", owner_id=None, type="team")
        for u, role in members:
            WorkspaceMemberModel.add(ws["_id"], u["_id"], role, status="active")
    return str(ws["_id"])


def _conv(flask_core, user, workspace_id, title="c", kind="chat"):
    from app.models.conversation import ConversationModel

    with flask_core.app_context():
        return ConversationModel.create(
            user_id=user["_id"], config_id="quick:x", title=title,
            workspace_id=workspace_id, kind=kind,
        )


# ---------------------------------------------------------------------------
# Admin member-budget endpoints.
# ---------------------------------------------------------------------------
def test_set_member_budget_and_list(client, mint_token, admin_user, plain_user):
    headers = _h(mint_token, admin_user, "admin")
    wid = plain_user["active_workspace_id"]

    resp = client.put(
        f"/api/admin/users/{plain_user['_id']}/budget",
        json={"workspace_id": wid, "amount_usd": 12.5}, headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["org_budget"] == {
        "amount_usd": 12.5, "spent_mtd_usd": 0.0, "remaining_usd": 12.5,
    }

    listed = client.get(f"/api/admin/users?workspace_id={wid}", headers=headers)
    assert listed.status_code == 200, listed.text
    rows = {u["_id"]: u for u in listed.json()["users"]}
    assert rows[plain_user["_id"]]["org_budget"]["amount_usd"] == 12.5
    assert rows[admin_user["_id"]]["org_budget"]["amount_usd"] is None
    assert "credit_remaining_usd" not in rows[plain_user["_id"]]

    cleared = client.put(
        f"/api/admin/users/{plain_user['_id']}/budget",
        json={"workspace_id": wid, "amount_usd": None}, headers=headers,
    )
    assert cleared.status_code == 200
    assert cleared.json()["org_budget"]["amount_usd"] is None


def test_admin_users_org_filter_excludes_non_members(client, flask_core, mint_token,
                                                     admin_user, plain_user, test_user):
    headers = _h(mint_token, admin_user, "admin")
    other = _other_org(flask_core, (plain_user, "viewer"))
    resp = client.get(f"/api/admin/users?workspace_id={other}", headers=headers)
    assert resp.status_code == 200
    ids = {u["_id"] for u in resp.json()["users"]}
    assert ids == {plain_user["_id"]}

    bad = client.get("/api/admin/users?workspace_id=nope", headers=headers)
    assert bad.status_code == 400


def test_set_member_budget_not_a_member(client, flask_core, mint_token, admin_user,
                                        plain_user, test_user):
    headers = _h(mint_token, admin_user, "admin")
    other = _other_org(flask_core, (plain_user, "viewer"))
    resp = client.put(
        f"/api/admin/users/{test_user['_id']}/budget",
        json={"workspace_id": other, "amount_usd": 5}, headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "not_a_member"


@pytest.mark.parametrize("body", [
    {"amount_usd": 5},
    {"workspace_id": "garbage", "amount_usd": 5},
    {"amount_usd": -1},
    {"amount_usd": "x"},
])
def test_set_member_budget_validation(client, mint_token, admin_user, plain_user, body):
    headers = _h(mint_token, admin_user, "admin")
    if "workspace_id" not in body and body.get("amount_usd") in (-1, "x"):
        body = {**body, "workspace_id": plain_user["active_workspace_id"]}
    resp = client.put(
        f"/api/admin/users/{plain_user['_id']}/budget", json=body, headers=headers,
    )
    assert resp.status_code == 400


def test_set_member_budget_requires_admin(client, mint_token, test_user, plain_user):
    resp = client.put(
        f"/api/admin/users/{plain_user['_id']}/budget",
        json={"workspace_id": plain_user["active_workspace_id"], "amount_usd": 1},
        headers=_h(mint_token, test_user, "manager"),
    )
    assert resp.status_code == 403


def test_bulk_member_budget_partial(client, flask_core, mint_token, admin_user,
                                    plain_user, test_user):
    headers = _h(mint_token, admin_user, "admin")
    other = _other_org(flask_core, (plain_user, "viewer"))
    resp = client.post(
        "/api/admin/users/budget/bulk",
        json={"workspace_id": other, "amount_usd": 3,
              "user_ids": [plain_user["_id"], test_user["_id"], "bad"]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applied"] == 1 and body["failed"] == 2
    by_uid = {r["user_id"]: r for r in body["results"]}
    assert by_uid[plain_user["_id"]]["org_budget"]["amount_usd"] == 3.0
    assert by_uid[test_user["_id"]]["error"] == "not_a_member"


def test_retired_user_credit_endpoints_410(client, mint_token, admin_user, plain_user):
    headers = _h(mint_token, admin_user, "admin")
    one = client.post(
        f"/api/admin/users/{plain_user['_id']}/credits",
        json={"amount_usd": 1}, headers=headers,
    )
    bulk = client.post(
        "/api/admin/users/credits/bulk",
        json={"amount_usd": 1, "user_ids": [plain_user["_id"]]}, headers=headers,
    )
    assert one.status_code == 410 and bulk.status_code == 410


# ---------------------------------------------------------------------------
# Spend gate — member scope (step 1b).
# ---------------------------------------------------------------------------
def test_spend_gate_member_budget_blocks(flask_core, plain_user):
    from app.models.budget_allocation import BudgetAllocationModel, member_scope_id
    from app.models.platform_settings import PlatformSettingsModel
    from app.models.spend_rollup import SpendRollupModel
    from app.services import spend_gate

    wid = plain_user["active_workspace_id"]
    with flask_core.app_context():
        PlatformSettingsModel.set_feature("billing_enforcement", True, None)
        # Fund the wallet so the company step can't be the one that fires.
        from app.models.credit_ledger import CreditLedgerModel
        CreditLedgerModel.add_entry(wid, 100.0, "top_up", "seed", added_by=None)
        sid = member_scope_id(wid, plain_user["_id"])
        BudgetAllocationModel.set_budget("member", sid, 2.0)
        spend_gate.gate(user_id=plain_user["_id"], workspace_id=wid, origin="web")
        SpendRollupModel.bump(
            "member", sid, SpendRollupModel.current_period_month(), 2.5, commit=True,
        )
        with pytest.raises(spend_gate.BudgetExceededError) as exc:
            spend_gate.gate(user_id=plain_user["_id"], workspace_id=wid, origin="web")
        # Another org is untouched by this org's member budget.
        other = str(uuid.uuid4())
        assert member_scope_id(other, plain_user["_id"]) != sid
        PlatformSettingsModel.set_feature("billing_enforcement", False, None)
    assert exc.value.scope == "user"
    assert exc.value.limit == 2.0


def test_record_usage_bumps_member_rollup(flask_core, plain_user):
    from app.models.budget_allocation import member_scope_id
    from app.models.spend_rollup import SpendRollupModel
    from app.services.openrouter_service import OpenRouterService

    wid = plain_user["active_workspace_id"]
    with flask_core.app_context():
        OpenRouterService._record_usage(
            user_id=plain_user["_id"], conversation_id=None, model_id="a/m",
            response_usage={"prompt_tokens": 1, "completion_tokens": 1, "cost": 0.5},
            feature="chat", workspace_id=wid, origin="web",
        )
        spent = SpendRollupModel.get_spent(
            "member", member_scope_id(wid, plain_user["_id"]),
            SpendRollupModel.current_period_month(),
        )
    assert spent == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Conversations are org-scoped.
# ---------------------------------------------------------------------------
def test_conversation_list_is_org_scoped(client, flask_core, mint_token, plain_user):
    headers = _h(mint_token, plain_user, "user")
    home = plain_user["active_workspace_id"]
    other = _other_org(flask_core, (plain_user, "viewer"))
    _conv(flask_core, plain_user, home, title="home chat")
    _conv(flask_core, plain_user, other, title="other chat")

    default = client.get("/api/conversations", headers=headers).json()
    assert [c["title"] for c in default["conversations"]] == ["home chat"]
    assert default["conversations"][0]["workspace_id"] == home

    scoped = client.get(f"/api/conversations?workspace_id={other}", headers=headers).json()
    assert [c["title"] for c in scoped["conversations"]] == ["other chat"]
    assert scoped["total"] == 1

    search = client.get(
        f"/api/conversations/search?q=chat&workspace_id={other}", headers=headers,
    ).json()
    assert [c["title"] for c in search["conversations"]] == ["other chat"]


def test_conversation_list_forbidden_for_non_member(client, flask_core, mint_token,
                                                    plain_user, test_user):
    other = _other_org(flask_core, (test_user, "owner"))
    resp = client.get(
        f"/api/conversations?workspace_id={other}",
        headers=_h(mint_token, plain_user, "user"),
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "workspace_access_denied"

    # Super-admin may read any org.
    from app.models.user import UserModel
    with flask_core.app_context():
        admin = UserModel.create(email="boss@gmail.com", password="TestPassword123!",
                                 display_name="Boss", role="admin")
    ok = client.get(
        f"/api/conversations?workspace_id={other}", headers=_h(mint_token, admin, "admin"),
    )
    assert ok.status_code == 200


def test_conversation_list_empty_without_org(client, flask_core, mint_token):
    from app.models.user import UserModel

    with flask_core.app_context():
        loner = UserModel.create(email="loner@gmail.com", password="TestPassword123!",
                                 display_name="Loner", role="user")
    resp = client.get("/api/conversations", headers=_h(mint_token, loner, "user"))
    assert resp.status_code == 200
    assert resp.json()["conversations"] == [] and resp.json()["total"] == 0


def test_agent_list_is_org_scoped(client, flask_core, mint_token, plain_user):
    from app.models.platform_settings import PlatformSettingsModel

    with flask_core.app_context():
        PlatformSettingsModel.set_feature("agent", True, None)
    other = _other_org(flask_core, (plain_user, "viewer"))
    _conv(flask_core, plain_user, plain_user["active_workspace_id"], "home", kind="agent")
    _conv(flask_core, plain_user, other, "away", kind="agent")
    resp = client.get("/api/agent", headers=_h(mint_token, plain_user, "user"))
    assert resp.status_code == 200, resp.text
    assert [c["title"] for c in resp.json()["conversations"]] == ["home"]


def test_create_stamps_active_workspace(client, mint_token, plain_user):
    resp = client.post(
        "/api/conversations", json={"config_id": "quick:x"},
        headers=_h(mint_token, plain_user, "user"),
    )
    assert resp.status_code == 201
    assert resp.json()["conversation"]["workspace_id"] == plain_user["active_workspace_id"]


def test_send_forbidden_after_leaving_org(client, flask_core, mint_token, plain_user,
                                          test_user):
    from app.models.workspace_member import WorkspaceMemberModel

    other = _other_org(flask_core, (plain_user, "viewer"))
    conv = _conv(flask_core, plain_user, other, "left behind")
    with flask_core.app_context():
        WorkspaceMemberModel.remove(other, plain_user["_id"])
    headers = _h(mint_token, plain_user, "user")
    body = {"conversation_id": conv["_id"], "message": "hi", "config_id": "quick:x"}
    for path in ("/api/chat/send", "/api/chat/stream"):
        resp = client.post(path, json=body, headers=headers)
        assert resp.status_code == 403, (path, resp.text)
        assert resp.json()["code"] == "workspace_access_denied"


# ---------------------------------------------------------------------------
# /usage/me is org-scoped.
# ---------------------------------------------------------------------------
def test_usage_me_filters_by_org(client, flask_core, mint_token, plain_user):
    from app.models.budget_allocation import BudgetAllocationModel, member_scope_id
    from app.models.usage_log import UsageLogModel

    home = plain_user["active_workspace_id"]
    other = _other_org(flask_core, (plain_user, "viewer"))
    with flask_core.app_context():
        UsageLogModel.create(user_id=plain_user["_id"], model="a/m", feature="chat",
                             cost_usd=1.0, prompt_tokens=10, workspace_id=home)
        UsageLogModel.create(user_id=plain_user["_id"], model="a/m", feature="chat",
                             cost_usd=4.0, prompt_tokens=40, workspace_id=other)
        BudgetAllocationModel.set_budget(
            "member", member_scope_id(other, plain_user["_id"]), 9.0,
        )
    headers = _h(mint_token, plain_user, "user")

    home_resp = client.get("/api/usage/me", headers=headers).json()
    assert home_resp["total_tokens"] == 10
    assert home_resp["total_cost"] is None  # viewer never sees $
    assert home_resp["my_budget"] is None

    other_resp = client.get(f"/api/usage/me?workspace_id={other}", headers=headers).json()
    assert other_resp["total_tokens"] == 40
    assert other_resp["my_budget"]["amount_usd"] == 9.0
    assert other_resp["my_budget"]["scope"] == "member"

    denied = client.get(
        f"/api/usage/me?workspace_id={uuid.uuid4()}", headers=headers,
    )
    assert denied.status_code == 403


def test_usage_me_owner_sees_price(client, flask_core, mint_token, test_user):
    from app.models.usage_log import UsageLogModel

    with flask_core.app_context():
        UsageLogModel.create(user_id=test_user["_id"], model="a/m", feature="chat",
                             cost_usd=2.0, prompt_tokens=5,
                             workspace_id=test_user["active_workspace_id"])
    resp = client.get("/api/usage/me", headers=_h(mint_token, test_user, "manager"))
    assert resp.json()["total_cost"] == pytest.approx(2.0)
