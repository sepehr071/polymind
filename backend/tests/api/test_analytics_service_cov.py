"""P0 + P1 — unified usage-analytics service coverage.

Exercises the read-only analytics stack end to end at the service layer:

  1. P0 ``UsageLogModel`` time-bucket primitives — gap-filled bucket math
     (day/week/month boundaries), window totals, active-users non-summability,
     and the immediately-preceding equal-length previous window.
  2. P1 ``analytics_service.usage()`` envelope — scope -> children kind
     (holding->companies, company->teams, team->users, user->leaf+by_model),
     period-over-period deltas (incl. zero-previous => pct None), the by_model
     breakdown, and binary $-masking.

Mirrors the sibling cov-test style: real model facades on Postgres inside a
``flask_core.app_context()``, legacy-shaped dicts. READ-ONLY over usage_logs —
rows are written only as fixtures via the SOLE-writer ``UsageLogModel.create``.
"""
from datetime import datetime, timedelta, timezone

import pytest

from tests.api.conftest import _make_user


# ---------------------------------------------------------------------------
# Seeding helpers.
# ---------------------------------------------------------------------------
def _user(flask_core, *, email, role="user", display_name="User"):
    return _make_user(flask_core, email=email, password="TestPassword123!",
                      display_name=display_name, role=role)


def _workspace(flask_core, *, owner, name="Analytics Co", type="team"):
    from app.models.workspace import WorkspaceModel
    from app.models.workspace_member import WorkspaceMemberModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name=name, owner_id=owner["_id"], type=type)
        WorkspaceMemberModel.add(
            ws["_id"], owner["_id"], "owner", invited_by=owner["_id"], status="active"
        )
        return ws


def _project(flask_core, *, wid, owner, name="Team A"):
    from app.models.project import ProjectModel

    with flask_core.app_context():
        return ProjectModel.create(workspace_id=wid, name=name, created_by=owner["_id"])


def _seed_usage(flask_core, *, wid=None, pid=None, uid=None,
                model="openai/gpt-5", cost=1.0, when=None):
    """Write one usage row via the SOLE-writer facade (fixture only), optionally
    backdated to ``when`` so it lands in a known bucket."""
    from app.models.usage_log import UsageLog, UsageLogModel
    from app.extensions import db

    with flask_core.app_context():
        row = UsageLogModel.create(
            user_id=uid,
            workspace_id=wid,
            project_id=pid,
            model=model,
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            cost_usd=cost,
            origin="web",
        )
        if when is not None:
            obj = db.session.get(UsageLog, row["_id"])
            obj.created_at = when
            db.session.commit()
        return row


def _utc(y, m, d, h=12):
    return datetime(y, m, d, h, 0, 0, tzinfo=timezone.utc)


# ===========================================================================
# 1. P0 primitives — bucket math, gap-fill, active-users non-summability.
# ===========================================================================
def test_usage_series_day_gap_fill(flask_core):
    """Two days of usage three days apart -> the empty middle days zero-fill."""
    from app.models.usage_log import UsageLogModel

    user = _user(flask_core, email="series@gmail.com")
    _seed_usage(flask_core, uid=user["_id"], cost=2.0, when=_utc(2026, 5, 1))
    _seed_usage(flask_core, uid=user["_id"], cost=3.0, when=_utc(2026, 5, 4))

    with flask_core.app_context():
        series = UsageLogModel.usage_series(
            "day",
            datetime(2026, 5, 1),
            datetime(2026, 5, 4, 23, 59),
        )

    # 4 daily buckets, May 1..May 4 inclusive.
    assert [r["bucket"] for r in series] == [
        "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04",
    ]
    assert series[0]["cost"] == pytest.approx(2.0)
    assert series[1]["cost"] == pytest.approx(0.0)   # gap-filled
    assert series[2]["cost"] == pytest.approx(0.0)   # gap-filled
    assert series[3]["cost"] == pytest.approx(3.0)
    assert series[0]["calls"] == 1
    assert series[1]["calls"] == 0


def test_usage_series_invalid_granularity_raises(flask_core):
    from app.models.usage_log import UsageLogModel

    with flask_core.app_context():
        with pytest.raises(ValueError):
            UsageLogModel.usage_series(
                "hour", datetime(2026, 5, 1), datetime(2026, 5, 2)
            )


