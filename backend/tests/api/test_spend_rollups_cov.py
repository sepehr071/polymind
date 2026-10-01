"""Coverage tests for the Phase-1 hierarchical-billing schema + rollups.

Exercises (all inside ``flask_core.app_context()`` against the isolated
``unichat_test`` Postgres):

  (a) ``BudgetAllocationModel`` facade CRUD round-trip — set/get_active/get_any/
      upsert-on-set/clear; get_active skips disabled rows.
  (b) ``SpendRollupModel.bump`` create-then-increment; ``get_spent`` 0.0 absent.
  (c) ``OpenRouterService._record_usage`` writes a usage_logs row AND all four
      rollups (company month, company lifetime, team month, user month).
  (d) Scope gating: project_id=None -> NO team row; workspace_id=None -> NO
      company rows but user row still bumped.
  (e) A bump with last month's period_month leaves the current month untouched
      (MTD reset semantics).
"""
import uuid
from datetime import date

import pytest

from app.services.openrouter_service import OpenRouterService


# ---------------------------------------------------------------------------
# Helpers — read rollup rows directly via the ORM.
# ---------------------------------------------------------------------------
def _rollup_row(flask_core, scope_type, scope_id, period_month):
    from app.api.core import db
    from app.models.spend_rollup import SpendRollup
    from sqlalchemy import select
    with flask_core.app_context():
        return db.session.execute(
            select(SpendRollup).where(
                SpendRollup.scope_type == scope_type,
                SpendRollup.scope_id == uuid.UUID(str(scope_id)),
                SpendRollup.period_month == period_month,
            )
        ).scalar_one_or_none()


def _new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# (a) BudgetAllocationModel facade CRUD.
# ---------------------------------------------------------------------------
def test_budget_allocation_set_get_upsert_clear(flask_core):
    from app.models.budget_allocation import BudgetAllocationModel as B

    wid = _new_id()
    with flask_core.app_context():
        created = B.set_budget('company', wid, 100.0, by=None)
        assert created['scope_type'] == 'company'
        assert created['scope_id'] == wid
        assert created['period'] == 'mtd'
        assert created['amount_usd'] == pytest.approx(100.0)
        assert created['enabled'] is True

        # get_active returns it.
        active = B.get_active('company', wid)
        assert active is not None
        assert active['amount_usd'] == pytest.approx(100.0)

        # Upsert on the same (scope_type, scope_id, period) — updates in place.
        updated = B.set_budget('company', wid, 250.0, by=None)
        assert updated['_id'] == created['_id']  # same row id (UPSERT, not insert)
        assert updated['amount_usd'] == pytest.approx(250.0)

        # Only one row exists.
        from app.api.core import db
        from app.models.budget_allocation import BudgetAllocation
        from sqlalchemy import select, func
        count = db.session.execute(
            select(func.count()).select_from(BudgetAllocation).where(
                BudgetAllocation.scope_type == 'company',
                BudgetAllocation.scope_id == uuid.UUID(wid),
            )
        ).scalar_one()
        assert count == 1

        # clear deletes it.
        assert B.clear_budget('company', wid) is True
        assert B.get_active('company', wid) is None
        # Clearing a missing row -> False.
        assert B.clear_budget('company', wid) is False


def test_budget_allocation_get_active_skips_disabled(flask_core):
    from app.models.budget_allocation import BudgetAllocationModel as B

    uid = _new_id()
    with flask_core.app_context():
        B.set_budget('user', uid, 50.0, enabled=False, by=None)
        # Disabled -> get_active is None, get_any still returns it.
        assert B.get_active('user', uid) is None
        any_row = B.get_any('user', uid)
        assert any_row is not None
        assert any_row['enabled'] is False
        assert any_row['amount_usd'] == pytest.approx(50.0)


