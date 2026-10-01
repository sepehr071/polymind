"""Holding-admin routes — the platform-operator powers absorbed by super-admin.

The platform-admin principal was eliminated; the super-admin (``role=='admin'``)
now owns the holding pool, feature flags, and company-credit transfers. Every
operation is gated by ``require_admin`` and writes an ``audit_logs`` row with
``category='holding'`` (actor = the super-admin's ``users.id``).

Mounted at ``/api/admin`` alongside ``admin.py``; the six paths here
(``/features``, ``/holding/*``, ``/companies/{wid}/credits``) do not collide with
``admin.py``'s routes.
"""
from __future__ import annotations

import logging
import math

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.deps import flask_ctx, require_admin
from app.models.audit_log import AuditLogModel
from app.models.credit_ledger import CreditLedgerModel
from app.models.platform_settings import PlatformSettingsModel, DEFAULT_FEATURES
from app.models.workspace import WorkspaceModel
from app.services import holding_analytics
from app.utils.helpers import serialize_doc

logger = logging.getLogger(__name__)

# Router-level dependency: every request runs inside the contextvar-scoped session.
router = APIRouter(dependencies=[Depends(flask_ctx)])


async def _json_body(request: Request) -> dict:
    """Read JSON body, tolerating empty/garbage like get_json(silent=True)."""
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def _client_ip(request: Request) -> str | None:
    """Audit-trail client IP. Uses the proxy connection peer (``request.client``)
    as the source of truth, NOT the client-supplied ``X-Forwarded-For`` — the
    leftmost XFF token is attacker-forgeable and the origin nginx does not
    rewrite it, so trusting it would let a privileged actor spoof the IP on
    money-path audit rows."""
    return (request.client.host if request.client else "") or None


# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------
def _resolve_updated_by(updated_by):
    """Hydrate updated_by (a ``users.id``) -> {id, email, display_name} or None."""
    if not updated_by:
        return None
    from app.models.user import UserModel
    u = UserModel.find_by_id(updated_by)
    if not u:
        return None
    prof = u.get("profile") or {}
    return {
        "id": str(u["_id"]),
        "email": u.get("email"),
        "display_name": prof.get("display_name") or u.get("display_name"),
    }


@router.get("/features")
def get_features(request: Request, user: dict = Depends(require_admin)):
    """Return current feature flags + updated_at + updated_by metadata."""
    doc = PlatformSettingsModel.get()
    return {
        "features": doc["features"],
        "updated_at": doc["updated_at"] if doc.get("updated_at") else None,
        "updated_by": _resolve_updated_by(doc.get("updated_by")),
    }


@router.put("/features")
async def set_features(request: Request, user: dict = Depends(require_admin)):
    """Toggle one or many feature flags.

    Accepts either ``{"feature": "arena", "enabled": true}`` or
    ``{"features": {"arena": true, "debate": false}}``. Writes one audit row per
    call (``category='holding'``).
    """
    data = await _json_body(request)

    by_id = user["_id"]
    before = PlatformSettingsModel.get()["features"]

    # Build the desired delta.
    delta = {}
    if "feature" in data:
        name = (data.get("feature") or "").strip()
        if name not in DEFAULT_FEATURES:
            return JSONResponse({
                "error": f"Unknown feature: {name!r}",
                "allowed": sorted(DEFAULT_FEATURES.keys()),
            }, status_code=400)
        if "enabled" not in data or not isinstance(data["enabled"], bool):
            return JSONResponse(
                {"error": "`enabled` (bool) required when toggling a single feature"},
                status_code=400,
            )
        delta[name] = bool(data["enabled"])
    elif "features" in data:
        features = data.get("features") or {}
        if not isinstance(features, dict) or not features:
            return JSONResponse({"error": "`features` must be a non-empty object"}, status_code=400)
        unknown = [k for k in features.keys() if k not in DEFAULT_FEATURES]
        if unknown:
            return JSONResponse({
                "error": f"Unknown feature keys: {unknown}",
                "allowed": sorted(DEFAULT_FEATURES.keys()),
            }, status_code=400)
        for k, v in features.items():
            if not isinstance(v, bool):
                return JSONResponse({"error": f"Feature {k!r} value must be bool"}, status_code=400)
            delta[k] = v
    else:
        return JSONResponse(
            {"error": "Must provide either {feature, enabled} or {features:{...}}"},
            status_code=400,
        )

    # Filter to only actual changes for the audit record.
    changes = []
    for name, new_val in delta.items():
        old_val = bool(before.get(name, DEFAULT_FEATURES.get(name, False)))
        if old_val != new_val:
            changes.append({"name": name, "old": old_val, "new": new_val})

    try:
        updated = PlatformSettingsModel.bulk_set(delta, by_id)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    # One audit row per call, listing every changed flag in `details.features`.
    if changes:
        AuditLogModel.create(
            action="feature_toggle",
            admin_id=user["_id"],
            target_type="platform_settings",
            target_id="singleton",
            details={"features": changes},
            ip_address=_client_ip(request),
            category="holding",
        )

    return {
        "features": updated["features"],
        "updated_at": updated["updated_at"] if updated.get("updated_at") else None,
        "updated_by": _resolve_updated_by(updated.get("updated_by")),
        "changes": changes,
    }


