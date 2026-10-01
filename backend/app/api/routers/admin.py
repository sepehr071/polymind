"""Admin (super-admin / CEO) routes, translated from app/routes/admin.py.

Every Flask handler maps 1:1 to a FastAPI path operation. The whole blueprint
was gated by ``@jwt_required() + @admin_required`` (user.role == 'admin'), so
every route here takes ``user: dict = Depends(require_admin)`` — which resolves
the Bearer token to the legacy user dict and 403s non-admins (reading the role
from the DB-loaded user, NEVER from a JWT claim).

The router-level ``Depends(flask_ctx)`` binds one Flask app_context per request
so the existing model facades + services run VERBATIM. Response shapes (the Mongo
``_id`` alias from ``to_dict()`` / ``serialize_doc``) are preserved exactly — no
``response_model`` (it would strip fields).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import and_, func, or_, select

from app.api.core import db
from app.api.deps import flask_ctx, require_admin
from app.models.audit_log import AuditLogModel
from app.models.conversation import Conversation, ConversationModel
from app.models.llm_config import LLMConfigModel
from app.models.message import Message, MessageModel
from app.models.usage_log import UsageLog
from app.models.user import User, UserModel, VALID_USER_ROLES
from app.utils.helpers import serialize_doc

# Router-level dependency: every request runs inside the Flask app_context.
# Mirror the Flask url_prefix '/api/admin' (prefix is applied at wiring time).
router = APIRouter(dependencies=[Depends(flask_ctx)])


async def _json_body(request: Request) -> dict:
    """Read the request JSON body, tolerating empty/garbage like get_json(silent=True)."""
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def _int_arg(request: Request, key: str, default: int) -> int:
    """Parse an int query arg, falling back to ``default`` on missing/garbage.

    (The old Flask code did a bare ``int(...)`` that raised on non-numeric input,
    surfacing as a global 500 on every admin list endpoint for a bad ``?page=``
    /``?limit=``. Degrade to the default instead.)
    """
    raw = request.query_params.get(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Users.
# ---------------------------------------------------------------------------
@router.get("/users")
def get_users(request: Request, user: dict = Depends(require_admin)):
    """Get all users."""
    page = _int_arg(request, "page", 1)
    limit = _int_arg(request, "limit", 20)
    include_banned = (request.query_params.get("include_banned", "true") or "").lower() == "true"
    search = (request.query_params.get("search", "") or "").strip()
    role_filter = (request.query_params.get("role", "") or "").strip().lower() or None
    # Optional org filter: only ACTIVE members of that company, each with their
    # per-user monthly budget there (``org_budget``).
    org_id = (request.query_params.get("workspace_id", "") or "").strip() or None
    org_uuid = None
    if org_id:
        try:
            org_uuid = uuid.UUID(org_id)
        except (ValueError, TypeError):
            return JSONResponse(
                {"error": "Invalid workspace_id", "status": 400}, status_code=400
            )
    skip = (page - 1) * limit

    stmt = select(User)
    count_stmt = select(func.count()).select_from(User)
    conditions = []
    if not include_banned:
        cond = or_(
            User.status["is_banned"].astext == "false",
            User.status["is_banned"].astext.is_(None),
        )
        conditions.append(cond)
    if role_filter:
        conditions.append(User.role == role_filter)
    if org_uuid is not None:
        from app.models.workspace_member import WorkspaceMember

        conditions.append(User.id.in_(
            select(WorkspaceMember.user_id).where(
                WorkspaceMember.workspace_id == org_uuid,
                WorkspaceMember.status == "active",
            )
        ))
    if search:
        like = f"%{search}%"
        conditions.append(or_(
            User.email.ilike(like),
            User.display_name.ilike(like),
            User.profile["display_name"].astext.ilike(like),
        ))
    if conditions:
        stmt = stmt.where(and_(*conditions))
        count_stmt = count_stmt.where(and_(*conditions))

    total = int(db.session.execute(count_stmt).scalar() or 0)
    rows = db.session.execute(
        stmt.order_by(User.created_at.desc()).offset(skip).limit(limit)
    ).scalars().all()
    users = [r.to_dict() for r in rows]

    # Authoritative lifetime usage from usage_logs (not the chat-only
    # User.usage.tokens_used JSONB counter, which misses Image Studio / non-chat
    # features). ONE grouped aggregation scoped to this page's user ids; total_tokens
    # is the canonical per-row token sum (image-gen rows now carry nonzero tokens).
    page_user_ids = [r.id for r in rows]
    usage_by_uid: dict = {}
    if page_user_ids:
        for u_row in db.session.execute(
            select(
                UsageLog.user_id,
                func.coalesce(func.sum(UsageLog.cost_usd), 0).label("cost_usd"),
                func.coalesce(func.sum(UsageLog.total_tokens), 0).label("tokens"),
                func.count().label("calls"),
            )
            .where(UsageLog.user_id.in_(page_user_ids))
            .group_by(UsageLog.user_id)
        ).all():
            usage_by_uid[str(u_row.user_id)] = u_row

    budgets_by_uid: dict = {}
    if org_uuid is not None and page_user_ids:
        from app.models.budget_allocation import member_budgets_bulk

        budgets_by_uid = member_budgets_bulk(org_uuid, page_user_ids)

    serialized = serialize_doc(users)
    for item in serialized:
        agg = usage_by_uid.get(str(item.get("_id")))
        item["usage_cost_usd"] = round(float(agg.cost_usd or 0), 4) if agg else 0.0
        item["usage_tokens"] = int(agg.tokens or 0) if agg else 0
        item["usage_calls"] = int(agg.calls or 0) if agg else 0
        if org_uuid is not None:
            item["org_budget"] = budgets_by_uid.get(str(item.get("_id"))) or {
                "amount_usd": None, "spent_mtd_usd": 0.0, "remaining_usd": None,
            }

    return {
        "users": serialized,
        "total": total,
        "page": page,
        "limit": limit,
        "has_more": skip + len(users) < total,
    }


@router.get("/users/{user_id}")
def get_user(user_id: str, user: dict = Depends(require_admin)):
    """Get detailed user info."""
    found = UserModel.find_by_id(user_id)
    if not found:
        return JSONResponse({"error": "User not found"}, status_code=404)

    user_data = serialize_doc(found)
    if "password_hash" in user_data:
        del user_data["password_hash"]

    conversation_count = ConversationModel.count_by_user(user_id)
    config_count = LLMConfigModel.count_by_owner(user_id)

    user_data["stats"] = {
        "conversation_count": conversation_count,
        "config_count": config_count,
    }

    return {"user": user_data}


@router.patch("/users/{user_id}")
async def update_user(user_id: str, request: Request, user: dict = Depends(require_admin)):
    """Update a user's role (and other non-sensitive fields)."""
    found = UserModel.find_by_id(user_id)
    if not found:
        return JSONResponse({"error": "User not found"}, status_code=404)

    data = await _json_body(request)
    update_fields = {}

    if "role" in data:
        role = (data["role"] or "").strip().lower()
        if role not in VALID_USER_ROLES:
            return JSONResponse(
                {"error": f"role must be one of {sorted(VALID_USER_ROLES)}"},
                status_code=400,
            )
        update_fields["role"] = role

    if not update_fields:
        return JSONResponse({"error": "No valid fields to update"}, status_code=400)

    UserModel.update(user_id, update_fields)
    updated = UserModel.find_by_id(user_id)
    updated_data = serialize_doc(updated)
    updated_data.pop("password_hash", None)
    return {"user": updated_data}