def test_budget_allocation_holding_scope_null_id(flask_core):
    from app.models.budget_allocation import BudgetAllocationModel as B

    with flask_core.app_context():
        created = B.set_budget('holding', None, 9999.0, by=None)
        assert created['scope_type'] == 'holding'
        assert created['scope_id'] is None
        active = B.get_active('holding', None)
        assert active is not None
        assert active['amount_usd'] == pytest.approx(9999.0)
        # Upsert again — COALESCE(NULL) collides, so it updates not duplicates.
        B.set_budget('holding', None, 12345.0, by=None)
        active2 = B.get_active('holding', None)
        assert active2['amount_usd'] == pytest.approx(12345.0)
        assert active2['_id'] == active['_id']
        assert B.clear_budget('holding', None) is True


def test_budget_allocation_list_for_scope_ids(flask_core):
    from app.models.budget_allocation import BudgetAllocationModel as B

    t1, t2, t3 = _new_id(), _new_id(), _new_id()
    with flask_core.app_context():
        B.set_budget('team', t1, 10.0, by=None)
        B.set_budget('team', t2, 20.0, enabled=False, by=None)  # disabled
        B.set_budget('team', t3, 30.0, by=None)
        out = B.list_for_scope_ids('team', [t1, t2, t3])
        # Only enabled rows surface.
        assert set(out.keys()) == {t1, t3}
        assert out[t1]['amount_usd'] == pytest.approx(10.0)
        assert out[t3]['amount_usd'] == pytest.approx(30.0)
        # Empty input -> empty dict.
        assert B.list_for_scope_ids('team', []) == {}


def test_budget_allocation_invalid_scope_and_period(flask_core):
    from app.models.budget_allocation import BudgetAllocationModel as B

    with flask_core.app_context():
        with pytest.raises(ValueError):
            B.set_budget('bogus', _new_id(), 1.0)
        with pytest.raises(ValueError):
            B.set_budget('company', None, 1.0)  # non-holding requires scope_id
        with pytest.raises(ValueError):
            B.set_budget('company', _new_id(), 1.0, period='weekly')


# ---------------------------------------------------------------------------
# (b) SpendRollupModel.bump create-then-increment + get_spent.
# ---------------------------------------------------------------------------
def test_spend_rollup_bump_creates_then_increments(flask_core):
    from app.models.spend_rollup import SpendRollupModel as S

    uid = _new_id()
    month = S.current_period_month()
    with flask_core.app_context():
        # Absent -> 0.0
        assert S.get_spent('user', uid, month) == 0.0
        # First bump creates the row.
        S.bump('user', uid, month, 1.5, calls=1, commit=True)
        assert S.get_spent('user', uid, month) == pytest.approx(1.5)
        # Second bump accumulates.
        S.bump('user', uid, month, 2.25, calls=2, commit=True)
        assert S.get_spent('user', uid, month) == pytest.approx(3.75)

    row = _rollup_row(flask_core, 'user', uid, month)
    assert row is not None
    assert int(row.calls) == 3


def test_spend_rollup_bump_invalid_scope(flask_core):
    from app.models.spend_rollup import SpendRollupModel as S

    with flask_core.app_context():
        with pytest.raises(ValueError):
            S.bump('holding', _new_id(), S.current_period_month(), 1.0, commit=True)


# ---------------------------------------------------------------------------
# (c) _record_usage writes usage_logs + all four rollups.
# ---------------------------------------------------------------------------
def _count_usage_rows(flask_core):
    from app.api.core import db
    from app.models.usage_log import UsageLog
    with flask_core.app_context():
        return db.session.query(UsageLog).count()


def _make_workspace_project(flask_core, owner_id):
    """Create a real workspace + project (usage_logs has FKs to both)."""
    from app.models.workspace import WorkspaceModel
    from app.models.project import ProjectModel
    with flask_core.app_context():
        ws = WorkspaceModel.create(name="RollupCo", owner_id=owner_id, type="team")
        proj = ProjectModel.create(
            workspace_id=ws["_id"], name="RollupTeam", created_by=owner_id
        )
        return ws["_id"], proj["_id"]