# ---------------------------------------------------------------------------
# Billing config — markup_pct + credits_per_usd (profit redesign).
# ---------------------------------------------------------------------------
@router.get("/billing/config")
def get_billing_config(request: Request, user: dict = Depends(require_admin)):
    """Return the two profit knobs: ``{markup_pct, credits_per_usd}``.

    Falls back to module defaults (markup 0 / credits_per_usd 1000) on a fresh DB.
    """
    return PlatformSettingsModel.get_billing_config()


@router.put("/billing/config")
async def set_billing_config(request: Request, user: dict = Depends(require_admin)):
    """Partial update of the profit knobs.

    Accepts ``{markup_pct?, credits_per_usd?}`` (either or both). Each knob is
    bounds-validated by ``set_billing_config``; a fat-finger raises ``ValueError``
    which we normalize to a legacy-shaped 400 (``{error, status}``). One audit row
    (``category='holding'``, ``action='billing_config_set'``) is written.
    """
    data = await _json_body(request)

    delta = {
        k: data[k]
        for k in ("markup_pct", "credits_per_usd")
        if data.get(k) is not None
    }
    if not delta:
        return JSONResponse(
            {"error": "Must provide markup_pct and/or credits_per_usd", "status": 400},
            status_code=400,
        )

    before = PlatformSettingsModel.get_billing_config()
    try:
        updated = PlatformSettingsModel.set_billing_config(delta, by=user["_id"])
    except ValueError as exc:
        return JSONResponse({"error": str(exc), "status": 400}, status_code=400)

    AuditLogModel.create(
        action="billing_config_set",
        admin_id=user["_id"],
        target_type="platform_settings",
        target_id="singleton",
        details={"before": before, "after": updated},
        ip_address=_client_ip(request),
        category="holding",
    )

    return updated


# ---------------------------------------------------------------------------
# Holding overview
# ---------------------------------------------------------------------------
@router.get("/holding/overview")
def holding_overview(request: Request, days: str | None = None,
                     user: dict = Depends(require_admin)):
    """Holding-wide analytics rollup."""
    days_val = int(days) if days is not None else 30
    payload = holding_analytics.holding_overview(days=days_val)
    payload["usage_30d_cost_usd"] = payload.get("totals", {}).get("cost_usd", 0.0)
    return payload


@router.get("/holding/ledger")
def holding_ledger(request: Request, skip: str | None = None,
                   limit: str | None = None, user: dict = Depends(require_admin)):
    """List recent holding-scope audit-log rows that recorded credit movements."""
    payload = holding_analytics.holding_ledger(
        skip=int(skip) if skip is not None else 0,
        limit=int(limit) if limit is not None else 50,
    )
    return payload


# ---------------------------------------------------------------------------
# Credit charging — company-scoped and holding-scoped
# ---------------------------------------------------------------------------
_LEDGER_TYPES = {"top_up", "adjustment", "refund"}


