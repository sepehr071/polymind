"""Company cascade reporting + own-budget surfaces (hierarchical billing).

Exercises the read-only reporting added on top of the Phase 1-3 budget engine:

  1. ``GET /workspaces/{wid}/billing/usage`` carries a ``cascade`` block:
     enforcement flag + company remaining wallet + company MTD ceiling + a
     per-team (project) row joining each team's ``budget_allocations`` ceiling
     against its current-month ``spend_rollups`` counter (NEVER SUM(usage_logs)).
  2. ``analytics_service.budget()`` carries an ``enforced`` block listing
     team/user budget breaches (``spend >= budget``) — masked when the viewer
     can't see cost.
  3. ``GET /usage/me`` carries ``my_budget`` (the caller's own ceiling + MTD
     spend) — ALWAYS cost-visible (it is the user's own limit).

Mirrors the sibling cov-test style: TestClient -> flask_ctx app_context -> real
model facades on the isolated ``unichat_test`` Postgres -> legacy-shaped JSON.
The budget engine writes nothing here — rollups/budgets are seeded via facades.

NOTE: ``truncate_all`` wipes ``platform_settings`` after EVERY test, so the
enforcement flag is set per-test inside an app_context where it matters.
"""
from datetime import datetime, timezone

import pytest

from tests.api.conftest import _headers, _mint


# ---------------------------------------------------------------------------
# Seeding helpers.
# ---------------------------------------------------------------------------
def _make_user(flask_core, *, email, role="user", display_name="User"):
    from app.models.user import UserModel

    with flask_core.app_context():
        return UserModel.create(
            email=email, password="TestPassword123!", display_name=display_name,
            role=role,
        )


def _make_workspace(flask_core, *, owner, name="Cascade Team", type="team"):
    from app.models.workspace import WorkspaceModel
    from app.models.workspace_member import WorkspaceMemberModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name=name, owner_id=owner["_id"], type=type)
        WorkspaceMemberModel.add(
            ws["_id"], owner["_id"], "owner", invited_by=owner["_id"], status="active"
        )
        return ws


def _make_project(flask_core, *, wid, owner, name="Team A"):
    from app.models.project import ProjectModel

    with flask_core.app_context():
        return ProjectModel.create(
            workspace_id=wid, name=name, created_by=owner["_id"]
        )


def _add_member(flask_core, *, wid, user, role="editor"):
    from app.models.workspace_member import WorkspaceMemberModel

    with flask_core.app_context():
        WorkspaceMemberModel.add(wid, user["_id"], role, status="active")


def _set_budget(flask_core, scope_type, scope_id, amount, *, enabled=True):
    from app.models.budget_allocation import BudgetAllocationModel

    with flask_core.app_context():
        return BudgetAllocationModel.set_budget(
            scope_type, scope_id, amount, by=None, enabled=enabled
        )


def _bump_current_month(flask_core, scope_type, scope_id, cost):
    from app.models.spend_rollup import SpendRollupModel

    with flask_core.app_context():
        SpendRollupModel.bump(
            scope_type, scope_id, SpendRollupModel.current_period_month(),
            cost, commit=True,
        )


def _set_enforcement(flask_core, value):
    from app.models.platform_settings import PlatformSettingsModel

    with flask_core.app_context():
        PlatformSettingsModel.set_feature("billing_enforcement", value, None)


def _topup(flask_core, wid, amount):
    from app.models.credit_ledger import CreditLedgerModel

    with flask_core.app_context():
        CreditLedgerModel.add_entry(wid, amount, "topup", note="seed", added_by=None)


def _hdr(user, role="user"):
    return _headers(_mint(user["_id"], role=role))


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------
@pytest.fixture
def owner_user(flask_core):
    return _make_user(flask_core, email="cascade_owner@gmail.com", role="manager",
                      display_name="Cascade Owner")


@pytest.fixture
def owner_headers(owner_user):
    return _hdr(owner_user, role="manager")


@pytest.fixture
def team_ws(flask_core, owner_user):
    return _make_workspace(flask_core, owner=owner_user, name="Cascade Team")


@pytest.fixture
def project_a(flask_core, team_ws, owner_user):
    return _make_project(flask_core, wid=team_ws["_id"], owner=owner_user,
                         name="Team A")