@router.put("/users/{user_id}/ban")
async def ban_user(user_id: str, request: Request, user: dict = Depends(require_admin)):
    """Ban a user."""
    admin = user
    data = await _json_body(request)

    found = UserModel.find_by_id(user_id)
    if not found:
        return JSONResponse({"error": "User not found"}, status_code=404)

    # Prevent self-ban.
    if str(found["_id"]) == str(admin["_id"]):
        return JSONResponse({"error": "Cannot ban yourself"}, status_code=400)

    # Prevent banning other admins.
    if found.get("role") == "admin":
        return JSONResponse({"error": "Cannot ban admin users"}, status_code=400)

    reason = data.get("reason", "No reason provided")
    UserModel.ban_user(user_id, reason, str(admin["_id"]))

    return {"message": "User banned", "user_id": user_id, "reason": reason}


@router.put("/users/{user_id}/unban")
def unban_user(user_id: str, user: dict = Depends(require_admin)):
    """Unban a user."""
    found = UserModel.find_by_id(user_id)
    if not found:
        return JSONResponse({"error": "User not found"}, status_code=404)

    UserModel.unban_user(user_id)

    return {"message": "User unbanned", "user_id": user_id}


@router.put("/users/{user_id}/limits")
async def set_user_limits(user_id: str, request: Request, user: dict = Depends(require_admin)):
    """Set usage limits for a user."""
    data = await _json_body(request)

    found = UserModel.find_by_id(user_id)
    if not found:
        return JSONResponse({"error": "User not found"}, status_code=404)

    tokens_limit = data.get("tokens_limit", -1)  # -1 = unlimited
    UserModel.update(user_id, {"usage.tokens_limit": tokens_limit})

    return {"message": "User limits updated", "user_id": user_id, "tokens_limit": tokens_limit}


