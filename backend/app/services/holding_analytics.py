"""Holding-wide analytics service.

Single source of truth for the cross-company aggregations consumed by the
super-admin panels (`/api/admin/companies*`, `/api/admin/users-overview`,
`/api/admin/holding/*`).

Pure data layer — returns JSON-serialisable dicts. No request/decorator concerns.

Phase 5: all aggregations run on Postgres via SQLAlchemy. Mongo imports are
retained only for the Phase 7 cleanup pass.
"""

from datetime import datetime, timedelta
import uuid

from bson import ObjectId  # noqa: F401 — retained for Phase 7
from sqlalchemy import func, or_, select

from app.extensions import db, mongo  # noqa: F401 — `mongo` retained for Phase 7
from app.models.audit_log import AuditLog
from app.models.conversation import Conversation
from app.models.credit_ledger import CreditLedgerModel
from app.models.project import Project
from app.models.usage_log import UsageLog
from app.models.user import User, VALID_USER_ROLES
from app.models.workspace import Workspace
from app.models.workspace_member import WorkspaceMember


def _maybe_uuid(val):
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except Exception:
        return None


def _empty_totals(days: int = 30) -> dict:
    return {
        'companies': 0, 'members': 0, 'projects': 0, 'conversations': 0,
        f'cost_{days}d': 0.0, f'tokens_{days}d': 0, f'calls_{days}d': 0,
        'credits_balance_usd': 0.0,
    }


def list_companies(days: int = 30) -> dict:
    """Return aggregated stats for every team workspace."""
    cutoff = datetime.utcnow() - timedelta(days=days)

    workspaces = db.session.execute(
        select(Workspace)
        .where(Workspace.is_personal.is_(False))
        .order_by(Workspace.created_at.desc())
    ).scalars().all()
    if not workspaces:
        return {'companies': [], 'totals': _empty_totals(days), 'days': days}

    wids = [w.id for w in workspaces]

    # Member counts (active only).
    member_counts: dict = {}
    for row in db.session.execute(
        select(WorkspaceMember.workspace_id, func.count().label('c'))
        .where(WorkspaceMember.workspace_id.in_(wids),
               WorkspaceMember.status == 'active')
        .group_by(WorkspaceMember.workspace_id)
    ).all():
        member_counts[row.workspace_id] = int(row.c)

    # Project counts (active only).
    project_counts: dict = {}
    for row in db.session.execute(
        select(Project.workspace_id, func.count().label('c'))
        .where(Project.workspace_id.in_(wids), Project.archived.is_(False))
        .group_by(Project.workspace_id)
    ).all():
        project_counts[row.workspace_id] = int(row.c)

    # Conversation counts (via conversations → projects → workspace).
    conv_counts: dict = {}
    for row in db.session.execute(
        select(Project.workspace_id, func.count(Conversation.id).label('c'))
        .join(Conversation, Conversation.project_id == Project.id)
        .where(Project.workspace_id.in_(wids))
        .group_by(Project.workspace_id)
    ).all():
        conv_counts[row.workspace_id] = int(row.c)

    # Usage rollup.
    usage: dict = {}
    for row in db.session.execute(
        select(
            UsageLog.workspace_id,
            func.coalesce(func.sum(UsageLog.cost_usd), 0).label('cost_usd'),
            func.coalesce(
                func.sum(UsageLog.input_tokens + UsageLog.output_tokens), 0
            ).label('tokens'),
            func.count().label('calls'),
        )
        .where(UsageLog.workspace_id.in_(wids), UsageLog.created_at >= cutoff)
        .group_by(UsageLog.workspace_id)
    ).all():
        usage[row.workspace_id] = row

    out = []
    for w in workspaces:
        u = usage.get(w.id)
        settings = w.settings or {}
        out.append({
            '_id': str(w.id),
            'name': w.display_name or settings.get('name') or '',
            'slug': w.slug,
            'domain': settings.get('domain'),
            'created_at': w.created_at,
            'owner_id': str(w.owner_user_id) if w.owner_user_id else None,
            'plan_tier': settings.get('plan_tier') or settings.get('plan') or 'free',
            'credits_balance_usd': float(w.credits_balance_usd or 0),
            'member_count': member_counts.get(w.id, 0),
            'project_count': project_counts.get(w.id, 0),
            'conversation_count': conv_counts.get(w.id, 0),
            f'usage_{days}d': {
                'cost_usd': round(float(u.cost_usd) if u else 0.0, 4),
                'tokens':   int(u.tokens) if u else 0,
                'calls':    int(u.calls) if u else 0,
            },
        })

    totals = {
        'companies': len(workspaces),
        'members':   sum(member_counts.values()),
        'projects':  sum(project_counts.values()),
        'conversations': sum(conv_counts.values()),
        f'cost_{days}d':   round(sum(float(v.cost_usd or 0) for v in usage.values()), 4),
        f'tokens_{days}d': sum(int(v.tokens or 0) for v in usage.values()),
        f'calls_{days}d':  sum(int(v.calls or 0) for v in usage.values()),
        'credits_balance_usd': round(
            sum(float(w.credits_balance_usd or 0) for w in workspaces), 2
        ),
    }

    return {'companies': out, 'totals': totals, 'days': days}


