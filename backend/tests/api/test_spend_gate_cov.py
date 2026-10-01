"""Coverage tests for the Phase-2 spend gate (pure unit, no HTTP).

Every facade call runs inside ``flask_core.app_context()`` against the isolated
``unichat_test`` Postgres. ``truncate_all`` wipes ``platform_settings`` after
EVERY test, so an autouse fixture re-flips ``billing_enforcement`` ON at the top
of each test; the flag-off tests turn it back OFF explicitly to prove the gate
short-circuits when enforcement is disabled.

Exercises:
  - flag off -> gate passes even with exhausted budgets.
  - no budgets anywhere -> passes (unlimited).
  - user budget breach -> budget_exceeded scope=user (remaining/limit populated).
  - team budget breach (project_id present) -> scope=team; project_id=None skips.
  - company wallet exhaustion -> insufficient_credits scope=company.
  - company MTD ceiling breach -> budget_exceeded scope=company.
  - origin='dlp' / EXEMPT_FEATURES exempt.
  - order: user breach wins over team/company when multiple are exhausted.
"""
import uuid

import pytest

from app.services.spend_gate import (
    BudgetExceededError,
    EXEMPT_FEATURES,
    gate,
)


def _new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Fixtures — enforcement ON by default; helpers for budgets + wallet + rollups.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _enable_enforcement(flask_core):
    """Flip ``billing_enforcement`` ON before each test (truncate_all wiped it)."""
    from app.models.platform_settings import PlatformSettingsModel
    with flask_core.app_context():
        PlatformSettingsModel.set_feature('billing_enforcement', True, None)


def _disable_enforcement(flask_core):
    from app.models.platform_settings import PlatformSettingsModel
    with flask_core.app_context():
        PlatformSettingsModel.set_feature('billing_enforcement', False, None)


def _set_budget(flask_core, scope_type, scope_id, amount):
    from app.models.budget_allocation import BudgetAllocationModel
    with flask_core.app_context():
        BudgetAllocationModel.set_budget(scope_type, scope_id, amount, by=None)


def _bump(flask_core, scope_type, scope_id, period_month, cost):
    from app.models.spend_rollup import SpendRollupModel
    with flask_core.app_context():
        SpendRollupModel.bump(scope_type, scope_id, period_month, cost, commit=True)


def _current_month(flask_core):
    from app.models.spend_rollup import SpendRollupModel
    with flask_core.app_context():
        return SpendRollupModel.current_period_month()


def _lifetime():
    from app.models.spend_rollup import SpendRollupModel
    return SpendRollupModel.LIFETIME


def _make_workspace(flask_core, owner_id):
    """Real workspace row (credit_ledger.workspace_id FKs to workspaces)."""
    from app.models.workspace import WorkspaceModel
    with flask_core.app_context():
        ws = WorkspaceModel.create(name="GateCo", owner_id=owner_id, type="team")
        return ws["_id"]


def _topup(flask_core, wid, amount_usd):
    """Record a prepaid credit top-up (USD -> micro-USD ints)."""
    from app.models.credit_ledger import CreditLedgerModel
    with flask_core.app_context():
        CreditLedgerModel.create(
            wid, delta_micro_usd=int(round(amount_usd * 1_000_000)), kind='topup'
        )


def _set_company_mtd(flask_core, wid, amount):
    from app.models.workspace import WorkspaceModel
    with flask_core.app_context():
        WorkspaceModel.update(wid, {'budget_mtd_usd': amount})


def _set_allowance(flask_core, wid, amount):
    """Set the department-plan monthly INCLUDED allowance (USD or None)."""
    from app.models.workspace import WorkspaceModel
    with flask_core.app_context():
        WorkspaceModel.update(wid, {'monthly_allowance_usd': amount})


def _call_gate(flask_core, **kwargs):
    with flask_core.app_context():
        gate(**kwargs)


# ---------------------------------------------------------------------------
# Flag off — enforcement disabled entirely.
# ---------------------------------------------------------------------------
def test_flag_off_passes_with_exhausted_budget(flask_core, test_user):
    uid = test_user["_id"]
    month = _current_month(flask_core)
    # Exhausted user budget that WOULD breach when enforcement is on.
    _set_budget(flask_core, 'user', uid, 5.0)
    _bump(flask_core, 'user', uid, month, 5.0)

    _disable_enforcement(flask_core)
    # No raise — the gate returns before touching any budget.
    _call_gate(flask_core, user_id=uid, origin='web', feature='chat')


