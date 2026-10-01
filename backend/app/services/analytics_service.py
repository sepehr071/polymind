"""Unified usage-analytics service (P1).

Single composition layer over the read-only ``UsageLogModel`` time-bucket
primitives (``usage_series`` / ``usage_totals`` / ``usage_previous_totals``,
added in P0) plus a handful of grouped child rollups. Produces the ONE envelope
both admin tiers consume (``GET /api/{admin,platform}/analytics/usage``):

    {scope, scope_id, granularity, window:{from,to}, series, totals, previous,
     deltas, breakdown:{by_model, children}, cost_visible}

Scope → children mapping:
    holding → companies (workspaces)
    company → teams (projects within the workspace)
    team    → users (distinct users who logged usage on the project)
    user    → null (leaf); ``breakdown.by_model`` carries the model split

READ-ONLY. NEVER writes ``usage_logs`` (the SOLE writer is
``OpenRouterService._record_usage``). All cost figures are masked to ``None``
when ``cost_visible`` is False (binary super-admin / platform-admin tier).
"""
from __future__ import annotations

import calendar
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text as _sql_text

from app.extensions import db
from app.models.openrouter_model import OpenRouterModel
from app.models.project import Project
from app.models.usage_log import UsageLogModel
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceModel, _coerce_cap

VALID_SCOPES = ("holding", "company", "team", "user")
VALID_GRANULARITIES = ("day", "week", "month")
DEFAULT_WINDOW_DAYS = 30

# Cap the number of charted child rows (top-N by cost) so a large holding
# doesn't fan a per-child spark query out to thousands of rows.
_MAX_CHILDREN = 50


def _maybe_uuid(val):
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except (ValueError, TypeError):
        return None


def _parse_dt(val, default: datetime, end_of_day: bool = False) -> datetime:
    """Parse an ISO ``YYYY-MM-DD`` or full ISO-8601 string to a naive UTC
    datetime; fall back to ``default`` on empty/garbage. Naive to match the
    primitives' ``datetime.utcnow()`` comparisons against ``created_at``.

    A **date-only** value (``YYYY-MM-DD``, no time component) used as an upper
    bound (``end_of_day=True``) is pushed to ``23:59:59.999999`` so the SQL
    ``created_at <= :to`` filter includes that whole day — otherwise a bare
    ``to`` of today parses to midnight and silently drops every row logged so
    far today (the single most common query the dashboards issue)."""
    if not val:
        return default
    if isinstance(val, datetime):
        dt = val
    else:
        s = str(val).strip()
        date_only = len(s) == 10 and "T" not in s
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return default
        if date_only and end_of_day:
            dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _resolve_window(frm, to) -> tuple[datetime, datetime]:
    """Resolve the ``[from, to]`` window, defaulting to the trailing 30 days.

    The upper bound is end-of-day for a date-only ``to`` so today's usage is
    never dropped (see :func:`_parse_dt`)."""
    now = datetime.utcnow()
    to_dt = _parse_dt(to, now, end_of_day=True)
    default_from = to_dt - timedelta(days=DEFAULT_WINDOW_DAYS)
    frm_dt = _parse_dt(frm, default_from)
    if frm_dt > to_dt:
        frm_dt, to_dt = to_dt, frm_dt
    return frm_dt, to_dt


def _deltas(totals: dict, previous: dict) -> dict:
    """Period-over-period ``{metric: {abs, pct}}``. ``pct`` is ``None`` when the
    previous-window value is zero (undefined growth)."""
    out: dict = {}
    for metric in ("cost", "calls", "tokens", "active_users"):
        cur = totals.get(metric) or 0
        prev = previous.get(metric) or 0
        abs_delta = cur - prev
        pct = round((abs_delta / prev) * 100, 2) if prev else None
        out[metric] = {"abs": abs_delta, "pct": pct}
    return out


def _model_labels(model_ids: list[str]) -> dict:
    """Map model id → human label (catalog ``display_name``, else the id)."""
    ids = [m for m in model_ids if m]
    if not ids:
        return {}
    rows = db.session.execute(
        select(OpenRouterModel.id, OpenRouterModel.display_name).where(
            OpenRouterModel.id.in_(ids)
        )
    ).all()
    return {r.id: (r.display_name or r.id) for r in rows}