def test_usage_series_month_buckets(flask_core):
    """Spend in two distinct calendar months -> two monthly buckets."""
    from app.models.usage_log import UsageLogModel

    user = _user(flask_core, email="monthly@gmail.com")
    _seed_usage(flask_core, uid=user["_id"], cost=5.0, when=_utc(2026, 4, 15))
    _seed_usage(flask_core, uid=user["_id"], cost=7.0, when=_utc(2026, 5, 20))

    with flask_core.app_context():
        series = UsageLogModel.usage_series(
            "month", datetime(2026, 4, 1), datetime(2026, 5, 31)
        )

    assert [r["bucket"] for r in series] == ["2026-04-01", "2026-05-01"]
    assert series[0]["cost"] == pytest.approx(5.0)
    assert series[1]["cost"] == pytest.approx(7.0)


def test_usage_totals_active_users_distinct_not_summed(flask_core):
    """The same user active across two buckets counts ONCE in the window total
    (active_users is count-distinct, not the sum of per-bucket distincts)."""
    from app.models.usage_log import UsageLogModel

    u1 = _user(flask_core, email="au1@gmail.com")
    u2 = _user(flask_core, email="au2@gmail.com")
    # u1 active on two different days, u2 on one -> 2 distinct users total.
    _seed_usage(flask_core, uid=u1["_id"], cost=1.0, when=_utc(2026, 5, 1))
    _seed_usage(flask_core, uid=u1["_id"], cost=1.0, when=_utc(2026, 5, 2))
    _seed_usage(flask_core, uid=u2["_id"], cost=1.0, when=_utc(2026, 5, 2))

    with flask_core.app_context():
        series = UsageLogModel.usage_series(
            "day", datetime(2026, 5, 1), datetime(2026, 5, 2, 23, 59)
        )
        totals = UsageLogModel.usage_totals(
            datetime(2026, 5, 1), datetime(2026, 5, 2, 23, 59)
        )

    # Per-bucket distincts sum to 3 (1 + 2) but the window distinct is 2.
    assert sum(r["active_users"] for r in series) == 3
    assert totals["active_users"] == 2
    assert totals["calls"] == 3
    assert totals["cost"] == pytest.approx(3.0)


def test_usage_previous_totals_preceding_window(flask_core):
    """Previous-window totals cover [from - (to-from), from)."""
    from app.models.usage_log import UsageLogModel

    user = _user(flask_core, email="prev@gmail.com")
    # current window May 10..May 20 (~10d) -> previous window ~Apr 30..May 10.
    _seed_usage(flask_core, uid=user["_id"], cost=4.0, when=_utc(2026, 5, 15))
    _seed_usage(flask_core, uid=user["_id"], cost=9.0, when=_utc(2026, 5, 5))

    with flask_core.app_context():
        previous = UsageLogModel.usage_previous_totals(
            datetime(2026, 5, 10), datetime(2026, 5, 20)
        )

    # Only the May 5 row falls in the preceding window.
    assert previous["cost"] == pytest.approx(9.0)
    assert previous["calls"] == 1


def test_usage_series_bad_scope_id_empty(flask_core):
    """An unparsable scope id yields an empty series (no rows can match)."""
    from app.models.usage_log import UsageLogModel

    with flask_core.app_context():
        series = UsageLogModel.usage_series(
            "day", datetime(2026, 5, 1), datetime(2026, 5, 2),
            workspace_id="not-a-uuid",
        )
        totals = UsageLogModel.usage_totals(
            datetime(2026, 5, 1), datetime(2026, 5, 2), workspace_id="not-a-uuid"
        )
    assert series == []
    assert totals == {"cost": 0.0, "calls": 0, "tokens": 0, "active_users": 0}


# ===========================================================================
# 2. P1 envelope — scope -> children kind + by_model + deltas + masking.
# ===========================================================================
@pytest.fixture
def holding(flask_core):
    """A small holding: one company, one team (project), two users with usage."""
    owner = _user(flask_core, email="ceo@gmail.com", role="admin",
                  display_name="CEO")
    ws = _workspace(flask_core, owner=owner, name="Globex")
    proj = _project(flask_core, wid=ws["_id"], owner=owner, name="Platform Team")
    alice = _user(flask_core, email="alice@gmail.com", display_name="Alice")
    bob = _user(flask_core, email="bob@gmail.com", display_name="Bob")

    when = datetime.now(timezone.utc) - timedelta(days=2)
    _seed_usage(flask_core, wid=ws["_id"], pid=proj["_id"], uid=alice["_id"],
                model="openai/gpt-5", cost=10.0, when=when)
    _seed_usage(flask_core, wid=ws["_id"], pid=proj["_id"], uid=bob["_id"],
                model="google/gemini-3", cost=4.0, when=when)
    return {"owner": owner, "ws": ws, "proj": proj, "alice": alice, "bob": bob}


