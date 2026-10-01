"""Spend gate — pre-flight budget/credit enforcement at every LLM chokepoint.

Phase 2 of the hierarchical-billing build. Mirrors ``app/services/dlp_gate.py``
in shape: a single ``gate(...)`` helper raises a typed exception that the
FastAPI error handler maps to an HTTP body, plus a ``format_*_response`` shaper.

The gate consults the incrementally-maintained ``spend_rollups`` counters
(NEVER ``SUM(usage_logs)`` — that's the whole point of the rollups) against the
configurable ``budget_allocations`` ceilings and the prepaid credit wallet. An
absent / disabled / NULL-amount budget at any level means "unlimited" there.

Enforcement is gated behind the ``billing_enforcement`` platform feature flag
(default OFF): when off, the gate returns immediately and nothing is enforced.
``origin='dlp'`` and the title-generation feature are exempt so internal/system
calls never get budget-blocked.

Check order (cheapest, most-specific first; the first breach wins):
  1. USER budget   — user MTD rollup vs the user ``budget_allocations`` ceiling.
  1b. MEMBER budget — user-in-this-org MTD rollup vs the ``member`` ceiling.
  2. TEAM budget   — team MTD rollup vs the team ceiling (only when project_id).
  3. COMPANY       — wallet remaining (materialized ``credits_balance_usd`` −
     lifetime rollup) <= 0 raises ``insufficient_credits``; then an optional MTD
     ceiling (``workspace.budget_mtd_usd``) vs the company MTD rollup.
"""
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Internal/system origins that must never be budget-blocked.
EXEMPT_ORIGINS = {'dlp'}

# Feature tags exempt from enforcement: DLP smart-scan classification
# (``content_safety``) and chat auto-title generation (``auto_title``) are
# system-initiated calls the end user never asked for — blocking them on a
# budget breach would silently break unrelated UX.
EXEMPT_FEATURES = {'content_safety', 'auto_title'}


class BudgetExceededError(Exception):
    """Raised when a pre-flight spend check fails (budget cap or credit wallet).

    Mapped to HTTP 402 in ``app/api/errors.py``.
    """

    def __init__(
        self,
        code: str,
        scope: str,
        *,
        remaining: Optional[float] = None,
        limit: Optional[float] = None,
        message: str = "",
    ) -> None:
        super().__init__(message or code)
        self.code = code  # 'budget_exceeded' | 'insufficient_credits'
        self.scope = scope  # 'user' | 'team' | 'company' | 'holding'
        self.remaining = remaining  # remaining headroom in USD (or None)
        self.limit = limit  # the ceiling that was hit in USD (or None)