# ---------------------------------------------------------------------------
# Grouped child rollups — one DB pass for window totals, one for previous
# totals, then a bounded per-child spark fetch. Raw SQL mirrors the P0
# primitive style (the GROUP BY column is an internal constant, values bind).
# ---------------------------------------------------------------------------
def _child_rollup(group_col: str, frm, to, parent_filter_sql: str,
                  parent_params: dict) -> dict:
    """Per-child window totals keyed by the grouping column's value (str)."""
    sql = f"""
        SELECT
            {group_col} AS child_id,
            COALESCE(SUM(cost_usd), 0) AS cost,
            COALESCE(SUM(upstream_cost_usd), 0) AS upstream,
            COUNT(*) AS calls,
            COALESCE(SUM(total_tokens), 0) AS tokens,
            COUNT(DISTINCT user_id) AS active_users
        FROM usage_logs
        WHERE created_at >= :frm AND created_at <= :to{parent_filter_sql}
          AND {group_col} IS NOT NULL
        GROUP BY {group_col}
    """
    params = {"frm": frm, "to": to, **parent_params}
    rows = db.session.execute(_sql_text(sql), params).all()
    return {
        str(r.child_id): {
            "cost": float(r.cost or 0),
            "upstream": float(r.upstream or 0),
            "calls": int(r.calls or 0),
            "tokens": int(r.tokens or 0),
            "active_users": int(r.active_users or 0),
        }
        for r in rows
    }


def _child_previous_cost(group_col: str, frm, to, parent_filter_sql: str,
                         parent_params: dict) -> dict:
    """Per-child cost over the immediately-preceding equal-length window — the
    baseline for each row's ``delta_pct``. Half-open upper bound (< frm)."""
    delta = to - frm
    sql = f"""
        SELECT {group_col} AS child_id, COALESCE(SUM(cost_usd), 0) AS cost
        FROM usage_logs
        WHERE created_at >= :frm AND created_at < :to{parent_filter_sql}
          AND {group_col} IS NOT NULL
        GROUP BY {group_col}
    """
    params = {"frm": frm - delta, "to": frm, **parent_params}
    rows = db.session.execute(_sql_text(sql), params).all()
    return {str(r.child_id): float(r.cost or 0) for r in rows}


def _day_axis(frm, to) -> list:
    """Ordered ``YYYY-MM-DD`` day labels spanning ``[frm, to]`` (inclusive) — the
    uniform x-axis every child sparkline is aligned to."""
    days = []
    d = frm.replace(hour=0, minute=0, second=0, microsecond=0)
    end = to.replace(hour=0, minute=0, second=0, microsecond=0)
    while d <= end:
        days.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return days


def _child_sparks(group_col: str, frm, to, parent_filter_sql: str,
                  parent_params: dict, child_ids: list, cost_visible: bool) -> dict:
    """Per-child daily spark series in ONE GROUP BY pass (no per-child N+1).

    Returns ``{child_id: [value_per_day]}`` zero-filled along :func:`_day_axis`.
    The plotted metric is cost when visible, else calls (so a masked viewer's
    sparkline never encodes hidden spend)."""
    if not child_ids:
        return {}
    metric_expr = "SUM(cost_usd)" if cost_visible else "COUNT(*)"
    sql = f"""
        SELECT
            {group_col} AS child_id,
            to_char(date_trunc('day', created_at), 'YYYY-MM-DD') AS bucket,
            COALESCE({metric_expr}, 0) AS val
        FROM usage_logs
        WHERE created_at >= :frm AND created_at <= :to{parent_filter_sql}
          AND {group_col} IS NOT NULL
        GROUP BY {group_col}, bucket
    """
    rows = db.session.execute(
        _sql_text(sql), {"frm": frm, "to": to, **parent_params}
    ).all()
    by_child: dict = {}
    for r in rows:
        by_child.setdefault(str(r.child_id), {})[r.bucket] = float(r.val or 0)
    axis = _day_axis(frm, to)
    wanted = set(child_ids)
    return {
        cid: [by_child.get(cid, {}).get(day, 0.0) for day in axis]
        for cid in wanted
    }


