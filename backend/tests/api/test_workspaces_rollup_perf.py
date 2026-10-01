"""Perf-MED regression tests: workspace credits + overview now read the
``spend_rollups`` counters (point-reads) instead of unbounded ``SUM(usage_logs)``.

Locks three contracts:
  1. ``WorkspaceModel.credits_remaining_usd`` = Σledger − company LIFETIME rollup
     (seeded rollup row is the spend half; usage_logs are NOT summed).
  2. A brand-new company with no rollup row => remaining == ledger sum
     (``get_spent`` returns 0.0 for a missing sentinel — genuine zero spend).
  3. ``GET /{wid}/overview`` keeps a byte-identical response key set, its
     ``billing.spend_mtd_usd`` tracks the company current-month rollup, and the
     ``stats.messages_mtd`` / ``stats.active_projects`` values survive the merge
     into the single ``overview_usage_bundle`` grouped query.

Mirrors the sibling cov-file seeding style (TestClient -> flask_ctx -> real
facades on Postgres -> legacy-shaped JSON).
"""
import uuid

import pytest

from tests.api.conftest import _headers, _mint


# ---------------------------------------------------------------------------
# Seeding helpers + fixtures (mirror tests/api/test_workspaces_router_cov.py).
# ---------------------------------------------------------------------------
def _make_user(flask_core, *, email, role="manager", display_name="Owner"):
    from app.models.user import UserModel

    with flask_core.app_context():
        return UserModel.create(
            email=email, password="TestPassword123!", display_name=display_name, role=role
        )


def _make_workspace(flask_core, *, owner, name="Rollup Team", type="team"):
    from app.models.workspace import WorkspaceModel
    from app.models.workspace_member import WorkspaceMemberModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name=name, owner_id=owner["_id"], type=type)
        WorkspaceMemberModel.add(
            ws["_id"], owner["_id"], "owner", invited_by=owner["_id"], status="active"
        )
        return ws


@pytest.fixture
def owner_user(flask_core):
    return _make_user(flask_core, email="rollup_owner@gmail.com", role="manager")


@pytest.fixture
def owner_headers(owner_user):
    return _headers(_mint(owner_user["_id"], role="manager"))


@pytest.fixture
def team_ws(flask_core, owner_user):
    return _make_workspace(flask_core, owner=owner_user, name="Rollup Team")


def _seed_topup(flask_core, wid, usd):
    from app.models.credit_ledger import CreditLedgerModel

    with flask_core.app_context():
        CreditLedgerModel.create(
            workspace_id=wid,
            delta_micro_usd=int(round(usd * 1_000_000)),
            kind="topup",
        )


def _seed_lifetime_rollup(flask_core, wid, usd):
    from app.models.spend_rollup import SpendRollupModel

    with flask_core.app_context():
        SpendRollupModel.bump(
            "company", wid, SpendRollupModel.LIFETIME, cost_usd=usd, calls=1, commit=True
        )


def _seed_month_rollup(flask_core, wid, usd):
    from app.models.spend_rollup import SpendRollupModel

    with flask_core.app_context():
        SpendRollupModel.bump(
            "company",
            wid,
            SpendRollupModel.current_period_month(),
            cost_usd=usd,
            calls=1,
            commit=True,
        )


# ===========================================================================
# 1) credits_remaining_usd reads the LIFETIME rollup, NOT a usage SUM.
# ===========================================================================
def test_credits_remaining_reads_lifetime_rollup(flask_core, team_ws):
    """Σledger ($10) − LIFETIME rollup ($3) = $7, regardless of usage_logs."""
    from app.models.usage_log import UsageLogModel
    from app.models.workspace import WorkspaceModel

    _seed_topup(flask_core, team_ws["_id"], 10.0)
    _seed_lifetime_rollup(flask_core, team_ws["_id"], 3.0)

    # A usage_logs row that is DELIBERATELY larger than the rollup — proves the
    # method does not sum usage_logs (else remaining would be 10 - 9 = 1).
    with flask_core.app_context():
        UsageLogModel.create(
            workspace_id=team_ws["_id"],
            model="openai/gpt-5",
            cost_usd=9.0,
            origin="web",
        )
        remaining = WorkspaceModel.credits_remaining_usd(team_ws["_id"])

    assert remaining == pytest.approx(7.0)


# ===========================================================================
# 2) New company, no rollup row => remaining == ledger sum (get_spent -> 0.0).
# ===========================================================================
def test_credits_remaining_new_company_no_rollup(flask_core, team_ws):
    from app.models.workspace import WorkspaceModel

    _seed_topup(flask_core, team_ws["_id"], 25.0)
    with flask_core.app_context():
        remaining = WorkspaceModel.credits_remaining_usd(team_ws["_id"])
    assert remaining == pytest.approx(25.0)


def test_credits_remaining_no_ledger_no_rollup_is_zero(flask_core, team_ws):
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        remaining = WorkspaceModel.credits_remaining_usd(team_ws["_id"])
    assert remaining == pytest.approx(0.0)