def gate(
    *,
    user_id: Any,
    workspace_id: Any = None,
    project_id: Any = None,
    origin: str = 'web',
    feature: Optional[str] = None,
) -> None:
    """Pre-flight budget/credit enforcement. Raises ``BudgetExceededError`` on breach.

    Returns ``None`` when the call is allowed (flag off, exempt, or under every
    configured ceiling). Performs at most a handful of indexed point-reads
    against ``budget_allocations`` / ``spend_rollups`` / ``workspaces`` — it
    NEVER aggregates (no ``SUM(usage_logs)``, no ``SUM(credit_ledger)``).
    """
    # Flag off -> enforcement disabled entirely.
    from app.models.platform_settings import PlatformSettingsModel
    if not PlatformSettingsModel.get_features().get('billing_enforcement', False):
        return

    # System/internal calls are exempt.
    if origin in EXEMPT_ORIGINS or (feature is not None and feature in EXEMPT_FEATURES):
        return

    from app.models.budget_allocation import BudgetAllocationModel
    from app.models.spend_rollup import SpendRollupModel

    uid = str(user_id) if user_id is not None else None
    wid = str(workspace_id) if workspace_id is not None else None
    pid = str(project_id) if project_id is not None else None
    current_month = SpendRollupModel.current_period_month()

    # (1) USER budget — most specific. Spent this month vs the user's ceiling.
    if uid:
        user_budget = BudgetAllocationModel.get_active('user', uid)
        if user_budget is not None and user_budget.get('amount_usd') is not None:
            limit = float(user_budget['amount_usd'])
            spent = SpendRollupModel.get_spent('user', uid, current_month)
            if spent >= limit:
                raise BudgetExceededError(
                    code='budget_exceeded',
                    scope='user',
                    remaining=max(0.0, limit - spent),
                    limit=limit,
                    message='Monthly budget exceeded',
                )

    # (1b) MEMBER budget — this user's monthly cap inside this org. Reported
    #      as scope='user' (it is the caller's own limit).
    if uid and wid:
        from app.models.budget_allocation import member_scope_id
        member_sid = member_scope_id(wid, uid)
        member_budget = (
            BudgetAllocationModel.get_active('member', member_sid)
            if member_sid is not None else None
        )
        if member_budget is not None and member_budget.get('amount_usd') is not None:
            limit = float(member_budget['amount_usd'])
            spent = SpendRollupModel.get_spent('member', member_sid, current_month)
            if spent >= limit:
                raise BudgetExceededError(
                    code='budget_exceeded',
                    scope='user',
                    remaining=max(0.0, limit - spent),
                    limit=limit,
                    message='Monthly budget exceeded',
                )

    # (2) TEAM budget — only meaningful when the call is project-scoped.
    if pid:
        team_budget = BudgetAllocationModel.get_active('team', pid)
        if team_budget is not None and team_budget.get('amount_usd') is not None:
            limit = float(team_budget['amount_usd'])
            spent = SpendRollupModel.get_spent('team', pid, current_month)
            if spent >= limit:
                raise BudgetExceededError(
                    code='budget_exceeded',
                    scope='team',
                    remaining=max(0.0, limit - spent),
                    limit=limit,
                    message='Monthly budget exceeded',
                )

    # (3) COMPANY — department-plan allowance first, then the prepaid wallet
    #     (only on overage), then an optional advisory MTD ceiling.
    if wid:
        # One workspace point-read serves the allowance + the optional MTD
        # ceiling below.
        from app.models.workspace import WorkspaceModel
        from app.models.credit_ledger import CreditLedgerModel
        ws = WorkspaceModel.find_by_id(wid)

        # Monthly INCLUDED allowance (USD), hoisted to top level by find_by_id.
        # A POSITIVE allowance that this month's company spend is still WITHIN
        # covers the call, so we DO NOT draw / block on the wallet. On overage
        # (spend past a positive allowance) OR when NO allowance is configured
        # (None / 0), the prepaid wallet is the hard floor — the original
        # pre-plan behavior.
        #
        # IMPORTANT: an absent allowance must NOT be read as "unlimited" — that
        # would strip cost control from every workspace that never opted into a
        # plan (and from brand-new ones). "Unlimited" is expressed by funding
        # the wallet, not by leaving the allowance unset. An enterprise plan is
        # just a high custom allowance number.
        allowance = (ws or {}).get('monthly_allowance_usd')
        company_mtd = SpendRollupModel.get_spent('company', wid, current_month)
        allowance_covers = (
            allowance is not None
            and float(allowance) > 0
            and company_mtd <= float(allowance)
        )

        if not allowance_covers:
            # Overage (or no allowance) -> the prepaid wallet is the hard floor.
            # Wallet funded = Σ credit_ledger (the reconciled source of truth). We
            # do NOT substitute the materialized ``credits_balance_usd`` column:
            # workspace.py documents it as "lifetime top-ups that never
            # decrements", which is not the signed ledger sum the wallet check
            # needs (a refund/adjustment would diverge, under-funding the gate).
            # ``sum_credits`` is a small index-supported aggregate over the
            # append-only manual-topup table — fine on this dormant path (gate is
            # a no-op unless billing_enforcement is on).
            funded = float(CreditLedgerModel.sum_credits(wid) or 0.0)
            lifetime_spent = SpendRollupModel.get_spent(
                'company', wid, SpendRollupModel.LIFETIME
            )
            remaining = funded - lifetime_spent
            if remaining <= 0:
                # remaining/limit deliberately omitted: the 402 body reaches ANY
                # member who triggers a call, but company wallet totals (both $
                # AND credits) are owner-only data ($-masking policy). The modal
                # hides null rows. User/team breaches DO populate remaining/limit
                # -> those expose the user-safe credit form (see formatter).
                raise BudgetExceededError(
                    code='insufficient_credits',
                    scope='company',
                    message='Insufficient prepaid credits',
                )

        # Optional company MTD ceiling (advisory budget hoisted to top level by
        # WorkspaceModel.find_by_id). 0 / absent == no ceiling == unlimited.
        # Independent of the allowance — an owner can cap monthly spend below the
        # plan allowance. Reuses the company_mtd point-read above.
        budget_mtd = float((ws or {}).get('budget_mtd_usd') or 0.0)
        if budget_mtd > 0 and company_mtd >= budget_mtd:
            # Company budget figures are owner-only — see wallet note above.
            raise BudgetExceededError(
                code='budget_exceeded',
                scope='company',
                message='Monthly budget exceeded',
            )


def format_budget_blocked_response(err: BudgetExceededError) -> dict[str, Any]:
    """Shape the JSON body returned to clients on a budget / credit block.

    The raw ``remaining``/``limit`` USD figures stay in the body for the
    owner-facing surfaces, but they are only populated for user/team breaches
    (company wallet totals are null-masked — owner-only $). When present, the
    body ALSO carries the normalized ``remaining_credits``/``limit_credits``
    (Polymind Credits) so the budget-exceeded modal can show a number to NORMAL
    employees without leaking the dollar price.
    """
    body: dict[str, Any] = {
        'error': str(err),
        'code': err.code,
        'scope': err.scope,
        'remaining': err.remaining,
        'limit': err.limit,
    }
    if err.remaining is not None or err.limit is not None:
        from app.utils.credits import to_credits
        if err.remaining is not None:
            body['remaining_credits'] = to_credits(err.remaining)
        if err.limit is not None:
            body['limit_credits'] = to_credits(err.limit)
    return body