def company_detail(wid, days: int = 30):
    """Per-company drill-down. Returns ``None`` if workspace not found."""
    ws_uuid = _maybe_uuid(wid)
    if ws_uuid is None:
        return None

    cutoff = datetime.utcnow() - timedelta(days=days)

    workspace = db.session.execute(
        select(Workspace).where(Workspace.id == ws_uuid)
    ).scalar_one_or_none()
    if workspace is None:
        return None

    projects = db.session.execute(
        select(Project).where(Project.workspace_id == ws_uuid)
    ).scalars().all()
    project_ids = [p.id for p in projects]

    project_usage: dict = {}
    if project_ids:
        for row in db.session.execute(
            select(
                UsageLog.project_id,
                func.coalesce(func.sum(UsageLog.cost_usd), 0).label('cost_usd'),
                func.coalesce(
                    func.sum(UsageLog.input_tokens + UsageLog.output_tokens), 0
                ).label('tokens'),
                func.count().label('calls'),
            )
            .where(UsageLog.project_id.in_(project_ids),
                   UsageLog.created_at >= cutoff)
            .group_by(UsageLog.project_id)
        ).all():
            project_usage[row.project_id] = row

    project_rows = []
    for p in projects:
        u = project_usage.get(p.id)
        settings = p.settings or {}
        project_rows.append({
            '_id': str(p.id),
            'name': p.name,
            'archived': bool(p.archived),
            'pinned': bool(settings.get('pinned') or False),
            'cost_usd': round(float(u.cost_usd) if u else 0.0, 4),
            'tokens': int(u.tokens) if u else 0,
            'calls': int(u.calls) if u else 0,
        })
    project_rows.sort(key=lambda r: r['cost_usd'], reverse=True)

    # Top users.
    top_users = []
    user_rollup = db.session.execute(
        select(
            UsageLog.user_id,
            func.coalesce(func.sum(UsageLog.cost_usd), 0).label('cost_usd'),
            func.count().label('calls'),
        )
        .where(UsageLog.workspace_id == ws_uuid, UsageLog.created_at >= cutoff)
        .group_by(UsageLog.user_id)
        .order_by(func.coalesce(func.sum(UsageLog.cost_usd), 0).desc())
        .limit(10)
    ).all()
    if user_rollup:
        uids = [r.user_id for r in user_rollup if r.user_id is not None]
        users_map = {}
        if uids:
            users_map = {
                u.id: u for u in db.session.execute(
                    select(User).where(User.id.in_(uids))
                ).scalars().all()
            }
        for r in user_rollup:
            u = users_map.get(r.user_id)
            display_name = None
            email = None
            role = None
            if u is not None:
                email = u.email
                role = u.role
                display_name = u.display_name or (u.profile or {}).get('display_name')
            top_users.append({
                '_id': str(r.user_id) if r.user_id else None,
                'email': email,
                'name': display_name,
                'role': role,
                'cost_usd': round(float(r.cost_usd or 0), 4),
                'calls': int(r.calls or 0),
            })

    # Top models.
    top_models = []
    for row in db.session.execute(
        select(
            UsageLog.model,
            func.coalesce(func.sum(UsageLog.cost_usd), 0).label('cost_usd'),
            func.count().label('calls'),
        )
        .where(UsageLog.workspace_id == ws_uuid, UsageLog.created_at >= cutoff)
        .group_by(UsageLog.model)
        .order_by(func.coalesce(func.sum(UsageLog.cost_usd), 0).desc())
        .limit(8)
    ).all():
        top_models.append({
            'model': row.model,
            'cost_usd': round(float(row.cost_usd or 0), 4),
            'calls': int(row.calls or 0),
        })

    # By role — join usage → users, group_by (role, user_id) then re-roll on role.
    by_role = {'admin': {'cost_usd': 0.0, 'tokens': 0, 'calls': 0, 'users': 0},
               'manager': {'cost_usd': 0.0, 'tokens': 0, 'calls': 0, 'users': 0},
               'user':    {'cost_usd': 0.0, 'tokens': 0, 'calls': 0, 'users': 0}}
    inner = (
        select(
            func.coalesce(User.role, 'user').label('role'),
            UsageLog.user_id.label('user_id'),
            func.coalesce(func.sum(UsageLog.cost_usd), 0).label('cost_usd'),
            func.coalesce(
                func.sum(UsageLog.input_tokens + UsageLog.output_tokens), 0
            ).label('tokens'),
            func.count().label('calls'),
        )
        .select_from(UsageLog)
        .outerjoin(User, UsageLog.user_id == User.id)
        .where(UsageLog.workspace_id == ws_uuid, UsageLog.created_at >= cutoff)
        .group_by(User.role, UsageLog.user_id)
        .subquery()
    )
    for row in db.session.execute(
        select(
            inner.c.role,
            func.coalesce(func.sum(inner.c.cost_usd), 0).label('cost_usd'),
            func.coalesce(func.sum(inner.c.tokens), 0).label('tokens'),
            func.coalesce(func.sum(inner.c.calls), 0).label('calls'),
            func.count().label('users'),
        ).group_by(inner.c.role)
    ).all():
        role = (row.role or 'user').lower()
        if role not in by_role:
            role = 'user'
        by_role[role] = {
            'cost_usd': round(float(row.cost_usd or 0), 4),
            'tokens':   int(row.tokens or 0),
            'calls':    int(row.calls or 0),
            'users':    int(row.users or 0),
        }

    # Daily fill — first roll usage by day, then 0-fill the missing days.
    daily_raw: dict = {}
    day_expr = func.to_char(UsageLog.created_at, 'YYYY-MM-DD').label('day')
    for row in db.session.execute(
        select(
            day_expr,
            func.coalesce(func.sum(UsageLog.cost_usd), 0).label('cost_usd'),
            func.coalesce(
                func.sum(UsageLog.input_tokens + UsageLog.output_tokens), 0
            ).label('tokens'),
            func.count().label('calls'),
        )
        .where(UsageLog.workspace_id == ws_uuid, UsageLog.created_at >= cutoff)
        .group_by('day')
    ).all():
        daily_raw[row.day] = row
    daily = []
    for i in range(days):
        d = (datetime.utcnow() - timedelta(days=days - i - 1)).strftime('%Y-%m-%d')
        r = daily_raw.get(d)
        daily.append({
            'date': d,
            'cost_usd': round(float(r.cost_usd) if r else 0.0, 4),
            'tokens':   int(r.tokens) if r else 0,
            'calls':    int(r.calls) if r else 0,
        })

    # Credits block.
    lifetime_topups = float(CreditLedgerModel.sum_credits(ws_uuid))
    lifetime_spend = float(db.session.execute(
        select(func.coalesce(func.sum(UsageLog.cost_usd), 0))
        .where(UsageLog.workspace_id == ws_uuid)
    ).scalar() or 0)
    credits_block = {
        'lifetime_topups_usd': round(lifetime_topups, 4),
        'lifetime_spend_usd':  round(lifetime_spend, 4),
        'remaining_usd':       round(lifetime_topups - lifetime_spend, 4),
        'balance_field':       float(workspace.credits_balance_usd or 0),
    }

    # Recent ledger entries (use the model API; hydrate admin info).
    recent_rows = CreditLedgerModel.find_by_workspace(ws_uuid, limit=5)
    uid_objs = [_maybe_uuid(r.get('added_by')) for r in recent_rows if r.get('added_by')]
    uid_objs = [u for u in uid_objs if u is not None]
    user_map: dict = {}
    if uid_objs:
        for u in db.session.execute(
            select(User).where(User.id.in_(uid_objs))
        ).scalars().all():
            user_map[u.id] = {
                'email': u.email,
                'display_name': u.display_name or (u.profile or {}).get('display_name'),
            }
    recent_ledger = []
    for r in recent_rows:
        added_by_uuid = _maybe_uuid(r.get('added_by'))
        info = user_map.get(added_by_uuid, {}) if added_by_uuid else {}
        recent_ledger.append({
            '_id': str(r['_id']),
            'amount_usd': float(r.get('amount_usd') or 0),
            'type': r.get('type'),
            'note': r.get('note') or '',
            'created_at': r.get('created_at'),
            'added_by': {
                'id': str(added_by_uuid) if added_by_uuid else None,
                'email': info.get('email'),
                'display_name': info.get('display_name'),
            },
        })

    member_count = int(db.session.execute(
        select(func.count()).select_from(WorkspaceMember).where(
            WorkspaceMember.workspace_id == ws_uuid,
            WorkspaceMember.status == 'active',
        )
    ).scalar() or 0)

    # Serialize workspace to a Mongo-like dict for back-compat consumers.
    ws_settings = workspace.settings or {}
    workspace_doc = {
        '_id': str(workspace.id),
        'id': str(workspace.id),
        'slug': workspace.slug,
        'name': workspace.display_name or ws_settings.get('name') or '',
        'type': 'personal' if workspace.is_personal else 'team',
        'owner_id': str(workspace.owner_user_id) if workspace.owner_user_id else None,
        'created_at': workspace.created_at,
        'updated_at': workspace.updated_at,
        'plan': ws_settings.get('plan') or 'free',
        'plan_tier': ws_settings.get('plan_tier') or 'free',
        'domain': ws_settings.get('domain'),
        'credits_balance_usd': float(workspace.credits_balance_usd or 0),
        'avatar': workspace.avatar or {},
        'settings': ws_settings,
        'ip_allowlist': workspace.ip_allowlist or [],
    }

    return {
        'workspace': workspace_doc,
        'days': days,
        'member_count': member_count,
        'project_count': len([p for p in projects if not p.archived]),
        'projects': project_rows,
        'top_users': top_users,
        'top_models': top_models,
        'by_role': by_role,
        'daily': daily,
        'credits': credits_block,
        'recent_ledger': recent_ledger,
    }