def _build_children(group_col: str, frm, to, parent_filter_sql: str,
                    parent_params: dict, label_fn, scope_kwarg: str,
                    cost_visible: bool, margin_visible: bool = False) -> list:
    """Assemble the ``children`` list for the current scope.

    ``group_col`` is the ``usage_logs`` column to group by
    (``workspace_id`` | ``project_id`` | ``user_id``); ``label_fn`` maps the set
    of child id strings → ``{id: label}``. ``scope_kwarg`` is retained for
    signature compatibility (sparklines are now batched, not per-child).

    When cost is masked, ``cost`` AND ``delta_pct`` are withheld — ``delta_pct``
    is derived from cost growth, so emitting it would leak the spend trend
    (sign + magnitude) to a viewer who cannot see the spend itself.

    When ``margin_visible`` (super-admin profit report), each row additionally
    carries ``upstream_cost`` / ``margin`` / ``margin_pct``; otherwise those keys
    are absent.
    """
    totals = _child_rollup(group_col, frm, to, parent_filter_sql, parent_params)
    if not totals:
        return []

    prev_cost = (
        _child_previous_cost(group_col, frm, to, parent_filter_sql, parent_params)
        if cost_visible else {}
    )
    # Top-N by cost (cost-rank is stable even when masked from the response).
    ranked = sorted(totals.items(), key=lambda kv: kv[1]["cost"], reverse=True)
    ranked = ranked[:_MAX_CHILDREN]
    ranked_ids = [cid for cid, _ in ranked]
    labels = label_fn(ranked_ids)
    sparks = _child_sparks(
        group_col, frm, to, parent_filter_sql, parent_params,
        ranked_ids, cost_visible,
    )

    children = []
    for cid, agg in ranked:
        cost = agg["cost"]
        delta_pct = None
        if cost_visible:
            prev = prev_cost.get(cid, 0.0)
            delta_pct = round(((cost - prev) / prev) * 100, 2) if prev else None
        row = {
            "id": cid,
            "label": labels.get(cid) or cid,
            "cost": cost if cost_visible else None,
            "calls": agg["calls"],
            "tokens": agg["tokens"],
            "active_users": agg["active_users"],
            "spark": sparks.get(cid, []),
            "delta_pct": delta_pct,
        }
        if margin_visible:
            row.update(_margin_fields(cost, agg["upstream"]))
        children.append(row)
    return children


# ---------------------------------------------------------------------------
# Child-label resolvers (batch-loaded; never N+1).
# ---------------------------------------------------------------------------
def _workspace_labels(ids: list[str]) -> dict:
    uuids = [u for u in (_maybe_uuid(i) for i in ids) if u is not None]
    if not uuids:
        return {}
    rows = db.session.execute(
        select(Workspace.id, Workspace.display_name, Workspace.slug).where(
            Workspace.id.in_(uuids)
        )
    ).all()
    return {str(r.id): (r.display_name or r.slug or str(r.id)) for r in rows}


def _project_labels(ids: list[str]) -> dict:
    uuids = [u for u in (_maybe_uuid(i) for i in ids) if u is not None]
    if not uuids:
        return {}
    rows = db.session.execute(
        select(Project.id, Project.name).where(Project.id.in_(uuids))
    ).all()
    return {str(r.id): (r.name or str(r.id)) for r in rows}


def _user_labels(ids: list[str]) -> dict:
    uuids = [u for u in (_maybe_uuid(i) for i in ids) if u is not None]
    if not uuids:
        return {}
    rows = db.session.execute(
        select(User.id, User.email, User.display_name).where(User.id.in_(uuids))
    ).all()
    return {str(r.id): (r.display_name or r.email or str(r.id)) for r in rows}