def _parse_credit_body(data: dict):
    """Shared validator for both company + holding credit endpoints.

    Returns ``(body, None)`` on success or ``(None, JSONResponse)`` on error.
    """
    try:
        amount = float(data.get("amount_usd"))
    except (TypeError, ValueError):
        return None, JSONResponse({"error": "amount_usd (number) is required"}, status_code=400)
    if amount == 0:
        return None, JSONResponse({"error": "amount_usd must be non-zero"}, status_code=400)
    type_ = (data.get("type") or "top_up").strip().lower()
    if type_ not in _LEDGER_TYPES:
        return None, JSONResponse(
            {"error": "type must be one of 'top_up' | 'adjustment' | 'refund'"},
            status_code=400,
        )
    note = (data.get("note") or "").strip()
    return {"amount": amount, "type": type_, "note": note}, None


_CREDIT_SOURCES = {"holding", "external"}


def _add_external_credit(
    *,
    request: Request,
    user: dict,
    wid: str,
    ws: dict,
    body: dict,
    commit: bool = True,
    target_type: str = "workspace",
    target_id=None,
    audit_action: str = "company_credits_added",
    audit_extra: dict | None = None,
):
    """Append an external (non-pool) credit entry to a workspace + bump its balance.

    The shared 'external' write used by both the company-credit route and the
    per-user-credit routes: a ledger ``add_entry`` (with the given ``commit``),
    the materialized ``credits_balance_usd`` bump (same ``commit``), and one
    ``audit_logs`` row. The holding pool is NOT touched.

    Returns ``(entry_dict, new_balance)`` so the caller assembles its own
    response shape. With ``commit=False`` the ledger/balance writes flush but
    defer their COMMIT so the caller can batch many users in one transaction.
    """
    user_id = user["_id"]
    new_balance = float(ws.get("credits_balance_usd") or 0) + body["amount"]

    entry = CreditLedgerModel.add_entry(
        workspace_id=wid,
        amount_usd=body["amount"],
        type=body["type"],
        note=body["note"],
        added_by=user_id,
        commit=commit,
    )
    WorkspaceModel.update(wid, {"credits_balance_usd": new_balance}, commit=commit)

    details = {
        "amount_usd": body["amount"],
        "type": body["type"],
        "note": body["note"],
        "workspace_name": ws.get("name"),
        "new_balance_usd": new_balance,
    }
    if audit_extra:
        details.update(audit_extra)
    AuditLogModel.create(
        action=audit_action,
        admin_id=user_id,
        target_type=target_type,
        target_id=target_id if target_id is not None else wid,
        details=details,
        ip_address=_client_ip(request),
        category="holding",
    )

    return serialize_doc(entry), new_balance


@router.post("/companies/{wid}/credits")
async def charge_company(wid: str, request: Request,
                         user: dict = Depends(require_admin)):
    """Append a ledger entry to a company and bump its materialized balance.

    ``source`` (default ``'external'``) selects the funding origin:
      * ``external`` — exactly the legacy behavior: credits appear from outside,
        the holding pool is untouched.
      * ``holding`` — the credits are TRANSFERRED out of the holding pool. The
        transferable pool (``topups − transferred``) is checked first; an
        over-draw raises ``BudgetExceededError`` (HTTP 402). On success the
        ledger entry, the holding ``transferred`` counter, and the company
        balance bump all commit in ONE transaction so a failure leaves the pool
        and the wallet untouched (atomicity).
    """
    from app.utils.ids import is_valid_id

    if not is_valid_id(wid):
        return JSONResponse({"error": "invalid id"}, status_code=400)

    data = await _json_body(request)
    body, err = _parse_credit_body(data)
    if err:
        return err

    source = (data.get("source") or "external").strip().lower()
    if source not in _CREDIT_SOURCES:
        return JSONResponse(
            {"error": "source must be one of 'holding' | 'external'"},
            status_code=400,
        )

    ws = WorkspaceModel.find_by_id(wid)
    if not ws:
        return JSONResponse({"error": "Workspace not found"}, status_code=404)

    user_id = user["_id"]
    new_balance = float(ws.get("credits_balance_usd") or 0) + body["amount"]

    if source == "holding":
        return await _transfer_from_holding(request, user, user_id, wid, ws, body, new_balance)

    # source == 'external' — legacy path, holding pool untouched.
    entry, new_balance = _add_external_credit(
        request=request,
        user=user,
        wid=wid,
        ws=ws,
        body=body,
    )

    return JSONResponse({
        "entry": entry,
        "credits_balance_usd": new_balance,
        "source": "external",
    }, status_code=201)