# ---------------------------------------------------------------------------
# No budgets anywhere -> unlimited.
# ---------------------------------------------------------------------------
def test_no_budgets_passes(flask_core, test_user):
    uid = test_user["_id"]
    wid = _make_workspace(flask_core, uid)
    pid = _new_id()
    # Fund the wallet so the company step doesn't trip on a zero wallet.
    _topup(flask_core, wid, 10.0)
    _call_gate(
        flask_core, user_id=uid, workspace_id=wid, project_id=pid,
        origin='web', feature='chat',
    )


# ---------------------------------------------------------------------------
# USER budget breach.
# ---------------------------------------------------------------------------
def test_user_budget_exceeded(flask_core, test_user):
    uid = test_user["_id"]
    month = _current_month(flask_core)
    _set_budget(flask_core, 'user', uid, 5.0)
    _bump(flask_core, 'user', uid, month, 5.0)  # spent == limit -> breach

    with pytest.raises(BudgetExceededError) as exc:
        _call_gate(flask_core, user_id=uid, origin='web', feature='chat')
    err = exc.value
    assert err.code == 'budget_exceeded'
    assert err.scope == 'user'
    assert err.limit == pytest.approx(5.0)
    assert err.remaining == pytest.approx(0.0)


def test_user_under_budget_passes(flask_core, test_user):
    uid = test_user["_id"]
    month = _current_month(flask_core)
    _set_budget(flask_core, 'user', uid, 5.0)
    _bump(flask_core, 'user', uid, month, 4.99)  # under -> ok
    _call_gate(flask_core, user_id=uid, origin='web', feature='chat')


# ---------------------------------------------------------------------------
# TEAM budget breach — only when project_id present.
# ---------------------------------------------------------------------------
def test_team_budget_exceeded_with_project(flask_core, test_user):
    uid = test_user["_id"]
    pid = _new_id()
    month = _current_month(flask_core)
    # User well under budget so the user step passes.
    _set_budget(flask_core, 'user', uid, 100.0)
    _bump(flask_core, 'user', uid, month, 1.0)
    # Team budget exhausted.
    _set_budget(flask_core, 'team', pid, 3.0)
    _bump(flask_core, 'team', pid, month, 3.0)

    with pytest.raises(BudgetExceededError) as exc:
        _call_gate(
            flask_core, user_id=uid, project_id=pid, origin='web', feature='chat',
        )
    err = exc.value
    assert err.code == 'budget_exceeded'
    assert err.scope == 'team'
    assert err.limit == pytest.approx(3.0)


def test_team_budget_skipped_without_project(flask_core, test_user):
    uid = test_user["_id"]
    pid = _new_id()
    month = _current_month(flask_core)
    _set_budget(flask_core, 'user', uid, 100.0)
    # Team budget exhausted but NO project_id passed -> team step skipped.
    _set_budget(flask_core, 'team', pid, 3.0)
    _bump(flask_core, 'team', pid, month, 3.0)

    # project_id=None -> passes (team never consulted).
    _call_gate(flask_core, user_id=uid, project_id=None, origin='web', feature='chat')


# ---------------------------------------------------------------------------
# COMPANY wallet — prepaid credit exhaustion.
# ---------------------------------------------------------------------------
def test_company_wallet_exhausted_insufficient_credits(flask_core, test_user):
    uid = test_user["_id"]
    wid = _make_workspace(flask_core, uid)
    # Funded 10 USD, lifetime company spend 10 USD -> remaining 0 -> breach.
    _topup(flask_core, wid, 10.0)
    _bump(flask_core, 'company', wid, _lifetime(), 10.0)

    with pytest.raises(BudgetExceededError) as exc:
        _call_gate(
            flask_core, user_id=uid, workspace_id=wid, origin='web', feature='chat',
        )
    err = exc.value
    assert err.code == 'insufficient_credits'
    assert err.scope == 'company'
    # Company wallet totals are owner-only — the 402 body must not leak them.
    assert err.remaining is None
    assert err.limit is None