# ---------------------------------------------------------------------------
# by_model breakdown — per-entity model split over the window.
# ---------------------------------------------------------------------------
def _by_model(frm, to, scope_filter_sql: str, scope_params: dict,
              cost_visible: bool, margin_visible: bool = False) -> list:
    sql = f"""
        SELECT
            model AS model,
            COALESCE(SUM(cost_usd), 0) AS cost,
            COALESCE(SUM(upstream_cost_usd), 0) AS upstream,
            COUNT(*) AS calls,
            COALESCE(SUM(total_tokens), 0) AS tokens
        FROM usage_logs
        WHERE created_at >= :frm AND created_at <= :to{scope_filter_sql}
        GROUP BY model
        ORDER BY cost DESC
    """
    params = {"frm": frm, "to": to, **scope_params}
    rows = db.session.execute(_sql_text(sql), params).all()
    labels = _model_labels([r.model for r in rows])
    out = []
    for r in rows:
        row = {
            "key": r.model,
            "label": labels.get(r.model) or r.model,
            "cost": float(r.cost or 0) if cost_visible else None,
            "calls": int(r.calls or 0),
            "tokens": int(r.tokens or 0),
        }
        if margin_visible:
            row.update(_margin_fields(float(r.cost or 0), float(r.upstream or 0)))
        out.append(row)
    return out


def _mask_metrics(metrics: dict, cost_visible: bool) -> dict:
    """Return a copy with ``cost`` nulled when cost is not visible."""
    out = dict(metrics)
    if not cost_visible:
        out["cost"] = None
    return out


def _viewer_cost_visible(viewer: dict | None) -> bool:
    """Binary $-visibility: super-admin (``role=='admin'``). The admin endpoints
    gate on exactly that role, so this is effectively always ``True`` on those
    paths; it stays parametric so a future owner/manager path can pass a
    non-admin viewer and get masking for free.
    """
    if not viewer:
        return False
    return viewer.get("role") == "admin"


def _viewer_margin_visible(viewer: dict | None) -> bool:
    """Binary profit-visibility: ONLY super-admin (``role=='admin'``) may see the
    upstream (true) cost and the derived margin. The CEO profit report is the sole
    consumer; every other viewer (owner/manager/user) gets these keys masked
    entirely (absent / ``None``), so marked-up price never leaks against true cost.
    """
    if not viewer:
        return False
    return viewer.get("role") == "admin"


def _margin_fields(cost: float, upstream: float) -> dict:
    """Profit triplet for a cost/upstream pair: ``upstream_cost``, ``margin``
    (= cost − upstream), ``margin_pct`` (= margin / cost when cost > 0, else 0).

    Caller decides whether to emit these — they are ONLY produced when the viewer
    is margin-visible (super-admin). ``cost`` here is the marked-up PRICE
    (``cost_usd`` sum); ``upstream`` is the true cost (``upstream_cost_usd`` sum).
    """
    margin = cost - upstream
    margin_pct = round((margin / cost) * 100, 2) if cost > 0 else 0.0
    return {
        "upstream_cost": upstream,
        "margin": margin,
        "margin_pct": margin_pct,
    }


