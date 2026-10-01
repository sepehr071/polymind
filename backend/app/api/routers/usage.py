"""Usage + OpenAPI docs routes on the broad ``/api`` mount.

``api_router`` carries ``/usage/me``, ``/admin/usage``, and the dev-only
OpenAPI yaml/json endpoints (docs_bp).
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, JSONResponse

from app.api.deps import current_user, flask_ctx, require_admin

logger = logging.getLogger(__name__)

api_router = APIRouter(dependencies=[Depends(flask_ctx)])

# ===========================================================================
# Usage  (usage_bp -> /api)
# ===========================================================================

def _parse_iso(value: Optional[str]):
    """Parse an ISO-8601 date/time string to a naive UTC datetime.

    Accepts ``Z`` and fractional seconds (the FE sends ``…T00:00:00.000Z``).
    The old strptime pair dropped those and returned None → no date filter.
    """
    from datetime import datetime

    if not value:
        return None
    if isinstance(value, datetime):
        return value
    raw = str(value).strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.replace(tzinfo=None)
        return parsed
    except ValueError:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


@api_router.get("/usage/me")
def get_my_usage(request: Request, user: dict = Depends(current_user)):
    """Return the caller's usage inside ONE org.

    Org = ``?workspace_id`` else the active workspace; non-admins must be an
    active member (403 ``workspace_access_denied``). Nothing resolves -> an
    empty envelope. Aggregates filter on ``usage_logs.workspace_id``.

    Money-visibility (``total_cost`` = the marked-up PRICE):
      * super-admin — sees price.
      * owner (membership role) of that TEAM workspace — sees price.
      * everyone else — ``total_cost`` is ``None``.

    ``total_credits`` + per-row ``credits`` are ALWAYS returned (never masked);
    tokens are always returned. Upstream cost / margin are NEVER emitted here.
    ``my_budget`` = the caller's member budget in that org (fallback: the
    global user budget row).
    """
    from app.api.routers.conversations import _resolve_list_workspace
    from app.models.usage_log import UsageLogModel
    from app.utils.credits import to_credits
    from app.utils.permissions import owned_team_workspace_ids

    user_id = user["_id"]
    group_by = request.query_params.get("group_by", "feature")
    from_ = _parse_iso(request.query_params.get("from"))
    to = _parse_iso(request.query_params.get("to"))

    workspace_id, err = _resolve_list_workspace(
        user, request.query_params.get("workspace_id")
    )
    if err:
        return err

    my_budget = _my_budget(user_id, workspace_id)

    if workspace_id is None:
        return {
            "data": [],
            "total_cost": None,
            "total_credits": to_credits(0),
            "total_tokens": 0,
            "my_budget": my_budget,
            "workspace_id": None,
        }

    try:
        data = UsageLogModel.aggregate_by(
            group_by=group_by,
            user_id=user_id,
            from_=from_,
            to=to,
            workspace_id=workspace_id,
        )
    except Exception:  # noqa: BLE001
        logger.exception("usage aggregate_by failed")
        return JSONResponse({"error": "internal error"}, status_code=500)

    price_visible = user.get("role") == "admin" or (
        str(workspace_id) in {str(w) for w in owned_team_workspace_ids(user_id)}
    )

    real_total_cost = 0.0
    for row in data:
        row_cost = row.get("total_cost", 0) or 0
        real_total_cost += row_cost
        # Credits derive from the REAL price — set BEFORE masking.
        row["credits"] = to_credits(row_cost)
        if not price_visible:
            row["total_cost"] = None

    total_tokens = sum(row.get("total_tokens", 0) for row in data)

    return {
        "data": data,
        "total_cost": real_total_cost if price_visible else None,
        "total_credits": to_credits(real_total_cost),
        "total_tokens": total_tokens,
        "my_budget": my_budget,
        "workspace_id": str(workspace_id),
    }


def _my_budget(user_id, workspace_id=None) -> dict | None:
    """The caller's OWN budget + this-month spend.

    Member budget inside ``workspace_id`` when one is set; otherwise the global
    ``user`` budget row. Always cost-visible — it is the user's own limit.
    Returns ``None`` when neither exists.
    Shape: ``{amount_usd, enabled, spend_mtd, remaining, scope}``.
    """
    from app.models.budget_allocation import BudgetAllocationModel, member_scope_id
    from app.models.spend_rollup import SpendRollupModel

    month = SpendRollupModel.current_period_month()
    alloc = None
    scope, sid = "user", user_id
    member_sid = member_scope_id(workspace_id, user_id) if workspace_id else None
    if member_sid is not None:
        alloc = BudgetAllocationModel.get_any("member", member_sid)
        if alloc:
            scope, sid = "member", member_sid
    if not alloc:
        alloc = BudgetAllocationModel.get_any("user", user_id)
    if not alloc:
        return None
    amount = alloc.get("amount_usd")
    spend_mtd = SpendRollupModel.get_spent(scope, sid, month)
    remaining = (amount - spend_mtd) if amount is not None else None
    return {
        "amount_usd": amount,
        "enabled": bool(alloc.get("enabled")),
        "spend_mtd": spend_mtd,
        "remaining": remaining,
        "scope": scope,
    }


@api_router.get("/admin/usage")
def get_admin_usage(request: Request, user: dict = Depends(require_admin)):
    """Return usage aggregation across all users.  Admin only."""
    from app.models.usage_log import UsageLogModel

    group_by = request.query_params.get("group_by", "feature")
    from_ = _parse_iso(request.query_params.get("from"))
    to = _parse_iso(request.query_params.get("to"))
    per_user = request.query_params.get("per_user", "false").lower() == "true"
    # Optional per-user breakdown: scope the aggregation to a single user when
    # ?user_id=<uuid> is supplied. Absent/blank → unchanged global (all-users) view.
    user_id_filter = (request.query_params.get("user_id") or "").strip() or None

    try:
        data = UsageLogModel.aggregate_by(
            group_by=group_by,
            user_id=user_id_filter,
            from_=from_,
            to=to,
        )
    except Exception:  # noqa: BLE001
        logger.exception("admin usage aggregate_by failed")
        return JSONResponse({"error": "internal error"}, status_code=500)

    total_cost = sum(row.get("total_cost", 0) for row in data)
    total_tokens = sum(row.get("total_tokens", 0) for row in data)

    result = {
        "data": data,
        "total_cost": total_cost,
        "total_tokens": total_tokens,
    }

    if per_user and group_by == "user":
        result["per_user"] = data  # already broken down by user when group_by=user

    return result


# ===========================================================================
# Docs  (docs_bp -> /api)
# ===========================================================================

# app/routes/docs.py computes SWAGGER_DIR relative to app/routes/. This module
# lives in app/api/routers/, so reconstruct the same path from the package root:
# .../app/api/routers/usage.py -> up 3 -> .../app -> swagger/openapi.yaml.
_SWAGGER_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "swagger"
)


def _docs_disabled_in_prod() -> bool:
    """True when the public API-spec routes must be hidden (prod only).

    Mirrors the FastAPI ``/docs`` gating in ``app.asgi``: the route inventory +
    schemas are dev aids, not something to expose to anonymous prod callers.
    """
    return os.environ.get("FLASK_ENV") == "production"


@api_router.get("/openapi.yaml")
def serve_openapi_spec():
    """Serve the OpenAPI specification file (dev only — hidden in prod)."""
    if _docs_disabled_in_prod():
        return JSONResponse({"error": "Not found"}, status_code=404)
    spec_path = os.path.join(_SWAGGER_DIR, "openapi.yaml")
    return FileResponse(spec_path, media_type="text/yaml")


@api_router.get("/openapi.json")
def serve_openapi_json():
    """Serve the OpenAPI specification as JSON (dev only — hidden in prod)."""
    if _docs_disabled_in_prod():
        return JSONResponse({"error": "Not found"}, status_code=404)
    import yaml

    spec_path = os.path.join(_SWAGGER_DIR, "openapi.yaml")
    with open(spec_path, "r", encoding="utf-8") as f:
        spec = yaml.safe_load(f)

    return JSONResponse(spec)



__all__ = ["api_router"]