@router.get("/users/{user_id}/history")
def get_user_history(user_id: str, request: Request, user: dict = Depends(require_admin)):
    """Get user's chat history (conversation metadata only by default).

    Messages are fetched lazily per-conversation via
    ``GET /users/{user_id}/history/{conversation_id}/messages`` (the admin
    User-History page expands one conversation at a time). Passing
    ``include_messages=true`` still eager-loads every conversation's messages
    for any legacy caller that relies on it.
    """
    found = UserModel.find_by_id(user_id)
    if not found:
        return JSONResponse({"error": "User not found"}, status_code=404)

    page = _int_arg(request, "page", 1)
    limit = _int_arg(request, "limit", 20)
    skip = (page - 1) * limit

    conversations = ConversationModel.get_by_user_for_admin(user_id, skip=skip, limit=limit)

    include_messages = (request.query_params.get("include_messages", "false") or "").lower() == "true"
    if include_messages:
        for conv in conversations:
            messages = MessageModel.find_by_conversation(str(conv["_id"]), limit=50)
            conv["messages"] = messages

    return {
        "conversations": serialize_doc(conversations),
        "user": {
            "id": str(found["_id"]),
            "email": found["email"],
            "display_name": found["profile"]["display_name"],
        },
    }


@router.get("/users/{user_id}/history/{conversation_id}/messages")
def get_user_history_messages(
    user_id: str, conversation_id: str, user: dict = Depends(require_admin)
):
    """Lazily fetch one conversation's messages (admin User-History expand)."""
    found = UserModel.find_by_id(user_id)
    if not found:
        return JSONResponse({"error": "User not found"}, status_code=404)

    conversation = ConversationModel.find_by_id(conversation_id)
    if not conversation or str(conversation.get("user_id")) != str(found["_id"]):
        return JSONResponse({"error": "Conversation not found"}, status_code=404)

    messages = MessageModel.find_by_conversation(conversation_id, limit=50)
    return {"messages": serialize_doc(messages)}


# ---------------------------------------------------------------------------
# Templates.
# ---------------------------------------------------------------------------
@router.get("/templates")
def get_templates(user: dict = Depends(require_admin)):
    """Get all templates."""
    templates = LLMConfigModel.find_templates()
    return {"templates": serialize_doc(templates)}


@router.post("/templates")
async def create_template(request: Request, user: dict = Depends(require_admin)):
    """Create a new template."""
    data = await _json_body(request)

    name = (data.get("name") or "").strip()
    model_id = data.get("model_id")

    if not name or not model_id:
        return JSONResponse({"error": "Name and model_id are required"}, status_code=400)

    template = LLMConfigModel.create(
        name=name,
        model_id=model_id,
        model_name=data.get("model_name", model_id),
        owner_id=None,  # Templates have no owner.
        description=data.get("description", ""),
        system_prompt=data.get("system_prompt", ""),
        visibility="template",
        avatar=data.get("avatar"),
        parameters=data.get("parameters"),
        tags=data.get("tags", []),
    )

    return JSONResponse({"template": serialize_doc(template)}, status_code=201)


@router.put("/templates/{template_id}")
async def update_template(template_id: str, request: Request, user: dict = Depends(require_admin)):
    """Update a template."""
    template = LLMConfigModel.find_by_id(template_id)
    if not template or template["visibility"] != "template":
        return JSONResponse({"error": "Template not found"}, status_code=404)

    data = await _json_body(request)
    update_fields = {}

    for field in ["name", "description", "system_prompt", "model_id", "model_name",
                  "avatar", "parameters", "tags"]:
        if field in data:
            update_fields[field] = data[field]

    if update_fields:
        LLMConfigModel.update(template_id, update_fields)

    updated = LLMConfigModel.find_by_id(template_id)
    return {"template": serialize_doc(updated)}