_ADMIN_VIEWER = {"role": "admin"}


def test_usage_invalid_scope_raises(flask_core):
    from app.services import analytics_service

    with flask_core.app_context():
        with pytest.raises(ValueError):
            analytics_service.usage("galaxy", None, "day", None, None,
                                    viewer=_ADMIN_VIEWER)


def test_usage_invalid_granularity_raises(flask_core):
    from app.services import analytics_service

    with flask_core.app_context():
        with pytest.raises(ValueError):
            analytics_service.usage("holding", None, "hour", None, None,
                                    viewer=_ADMIN_VIEWER)


def test_usage_holding_children_are_companies(flask_core, holding):
    from app.services import analytics_service

    with flask_core.app_context():
        env = analytics_service.usage("holding", None, "day", None, None,
                                      viewer=_ADMIN_VIEWER)

    assert env["scope"] == "holding"
    assert env["scope_id"] is None
    assert env["cost_visible"] is True
    children = env["breakdown"]["children"]
    assert children is not None
    assert any(c["id"] == str(holding["ws"]["_id"]) for c in children)
    company = next(c for c in children if c["id"] == str(holding["ws"]["_id"]))
    assert company["label"] == "Globex"
    assert company["cost"] == pytest.approx(14.0)   # 10 + 4
    assert company["active_users"] == 2
    assert isinstance(company["spark"], list)
    # Holding-level totals roll the whole window.
    assert env["totals"]["cost"] == pytest.approx(14.0)
    assert env["totals"]["active_users"] == 2


def test_usage_company_children_are_teams(flask_core, holding):
    from app.services import analytics_service

    with flask_core.app_context():
        env = analytics_service.usage(
            "company", holding["ws"]["_id"], "day", None, None,
            viewer=_ADMIN_VIEWER,
        )

    assert env["scope"] == "company"
    assert env["scope_id"] == str(holding["ws"]["_id"])
    children = env["breakdown"]["children"]
    assert children is not None
    team = next(c for c in children if c["id"] == str(holding["proj"]["_id"]))
    assert team["label"] == "Platform Team"
    assert team["cost"] == pytest.approx(14.0)


def test_usage_team_children_are_users(flask_core, holding):
    from app.services import analytics_service

    with flask_core.app_context():
        env = analytics_service.usage(
            "team", holding["proj"]["_id"], "day", None, None,
            viewer=_ADMIN_VIEWER,
        )

    assert env["scope"] == "team"
    children = env["breakdown"]["children"]
    ids = {c["id"] for c in children}
    assert {str(holding["alice"]["_id"]), str(holding["bob"]["_id"])} <= ids
    alice = next(c for c in children if c["id"] == str(holding["alice"]["_id"]))
    assert alice["label"] == "Alice"
    assert alice["cost"] == pytest.approx(10.0)


def test_usage_user_is_leaf_with_by_model(flask_core, holding):
    from app.services import analytics_service

    with flask_core.app_context():
        env = analytics_service.usage(
            "user", holding["alice"]["_id"], "day", None, None,
            viewer=_ADMIN_VIEWER,
        )

    assert env["scope"] == "user"
    # Leaf: no children, but by_model carried even without breakdown=model.
    assert env["breakdown"]["children"] is None
    by_model = env["breakdown"]["by_model"]
    assert by_model is not None
    assert by_model[0]["key"] == "openai/gpt-5"
    assert by_model[0]["cost"] == pytest.approx(10.0)


def test_usage_breakdown_model_flag(flask_core, holding):
    """``breakdown=model`` adds the per-model split at a non-leaf scope."""
    from app.services import analytics_service

    with flask_core.app_context():
        without = analytics_service.usage(
            "holding", None, "day", None, None, viewer=_ADMIN_VIEWER,
        )
        with_model = analytics_service.usage(
            "holding", None, "day", None, None, breakdown="model",
            viewer=_ADMIN_VIEWER,
        )

    assert without["breakdown"]["by_model"] is None
    models = {m["key"] for m in with_model["breakdown"]["by_model"]}
    assert {"openai/gpt-5", "google/gemini-3"} <= models