# ===========================================================================
# 1. billing_usage cascade block.
# ===========================================================================
def test_cascade_block_shape_with_team_budget_and_rollup(
    client, flask_core, owner_headers, team_ws, project_a
):
    """A seeded team budget + current-month rollup surfaces in the cascade."""
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        WorkspaceModel.update(team_ws["_id"], {"budget_mtd_usd": 200.0})
    _topup(flask_core, team_ws["_id"], 500.0)
    _set_budget(flask_core, "team", project_a["_id"], 50.0)
    _bump_current_month(flask_core, "team", project_a["_id"], 12.5)

    resp = client.get(
        f"/api/workspaces/{team_ws['_id']}/billing/usage", headers=owner_headers
    )
    assert resp.status_code == 200, resp.text
    cascade = resp.json()["cascade"]

    assert set(cascade) == {
        "enforcement", "company_remaining", "company_budget_mtd", "teams"
    }
    assert cascade["company_budget_mtd"] == pytest.approx(200.0)
    # remaining = lifetime topups (500) - lifetime company rollup (0 here).
    assert cascade["company_remaining"] == pytest.approx(500.0)

    teams = cascade["teams"]
    assert len(teams) == 1
    row = teams[0]
    assert row["project_id"] == str(project_a["_id"])
    assert row["name"] == "Team A"
    assert row["budget"] == pytest.approx(50.0)
    assert row["spend"] == pytest.approx(12.5)
    assert row["remaining"] == pytest.approx(37.5)


def test_cascade_team_without_budget_has_null_budget_and_remaining(
    client, flask_core, owner_headers, team_ws, project_a
):
    """A team with NO budget row reports budget/remaining null but real spend."""
    _bump_current_month(flask_core, "team", project_a["_id"], 4.0)

    resp = client.get(
        f"/api/workspaces/{team_ws['_id']}/billing/usage", headers=owner_headers
    )
    assert resp.status_code == 200, resp.text
    teams = resp.json()["cascade"]["teams"]
    assert len(teams) == 1
    row = teams[0]
    assert row["budget"] is None
    assert row["remaining"] is None
    assert row["spend"] == pytest.approx(4.0)


def test_cascade_company_budget_null_when_unset(
    client, flask_core, owner_headers, team_ws
):
    resp = client.get(
        f"/api/workspaces/{team_ws['_id']}/billing/usage", headers=owner_headers
    )
    assert resp.status_code == 200, resp.text
    cascade = resp.json()["cascade"]
    assert cascade["company_budget_mtd"] is None
    assert cascade["teams"] == []  # no projects yet


def test_cascade_enforcement_flag_false_then_true(
    client, flask_core, owner_headers, team_ws
):
    _set_enforcement(flask_core, False)
    resp = client.get(
        f"/api/workspaces/{team_ws['_id']}/billing/usage", headers=owner_headers
    )
    assert resp.json()["cascade"]["enforcement"] is False

    _set_enforcement(flask_core, True)
    resp = client.get(
        f"/api/workspaces/{team_ws['_id']}/billing/usage", headers=owner_headers
    )
    assert resp.json()["cascade"]["enforcement"] is True


# ===========================================================================
# 2. analytics_service.budget() enforced block.
# ===========================================================================
def test_enforced_block_present_and_empty_by_default(flask_core, team_ws):
    from app.services import analytics_service

    with flask_core.app_context():
        b = analytics_service.budget(team_ws["_id"], cost_visible=True)
    enforced = b["enforced"]
    assert set(enforced) == {"enabled", "team_breaches", "user_breaches"}
    assert enforced["team_breaches"] == []
    assert enforced["user_breaches"] == []


def test_enforced_team_and_user_breaches_when_spend_ge_budget(
    flask_core, team_ws, project_a, owner_user
):
    """A team + a member user both over their enabled budget surface as breaches."""
    from app.services import analytics_service

    member = _make_user(flask_core, email="member@gmail.com", display_name="Member")
    _add_member(flask_core, wid=team_ws["_id"], user=member)

    # Team: budget 20, spend 25 -> breach (spend >= budget).
    _set_budget(flask_core, "team", project_a["_id"], 20.0)
    _bump_current_month(flask_core, "team", project_a["_id"], 25.0)
    # User: budget 10, spend exactly 10 -> breach (boundary, >=).
    _set_budget(flask_core, "user", member["_id"], 10.0)
    _bump_current_month(flask_core, "user", member["_id"], 10.0)
    # Owner has a budget but is UNDER it -> no breach.
    _set_budget(flask_core, "user", owner_user["_id"], 100.0)
    _bump_current_month(flask_core, "user", owner_user["_id"], 5.0)

    with flask_core.app_context():
        _set_enforcement(flask_core, True)
        b = analytics_service.budget(team_ws["_id"], cost_visible=True)

    enforced = b["enforced"]
    assert enforced["enabled"] is True

    assert len(enforced["team_breaches"]) == 1
    tb = enforced["team_breaches"][0]
    assert tb["project_id"] == str(project_a["_id"])
    assert tb["budget"] == pytest.approx(20.0)
    assert tb["spend"] == pytest.approx(25.0)

    assert len(enforced["user_breaches"]) == 1
    ub = enforced["user_breaches"][0]
    assert ub["user_id"] == str(member["_id"])
    assert ub["budget"] == pytest.approx(10.0)
    assert ub["spend"] == pytest.approx(10.0)