def test_record_usage_bumps_all_four_rollups(flask_core, test_user):
    from app.models.spend_rollup import SpendRollupModel as S

    uid = test_user["_id"]
    wid, pid = _make_workspace_project(flask_core, uid)
    month = S.current_period_month()
    usage = {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.5}

    before = _count_usage_rows(flask_core)
    with flask_core.app_context():
        OpenRouterService._record_usage(
            uid, None, "openai/gpt-4o", usage, "chat",
            workspace_id=wid, project_id=pid, origin="web",
        )
    assert _count_usage_rows(flask_core) == before + 1

    with flask_core.app_context():
        assert S.get_spent('company', wid, month) == pytest.approx(0.5)
        assert S.get_spent('company', wid, S.LIFETIME) == pytest.approx(0.5)
        assert S.get_spent('team', pid, month) == pytest.approx(0.5)
        assert S.get_spent('user', uid, month) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# (d) Scope gating — missing project_id / workspace_id.
# ---------------------------------------------------------------------------
def test_record_usage_no_project_skips_team_rollup(flask_core, test_user):
    from app.models.spend_rollup import SpendRollupModel as S

    uid = test_user["_id"]
    wid, _pid = _make_workspace_project(flask_core, uid)
    month = S.current_period_month()
    usage = {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.3}
    with flask_core.app_context():
        OpenRouterService._record_usage(
            uid, None, "openai/gpt-4o", usage, "chat",
            workspace_id=wid, project_id=None, origin="web",
        )
    with flask_core.app_context():
        assert S.get_spent('company', wid, month) == pytest.approx(0.3)
        assert S.get_spent('company', wid, S.LIFETIME) == pytest.approx(0.3)
        assert S.get_spent('user', uid, month) == pytest.approx(0.3)
        # No team row — there's no project to attribute it to.
        from app.api.core import db
        from app.models.spend_rollup import SpendRollup
        from sqlalchemy import select, func
        team_count = db.session.execute(
            select(func.count()).select_from(SpendRollup).where(
                SpendRollup.scope_type == 'team'
            )
        ).scalar_one()
        assert team_count == 0


def test_record_usage_no_workspace_skips_company_rollups(flask_core, test_user):
    from app.models.spend_rollup import SpendRollupModel as S

    uid = test_user["_id"]
    month = S.current_period_month()
    usage = {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.7}
    with flask_core.app_context():
        OpenRouterService._record_usage(
            uid, None, "openai/gpt-4o", usage, "chat",
            workspace_id=None, project_id=None, origin="web",
        )
    with flask_core.app_context():
        # User rollup still bumped.
        assert S.get_spent('user', uid, month) == pytest.approx(0.7)
        # No company rows at all.
        from app.api.core import db
        from app.models.spend_rollup import SpendRollup
        from sqlalchemy import select, func
        company_count = db.session.execute(
            select(func.count()).select_from(SpendRollup).where(
                SpendRollup.scope_type == 'company'
            )
        ).scalar_one()
        assert company_count == 0


# ---------------------------------------------------------------------------
# (e) MTD reset — a bump in a prior month does not touch the current month.
# ---------------------------------------------------------------------------
def test_spend_rollup_prior_month_isolated_from_current(flask_core):
    from app.models.spend_rollup import SpendRollupModel as S

    uid = _new_id()
    current = S.current_period_month()
    # Pick a definitely-different month bucket.
    if current.month == 1:
        last = date(current.year - 1, 12, 1)
    else:
        last = date(current.year, current.month - 1, 1)

    with flask_core.app_context():
        S.bump('user', uid, last, 5.0, commit=True)
        # Last month has the spend; current month is untouched.
        assert S.get_spent('user', uid, last) == pytest.approx(5.0)
        assert S.get_spent('user', uid, current) == 0.0
        # Bumping current is isolated from last.
        S.bump('user', uid, current, 2.0, commit=True)
        assert S.get_spent('user', uid, current) == pytest.approx(2.0)
        assert S.get_spent('user', uid, last) == pytest.approx(5.0)