def test_usage_deltas_zero_previous_pct_none(flask_core, holding):
    """With no spend in the preceding window, pct growth is undefined (None)
    while abs delta equals the current total."""
    from app.services import analytics_service

    with flask_core.app_context():
        env = analytics_service.usage("holding", None, "day", None, None,
                                      viewer=_ADMIN_VIEWER)

    assert env["previous"]["cost"] == pytest.approx(0.0)
    assert env["deltas"]["cost"]["pct"] is None
    assert env["deltas"]["cost"]["abs"] == pytest.approx(14.0)


def test_usage_masked_when_not_cost_visible(flask_core, holding):
    """A non-admin viewer => cost_visible False => every cost field nulled,
    but volume metrics (calls/tokens/active_users) stay visible."""
    from app.services import analytics_service

    with flask_core.app_context():
        env = analytics_service.usage("holding", None, "day", None, None,
                                      viewer={"role": "user"})

    assert env["cost_visible"] is False
    assert env["totals"]["cost"] is None
    assert env["previous"]["cost"] is None
    assert env["deltas"]["cost"] == {"abs": None, "pct": None}
    assert all(pt["cost"] is None for pt in env["series"])
    # Volume metrics never masked.
    assert env["totals"]["calls"] == 2
    assert env["totals"]["active_users"] == 2
    company = env["breakdown"]["children"][0]
    assert company["cost"] is None
    assert company["calls"] >= 1


def test_usage_window_passthrough(flask_core, holding):
    """Explicit from/to ISO dates land verbatim in the window block."""
    from app.services import analytics_service

    with flask_core.app_context():
        env = analytics_service.usage(
            "holding", None, "week", "2026-05-01", "2026-05-31",
            viewer=_ADMIN_VIEWER,
        )

    assert env["granularity"] == "week"
    assert env["window"] == {"from": "2026-05-01", "to": "2026-05-31"}


# ===========================================================================
# 3. Regression — the three HIGH bugs caught in review.
# ===========================================================================
def test_usage_today_not_dropped(flask_core):
    """A bare ``YYYY-MM-DD`` ``to`` of today must INCLUDE rows logged earlier
    today (end-of-day upper bound). Before the fix a date-only ``to`` parsed to
    midnight and ``created_at <= :to`` silently dropped the whole current day."""
    from app.services import analytics_service

    user = _user(flask_core, email="today@gmail.com")
    now = datetime.now(timezone.utc)
    _seed_usage(flask_core, uid=user["_id"], cost=6.0, when=now)
    today = now.strftime("%Y-%m-%d")

    with flask_core.app_context():
        env = analytics_service.usage(
            "user", user["_id"], "day", today, today, viewer=_ADMIN_VIEWER,
        )

    assert env["totals"]["cost"] == pytest.approx(6.0)
    assert env["totals"]["calls"] == 1


@pytest.mark.parametrize("scope", ["company", "team", "user"])
def test_usage_nonholding_bad_scope_id_raises(flask_core, scope):
    """A non-holding scope with a missing/unparsable ``scope_id`` must raise
    (→ 400), NOT silently fall back to holding-wide totals under an entity
    label (the masking/identity leak caught in review)."""
    from app.services import analytics_service

    with flask_core.app_context():
        with pytest.raises(ValueError):
            analytics_service.usage(scope, "not-a-uuid", "day", None, None,
                                    viewer=_ADMIN_VIEWER)
        with pytest.raises(ValueError):
            analytics_service.usage(scope, None, "day", None, None,
                                    viewer=_ADMIN_VIEWER)


def test_usage_masked_children_delta_pct_withheld(flask_core, holding):
    """``children[].delta_pct`` is derived from cost growth; a masked viewer
    must get ``None`` (not the spend trend) while an admin still sees the real
    percentage. Seeds the previous window so the admin delta is non-null."""
    from app.services import analytics_service

    _seed_usage(
        flask_core, wid=holding["ws"]["_id"], pid=holding["proj"]["_id"],
        uid=holding["alice"]["_id"], cost=5.0,
        when=datetime.now(timezone.utc) - timedelta(days=35),
    )
    wid = str(holding["ws"]["_id"])

    with flask_core.app_context():
        admin_env = analytics_service.usage("holding", None, "day", None, None,
                                            viewer=_ADMIN_VIEWER)
        masked_env = analytics_service.usage("holding", None, "day", None, None,
                                             viewer={"role": "user"})

    admin_co = next(c for c in admin_env["breakdown"]["children"] if c["id"] == wid)
    masked_co = next(c for c in masked_env["breakdown"]["children"] if c["id"] == wid)
    assert admin_co["delta_pct"] is not None        # admin sees the real trend
    assert masked_co["cost"] is None
    assert masked_co["delta_pct"] is None           # masked: trend withheld