def usage(
    scope: str,
    scope_id,
    granularity: str,
    frm,
    to,
    breakdown: str | None = None,
    viewer: dict | None = None,
) -> dict:
    """Compose the unified usage-analytics envelope.

    Raises ``ValueError`` on an invalid ``scope`` / ``granularity`` so the thin
    router can translate it to a legacy ``{error}`` 400.
    """
    if scope not in VALID_SCOPES:
        raise ValueError(f"scope must be one of {list(VALID_SCOPES)}")
    if granularity not in VALID_GRANULARITIES:
        raise ValueError(f"granularity must be one of {list(VALID_GRANULARITIES)}")

    frm_dt, to_dt = _resolve_window(frm, to)
    cost_visible = _viewer_cost_visible(viewer)
    margin_visible = _viewer_margin_visible(viewer)

    # Map the scope to the entity-scope kwarg for the P0 primitives + the
    # child grouping column / label resolver / spark scope kwarg.
    if scope == "holding":
        entity_kwargs: dict = {}
        scope_filter_sql = ""
        scope_params: dict = {}
        child_col = "workspace_id"
        child_label_fn = _workspace_labels
        child_scope_kwarg = "workspace_id"
    elif scope == "company":
        wid = _maybe_uuid(scope_id)
        if wid is None:
            raise ValueError("company scope requires a valid scope_id")
        entity_kwargs = {"workspace_id": wid}
        scope_filter_sql = " AND workspace_id = :scope_id"
        scope_params = {"scope_id": wid}
        child_col = "project_id"
        child_label_fn = _project_labels
        child_scope_kwarg = "project_id"
    elif scope == "team":
        pid = _maybe_uuid(scope_id)
        if pid is None:
            raise ValueError("team scope requires a valid scope_id")
        entity_kwargs = {"project_id": pid}
        scope_filter_sql = " AND project_id = :scope_id"
        scope_params = {"scope_id": pid}
        child_col = "user_id"
        child_label_fn = _user_labels
        child_scope_kwarg = "user_id"
    else:  # user
        uid = _maybe_uuid(scope_id)
        if uid is None:
            raise ValueError("user scope requires a valid scope_id")
        entity_kwargs = {"user_id": uid}
        scope_filter_sql = " AND user_id = :scope_id"
        scope_params = {"scope_id": uid}
        child_col = None
        child_label_fn = None
        child_scope_kwarg = None

    series = UsageLogModel.usage_series(granularity, frm_dt, to_dt, **entity_kwargs)
    totals = UsageLogModel.usage_totals(frm_dt, to_dt, **entity_kwargs)
    previous = UsageLogModel.usage_previous_totals(frm_dt, to_dt, **entity_kwargs)
    deltas = _deltas(totals, previous)

    # Mask cost across every cost-bearing surface when not visible. The primitives
    # now also carry ``upstream`` (true cost) — derive the margin triplet onto each
    # surface ONLY for a margin-visible (super-admin) viewer, and drop the raw
    # ``upstream`` otherwise so marked-up price never leaks against true cost.
    series_out = []
    for pt in series:
        out_pt = {k: v for k, v in pt.items() if k != "upstream"}
        out_pt["cost"] = pt["cost"] if cost_visible else None
        if margin_visible:
            out_pt.update(_margin_fields(pt["cost"], pt["upstream"]))
        series_out.append(out_pt)

    totals_out = _mask_metrics(totals, cost_visible)
    totals_out.pop("upstream", None)
    previous_out = _mask_metrics(previous, cost_visible)
    previous_out.pop("upstream", None)
    if margin_visible:
        totals_out.update(_margin_fields(totals["cost"], totals["upstream"]))
        previous_out.update(_margin_fields(previous["cost"], previous["upstream"]))
    if not cost_visible:
        deltas["cost"] = {"abs": None, "pct": None}

    # Children (non-leaf scopes only).
    children = None
    if child_col is not None:
        children = _build_children(
            child_col, frm_dt, to_dt, scope_filter_sql, scope_params,
            child_label_fn, child_scope_kwarg, cost_visible, margin_visible,
        )

    # by_model breakdown (on request; always carried for the user leaf).
    by_model = None
    if breakdown == "model" or scope == "user":
        by_model = _by_model(frm_dt, to_dt, scope_filter_sql, scope_params,
                             cost_visible, margin_visible)

    return {
        "scope": scope,
        "scope_id": str(scope_id) if scope_id else None,
        "granularity": granularity,
        "window": {
            "from": frm_dt.strftime("%Y-%m-%d"),
            "to": to_dt.strftime("%Y-%m-%d"),
        },
        "series": series_out,
        "totals": totals_out,
        "previous": previous_out,
        "deltas": deltas,
        "breakdown": {
            "by_model": by_model,
            "children": children,
        },
        "cost_visible": cost_visible,
        "margin_visible": margin_visible,
    }


