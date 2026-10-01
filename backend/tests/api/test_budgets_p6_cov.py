"""P6 — budgets + alerts coverage.

Exercises three surfaces:

  1. The write path: PATCH ``/api/workspaces/{wid}`` now persists
     ``budget_mtd_usd`` / ``seats_total`` / ``renews_at`` / ``spend_caps``
     (previously silently dropped by the router), with cap normalization.
  2. ``analytics_service.budget()`` math: month-to-date spend, burn-rate,
     linear month-end projection, over-budget + projected-over-budget flags,
     per-user / per-model cap breaches, and $-masking.
  3. The owner billing endpoint carries the ``budget`` block.

Mirrors the sibling cov-test style: TestClient -> flask_ctx app_context ->
real model facades on Postgres -> legacy-shaped JSON. READ-ONLY over
usage_logs (rows are written via the model facade only as fixtures).
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
            email=email, password="TestPassword123!", display_name=display_name, role=role
        )


def _make_workspace(flask_core, *, owner, name="Budget Team", type="team"):
    from app.models.workspace import WorkspaceModel
    from app.models.workspace_member import WorkspaceMemberModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name=name, owner_id=owner["_id"], type=type)
        WorkspaceMemberModel.add(
            ws["_id"], owner["_id"], "owner", invited_by=owner["_id"], status="active"
        )
        return ws


def _seed_usage(flask_core, *, wid, uid, model="openai/gpt-5", cost, when=None,
                project_id=None):
    """Write one usage row via the SOLE-writer facade (test fixture only)."""
    from app.models.usage_log import UsageLog, UsageLogModel
    from app.extensions import db

    with flask_core.app_context():
        row = UsageLogModel.create(
            user_id=uid,
            workspace_id=wid,
            project_id=project_id,
            model=model,
            prompt_tokens=10,
            completion_tokens=5,
            cost_usd=cost,
            origin="web",
        )
        if when is not None:
            # Backdate so the row lands at a known point in the current month.
            obj = db.session.get(UsageLog, row["_id"])
            obj.created_at = when
            db.session.commit()
        return row


def _hdr(user, role="user"):
    return _headers(_mint(user["_id"], role=role))


@pytest.fixture
def owner_user(flask_core):
    return _make_user(flask_core, email="budget_owner@gmail.com", role="manager",
                      display_name="Budget Owner")


@pytest.fixture
def owner_headers(owner_user):
    return _hdr(owner_user, role="manager")


@pytest.fixture
def team_ws(flask_core, owner_user):
    return _make_workspace(flask_core, owner=owner_user, name="Budget Team")


def _early_month():
    """A tz-aware UTC timestamp at the very start of the current month.

    tz-aware (UTC) so it round-trips correctly through the ``timestamptz``
    ``created_at`` column on a non-UTC DB session, and early enough to always
    sit at/after ``month_start`` and before ``now`` (mid-month spend)."""
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, 1, 0, 30, 0, tzinfo=timezone.utc)


# ===========================================================================
# 1. Write path — PATCH now persists the previously-dropped billing fields.
# ===========================================================================
def test_patch_persists_budget_and_caps(client, owner_headers, team_ws):
    resp = client.patch(
        f"/api/workspaces/{team_ws['_id']}",
        json={
            "budget_mtd_usd": 500,
            "seats_total": 12,
            "spend_caps": {"per_user_usd": 50, "per_model_usd": 0},
        },
        headers=owner_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["budget_mtd_usd"] == pytest.approx(500.0)
    assert body["seats_total"] == 12
    # per_model_usd of 0 normalizes to None (a 0 cap blocks everything == off).
    assert body["spend_caps"] == {"per_user_usd": 50.0, "per_model_usd": None}


def test_patch_budget_negative_coerced_to_zero(client, owner_headers, team_ws):
    resp = client.patch(
        f"/api/workspaces/{team_ws['_id']}",
        json={"budget_mtd_usd": -10},
        headers=owner_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["budget_mtd_usd"] == pytest.approx(0.0)


def test_patch_spend_caps_not_object_400(client, owner_headers, team_ws):
    resp = client.patch(
        f"/api/workspaces/{team_ws['_id']}",
        json={"spend_caps": "nope"},
        headers=owner_headers,
    )
    assert resp.status_code == 400
    assert "spend_caps" in resp.json()["error"]


def test_patch_spend_caps_null_disables(client, owner_headers, team_ws):
    resp = client.patch(
        f"/api/workspaces/{team_ws['_id']}",
        json={"spend_caps": None},
        headers=owner_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["spend_caps"] == {"per_user_usd": None, "per_model_usd": None}


# ===========================================================================
# 2. analytics_service.budget() — math + flags + masking.
# ===========================================================================
def test_budget_none_for_bad_workspace(flask_core):
    from app.services import analytics_service

    with flask_core.app_context():
        assert analytics_service.budget("not-a-uuid", cost_visible=True) is None
        assert analytics_service.budget(
            "00000000-0000-0000-0000-000000000000", cost_visible=True
        ) is None


def test_budget_zero_when_no_usage(flask_core, team_ws):
    from app.services import analytics_service

    with flask_core.app_context():
        b = analytics_service.budget(team_ws["_id"], cost_visible=True)
    assert b is not None
    assert b["spend_mtd_usd"] == pytest.approx(0.0)
    assert b["burn_rate_usd_per_day"] == pytest.approx(0.0)
    assert b["projected_month_end_usd"] == pytest.approx(0.0)
    assert b["over_budget"] is False
    assert b["projected_over_budget"] is False
    assert b["budget_used_pct"] is None  # no budget set


def test_budget_burn_rate_and_projection(flask_core, team_ws, owner_user):
    """Spend recorded mid-month -> projection scales to the full month."""
    from app.models.workspace import WorkspaceModel
    from app.services import analytics_service

    with flask_core.app_context():
        WorkspaceModel.update(team_ws["_id"], {"budget_mtd_usd": 100.0})

    _seed_usage(flask_core, wid=team_ws["_id"], uid=owner_user["_id"],
                cost=30.0, when=_early_month())

    with flask_core.app_context():
        b = analytics_service.budget(team_ws["_id"], cost_visible=True)

    assert b["spend_mtd_usd"] == pytest.approx(30.0)
    assert b["budget_mtd_usd"] == pytest.approx(100.0)
    # Burn-rate * full month >= spend so far (linear extrapolation forward).
    assert b["projected_month_end_usd"] >= b["spend_mtd_usd"]
    assert b["burn_rate_usd_per_day"] > 0
    assert b["over_budget"] is False  # 30 < 100
    assert b["budget_used_pct"] == pytest.approx(30.0)


def test_budget_over_budget_flag(flask_core, team_ws, owner_user):
    from app.models.workspace import WorkspaceModel
    from app.services import analytics_service

    with flask_core.app_context():
        WorkspaceModel.update(team_ws["_id"], {"budget_mtd_usd": 10.0})
    _seed_usage(flask_core, wid=team_ws["_id"], uid=owner_user["_id"],
                cost=25.0, when=_early_month())

    with flask_core.app_context():
        b = analytics_service.budget(team_ws["_id"], cost_visible=True)

    assert b["spend_mtd_usd"] == pytest.approx(25.0)
    assert b["over_budget"] is True
    assert b["projected_over_budget"] is True
    assert b["budget_used_pct"] == pytest.approx(250.0)


def test_budget_per_user_cap_breach(flask_core, team_ws, owner_user):
    from app.models.workspace import WorkspaceModel
    from app.services import analytics_service

    heavy = _make_user(flask_core, email="heavy@gmail.com", display_name="Heavy User")
    light = _make_user(flask_core, email="light@gmail.com", display_name="Light User")
    with flask_core.app_context():
        WorkspaceModel.update(
            team_ws["_id"], {"spend_caps": {"per_user_usd": 20}}
        )
    _seed_usage(flask_core, wid=team_ws["_id"], uid=heavy["_id"], cost=35.0,
                when=_early_month())
    _seed_usage(flask_core, wid=team_ws["_id"], uid=light["_id"], cost=5.0,
                when=_early_month())

    with flask_core.app_context():
        b = analytics_service.budget(team_ws["_id"], cost_visible=True)

    breaches = b["caps"]["user_breaches"]
    assert len(breaches) == 1
    assert breaches[0]["id"] == str(heavy["_id"])
    assert breaches[0]["label"] == "Heavy User"
    assert breaches[0]["spend"] == pytest.approx(35.0)
    assert breaches[0]["cap"] == pytest.approx(20.0)
    assert b["caps"]["per_user_usd"] == pytest.approx(20.0)


def test_budget_per_model_cap_breach(flask_core, team_ws, owner_user):
    from app.models.workspace import WorkspaceModel
    from app.services import analytics_service

    with flask_core.app_context():
        WorkspaceModel.update(
            team_ws["_id"], {"spend_caps": {"per_model_usd": 10}}
        )
    _seed_usage(flask_core, wid=team_ws["_id"], uid=owner_user["_id"],
                model="openai/gpt-5", cost=15.0, when=_early_month())
    _seed_usage(flask_core, wid=team_ws["_id"], uid=owner_user["_id"],
                model="google/gemini-3", cost=3.0, when=_early_month())

    with flask_core.app_context():
        b = analytics_service.budget(team_ws["_id"], cost_visible=True)

    breaches = b["caps"]["model_breaches"]
    assert len(breaches) == 1
    assert breaches[0]["id"] == "openai/gpt-5"
    assert breaches[0]["spend"] == pytest.approx(15.0)
    assert b["caps"]["user_breaches"] == []  # per_user cap not set


def test_budget_masked_when_not_cost_visible(flask_core, team_ws, owner_user):
    from app.models.workspace import WorkspaceModel
    from app.services import analytics_service

    with flask_core.app_context():
        WorkspaceModel.update(
            team_ws["_id"],
            {"budget_mtd_usd": 10.0, "spend_caps": {"per_user_usd": 5}},
        )
    _seed_usage(flask_core, wid=team_ws["_id"], uid=owner_user["_id"], cost=20.0,
                when=_early_month())

    with flask_core.app_context():
        b = analytics_service.budget(team_ws["_id"], viewer={"role": "user"})

    assert b["cost_visible"] is False
    assert b["spend_mtd_usd"] is None
    assert b["budget_mtd_usd"] is None
    assert b["burn_rate_usd_per_day"] is None
    assert b["projected_month_end_usd"] is None
    assert b["caps"]["user_breaches"] == []  # breach detail masked
    # Boolean posture flags + non-cost cap config remain (no $ leaked).
    assert b["over_budget"] is True
    assert b["caps"]["per_user_usd"] == pytest.approx(5.0)


def test_budget_admin_viewer_cost_visible(flask_core, team_ws, owner_user):
    from app.services import analytics_service

    _seed_usage(flask_core, wid=team_ws["_id"], uid=owner_user["_id"], cost=7.0,
                when=_early_month())
    with flask_core.app_context():
        b = analytics_service.budget(team_ws["_id"], viewer={"role": "admin"})
    assert b["cost_visible"] is True
    assert b["spend_mtd_usd"] == pytest.approx(7.0)


# ===========================================================================
# 3. Owner billing endpoint carries the budget block.
# ===========================================================================
def test_billing_usage_includes_budget_block(client, flask_core, owner_headers,
                                              owner_user, team_ws):
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        WorkspaceModel.update(team_ws["_id"], {"budget_mtd_usd": 50.0})
    _seed_usage(flask_core, wid=team_ws["_id"], uid=owner_user["_id"], cost=12.0,
                when=_early_month())

    resp = client.get(
        f"/api/workspaces/{team_ws['_id']}/billing/usage"
        "?start=2020-01-01&end=2999-12-31",
        headers=owner_headers,
    )
    assert resp.status_code == 200, resp.text
    budget = resp.json()["budget"]
    assert budget is not None
    assert budget["cost_visible"] is True
    assert budget["budget_mtd_usd"] == pytest.approx(50.0)
    assert budget["spend_mtd_usd"] == pytest.approx(12.0)
    assert "burn_rate_usd_per_day" in budget
    assert "projected_month_end_usd" in budget
    assert budget["over_budget"] is False