def test_enforced_breaches_masked_for_non_cost_viewer(
    flask_core, team_ws, project_a
):
    """$ fields masked to None for a non-cost viewer; the breach row still lists."""
    from app.services import analytics_service

    _set_budget(flask_core, "team", project_a["_id"], 5.0)
    _bump_current_month(flask_core, "team", project_a["_id"], 9.0)

    with flask_core.app_context():
        b = analytics_service.budget(team_ws["_id"], viewer={"role": "user"})

    assert b["cost_visible"] is False
    breaches = b["enforced"]["team_breaches"]
    assert len(breaches) == 1
    assert breaches[0]["project_id"] == str(project_a["_id"])
    assert breaches[0]["budget"] is None
    assert breaches[0]["spend"] is None


def test_enforced_no_breach_when_under_budget(flask_core, team_ws, project_a):
    from app.services import analytics_service

    _set_budget(flask_core, "team", project_a["_id"], 50.0)
    _bump_current_month(flask_core, "team", project_a["_id"], 10.0)

    with flask_core.app_context():
        b = analytics_service.budget(team_ws["_id"], cost_visible=True)
    assert b["enforced"]["team_breaches"] == []


def test_enforced_disabled_budget_not_a_breach(flask_core, team_ws, project_a):
    """A DISABLED team budget is unlimited -> never a breach even when over."""
    from app.services import analytics_service

    _set_budget(flask_core, "team", project_a["_id"], 5.0, enabled=False)
    _bump_current_month(flask_core, "team", project_a["_id"], 99.0)

    with flask_core.app_context():
        b = analytics_service.budget(team_ws["_id"], cost_visible=True)
    assert b["enforced"]["team_breaches"] == []


# ===========================================================================
# 3. /usage/me my_budget.
# ===========================================================================
def test_usage_me_my_budget_null_then_populated(client, flask_core):
    user = _make_user(flask_core, email="budgetme@gmail.com", display_name="Me")
    headers = _hdr(user)

    # No budget row yet -> null.
    resp = client.get("/api/usage/me", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["my_budget"] is None

    # Set a budget + this-month spend.
    _set_budget(flask_core, "user", user["_id"], 40.0)
    _bump_current_month(flask_core, "user", user["_id"], 15.0)

    resp = client.get("/api/usage/me", headers=headers)
    assert resp.status_code == 200, resp.text
    mb = resp.json()["my_budget"]
    assert mb is not None
    assert mb["amount_usd"] == pytest.approx(40.0)
    assert mb["enabled"] is True
    assert mb["spend_mtd"] == pytest.approx(15.0)
    assert mb["remaining"] == pytest.approx(25.0)


def test_usage_me_my_budget_disabled_row_still_visible(client, flask_core):
    """get_any returns disabled rows too — own budget is always shown."""
    user = _make_user(flask_core, email="disabledbudget@gmail.com",
                      display_name="Dis")
    headers = _hdr(user)

    _set_budget(flask_core, "user", user["_id"], 30.0, enabled=False)
    _bump_current_month(flask_core, "user", user["_id"], 8.0)

    resp = client.get("/api/usage/me", headers=headers)
    assert resp.status_code == 200, resp.text
    mb = resp.json()["my_budget"]
    assert mb is not None
    assert mb["enabled"] is False
    assert mb["amount_usd"] == pytest.approx(30.0)
    assert mb["spend_mtd"] == pytest.approx(8.0)
    assert mb["remaining"] == pytest.approx(22.0)


def test_usage_me_my_budget_visible_for_super_admin_branch(client, flask_core):
    """The super-admin branch ALSO carries my_budget (own limit, no masking)."""
    admin = _make_user(flask_core, email="admincascade@gmail.com", role="admin",
                       display_name="Admin")
    headers = _hdr(admin, role="admin")

    _set_budget(flask_core, "user", admin["_id"], 100.0)
    _bump_current_month(flask_core, "user", admin["_id"], 20.0)

    resp = client.get("/api/usage/me", headers=headers)
    assert resp.status_code == 200, resp.text
    mb = resp.json()["my_budget"]
    assert mb is not None
    assert mb["amount_usd"] == pytest.approx(100.0)
    assert mb["spend_mtd"] == pytest.approx(20.0)
    assert mb["remaining"] == pytest.approx(80.0)