# ===========================================================================
# P6 — Budgets + alerts (read-only over usage_logs + the workspace budget /
# spend-cap config stored in workspaces.settings JSONB).
# ===========================================================================
def _month_bounds(now: datetime) -> tuple[datetime, datetime, float, int]:
    """``(month_start, now, days_elapsed, days_in_month)`` for the calendar
    month containing ``now``.

    Both bounds are **tz-aware UTC** so the ``created_at`` (``timestamptz``)
    comparison is unambiguous regardless of the DB session's timezone — a naive
    bound would be coerced into the session tz (e.g. ``Asia/Tehran`` on a dev
    box) and silently skew the month window. ``days_elapsed`` is floored at a
    fraction of a day so the first minutes of the month don't divide by ~0.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    elapsed_secs = (now - month_start).total_seconds()
    days_elapsed = max(elapsed_secs / 86400.0, 1.0 / 24.0)
    return month_start, now, days_elapsed, days_in_month


def _project_month_end(spend_mtd: float, days_elapsed: float,
                       days_in_month: int) -> float:
    """Linear month-end projection: current burn-rate * full month length."""
    if days_elapsed <= 0:
        return spend_mtd
    burn_rate = spend_mtd / days_elapsed
    return round(burn_rate * days_in_month, 6)


def _cap_breaches(group_col: str, frm, to, parent_filter_sql: str,
                  parent_params: dict, cap: float, label_fn) -> list:
    """Per-child MTD spend rows that meet/exceed ``cap`` (descending by spend).

    ``group_col`` is the grouping column (``user_id`` | ``model``); ``label_fn``
    maps the breaching ids to display labels (``None`` for the model split,
    which is already human-ish). Read-only single GROUP BY pass over the month.
    """
    sql = f"""
        SELECT {group_col} AS child_id, COALESCE(SUM(cost_usd), 0) AS cost
        FROM usage_logs
        WHERE created_at >= :frm AND created_at <= :to{parent_filter_sql}
          AND {group_col} IS NOT NULL
        GROUP BY {group_col}
        HAVING COALESCE(SUM(cost_usd), 0) >= :cap
        ORDER BY cost DESC
    """
    params = {"frm": frm, "to": to, "cap": cap, **parent_params}
    rows = db.session.execute(_sql_text(sql), params).all()
    if not rows:
        return []
    ids = [str(r.child_id) for r in rows]
    labels = label_fn(ids) if label_fn else {}
    return [
        {
            "id": str(r.child_id),
            "label": labels.get(str(r.child_id)) or str(r.child_id),
            "spend": float(r.cost or 0),
            "cap": cap,
        }
        for r in rows
    ]


def budget(scope_id, viewer: dict | None = None,
           cost_visible: bool | None = None) -> dict | None:
    """Month-to-date budget posture for one workspace (company scope).

    Returns ``None`` when the workspace can't be resolved. Shape::

        {
          "workspace_id": "<uuid>",
          "budget_mtd_usd": 500.0,          # 0 == no workspace budget set
          "spend_mtd_usd": 123.4,
          "burn_rate_usd_per_day": 8.2,
          "projected_month_end_usd": 246.0,
          "over_budget": false,             # spend already exceeds the budget
          "projected_over_budget": false,   # projection exceeds the budget
          "budget_used_pct": 24.7,          # null when no budget set
          "caps": {
            "per_user_usd": 50.0, "per_model_usd": null,
            "user_breaches": [{id,label,spend,cap}], "model_breaches": [...]
          },
          "cost_visible": true
        }

    READ-ONLY: aggregates ``usage_logs`` + reads the budget/cap config the owner
    persisted in ``workspaces.settings``. NEVER writes ``usage_logs``.

    ``cost_visible`` may be forced (the owner billing tab is its own $-tier);
    when ``None`` it derives from ``viewer`` like the rest of the service.
    """
    wid = _maybe_uuid(scope_id)
    if wid is None:
        return None
    ws = WorkspaceModel.find_by_id(str(wid))
    if not ws:
        return None

    if cost_visible is None:
        cost_visible = _viewer_cost_visible(viewer)

    now = datetime.now(timezone.utc)
    month_start, to_dt, days_elapsed, days_in_month = _month_bounds(now)

    spend_mtd = float(UsageLogModel.aggregate_workspace_spend(
        wid, start=month_start, end=to_dt
    ))
    burn_rate = round(spend_mtd / days_elapsed, 6) if days_elapsed else 0.0
    projected = _project_month_end(spend_mtd, days_elapsed, days_in_month)

    budget_amt = float(ws.get("budget_mtd_usd") or 0.0)
    over_budget = bool(budget_amt) and spend_mtd > budget_amt
    projected_over = bool(budget_amt) and projected > budget_amt
    used_pct = (
        round((spend_mtd / budget_amt) * 100, 2) if budget_amt else None
    )

    caps = ws.get("spend_caps") or {}
    per_user_cap = _coerce_cap(caps.get("per_user_usd"))
    per_model_cap = _coerce_cap(caps.get("per_model_usd"))

    scope_filter = " AND workspace_id = :scope_id"
    scope_params = {"scope_id": wid}
    user_breaches = (
        _cap_breaches("user_id", month_start, to_dt, scope_filter,
                      scope_params, per_user_cap, _user_labels)
        if per_user_cap else []
    )
    model_breaches = (
        _cap_breaches("model", month_start, to_dt, scope_filter,
                      scope_params, per_model_cap, None)
        if per_model_cap else []
    )

    enforced = _enforced_breaches(wid, cost_visible)

    return {
        "workspace_id": str(wid),
        "month_start": month_start.strftime("%Y-%m-%d"),
        "budget_mtd_usd": budget_amt if cost_visible else None,
        "spend_mtd_usd": spend_mtd if cost_visible else None,
        "burn_rate_usd_per_day": burn_rate if cost_visible else None,
        "projected_month_end_usd": projected if cost_visible else None,
        "over_budget": over_budget,
        "projected_over_budget": projected_over,
        "budget_used_pct": used_pct,
        "caps": {
            "per_user_usd": per_user_cap,
            "per_model_usd": per_model_cap,
            "user_breaches": user_breaches if cost_visible else [],
            "model_breaches": model_breaches if cost_visible else [],
        },
        "enforced": enforced,
        "cost_visible": cost_visible,
    }


def _enforced_breaches(wid, cost_visible: bool) -> dict:
    """ENFORCED-budget breaches for a company — the hierarchical-billing layer.

    READ-ONLY: reads the live ``billing_enforcement`` flag and compares the
    ENABLED ``budget_allocations`` ceilings for the workspace's teams (projects)
    and members (user budgets) against their current-month ``spend_rollups``
    counters — NEVER ``SUM(usage_logs)``. Only rows where ``spend >= budget`` are
    reported. ``$`` fields (``budget`` / ``spend``) are masked to ``None`` when
    the viewer can't see cost, matching the rest of ``budget()``.
    """
    from app.models.budget_allocation import BudgetAllocationModel
    from app.models.platform_settings import PlatformSettingsModel
    from app.models.project import ProjectModel
    from app.models.spend_rollup import SpendRollupModel
    from app.models.workspace_member import WorkspaceMemberModel

    enabled = bool(
        PlatformSettingsModel.get_features().get("billing_enforcement", False)
    )
    current_month = SpendRollupModel.current_period_month()

    # TEAM breaches — the workspace's projects with an enabled team budget.
    # One batched IN-read of the budgeted scope_ids' rollups (no per-id loop),
    # compared in Python against the already-batched allocations.
    projects = ProjectModel.find_by_workspace(str(wid))
    pids = [p["_id"] for p in projects if p.get("_id")]
    team_budgets = BudgetAllocationModel.list_for_scope_ids("team", pids)
    team_spend = SpendRollupModel.get_spent_bulk(
        "team", list(team_budgets.keys()), current_month
    )
    team_breaches = []
    for pid_str, alloc in team_budgets.items():
        budget = alloc.get("amount_usd")
        if budget is None:
            continue
        spend = team_spend.get(pid_str, 0.0)
        if spend >= budget:
            team_breaches.append({
                "project_id": pid_str,
                "budget": budget if cost_visible else None,
                "spend": spend if cost_visible else None,
            })

    # USER breaches — the workspace's members with an enabled user budget.
    members = WorkspaceMemberModel.find_by_workspace(str(wid))
    uids = [m["user_id"] for m in members if m.get("user_id")]
    user_budgets = BudgetAllocationModel.list_for_scope_ids("user", uids)
    user_spend = SpendRollupModel.get_spent_bulk(
        "user", list(user_budgets.keys()), current_month
    )
    user_breaches = []
    for uid_str, alloc in user_budgets.items():
        budget = alloc.get("amount_usd")
        if budget is None:
            continue
        spend = user_spend.get(uid_str, 0.0)
        if spend >= budget:
            user_breaches.append({
                "user_id": uid_str,
                "budget": budget if cost_visible else None,
                "spend": spend if cost_visible else None,
            })

    return {
        "enabled": enabled,
        "team_breaches": team_breaches,
        "user_breaches": user_breaches,
    }


__all__ = ["usage", "budget", "VALID_SCOPES", "VALID_GRANULARITIES"]