@router.delete("/templates/{template_id}")
def delete_template(template_id: str, user: dict = Depends(require_admin)):
    """Delete a template."""
    template = LLMConfigModel.find_by_id(template_id)
    if not template or template["visibility"] != "template":
        return JSONResponse({"error": "Template not found"}, status_code=404)

    LLMConfigModel.delete(template_id)

    return {"message": "Template deleted"}


# ---------------------------------------------------------------------------
# Analytics.
# ---------------------------------------------------------------------------
@router.get("/analytics")
def get_analytics(request: Request, user: dict = Depends(require_admin)):
    """Get usage analytics."""
    days = _int_arg(request, "days", 30)
    start_date = datetime.utcnow() - timedelta(days=days)

    total_users = UserModel.count()
    active_users = int(db.session.execute(
        select(func.count()).select_from(User).where(
            User.usage["last_active"].astext.cast(db.DateTime) >= start_date
        )
    ).scalar() or 0)

    total_conversations = int(db.session.execute(
        select(func.count()).select_from(Conversation)
    ).scalar() or 0)
    recent_conversations = int(db.session.execute(
        select(func.count()).select_from(Conversation).where(
            Conversation.created_at >= start_date
        )
    ).scalar() or 0)

    total_messages = int(db.session.execute(
        select(func.count()).select_from(Message)
    ).scalar() or 0)

    total_tokens = int(db.session.execute(
        select(func.coalesce(func.sum(UsageLog.total_tokens), 0))
    ).scalar() or 0)

    model_usage = []
    try:
        rows = db.session.execute(
            select(
                UsageLog.model.label("_id"),
                func.count().label("count"),
                func.coalesce(func.sum(UsageLog.total_tokens), 0).label("total_tokens"),
            )
            .where(UsageLog.created_at >= start_date)
            .group_by(UsageLog.model)
            .order_by(func.count().desc())
            .limit(10)
        ).all()
        model_usage = [
            {
                "_id": r._id,
                "count": int(r.count or 0),
                "total_tokens": int(r.total_tokens or 0),
            }
            for r in rows
        ]
    except Exception:  # noqa: BLE001
        pass

    return {
        "analytics": {
            "users": {"total": total_users, "active": active_users},
            "conversations": {"total": total_conversations, "recent": recent_conversations},
            "messages": {"total": total_messages},
            "tokens": {"total": total_tokens},
            "model_usage": model_usage,
            "period_days": days,
        }
    }


@router.get("/analytics/costs")
def get_cost_analytics(request: Request, user: dict = Depends(require_admin)):
    """Get API cost breakdown."""
    days = _int_arg(request, "days", 30)
    start_date = datetime.utcnow() - timedelta(days=days)

    try:
        rows = db.session.execute(
            select(
                UsageLog.model.label("_id"),
                func.coalesce(func.sum(UsageLog.cost_usd), 0).label("total_cost"),
                func.count().label("total_requests"),
                func.coalesce(func.sum(UsageLog.total_tokens), 0).label("total_tokens"),
            )
            .where(UsageLog.created_at >= start_date)
            .group_by(UsageLog.model)
            .order_by(func.coalesce(func.sum(UsageLog.cost_usd), 0).desc())
        ).all()
        costs = [
            {
                "_id": r._id,
                "total_cost": float(r.total_cost or 0),
                "total_requests": int(r.total_requests or 0),
                "total_tokens": int(r.total_tokens or 0),
            }
            for r in rows
        ]
        total_cost = sum(c["total_cost"] for c in costs)

        return {
            "costs": {
                "by_model": costs,
                "total_cost_usd": total_cost,
                "period_days": days,
            }
        }
    except Exception:  # noqa: BLE001
        return {
            "costs": {
                "by_model": [],
                "total_cost_usd": 0,
                "period_days": days,
                "note": "Cost tracking not yet implemented",
            }
        }