def test_company_wallet_with_headroom_passes(flask_core, test_user):
    uid = test_user["_id"]
    wid = _make_workspace(flask_core, uid)
    # Funded 10 USD, spent 9.99 -> remaining 0.01 > 0 -> ok.
    _topup(flask_core, wid, 10.0)
    _bump(flask_core, 'company', wid, _lifetime(), 9.99)
    _call_gate(
        flask_core, user_id=uid, workspace_id=wid, origin='web', feature='chat',
    )


# ---------------------------------------------------------------------------
# COMPANY MTD ceiling — advisory budget_mtd_usd on the workspace.
# ---------------------------------------------------------------------------
def test_company_mtd_ceiling_exceeded(flask_core, test_user):
    uid = test_user["_id"]
    wid = _make_workspace(flask_core, uid)
    month = _current_month(flask_core)
    # Wallet has plenty so insufficient_credits doesn't trip first.
    _topup(flask_core, wid, 1000.0)
    _set_company_mtd(flask_core, wid, 5.0)
    _bump(flask_core, 'company', wid, month, 5.0)  # MTD spend == ceiling -> breach

    with pytest.raises(BudgetExceededError) as exc:
        _call_gate(
            flask_core, user_id=uid, workspace_id=wid, origin='web', feature='chat',
        )
    err = exc.value
    assert err.code == 'budget_exceeded'
    assert err.scope == 'company'
    # Company budget figures are owner-only — not exposed in the 402 body.
    assert err.limit is None


# ---------------------------------------------------------------------------
# Exemptions — origin='dlp' and EXEMPT_FEATURES skip enforcement.
# ---------------------------------------------------------------------------
def test_origin_dlp_exempt(flask_core, test_user):
    uid = test_user["_id"]
    month = _current_month(flask_core)
    _set_budget(flask_core, 'user', uid, 5.0)
    _bump(flask_core, 'user', uid, month, 5.0)  # would breach for origin='web'
    # origin='dlp' -> exempt, no raise.
    _call_gate(flask_core, user_id=uid, origin='dlp', feature='content_safety')


def test_exempt_feature_skips_enforcement(flask_core, test_user):
    uid = test_user["_id"]
    month = _current_month(flask_core)
    _set_budget(flask_core, 'user', uid, 5.0)
    _bump(flask_core, 'user', uid, month, 5.0)  # would breach
    # A feature in EXEMPT_FEATURES -> exempt regardless of origin.
    exempt_feature = next(iter(EXEMPT_FEATURES))
    _call_gate(flask_core, user_id=uid, origin='web', feature=exempt_feature)


# ---------------------------------------------------------------------------
# Order — user breach wins when every level is exhausted.
# ---------------------------------------------------------------------------
def test_user_breach_wins_over_team_and_company(flask_core, test_user):
    uid = test_user["_id"]
    wid = _make_workspace(flask_core, uid)
    pid = _new_id()
    month = _current_month(flask_core)
    # Exhaust every level.
    _set_budget(flask_core, 'user', uid, 5.0)
    _bump(flask_core, 'user', uid, month, 5.0)
    _set_budget(flask_core, 'team', pid, 5.0)
    _bump(flask_core, 'team', pid, month, 5.0)
    _topup(flask_core, wid, 10.0)
    _bump(flask_core, 'company', wid, _lifetime(), 10.0)

    with pytest.raises(BudgetExceededError) as exc:
        _call_gate(
            flask_core, user_id=uid, workspace_id=wid, project_id=pid,
            origin='web', feature='chat',
        )
    # User checked first -> its breach is the one surfaced.
    assert exc.value.scope == 'user'
    assert exc.value.code == 'budget_exceeded'