# ---------------------------------------------------------------------------
# Per-user monthly budget INSIDE one org (``budget_allocations`` scope
# ``member``). Replaces the retired personal-workspace credit grants.
# ---------------------------------------------------------------------------
_BULK_USER_CAP = 500

_CREDITS_RETIRED = {
    "error": "Per-user credit was replaced by per-user budgets inside a company. "
             "Use PUT /api/admin/users/{id}/budget.",
    "code": "user_credits_retired",
    "status": 410,
}


@router.post("/users/{user_id}/credits")
def charge_user_credits_retired(user_id: str, _admin: dict = Depends(require_admin)):
    """Retired with personal workspaces (mig 0026)."""
    return JSONResponse(dict(_CREDITS_RETIRED), status_code=410)


@router.post("/users/credits/bulk")
def bulk_charge_user_credits_retired(_admin: dict = Depends(require_admin)):
    """Retired with personal workspaces (mig 0026)."""
    return JSONResponse(dict(_CREDITS_RETIRED), status_code=410)


def _parse_member_budget_amount(data: dict):
    """``amount_usd``: number >= 0, or ``null`` (clear = unlimited).

    Returns ``(amount_or_None, error_response_or_None)``.
    """
    if "amount_usd" not in data:
        return None, JSONResponse(
            {"error": "amount_usd is required (number >= 0 or null)", "status": 400},
            status_code=400,
        )
    raw = data.get("amount_usd")
    if raw is None:
        return None, None
    try:
        amount = float(raw) if not isinstance(raw, bool) else -1.0
    except (TypeError, ValueError):
        amount = -1.0
    if not math.isfinite(amount) or amount < 0:
        return None, JSONResponse(
            {"error": "amount_usd must be a number >= 0 or null", "status": 400},
            status_code=400,
        )
    return amount, None


def _resolve_budget_workspace(data: dict):
    """Validate ``workspace_id`` -> ``(wid, error_response_or_None)``."""
    from app.utils.ids import is_valid_id

    wid = str(data.get("workspace_id") or "").strip()
    if not wid or not is_valid_id(wid):
        return None, JSONResponse(
            {"error": "Valid workspace_id is required", "status": 400}, status_code=400
        )
    ws = WorkspaceModel.find_by_id(wid)
    if not ws:
        return None, JSONResponse(
            {"error": "workspace not found", "status": 404}, status_code=404
        )
    return str(ws["_id"]), None


def _apply_member_budget(wid: str, uid: str, amount, admin_id) -> dict:
    """Upsert (or clear on ``None``) one member budget; returns the snapshot."""
    from app.models.budget_allocation import (
        BudgetAllocationModel,
        member_budgets_bulk,
        member_scope_id,
    )

    sid = member_scope_id(wid, uid)
    if amount is None:
        BudgetAllocationModel.clear_budget("member", sid)
    else:
        BudgetAllocationModel.set_budget(
            "member", sid, amount, by=admin_id,
            parent_scope_type="company", parent_scope_id=wid,
        )
    return member_budgets_bulk(wid, [uid]).get(uid) or {
        "amount_usd": None, "spent_mtd_usd": 0.0, "remaining_usd": None,
    }


def _is_active_member(wid: str, uid: str) -> bool:
    from app.models.workspace_member import WorkspaceMemberModel

    m = WorkspaceMemberModel.find(wid, uid)
    return bool(m and m.get("status") == "active")