@router.get("/analytics/timeseries")
def get_timeseries_analytics(request: Request, user: dict = Depends(require_admin)):
    """Get time-series analytics data for charts."""
    days = _int_arg(request, "days", 30)
    granularity = request.query_params.get("granularity", "day")  # day, week, month
    start_date = datetime.utcnow() - timedelta(days=days)

    def _daily_count(table_cls):
        day_expr = func.to_char(table_cls.created_at, "YYYY-MM-DD").label("_id")
        rows = db.session.execute(
            select(day_expr, func.count().label("count"))
            .where(table_cls.created_at >= start_date)
            .group_by("_id")
            .order_by("_id")
        ).all()
        return [{"_id": r._id, "count": int(r.count or 0)} for r in rows]

    messages_by_day = _daily_count(Message)
    users_by_day = _daily_count(User)
    conversations_by_day = _daily_count(Conversation)

    tokens_by_day = []
    try:
        day_expr = func.to_char(UsageLog.created_at, "YYYY-MM-DD").label("_id")
        token_sum = func.coalesce(
            func.sum(UsageLog.input_tokens + UsageLog.output_tokens), 0
        ).label("tokens")
        rows = db.session.execute(
            select(day_expr, token_sum)
            .where(UsageLog.created_at >= start_date)
            .group_by("_id")
            .order_by("_id")
        ).all()
        tokens_by_day = [{"_id": r._id, "tokens": int(r.tokens or 0)} for r in rows]
    except Exception:  # noqa: BLE001
        pass

    popular_models = []
    try:
        model_expr = Message.message_metadata["model_id"].astext.label("_id")
        rows = db.session.execute(
            select(model_expr, func.count().label("count"))
            .where(Message.created_at >= start_date, model_expr.isnot(None))
            .group_by(model_expr)
            .order_by(func.count().desc())
            .limit(5)
        ).all()
        popular_models = [{"_id": r._id, "count": int(r.count or 0)} for r in rows]
    except Exception:  # noqa: BLE001
        pass

    def fill_dates(data, days):
        date_map = {item["_id"]: item["count"] for item in data}
        filled = []
        for i in range(days):
            date = (datetime.utcnow() - timedelta(days=days - i - 1)).strftime("%Y-%m-%d")
            filled.append({"date": date, "value": date_map.get(date, 0)})
        return filled

    return {
        "timeseries": {
            "messages": fill_dates(messages_by_day, days),
            "users": fill_dates(users_by_day, days),
            "conversations": fill_dates(conversations_by_day, days),
            "tokens": [{"date": t["_id"], "value": t.get("tokens", 0)} for t in tokens_by_day],
            "popular_models": [{"model": m["_id"], "count": m["count"]} for m in popular_models],
            "period_days": days,
            "granularity": granularity,
        }
    }


@router.get("/analytics/usage")
def get_usage_analytics(request: Request, user: dict = Depends(require_admin)):
    """Unified usage-analytics envelope (Company → Team → User drilldown).

    Query params: ``scope`` (holding|company|team|user, default holding),
    ``id`` (workspace/project/user UUID; null for holding),
    ``granularity`` (day|week|month, default day), ``from`` / ``to`` (ISO; default
    trailing 30d), ``breakdown`` (``model`` to include the per-model split).
    Super-admin viewer → ``cost_visible: true``.
    """
    from app.services import analytics_service

    scope = (request.query_params.get("scope") or "holding").strip().lower()
    granularity = (request.query_params.get("granularity") or "day").strip().lower()
    scope_id = request.query_params.get("id") or None
    breakdown = request.query_params.get("breakdown") or None
    frm = request.query_params.get("from") or None
    to = request.query_params.get("to") or None

    try:
        payload = analytics_service.usage(
            scope=scope,
            scope_id=scope_id,
            granularity=granularity,
            frm=frm,
            to=to,
            breakdown=breakdown,
            viewer=user,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc), "status": 400}, status_code=400)
    return payload