def users_overview(days: int = 30, page: int = 1, limit: int = 50,
                   search: str = '', role: str = '') -> dict:
    """Holding-wide per-user usage rollup. Raises ``ValueError`` for bad role.

    Rank + paginate run in Postgres: the page query LEFT JOINs a per-user usage
    aggregate (windowed to ``cutoff``), orders by cost desc, and applies SQL
    LIMIT/OFFSET so only the page's rows are materialised — not the whole user
    table. ``total`` and ``totals`` are two separate aggregate queries over the
    full filtered set. Response JSON shape is byte-identical to the prior
    all-in-Python implementation.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    page = max(1, int(page))
    limit = max(1, min(200, int(limit)))
    skip = (page - 1) * limit

    # Build the User filter once; reused by the page query, the count, and the
    # totals aggregate so all three see exactly the same matched set.
    conditions = []
    role = (role or '').strip().lower() or None
    if role:
        if role not in VALID_USER_ROLES:
            raise ValueError(f"role must be one of {sorted(VALID_USER_ROLES)}")
        conditions.append(User.role == role)
    search = (search or '').strip()
    if search:
        like = f'%{search}%'
        # NB: matches the Mongo behaviour where both `email` and
        # `profile.display_name` were searched.
        conditions.append(or_(
            User.email.ilike(like),
            User.display_name.ilike(like),
            func.coalesce(User.profile['display_name'].astext, '').ilike(like),
        ))

    # Per-user usage aggregate (windowed). Grouped subquery joined per user, so
    # the cost/token/call columns + the cost ranking come straight from SQL.
    usage_subq = (
        select(
            UsageLog.user_id.label('uid'),
            func.coalesce(func.sum(UsageLog.cost_usd), 0).label('cost_usd'),
            func.coalesce(
                func.sum(UsageLog.input_tokens + UsageLog.output_tokens), 0
            ).label('tokens'),
            func.count().label('calls'),
        )
        .where(UsageLog.created_at >= cutoff)
        .group_by(UsageLog.user_id)
        .subquery()
    )

    total = int(db.session.execute(
        select(func.count()).select_from(User).where(*conditions)
    ).scalar() or 0)
    if total == 0:
        return {
            'users': [], 'total': 0, 'page': page, 'limit': limit, 'days': days,
            'totals': {'cost_usd': 0.0, 'tokens': 0, 'calls': 0, 'users': 0},
        }

    # Totals = cost/tokens/calls summed over the WHOLE filtered set (not the
    # page). One aggregate over the same User⋈usage join.
    totals_row = db.session.execute(
        select(
            func.coalesce(func.sum(usage_subq.c.cost_usd), 0).label('cost_usd'),
            func.coalesce(func.sum(usage_subq.c.tokens), 0).label('tokens'),
            func.coalesce(func.sum(usage_subq.c.calls), 0).label('calls'),
        )
        .select_from(User)
        .outerjoin(usage_subq, usage_subq.c.uid == User.id)
        .where(*conditions)
    ).one()

    # Page query: rank by cost desc, SQL LIMIT/OFFSET. ``coalesce(cost,0)`` so
    # zero-usage users sort with 0-cost users at the bottom (as before); the
    # created_at tiebreaker makes the page order deterministic (the prior
    # Python stable-sort left ties in DB-arbitrary order).
    cost_rank = func.coalesce(usage_subq.c.cost_usd, 0)
    page_result = db.session.execute(
        select(
            User.id,
            User.email,
            User.display_name,
            User.role,
            User.profile,
            User.status,
            User.usage,
            User.created_at,
            func.coalesce(usage_subq.c.cost_usd, 0).label('cost_usd'),
            func.coalesce(usage_subq.c.tokens, 0).label('tokens'),
            func.coalesce(usage_subq.c.calls, 0).label('calls'),
        )
        .select_from(User)
        .outerjoin(usage_subq, usage_subq.c.uid == User.id)
        .where(*conditions)
        .order_by(cost_rank.desc(), User.created_at.desc())
        .offset(skip)
        .limit(limit)
    ).all()

    # Workspace counts: batched point-read on the page's user ids only.
    page_user_ids = [r.id for r in page_result]
    ws_counts: dict = {}
    if page_user_ids:
        for row in db.session.execute(
            select(WorkspaceMember.user_id, func.count().label('c'))
            .where(WorkspaceMember.user_id.in_(page_user_ids),
                   WorkspaceMember.status == 'active')
            .group_by(WorkspaceMember.user_id)
        ).all():
            ws_counts[row.user_id] = int(row.c)

    page_rows = []
    for r in page_result:
        prof = r.profile or {}
        status = r.status or {}
        usage_blob = r.usage or {}
        page_rows.append({
            '_id': str(r.id),
            'email': r.email,
            'display_name': r.display_name or prof.get('display_name'),
            'role': r.role or 'user',
            'is_banned': bool(status.get('is_banned')),
            'last_active': usage_blob.get('last_active'),
            'created_at': r.created_at,
            'workspaces_count': ws_counts.get(r.id, 0),
            'cost_usd': round(float(r.cost_usd or 0), 4),
            'tokens':   int(r.tokens or 0),
            'calls':    int(r.calls or 0),
        })

    totals = {
        'users': total,
        'cost_usd': round(float(totals_row.cost_usd or 0), 4),
        'tokens':   int(totals_row.tokens or 0),
        'calls':    int(totals_row.calls or 0),
    }

    return {
        'users': page_rows,
        'total': total,
        'page': page,
        'limit': limit,
        'days': days,
        'totals': totals,
    }


def holding_overview(days: int = 30) -> dict:
    """Holding-wide rollup: counts + per-window cost/calls/tokens, daily series, top companies/models, holding-credits."""
    from app.models.platform_settings import PlatformSettingsModel

    cutoff = datetime.utcnow() - timedelta(days=days)

    workspaces_count = int(db.session.execute(
        select(func.count()).select_from(Workspace)
    ).scalar() or 0)
    projects_count = int(db.session.execute(
        select(func.count()).select_from(Project)
    ).scalar() or 0)
    users_count = int(db.session.execute(
        select(func.count()).select_from(User)
    ).scalar() or 0)
    conversations_count = int(db.session.execute(
        select(func.count()).select_from(Conversation)
    ).scalar() or 0)

    ceo = None
    ceo_row = db.session.execute(
        select(User).where(User.role == 'admin').order_by(User.created_at.asc()).limit(1)
    ).scalar_one_or_none()
    if ceo_row is not None:
        prof = ceo_row.profile or {}
        ceo = {
            'email': ceo_row.email,
            'display_name': ceo_row.display_name or prof.get('display_name'),
        }

    totals_row = db.session.execute(
        select(
            func.coalesce(func.sum(UsageLog.cost_usd), 0).label('cost_usd'),
            func.coalesce(
                func.sum(UsageLog.input_tokens + UsageLog.output_tokens), 0
            ).label('tokens'),
            func.count().label('calls'),
        ).where(UsageLog.created_at >= cutoff)
    ).one()
    totals = {
        'cost_usd': round(float(totals_row.cost_usd or 0), 4),
        'tokens':   int(totals_row.tokens or 0),
        'calls':    int(totals_row.calls or 0),
    }

    daily_raw: dict = {}
    day_expr = func.to_char(UsageLog.created_at, 'YYYY-MM-DD').label('day')
    for row in db.session.execute(
        select(
            day_expr,
            func.coalesce(func.sum(UsageLog.cost_usd), 0).label('cost_usd'),
            func.coalesce(
                func.sum(UsageLog.input_tokens + UsageLog.output_tokens), 0
            ).label('tokens'),
            func.count().label('calls'),
        )
        .where(UsageLog.created_at >= cutoff)
        .group_by('day')
    ).all():
        daily_raw[row.day] = row
    daily = []
    for i in range(days):
        d = (datetime.utcnow() - timedelta(days=days - i - 1)).strftime('%Y-%m-%d')
        r = daily_raw.get(d)
        daily.append({
            'date': d,
            'cost_usd': round(float(r.cost_usd) if r else 0.0, 4),
            'tokens':   int(r.tokens) if r else 0,
            'calls':    int(r.calls) if r else 0,
        })

    top_companies = []
    company_rollup = db.session.execute(
        select(
            UsageLog.workspace_id,
            func.coalesce(func.sum(UsageLog.cost_usd), 0).label('cost_usd'),
            func.count().label('calls'),
        )
        .where(UsageLog.workspace_id.isnot(None),
               UsageLog.created_at >= cutoff)
        .group_by(UsageLog.workspace_id)
        .order_by(func.coalesce(func.sum(UsageLog.cost_usd), 0).desc())
        .limit(8)
    ).all()
    if company_rollup:
        wids = [r.workspace_id for r in company_rollup if r.workspace_id]
        ws_map = {}
        if wids:
            for w in db.session.execute(
                select(Workspace).where(Workspace.id.in_(wids))
            ).scalars().all():
                ws_map[w.id] = w
        for r in company_rollup:
            w = ws_map.get(r.workspace_id)
            settings = (w.settings or {}) if w is not None else {}
            if w is not None:
                name = w.display_name or settings.get('name') or '—'
                domain = settings.get('domain') or w.slug
            else:
                name = '—'
                domain = None
            top_companies.append({
                '_id': str(r.workspace_id) if r.workspace_id else None,
                'name': name,
                'domain': domain,
                'cost_usd': round(float(r.cost_usd or 0), 4),
                'calls': int(r.calls or 0),
            })

    top_models = []
    for row in db.session.execute(
        select(
            UsageLog.model,
            func.coalesce(func.sum(UsageLog.cost_usd), 0).label('cost_usd'),
            func.count().label('calls'),
        )
        .where(UsageLog.created_at >= cutoff)
        .group_by(UsageLog.model)
        .order_by(func.coalesce(func.sum(UsageLog.cost_usd), 0).desc())
        .limit(8)
    ).all():
        top_models.append({
            'model': row.model,
            'cost_usd': round(float(row.cost_usd or 0), 4),
            'calls': int(row.calls or 0),
        })

    # By role — same pattern as company_detail, but unscoped on workspace.
    by_role_doc = {'admin': {'cost_usd': 0.0, 'tokens': 0, 'calls': 0, 'users': 0},
                   'manager': {'cost_usd': 0.0, 'tokens': 0, 'calls': 0, 'users': 0},
                   'user':    {'cost_usd': 0.0, 'tokens': 0, 'calls': 0, 'users': 0}}
    inner = (
        select(
            func.coalesce(User.role, 'user').label('role'),
            UsageLog.user_id.label('user_id'),
            func.coalesce(func.sum(UsageLog.cost_usd), 0).label('cost_usd'),
            func.coalesce(
                func.sum(UsageLog.input_tokens + UsageLog.output_tokens), 0
            ).label('tokens'),
            func.count().label('calls'),
        )
        .select_from(UsageLog)
        .outerjoin(User, UsageLog.user_id == User.id)
        .where(UsageLog.created_at >= cutoff)
        .group_by(User.role, UsageLog.user_id)
        .subquery()
    )
    for row in db.session.execute(
        select(
            inner.c.role,
            func.coalesce(func.sum(inner.c.cost_usd), 0).label('cost_usd'),
            func.coalesce(func.sum(inner.c.tokens), 0).label('tokens'),
            func.coalesce(func.sum(inner.c.calls), 0).label('calls'),
            func.count().label('users'),
        ).group_by(inner.c.role)
    ).all():
        role = (row.role or 'user').lower()
        if role not in by_role_doc:
            role = 'user'
        by_role_doc[role] = {
            'cost_usd': round(float(row.cost_usd or 0), 4),
            'tokens':   int(row.tokens or 0),
            'calls':    int(row.calls or 0),
            'users':    int(row.users or 0),
        }

    settings_doc = PlatformSettingsModel.get()
    holding_topups = float((settings_doc or {}).get('holding_credits_topups_usd') or 0)
    holding_transferred = float((settings_doc or {}).get('holding_credits_transferred_usd') or 0)
    holding_lifetime_spend = float(db.session.execute(
        select(func.coalesce(func.sum(UsageLog.cost_usd), 0))
    ).scalar() or 0)
    holding_credits = {
        'lifetime_topups_usd': round(holding_topups, 4),
        'lifetime_spend_usd':  round(holding_lifetime_spend, 4),
        # Legacy advisory: pool topups − all-company usage. UNCHANGED semantics.
        'remaining_usd':       round(holding_topups - holding_lifetime_spend, 4),
        # Transfer accounting: credits moved out of the pool into company wallets,
        # and what remains transferable (topups − transferred).
        'transferred_usd':     round(holding_transferred, 4),
        'pool_remaining_usd':  round(holding_topups - holding_transferred, 4),
    }

    return {
        'workspaces_count': workspaces_count,
        'projects_count': projects_count,
        'users_count': users_count,
        'conversations_count': conversations_count,
        'ceo': ceo,
        'days': days,
        'totals': totals,
        'daily': daily,
        'top_companies': top_companies,
        'top_models': top_models,
        'by_role': by_role_doc,
        'holding_credits': holding_credits,
    }


# ---------------------------------------------------------------------------
# Holding-credit ledger (P2.32)
# ---------------------------------------------------------------------------

_HOLDING_LEDGER_ACTIONS = ('holding_credits_added', 'company_credits_transferred')


def holding_ledger(skip: int = 0, limit: int = 50) -> dict:
    """Return paginated holding-pool movement audit rows with actor metadata
    hydrated. This is the single touchpoint for the holding ledger so routes
    never hand-roll the aggregation (CLAUDE.md rule).

    Reads from ``audit_logs`` filtered to ``category='holding'`` plus the two
    movement actions; the actor (``admin_user_id`` → ``users.id``) is hydrated
    from ``users``. Two movement kinds appear, interleaved by time:
      * ``holding_credits_added``        — a top-up INTO the pool (positive).
      * ``company_credits_transferred``  — a transfer OUT of the pool into a
        company wallet (negative ``direction`` / signed ``amount_usd``).
    """
    skip = max(0, int(skip))
    limit = max(1, min(200, int(limit)))

    base = (
        select(AuditLog)
        .where(AuditLog.category == 'holding',
               AuditLog.action.in_(_HOLDING_LEDGER_ACTIONS))
    )
    rows = db.session.execute(
        base.order_by(AuditLog.created_at.desc()).offset(skip).limit(limit)
    ).scalars().all()

    actor_ids = list({r.admin_user_id for r in rows if r.admin_user_id is not None})
    actor_map: dict = {}
    if actor_ids:
        for u in db.session.execute(
            select(User).where(User.id.in_(actor_ids))
        ).scalars().all():
            prof = u.profile or {}
            actor_map[u.id] = {
                'email': u.email,
                'display_name': u.display_name or prof.get('display_name'),
            }

    entries = []
    for r in rows:
        info = actor_map.get(r.admin_user_id, {}) if r.admin_user_id else {}
        details = r.details or {}
        is_transfer = r.action == 'company_credits_transferred'
        raw_amount = float(details.get('amount_usd') or 0)
        # Transfers leave the pool: surface a negative signed amount + direction.
        signed_amount = -abs(raw_amount) if is_transfer else raw_amount
        entry = {
            '_id': str(r.id),
            'created_at': r.created_at,
            'action': r.action,
            'direction': 'out' if is_transfer else 'in',
            'amount_usd': signed_amount,
            'type': details.get('type'),
            'note': details.get('note') or '',
            'added_by': {
                'id': str(r.admin_user_id) if r.admin_user_id else None,
                'email': info.get('email'),
                'display_name': info.get('display_name'),
            },
        }
        if is_transfer:
            entry['workspace_id'] = str(r.target_id) if r.target_id else None
            entry['workspace_name'] = details.get('workspace_name')
        entries.append(entry)

    total = int(db.session.execute(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.category == 'holding',
            AuditLog.action.in_(_HOLDING_LEDGER_ACTIONS),
        )
    ).scalar() or 0)

    return {
        'entries': entries,
        'total': total,
        'skip': skip,
        'limit': limit,
    }