@router.put("/users/{user_id}/budget")
async def set_member_budget(user_id: str, request: Request,
                            admin: dict = Depends(require_admin)):
    """Set / clear ONE user's monthly budget inside one company.

    Body ``{workspace_id, amount_usd}``; ``amount_usd: null`` clears it
    (unlimited). The user must be an active member (400 ``not_a_member``).
    """
    from app.models.user import UserModel
    from app.utils.ids import is_valid_id

    if not is_valid_id(user_id):
        return JSONResponse({"error": "invalid id", "status": 400}, status_code=400)
    data = await _json_body(request)
    wid, err = _resolve_budget_workspace(data)
    if err:
        return err
    amount, err = _parse_member_budget_amount(data)
    if err:
        return err
    if not UserModel.find_by_id(user_id):
        return JSONResponse({"error": "user not found", "status": 404}, status_code=404)
    if not _is_active_member(wid, user_id):
        return JSONResponse(
            {"error": "User is not a member of this company", "code": "not_a_member",
             "status": 400},
            status_code=400,
        )

    snapshot = _apply_member_budget(wid, user_id, amount, admin["_id"])
    AuditLogModel.create(
        action="member_budget_set",
        admin_id=admin["_id"],
        target_type="user",
        target_id=user_id,
        details={"workspace_id": wid, "amount_usd": amount},
        ip_address=_client_ip(request),
        category="holding",
    )
    return {"user_id": user_id, "workspace_id": wid, "org_budget": snapshot}


@router.post("/users/budget/bulk")
async def bulk_set_member_budget(request: Request, admin: dict = Depends(require_admin)):
    """Set the same monthly budget for many members of ONE company.

    Partial success by design: each user is applied independently; non-members
    report ``{ok: false, error: 'not_a_member'}``.
    """
    from app.extensions import db
    from app.utils.ids import is_valid_id

    data = await _json_body(request)
    user_ids = data.get("user_ids")
    if not isinstance(user_ids, list) or not user_ids:
        return JSONResponse(
            {"error": "user_ids (non-empty list) is required", "status": 400}, status_code=400
        )
    if len(user_ids) > _BULK_USER_CAP:
        return JSONResponse(
            {"error": f"user_ids exceeds the cap of {_BULK_USER_CAP}", "status": 400},
            status_code=400,
        )
    wid, err = _resolve_budget_workspace(data)
    if err:
        return err
    amount, err = _parse_member_budget_amount(data)
    if err:
        return err

    results: list[dict] = []
    for raw_uid in user_ids:
        uid = str(raw_uid or "")
        if not is_valid_id(uid):
            results.append({"user_id": uid, "ok": False, "error": "invalid id"})
            continue
        if not _is_active_member(wid, uid):
            results.append({"user_id": uid, "ok": False, "error": "not_a_member"})
            continue
        try:
            snapshot = _apply_member_budget(wid, uid, amount, admin["_id"])
        except Exception as exc:  # noqa: BLE001
            db.session.rollback()
            logger.warning("bulk member budget failed for %s: %s", uid, exc)
            results.append({"user_id": uid, "ok": False, "error": "budget write failed"})
            continue
        results.append({"user_id": uid, "ok": True, "org_budget": snapshot})

    applied = sum(1 for r in results if r["ok"])
    AuditLogModel.create(
        action="member_budget_bulk_set",
        admin_id=admin["_id"],
        target_type="workspace",
        target_id=wid,
        details={"count": applied, "amount_usd": amount},
        ip_address=_client_ip(request),
        category="holding",
    )
    return {"results": results, "applied": applied, "failed": len(results) - applied}