@router.get("/analytics/profit")
def get_profit_analytics(request: Request, user: dict = Depends(require_admin)):
    """Holding-wide CEO profit report — revenue (marked-up price) vs. true
    upstream cost, with the derived margin. Super-admin (``role=='admin'``) ONLY.

    Reshapes the holding-scope analytics envelope into a profit-first shape.
    ``revenue`` = ``cost_usd`` sum (the price we charge); ``upstream_cost`` = the
    new ``upstream`` (``upstream_cost_usd``) sum (true cost); ``margin`` =
    revenue − upstream_cost. Margin fields are produced by the service ONLY for a
    margin-visible viewer, which ``require_admin`` guarantees here.

    Same query params as ``/analytics/usage`` (``granularity``/``from``/``to``;
    the per-company ``by_company`` split + per-model split are always carried, so
    ``breakdown``/``scope``/``id`` are ignored — this report is always holding-wide).
    """
    from app.services import analytics_service

    granularity = (request.query_params.get("granularity") or "day").strip().lower()
    frm = request.query_params.get("from") or None
    to = request.query_params.get("to") or None

    try:
        env = analytics_service.usage(
            scope="holding",
            scope_id=None,
            granularity=granularity,
            frm=frm,
            to=to,
            breakdown="model",
            viewer=user,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc), "status": 400}, status_code=400)

    t = env["totals"]
    series = [
        {
            "bucket": pt["bucket"],
            "revenue": pt.get("cost"),
            "upstream_cost": pt.get("upstream_cost"),
            "margin": pt.get("margin"),
            "margin_pct": pt.get("margin_pct"),
        }
        for pt in env["series"]
    ]
    totals = {
        "revenue": t.get("cost"),
        "upstream_cost": t.get("upstream_cost"),
        "margin": t.get("margin"),
        "margin_pct": t.get("margin_pct"),
        "tokens": t.get("tokens"),
        "calls": t.get("calls"),
    }
    return {
        "window": env["window"],
        "granularity": env["granularity"],
        "series": series,
        "totals": totals,
        "deltas": env["deltas"],
        # children rows carry the price as ``cost``; expose it as ``revenue`` too
        # so the profit table reads a profit-first field (keeps cost for any
        # shared consumer). upstream_cost/margin/margin_pct already present.
        "by_company": [
            {**c, "revenue": c.get("cost")} for c in env["breakdown"]["children"]
        ],
        "by_model": env["breakdown"]["by_model"],
        "margin_visible": env["margin_visible"],
    }


@router.get("/audit-logs")
def get_audit_logs(request: Request, user: dict = Depends(require_admin)):
    """Get audit logs with filtering and pagination."""
    skip = _int_arg(request, "skip", 0)
    limit = _int_arg(request, "limit", 50)
    action = request.query_params.get("action")

    logs = AuditLogModel.find_all(skip=skip, limit=limit, action=action)
    total = AuditLogModel.count(action=action)

    admin_ids = [log.get("admin_id") for log in logs if log.get("admin_id")]
    admin_map = {}
    if admin_ids:
        for a in UserModel.find_by_ids(admin_ids):
            admin_map[str(a["_id"])] = a.get("email")

    for log in logs:
        admin_id = str(log.get("admin_id") or "")
        log["admin_email"] = admin_map.get(admin_id, "Unknown")

    return {"logs": serialize_doc(logs), "total": total, "skip": skip, "limit": limit}


# ---------------------------------------------------------------------------
# Cross-company analytics — super-admin holding view.
# ---------------------------------------------------------------------------
@router.get("/companies")
def list_all_companies(request: Request, user: dict = Depends(require_admin)):
    """List every team workspace with aggregated stats. Super-admin only."""
    from app.services import holding_analytics

    days = _int_arg(request, "days", 30)
    return holding_analytics.list_companies(days=days)


@router.get("/companies/{wid}")
def get_company_detail(wid: str, request: Request, user: dict = Depends(require_admin)):
    """Drill-down stats for one company. Super-admin only."""
    from app.services import holding_analytics

    days = _int_arg(request, "days", 30)
    payload = holding_analytics.company_detail(wid, days=days)
    if payload is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return payload


@router.get("/users-overview")
def users_overview(request: Request, user: dict = Depends(require_admin)):
    """Cross-company users overview. Super-admin (user.role='admin') only.

    Thin wrapper around ``holding_analytics.users_overview``, gated by the in-app
    super-admin role.
    """
    from app.services import holding_analytics

    try:
        payload = holding_analytics.users_overview(
            days=_int_arg(request, "days", 30),
            page=_int_arg(request, "page", 1),
            limit=_int_arg(request, "limit", 50),
            search=request.query_params.get("search", ""),
            role=request.query_params.get("role", ""),
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return payload