# ===========================================================================
# 3a) overview response key set is byte-identical (frozen contract).
# ===========================================================================
_TOP_KEYS = {
    "workspace",
    "billing",
    "top_projects",
    "recent_activity",
    "groups",
    "usage_30d",
    "stats",
}
_BILLING_KEYS = {
    "plan_tier",
    "credits_remaining_usd",
    "credits_balance_usd",
    "spend_mtd_usd",
    "seats_used",
    "seats_total",
    "budget_mtd_usd",
    "renews_at",
    "sso_enforced",
    "scim_enabled",
    "domain",
}
_STATS_KEYS = {"messages_mtd", "active_projects", "members_active"}


def test_overview_response_keys_unchanged(client, owner_headers, team_ws):
    resp = client.get(f"/api/workspaces/{team_ws['_id']}/overview", headers=owner_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == _TOP_KEYS
    assert set(body["billing"].keys()) == _BILLING_KEYS
    assert set(body["stats"].keys()) == _STATS_KEYS


# ===========================================================================
# 3b) spend_mtd_usd reflects the company current-month rollup point-read.
# ===========================================================================
def test_overview_spend_mtd_matches_month_rollup(client, flask_core, owner_headers, team_ws):
    from app.models.usage_log import UsageLogModel

    _seed_month_rollup(flask_core, team_ws["_id"], 4.25)
    # Larger usage_logs row proves spend_mtd is the rollup, not the usage SUM.
    with flask_core.app_context():
        UsageLogModel.create(
            workspace_id=team_ws["_id"],
            model="openai/gpt-5",
            cost_usd=11.0,
            origin="web",
        )
    resp = client.get(f"/api/workspaces/{team_ws['_id']}/overview", headers=owner_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["billing"]["spend_mtd_usd"] == pytest.approx(4.25)


# ===========================================================================
# 3c) messages_mtd + active_projects survive the overview_usage_bundle merge.
# ===========================================================================
def test_overview_messages_mtd_and_active_projects_survive_merge(
    client, flask_core, owner_user, owner_headers, team_ws
):
    from app.models.project import ProjectModel
    from app.models.usage_log import UsageLogModel

    with flask_core.app_context():
        proj = ProjectModel.create(
            workspace_id=team_ws["_id"], name="Bundle Project", created_by=owner_user["_id"]
        )
        for _ in range(3):
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

    resp = client.get(f"/api/workspaces/{team_ws['_id']}/overview", headers=owner_headers)
    assert resp.status_code == 200, resp.text
    stats = resp.json()["stats"]
    # 3 usage rows this month -> messages_mtd == 3 (folded count partial).
    assert stats["messages_mtd"] == 3
    # 1 non-archived project -> projects-table count, NOT a usage distinct count.
    assert stats["active_projects"] == 1


def test_overview_bundle_matches_seeded_rows(flask_core, owner_user, team_ws):
    """The folded ``overview_usage_bundle`` aggregates seeded rows value-for-value.

    The two methods this bundle replaced (``aggregate_daily`` +
    ``total_messages_this_month``) were removed in the 2026-06-15 cleanup, so the
    contract is locked directly: seed N rows dated today and assert the bundle's
    single in-window ``daily`` bucket carries the exact cost/token/message totals
    those rows imply, and ``messages_mtd`` equals the row count. (Folded counts
    are also exercised end-to-end via the route in
    ``test_overview_messages_mtd_and_active_projects_survive_merge``.)"""
    from datetime import datetime

    from app.models.usage_log import UsageLogModel

    n = 2
    cost_each = 0.3
    prompt_each, completion_each = 8, 4
    with flask_core.app_context():
        for _ in range(n):
            UsageLogModel.create(
                user_id=owner_user["_id"],
                workspace_id=team_ws["_id"],
                model="openai/gpt-5",
                prompt_tokens=prompt_each,
                completion_tokens=completion_each,
                cost_usd=cost_each,
                origin="web",
            )
        bundle = UsageLogModel.overview_usage_bundle(team_ws["_id"], days=30)

    # All rows are dated "now" (UTC) -> a single daily bucket for today.
    today = datetime.utcnow().strftime("%Y-%m-%d")
    assert bundle["daily"] == [
        {
            "date": today,
            "cost_usd": pytest.approx(cost_each * n),
            "total_tokens": (prompt_each + completion_each) * n,
            "messages": n,
        }
    ]
    # Every seeded row is in the current month -> messages_mtd counts them all.
    assert bundle["messages_mtd"] == n


def test_overview_bundle_bad_id_empty():
    from app.models.usage_log import UsageLogModel

    assert UsageLogModel.overview_usage_bundle("not-a-uuid") == {"daily": [], "messages_mtd": 0}
    assert UsageLogModel.overview_usage_bundle(uuid.uuid4()) == {"daily": [], "messages_mtd": 0}