async def _transfer_from_holding(request, user, user_id, wid, ws, body, new_balance):
    """Move credits out of the holding pool into a company wallet, atomically."""
    from app.extensions import db
    from app.services.spend_gate import BudgetExceededError

    # A holding transfer MUST be strictly positive: a negative amount would
    # bypass the `amount > pool_remaining` pool guard (e.g. -50 > 0 is False),
    # then drive the never-decrementing `transferred` counter negative (inflating
    # the transferable pool) and push the company wallet below zero. (External
    # adjustment/refund ledger entries may still be negative — only the pool
    # transfer is constrained.)
    if body["amount"] <= 0:
        return JSONResponse(
            {"error": "amount_usd must be positive for a holding transfer"},
            status_code=400,
        )

    settings_doc = PlatformSettingsModel.get()
    topups = float((settings_doc or {}).get("holding_credits_topups_usd") or 0)
    transferred = float((settings_doc or {}).get("holding_credits_transferred_usd") or 0)
    pool_remaining = topups - transferred

    if body["amount"] > pool_remaining:
        # Cheap fast-fail on the obviously-empty pool. The AUTHORITATIVE check is
        # the guarded SQL below (this read is non-locking, so it can be stale).
        # Close the read transaction opened by ``PlatformSettingsModel.get()``
        # BEFORE raising so the pooled connection is returned clean: a lingering
        # 'idle in transaction' backend races the per-test truncate's
        # ``pg_terminate_backend`` loop (yielding flaky AdminShutdown on the next
        # checkout). The normal-return path commits, so this only matters here.
        db.session.rollback()
        raise BudgetExceededError(
            code="insufficient_credits",
            scope="holding",
            remaining=pool_remaining,
            limit=topups,
            message="Insufficient holding-pool credits to transfer",
        )

    pool_remaining_after = pool_remaining - body["amount"]

    # ONE transaction: ledger entry + balance bump are written first (deferred
    # COMMIT), THEN the guarded transferred-counter upsert serializes the
    # read-check-act against the live pool ceiling (closes the TOCTOU where two
    # concurrent transfers each pass the stale Python check above and over-draw
    # the pool below zero). If the guard rejects (``False``), it has already
    # rolled the session back — discarding the deferred ledger/balance writes —
    # so we raise the SAME insufficient-credits 402. Otherwise it commits all
    # three writes atomically.
    entry = CreditLedgerModel.add_entry(
        workspace_id=wid,
        amount_usd=body["amount"],
        type=body["type"],
        note=body["note"],
        added_by=user_id,
        commit=False,
    )
    WorkspaceModel.update(wid, {"credits_balance_usd": new_balance}, commit=False)
    wrote = PlatformSettingsModel.add_holding_transferred(
        body["amount"], by=user_id, commit=False, guarded=True
    )
    if not wrote:
        raise BudgetExceededError(
            code="insufficient_credits",
            scope="holding",
            remaining=pool_remaining,
            limit=topups,
            message="Insufficient holding-pool credits to transfer",
        )
    db.session.commit()

    AuditLogModel.create(
        action="company_credits_transferred",
        admin_id=user["_id"],
        target_type="workspace",
        target_id=wid,
        details={
            "amount_usd": body["amount"],
            "type": body["type"],
            "note": body["note"],
            "workspace_name": ws.get("name"),
            "new_balance_usd": new_balance,
            "pool_remaining_after": round(pool_remaining_after, 8),
        },
        ip_address=_client_ip(request),
        category="holding",
    )

    return JSONResponse({
        "entry": serialize_doc(entry),
        "credits_balance_usd": new_balance,
        "source": "holding",
        "holding_pool_remaining_usd": round(pool_remaining_after, 8),
    }, status_code=201)


@router.post("/holding/credits")
async def charge_holding(request: Request, user: dict = Depends(require_admin)):
    """Bump holding-level credit pool on platform_settings.singleton."""
    data = await _json_body(request)
    body, err = _parse_credit_body(data)
    if err:
        return err

    user_id = user["_id"]
    doc = PlatformSettingsModel.add_holding_credits(body["amount"], by=user_id)
    new_topups = float((doc or {}).get("holding_credits_topups_usd") or 0)

    AuditLogModel.create(
        action="holding_credits_added",
        admin_id=user["_id"],
        target_type="holding",
        target_id=None,
        details={
            "amount_usd": body["amount"],
            "type": body["type"],
            "note": body["note"],
            "new_lifetime_topups_usd": new_topups,
        },
        ip_address=_client_ip(request),
        category="holding",
    )

    return JSONResponse({
        "lifetime_topups_usd": round(new_topups, 4),
    }, status_code=201)


__all__ = ["router"]