# ---------------------------------------------------------------------------
# Department-plan allowance — the profit-redesign cascade. The INCLUDED monthly
# allowance covers spend before the wallet is ever drawn; the wallet hard-blocks
# (402 insufficient_credits) ONLY in overage with a depleted wallet.
# ---------------------------------------------------------------------------
def test_allowance_covers_spend_unfunded_wallet_passes(flask_core, test_user):
    """Within allowance -> wallet is NOT the limiter, even with $0 funded."""
    uid = test_user["_id"]
    wid = _make_workspace(flask_core, uid)
    month = _current_month(flask_core)
    # $50 included allowance, $30 spent this month -> still covered.
    _set_allowance(flask_core, wid, 50.0)
    _bump(flask_core, 'company', wid, month, 30.0)
    # Wallet deliberately UNFUNDED (remaining would be <= 0) -> must NOT block,
    # because the allowance covers the call before the wallet is consulted.
    _call_gate(
        flask_core, user_id=uid, workspace_id=wid, origin='web', feature='chat',
    )


def test_allowance_exceeded_funded_wallet_passes(flask_core, test_user):
    """Overage past the allowance, but the wallet has headroom -> NOT blocked."""
    uid = test_user["_id"]
    wid = _make_workspace(flask_core, uid)
    month = _current_month(flask_core)
    # $50 allowance, $60 spent this month -> $10 of overage draws the wallet.
    _set_allowance(flask_core, wid, 50.0)
    _bump(flask_core, 'company', wid, month, 60.0)
    # Wallet funded $100, lifetime company spend $60 -> remaining $40 > 0 -> ok.
    _topup(flask_core, wid, 100.0)
    _bump(flask_core, 'company', wid, _lifetime(), 60.0)
    _call_gate(
        flask_core, user_id=uid, workspace_id=wid, origin='web', feature='chat',
    )


def test_allowance_exceeded_empty_wallet_blocks(flask_core, test_user):
    """Overage past the allowance AND a depleted wallet -> 402 insufficient_credits."""
    uid = test_user["_id"]
    wid = _make_workspace(flask_core, uid)
    month = _current_month(flask_core)
    # $50 allowance, $60 spent this month -> in overage.
    _set_allowance(flask_core, wid, 50.0)
    _bump(flask_core, 'company', wid, month, 60.0)
    # Wallet funded $10, lifetime company spend $60 -> remaining <= 0 -> breach.
    _topup(flask_core, wid, 10.0)
    _bump(flask_core, 'company', wid, _lifetime(), 60.0)

    with pytest.raises(BudgetExceededError) as exc:
        _call_gate(
            flask_core, user_id=uid, workspace_id=wid, origin='web', feature='chat',
        )
    err = exc.value
    assert err.code == 'insufficient_credits'
    assert err.scope == 'company'
    # Company wallet totals stay owner-only — no leak in the 402 body.
    assert err.remaining is None
    assert err.limit is None


def test_no_allowance_falls_back_to_wallet(flask_core, test_user):
    """No allowance set (legacy/free) -> the wallet is the hard floor as before."""
    uid = test_user["_id"]
    wid = _make_workspace(flask_core, uid)
    # No allowance -> the very first cent draws the wallet; empty wallet blocks.
    _topup(flask_core, wid, 10.0)
    _bump(flask_core, 'company', wid, _lifetime(), 10.0)

    with pytest.raises(BudgetExceededError) as exc:
        _call_gate(
            flask_core, user_id=uid, workspace_id=wid, origin='web', feature='chat',
        )
    assert exc.value.code == 'insufficient_credits'
    assert exc.value.scope == 'company'


def test_zero_allowance_draws_wallet_immediately(flask_core, test_user):
    """``free`` tier allowance=0 -> wallet draws from the first cent (0 is NOT off)."""
    uid = test_user["_id"]
    wid = _make_workspace(flask_core, uid)
    # Explicit 0 allowance (free tier). Empty wallet -> immediate block.
    _set_allowance(flask_core, wid, 0)
    _topup(flask_core, wid, 5.0)
    _bump(flask_core, 'company', wid, _lifetime(), 5.0)

    with pytest.raises(BudgetExceededError) as exc:
        _call_gate(
            flask_core, user_id=uid, workspace_id=wid, origin='web', feature='chat',
        )
    assert exc.value.code == 'insufficient_credits'


def test_none_allowance_funded_wallet_passes_then_blocks(flask_core, test_user):
    """allowance=None (no plan configured) -> the prepaid WALLET is the limiter
    (the original pre-plan behavior). Absent allowance must NOT be read as
    'unlimited' — that would strip cost control from every workspace that never
    opted into a plan. 'Unlimited' is expressed by funding the wallet: a funded
    wallet passes, and once exhausted the same None-allowance company blocks."""
    uid = test_user["_id"]
    wid = _make_workspace(flask_core, uid)
    _set_allowance(flask_core, wid, None)
    # Funded wallet + None allowance -> passes (this is how 'unlimited' is done).
    _topup(flask_core, wid, 100.0)
    _bump(flask_core, 'company', wid, _lifetime(), 10.0)
    _call_gate(
        flask_core, user_id=uid, workspace_id=wid, origin='web', feature='chat',
    )
    # Exhaust that wallet -> None allowance now blocks (wallet is the floor).
    _bump(flask_core, 'company', wid, _lifetime(), 95.0)
    with pytest.raises(BudgetExceededError) as exc:
        _call_gate(
            flask_core, user_id=uid, workspace_id=wid, origin='web', feature='chat',
        )
    assert exc.value.code == 'insufficient_credits'


def test_allowance_within_but_mtd_ceiling_still_blocks(flask_core, test_user):
    """The optional advisory MTD ceiling still fires even inside the allowance."""
    uid = test_user["_id"]
    wid = _make_workspace(flask_core, uid)
    month = _current_month(flask_core)
    # $50 allowance, $5 advisory MTD cap, $5 spent -> covered by allowance but
    # the owner's stricter MTD ceiling still blocks.
    _set_allowance(flask_core, wid, 50.0)
    _set_company_mtd(flask_core, wid, 5.0)
    _bump(flask_core, 'company', wid, month, 5.0)
    _topup(flask_core, wid, 1000.0)  # wallet irrelevant here

    with pytest.raises(BudgetExceededError) as exc:
        _call_gate(
            flask_core, user_id=uid, workspace_id=wid, origin='web', feature='chat',
        )
    assert exc.value.code == 'budget_exceeded'
    assert exc.value.scope == 'company'


def test_flag_off_never_blocks_in_overage(flask_core, test_user):
    """With enforcement OFF, overage + empty wallet must NOT block (report-only)."""
    uid = test_user["_id"]
    wid = _make_workspace(flask_core, uid)
    month = _current_month(flask_core)
    _set_allowance(flask_core, wid, 50.0)
    _bump(flask_core, 'company', wid, month, 60.0)  # overage
    _topup(flask_core, wid, 10.0)
    _bump(flask_core, 'company', wid, _lifetime(), 60.0)  # wallet depleted

    _disable_enforcement(flask_core)
    # Flag off -> gate returns before any allowance/wallet read.
    _call_gate(
        flask_core, user_id=uid, workspace_id=wid, origin='web', feature='chat',
    )


# ---------------------------------------------------------------------------
# 402 body shape — user-safe credit fields appear when remaining/limit present.
# ---------------------------------------------------------------------------
def test_blocked_response_includes_credit_fields(flask_core, test_user):
    """A user breach (remaining/limit populated) -> body carries *_credits too."""
    from app.services.spend_gate import format_budget_blocked_response

    err = BudgetExceededError(
        code='budget_exceeded', scope='user', remaining=2.5, limit=5.0,
    )
    with flask_core.app_context():
        body = format_budget_blocked_response(err)
    assert body['remaining'] == pytest.approx(2.5)
    assert body['limit'] == pytest.approx(5.0)
    # Credits = round(usd * credits_per_usd); default knob 1000 -> $1 == 1000.
    from app.models.platform_settings import PlatformSettingsModel
    with flask_core.app_context():
        rate = PlatformSettingsModel.get_credits_per_usd()
    assert body['remaining_credits'] == round(2.5 * rate)
    assert body['limit_credits'] == round(5.0 * rate)


def test_blocked_response_omits_credit_fields_when_masked(flask_core):
    """Company wallet breach (remaining/limit None) -> no *_credits keys leak."""
    from app.services.spend_gate import format_budget_blocked_response

    err = BudgetExceededError(code='insufficient_credits', scope='company')
    with flask_core.app_context():
        body = format_budget_blocked_response(err)
    assert body['remaining'] is None
    assert body['limit'] is None
    assert 'remaining_credits' not in body
    assert 'limit_credits' not in body
