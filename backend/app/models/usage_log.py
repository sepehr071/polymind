"""Usage logs — captures full OpenRouter cost data per request.

Phase 5: All aggregations now run on Postgres via SQLAlchemy. The Mongo
`mongo.db.usage_logs` accessor is retained per Phase 7 cleanup; nothing reads
it anymore.
"""

import uuid
from datetime import datetime, timedelta


def _to_uuid(val):
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except Exception:
        return None


class UsageLogModel:
    """Model for tracking API usage and costs."""
    collection_name = 'usage_logs'

    @staticmethod
    def create(
        user_id=None,
        conversation_id=None,
        model_id=None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cached_tokens: int = 0,
        cost_usd: float = 0.0,
        feature: str = None,
        response_usage: dict = None,
        # legacy positional compat — callers that pass (message_id, tokens dict) still work
        message_id=None,
        tokens: dict = None,
        # Phase 1 enterprise fields.
        generation_id: str = None,
        workspace_id=None,
        project_id=None,
        model: str = None,
        provider: str = None,
        cache_write_tokens: int = 0,
        reasoning_tokens: int = 0,
        upstream_cost_usd: float = None,
        is_streaming: bool = False,
        finish_reason: str = None,
        origin: str = 'web',
        data: dict = None,
        # NEW PG columns (Phase 3/4) — accepted directly when callers send them.
        image_tokens: int = 0,
        web_search_tokens: int = 0,
        total_tokens: int = 0,
        total_cost: float = None,
    ):
        """Log a usage entry to Postgres.

        Accepts legacy kwargs (``model_id``, ``tokens=dict``, ``total_cost``,
        ``cost_usd``, ``prompt_tokens`` / ``completion_tokens``) AND the new
        unsuffixed PG schema (``model``, ``input_tokens`` via ``prompt_tokens``,
        ``output_tokens`` via ``completion_tokens``, ``cost_usd``).
        """
        # Allow callers to pass a single ``data`` dict instead of kwargs.
        if data is not None and isinstance(data, dict):
            generation_id = data.get('generation_id', generation_id)
            user_id = data.get('user_id', user_id)
            workspace_id = data.get('workspace_id', workspace_id)
            project_id = data.get('project_id', project_id)
            model = data.get('model', model)
            provider = data.get('provider', provider)
            prompt_tokens = data.get('prompt_tokens', prompt_tokens)
            completion_tokens = data.get('completion_tokens', completion_tokens)
            cached_tokens = data.get('cached_tokens', cached_tokens)
            cache_write_tokens = data.get('cache_write_tokens', cache_write_tokens)
            reasoning_tokens = data.get('reasoning_tokens', reasoning_tokens)
            cost_usd = data.get('cost_usd', cost_usd)
            upstream_cost_usd = data.get('upstream_cost_usd', upstream_cost_usd)
            is_streaming = data.get('is_streaming', is_streaming)
            finish_reason = data.get('finish_reason', finish_reason)
            conversation_id = data.get('conversation_id', conversation_id)
            origin = data.get('origin', origin)
            image_tokens = data.get('image_tokens', image_tokens)
            web_search_tokens = data.get('web_search_tokens', web_search_tokens)
            total_tokens = data.get('total_tokens', total_tokens)
            total_cost = data.get('total_cost', total_cost)

        # Legacy shim: if caller passed the old `tokens` dict, extract fields.
        if tokens is not None and isinstance(tokens, dict):
            prompt_tokens = tokens.get('prompt', prompt_tokens) or 0
            completion_tokens = tokens.get('completion', completion_tokens) or 0
            cached_tokens = tokens.get('cached', cached_tokens) or 0
            reasoning_tokens = tokens.get('reasoning', reasoning_tokens) or 0
            image_tokens = tokens.get('image', image_tokens) or 0
            web_search_tokens = tokens.get('web_search', web_search_tokens) or 0
            if not total_tokens:
                total_tokens = tokens.get('total', 0) or 0

        prompt_tokens = int(prompt_tokens or 0)
        completion_tokens = int(completion_tokens or 0)
        cached_tokens = int(cached_tokens or 0)
        cache_write_tokens = int(cache_write_tokens or 0)
        reasoning_tokens = int(reasoning_tokens or 0)
        image_tokens = int(image_tokens or 0)
        web_search_tokens = int(web_search_tokens or 0)
        total_tokens = int(total_tokens or (prompt_tokens + completion_tokens))

        # Resolve model: prefer explicit ``model`` kwarg, fall back to model_id.
        resolved_model = model or model_id or 'unknown'
        if not provider and resolved_model and '/' in resolved_model:
            provider = resolved_model.split('/', 1)[0]

        # cost_usd vs total_cost: prefer cost_usd; fall back to total_cost.
        resolved_cost = cost_usd if cost_usd is not None else total_cost
        resolved_cost = float(resolved_cost or 0)

        # Convert IDs to UUID. We tolerate parse failures by leaving them None
        # (the columns are nullable). Pre-PG ObjectId hex strings from legacy
        # tests will simply not parse — that's fine, this is greenfield PG.
        user_uuid = _to_uuid(user_id)
        ws_uuid = _to_uuid(workspace_id)
        proj_uuid = _to_uuid(project_id)

        # Keep the original `tokens` dict shape for forward-compat consumers.
        tokens_payload = tokens if isinstance(tokens, dict) else {
            'prompt': prompt_tokens,
            'completion': completion_tokens,
            'cached': cached_tokens,
            'reasoning': reasoning_tokens,
            'image': image_tokens,
            'web_search': web_search_tokens,
            'total': total_tokens,
        }

        ul = UsageLog(
            user_id=user_uuid,
            workspace_id=ws_uuid,
            project_id=proj_uuid,
            model=resolved_model,
            provider=provider,
            origin=origin or 'web',
            feature=feature,
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            cache_write_tokens=cache_write_tokens,
            reasoning_tokens=reasoning_tokens,
            image_tokens=image_tokens,
            web_search_tokens=web_search_tokens,
            total_tokens=total_tokens,
            cost_usd=resolved_cost,
            upstream_cost_usd=(
                float(upstream_cost_usd) if upstream_cost_usd is not None else None
            ),
            tokens=tokens_payload,
            response_usage=response_usage,
            generation_id=generation_id,
        )
        db.session.add(ul)
        db.session.commit()
        return ul.to_dict()

    # ------------------------------------------------------------------
    # Aggregations — Postgres-backed (Phase 5 cutover).
    # ------------------------------------------------------------------

    @staticmethod
    def get_user_costs(user_id, days=30):
        """Per-model cost rollup for a user over the trailing ``days``."""
        uid = _to_uuid(user_id)
        if uid is None:
            return {'by_model': [], 'total_cost_usd': 0.0, 'period_days': days}
        start_date = datetime.utcnow() - timedelta(days=days)
        rows = db.session.execute(
            _sa_select(
                UsageLog.model.label('_id'),
                _sa_func.coalesce(_sa_func.sum(UsageLog.cost_usd), 0).label('total_cost'),
                _sa_func.coalesce(_sa_func.sum(UsageLog.total_tokens), 0).label('total_tokens'),
                _sa_func.count().label('request_count'),
            )
            .where(UsageLog.user_id == uid, UsageLog.created_at >= start_date)
            .group_by(UsageLog.model)
            .order_by(_sa_func.coalesce(_sa_func.sum(UsageLog.cost_usd), 0).desc())
        ).all()
        results = [
            {
                '_id': r._id,
                'total_cost': float(r.total_cost or 0),
                'total_tokens': int(r.total_tokens or 0),
                'request_count': int(r.request_count or 0),
            }
            for r in rows
        ]
        total_cost = sum(r['total_cost'] for r in results)
        return {'by_model': results, 'total_cost_usd': total_cost, 'period_days': days}

    @staticmethod
    def get_user_total_cost(user_id):
        """Lifetime cost + tokens for one user."""
        uid = _to_uuid(user_id)
        if uid is None:
            return {'total_cost_usd': 0, 'total_tokens': 0}
        row = db.session.execute(
            _sa_select(
                _sa_func.coalesce(_sa_func.sum(UsageLog.cost_usd), 0).label('total_cost'),
                _sa_func.coalesce(_sa_func.sum(UsageLog.total_tokens), 0).label('total_tokens'),
            ).where(UsageLog.user_id == uid)
        ).one()
        return {
            'total_cost_usd': float(row.total_cost or 0),
            'total_tokens': int(row.total_tokens or 0),
        }

    @staticmethod
    def get_daily_costs(user_id=None, days=30):
        """Daily cost / tokens / request bucket, optionally filtered by user."""
        start_date = datetime.utcnow() - timedelta(days=days)
        day_expr = _sa_func.to_char(UsageLog.created_at, 'YYYY-MM-DD').label('_id')
        stmt = (
            _sa_select(
                day_expr,
                _sa_func.coalesce(_sa_func.sum(UsageLog.cost_usd), 0).label('cost'),
                _sa_func.coalesce(_sa_func.sum(UsageLog.total_tokens), 0).label('tokens'),
                _sa_func.count().label('requests'),
            )
            .where(UsageLog.created_at >= start_date)
        )
        if user_id is not None:
            uid = _to_uuid(user_id)
            if uid is None:
                return []
            stmt = stmt.where(UsageLog.user_id == uid)
        stmt = stmt.group_by('_id').order_by('_id')
        rows = db.session.execute(stmt).all()
        return [
            {
                '_id': r._id,
                'cost': float(r.cost or 0),
                'tokens': int(r.tokens or 0),
                'requests': int(r.requests or 0),
            }
            for r in rows
        ]

    @staticmethod
    def aggregate_by(group_by: str, user_id=None, from_=None, to=None, workspace_id=None):
        """Grouping by feature / model / user / day."""
        if group_by == 'feature':
            key_col = UsageLog.feature
        elif group_by == 'model':
            key_col = UsageLog.model
        elif group_by == 'user':
            key_col = UsageLog.user_id
        elif group_by == 'day':
            key_col = _sa_func.to_char(UsageLog.created_at, 'YYYY-MM-DD')
        else:
            raise ValueError(f'invalid group_by: {group_by}')

        token_sum = _sa_func.coalesce(
            _sa_func.sum(UsageLog.input_tokens + UsageLog.output_tokens), 0
        )
        cost_sum = _sa_func.coalesce(_sa_func.sum(UsageLog.cost_usd), 0)

        stmt = _sa_select(
            key_col.label('key'),
            cost_sum.label('total_cost'),
            token_sum.label('total_tokens'),
            _sa_func.count().label('count'),
        )

        if user_id is not None:
            uid = _to_uuid(user_id)
            if uid is None:
                return []
            stmt = stmt.where(UsageLog.user_id == uid)
        if workspace_id is not None:
            wid = _to_uuid(workspace_id)
            if wid is None:
                return []
            stmt = stmt.where(UsageLog.workspace_id == wid)
        if from_ is not None:
            stmt = stmt.where(UsageLog.created_at >= from_)
        if to is not None:
            stmt = stmt.where(UsageLog.created_at <= to)

        stmt = stmt.group_by(key_col).order_by(cost_sum.desc())
        rows = db.session.execute(stmt).all()
        return [
            {
                'key': str(r.key) if r.key is not None else 'None',
                'total_cost': float(r.total_cost or 0),
                'total_tokens': int(r.total_tokens or 0),
                'count': int(r.count or 0),
            }
            for r in rows
        ]

    @staticmethod
    def aggregate_by_with_workspace(group_by: str, user_id=None, from_=None, to=None,
                                    workspace_id=None):
        """Like ``aggregate_by`` but additionally groups by ``workspace_id``.

        Returns one row per ``(key, workspace_id)`` so a caller can BOTH roll the
        rows up per-key AND know which workspaces produced each key in a SINGLE
        DB pass (avoids the route running two near-identical GROUP BY queries for
        owner-only ``$`` masking on ``/usage/me``).

        Row shape: ``{'key', 'workspace_id' (str|None), 'total_cost', 'total_tokens', 'count'}``.
        """
        if group_by == 'feature':
            key_col = UsageLog.feature
        elif group_by == 'model':
            key_col = UsageLog.model
        elif group_by == 'user':
            key_col = UsageLog.user_id
        elif group_by == 'day':
            key_col = _sa_func.to_char(UsageLog.created_at, 'YYYY-MM-DD')
        else:
            raise ValueError(f'invalid group_by: {group_by}')

        token_sum = _sa_func.coalesce(
            _sa_func.sum(UsageLog.input_tokens + UsageLog.output_tokens), 0
        )
        cost_sum = _sa_func.coalesce(_sa_func.sum(UsageLog.cost_usd), 0)

        stmt = _sa_select(
            key_col.label('key'),
            UsageLog.workspace_id.label('workspace_id'),
            cost_sum.label('total_cost'),
            token_sum.label('total_tokens'),
            _sa_func.count().label('count'),
        )

        if user_id is not None:
            uid = _to_uuid(user_id)
            if uid is None:
                return []
            stmt = stmt.where(UsageLog.user_id == uid)
        if workspace_id is not None:
            wid = _to_uuid(workspace_id)
            if wid is None:
                return []
            stmt = stmt.where(UsageLog.workspace_id == wid)
        if from_ is not None:
            stmt = stmt.where(UsageLog.created_at >= from_)
        if to is not None:
            stmt = stmt.where(UsageLog.created_at <= to)

        stmt = stmt.group_by(key_col, UsageLog.workspace_id)
        rows = db.session.execute(stmt).all()
        return [
            {
                'key': str(r.key) if r.key is not None else 'None',
                'workspace_id': r.workspace_id,
                'total_cost': float(r.total_cost or 0),
                'total_tokens': int(r.total_tokens or 0),
                'count': int(r.count or 0),
            }
            for r in rows
        ]

    @staticmethod
    def aggregate_workspace_spend(workspace_id, start=None, end=None) -> float:
        """Lifetime / windowed total spend for one workspace."""
        wid = _to_uuid(workspace_id)
        if wid is None:
            return 0.0
        stmt = _sa_select(_sa_func.coalesce(_sa_func.sum(UsageLog.cost_usd), 0))
        stmt = stmt.where(UsageLog.workspace_id == wid)
        if start is not None:
            stmt = stmt.where(UsageLog.created_at >= start)
        if end is not None:
            stmt = stmt.where(UsageLog.created_at <= end)
        total = db.session.execute(stmt).scalar()
        return float(total or 0)

    @staticmethod
    def aggregate_user_spend(workspace_id, start=None, end=None) -> list:
        """Per-user spend within one workspace."""
        wid = _to_uuid(workspace_id)
        if wid is None:
            return []
        token_sum = _sa_func.coalesce(
            _sa_func.sum(UsageLog.input_tokens + UsageLog.output_tokens), 0
        )
        cost_sum = _sa_func.coalesce(_sa_func.sum(UsageLog.cost_usd), 0)
        stmt = (
            _sa_select(
                UsageLog.user_id.label('user_id'),
                cost_sum.label('total_cost'),
                token_sum.label('total_tokens'),
                _sa_func.count().label('count'),
            )
            .where(UsageLog.workspace_id == wid)
            .group_by(UsageLog.user_id)
            .order_by(cost_sum.desc())
        )
        if start is not None:
            stmt = stmt.where(UsageLog.created_at >= start)
        if end is not None:
            stmt = stmt.where(UsageLog.created_at <= end)
        rows = db.session.execute(stmt).all()
        return [
            {
                'user_id': str(r.user_id) if r.user_id else None,
                'total_cost': float(r.total_cost or 0),
                'total_tokens': int(r.total_tokens or 0),
                'count': int(r.count or 0),
            }
            for r in rows
        ]

    @staticmethod
    def aggregate_project_spend(workspace_id, start=None, end=None) -> list:
        """Per-project spend within one workspace."""
        wid = _to_uuid(workspace_id)
        if wid is None:
            return []
        token_sum = _sa_func.coalesce(
            _sa_func.sum(UsageLog.input_tokens + UsageLog.output_tokens), 0
        )
        cost_sum = _sa_func.coalesce(_sa_func.sum(UsageLog.cost_usd), 0)
        stmt = (
            _sa_select(
                UsageLog.project_id.label('project_id'),
                cost_sum.label('total_cost'),
                token_sum.label('total_tokens'),
                _sa_func.count().label('count'),
            )
            .where(UsageLog.workspace_id == wid)
            .group_by(UsageLog.project_id)
            .order_by(cost_sum.desc())
        )
        if start is not None:
            stmt = stmt.where(UsageLog.created_at >= start)
        if end is not None:
            stmt = stmt.where(UsageLog.created_at <= end)
        rows = db.session.execute(stmt).all()
        return [
            {
                'project_id': str(r.project_id) if r.project_id else None,
                'total_cost': float(r.total_cost or 0),
                'total_tokens': int(r.total_tokens or 0),
                'count': int(r.count or 0),
            }
            for r in rows
        ]

    @staticmethod
    def aggregate_model_spend(workspace_id, start=None, end=None) -> list:
        """Per-model spend within one workspace."""
        wid = _to_uuid(workspace_id)
        if wid is None:
            return []
        token_sum = _sa_func.coalesce(
            _sa_func.sum(UsageLog.input_tokens + UsageLog.output_tokens), 0
        )
        cost_sum = _sa_func.coalesce(_sa_func.sum(UsageLog.cost_usd), 0)
        stmt = (
            _sa_select(
                UsageLog.model.label('model'),
                cost_sum.label('total_cost'),
                token_sum.label('total_tokens'),
                _sa_func.count().label('count'),
            )
            .where(UsageLog.workspace_id == wid)
            .group_by(UsageLog.model)
            .order_by(cost_sum.desc())
        )
        if start is not None:
            stmt = stmt.where(UsageLog.created_at >= start)
        if end is not None:
            stmt = stmt.where(UsageLog.created_at <= end)
        rows = db.session.execute(stmt).all()
        return [
            {
                'model': r.model,
                'total_cost': float(r.total_cost or 0),
                'total_tokens': int(r.total_tokens or 0),
                'count': int(r.count or 0),
            }
            for r in rows
        ]

    @staticmethod
    def overview_usage_bundle(workspace_id, days: int = 30) -> dict:
        """One grouped pass yielding everything the workspace-overview page
        needs from ``usage_logs``: the 30-day daily series AND the
        month-to-date message count, folded into a single CTE so the handler
        spends ONE round-trip instead of two (``aggregate_daily`` +
        ``total_messages_this_month``).

        Boundaries match the other aggregations byte-for-byte: the session TZ is
        pinned UTC, ``daily`` buckets on ``to_char(created_at,'YYYY-MM-DD')``
        from ``utcnow() - days``, and ``messages_mtd`` counts rows since
        first-of-month (UTC). The MTD count is computed in the SAME scan via a
        ``FILTER`` so the row set is read once.

        Returns ``{'daily': [...], 'messages_mtd': <int>}`` where each ``daily``
        entry has the identical shape ``aggregate_daily`` emits
        (``date``/``cost_usd``/``total_tokens``/``messages``).

        Exactness vs. the two methods it replaces: the scan's lower bound is
        ``min(start, month_start)`` so the MTD partial
        (``count(*) FILTER (WHERE created_at >= month_start)``, summed in Python)
        sees every current-month row even on a 31st where ``now - 30 days``
        lands AFTER first-of-month. The per-day cost/token/message aggregates are
        themselves ``FILTER (WHERE created_at >= start)`` so the boundary day
        counts only in-window rows — byte-identical to ``aggregate_daily(days)``
        — and buckets that end up empty (a pre-``start`` day pulled in only to
        feed the MTD partial) are dropped.
        """
        wid = _to_uuid(workspace_id)
        if wid is None:
            return {'daily': [], 'messages_mtd': 0}
        now = datetime.utcnow()
        start = now - timedelta(days=days)
        month_start = datetime(now.year, now.month, 1)
        scan_start = min(start, month_start)
        in_window = UsageLog.created_at >= start
        cost_sum = _sa_func.coalesce(
            _sa_func.sum(UsageLog.cost_usd).filter(in_window), 0
        )
        token_sum = _sa_func.coalesce(
            _sa_func.sum(UsageLog.input_tokens + UsageLog.output_tokens).filter(in_window),
            0,
        )
        msg_count = _sa_func.count().filter(in_window)
        day_expr = _sa_func.to_char(UsageLog.created_at, 'YYYY-MM-DD').label('day')
        # Per-bucket MTD partial: rows in this day-group dated >= first-of-month.
        mtd_partial = _sa_func.count().filter(
            UsageLog.created_at >= month_start
        ).label('mtd')
        rows = db.session.execute(
            _sa_select(
                day_expr,
                cost_sum.label('cost_usd'),
                token_sum.label('total_tokens'),
                msg_count.label('messages'),
                mtd_partial,
            )
            .where(UsageLog.workspace_id == wid, UsageLog.created_at >= scan_start)
            .group_by('day')
            .order_by('day')
        ).all()
        daily = [
            {
                'date': r.day,
                'cost_usd': float(r.cost_usd or 0),
                'total_tokens': int(r.total_tokens or 0),
                'messages': int(r.messages or 0),
            }
            for r in rows
            if r.messages
        ]
        messages_mtd = int(sum(r.mtd or 0 for r in rows))
        return {'daily': daily, 'messages_mtd': messages_mtd}

    # ------------------------------------------------------------------
    # Parametric time-bucket analytics primitives (P0 — Usage Analytics
    # redesign). READ-ONLY. These are the building blocks the P1
    # ``analytics_service`` composes into the unified envelope; they live
    # here next to the other usage_logs aggregations.
    #
    # All three accept an optional single-entity scope (``workspace_id`` /
    # ``project_id`` / ``user_id``); pass none for a holding-wide rollup.
    # ``active_users`` = ``count(distinct user_id)`` — NOT summable across
    # buckets, so the window-total methods compute their own distinct count.
    # ------------------------------------------------------------------

    # granularity -> (date_trunc unit, generate_series step)
    _GRANULARITY_INTERVALS = {
        'day': ('day', '1 day'),
        'week': ('week', '1 week'),
        'month': ('month', '1 month'),
    }

    @staticmethod
    def _scope_filters(workspace_id=None, project_id=None, user_id=None):
        """Build a ``(sql_fragment, bind_params)`` pair for the optional entity
        scope. Column names are internal constants; values bind as params."""
        clauses: list[str] = []
        params: dict = {}
        if workspace_id is not None:
            wid = _to_uuid(workspace_id)
            if wid is None:
                return None, None
            clauses.append('workspace_id = :workspace_id')
            params['workspace_id'] = wid
        if project_id is not None:
            pid = _to_uuid(project_id)
            if pid is None:
                return None, None
            clauses.append('project_id = :project_id')
            params['project_id'] = pid
        if user_id is not None:
            uid = _to_uuid(user_id)
            if uid is None:
                return None, None
            clauses.append('user_id = :user_id')
            params['user_id'] = uid
        return (' AND '.join(clauses), params)

    @staticmethod
    def usage_series(
        granularity: str,
        frm: datetime,
        to: datetime,
        workspace_id=None,
        project_id=None,
        user_id=None,
    ) -> list:
        """Gap-filled bucketed series over ``[frm, to]``.

        Returns one row per bucket from ``date_trunc(g, frm)`` to
        ``date_trunc(g, to)`` inclusive (empty buckets zero-filled via a
        ``generate_series`` LEFT JOIN). Row shape::

            {'bucket': '2026-05-04', 'cost': 1.23, 'calls': 45,
             'tokens': 12000, 'active_users': 3}

        ``bucket`` is the truncated date in ``YYYY-MM-DD`` form.
        """
        unit_step = UsageLogModel._GRANULARITY_INTERVALS.get(granularity)
        if unit_step is None:
            raise ValueError(f'invalid granularity: {granularity}')
        unit, step = unit_step

        scope_sql, scope_params = UsageLogModel._scope_filters(
            workspace_id, project_id, user_id
        )
        # An unparsable scope id => empty series (no matching rows possible).
        if scope_sql is None:
            return []
        scope_clause = f' AND {scope_sql}' if scope_sql else ''

        params = {'frm': frm, 'to': to, **(scope_params or {})}
        sql = f"""
            WITH buckets AS (
                SELECT generate_series(
                    date_trunc('{unit}', CAST(:frm AS timestamptz)),
                    date_trunc('{unit}', CAST(:to AS timestamptz)),
                    INTERVAL '{step}'
                ) AS bucket
            ),
            agg AS (
                SELECT
                    date_trunc('{unit}', created_at) AS bucket,
                    COALESCE(SUM(cost_usd), 0) AS cost,
                    COALESCE(SUM(upstream_cost_usd), 0) AS upstream,
                    COUNT(*) AS calls,
                    COALESCE(SUM(total_tokens), 0) AS tokens,
                    COUNT(DISTINCT user_id) AS active_users
                FROM usage_logs
                WHERE created_at >= :frm AND created_at <= :to{scope_clause}
                GROUP BY 1
            )
            SELECT
                b.bucket AS bucket,
                COALESCE(a.cost, 0) AS cost,
                COALESCE(a.upstream, 0) AS upstream,
                COALESCE(a.calls, 0) AS calls,
                COALESCE(a.tokens, 0) AS tokens,
                COALESCE(a.active_users, 0) AS active_users
            FROM buckets b
            LEFT JOIN agg a ON a.bucket = b.bucket
            ORDER BY b.bucket
        """
        rows = db.session.execute(_sql_text_orm(sql), params).all()
        return [
            {
                'bucket': r.bucket.strftime('%Y-%m-%d') if r.bucket else None,
                'cost': float(r.cost or 0),
                'upstream': float(r.upstream or 0),
                'calls': int(r.calls or 0),
                'tokens': int(r.tokens or 0),
                'active_users': int(r.active_users or 0),
            }
            for r in rows
        ]

    @staticmethod
    def usage_totals(
        frm: datetime,
        to: datetime,
        workspace_id=None,
        project_id=None,
        user_id=None,
    ) -> dict:
        """Window totals over ``[frm, to]``. ``active_users`` is a single
        ``count(distinct user_id)`` over the whole window (NOT the sum of the
        per-bucket distinct counts). Shape::

            {'cost': 0.0, 'calls': 0, 'tokens': 0, 'active_users': 0}
        """
        scope_sql, scope_params = UsageLogModel._scope_filters(
            workspace_id, project_id, user_id
        )
        if scope_sql is None:
            return {'cost': 0.0, 'calls': 0, 'tokens': 0, 'active_users': 0}
        scope_clause = f' AND {scope_sql}' if scope_sql else ''
        params = {'frm': frm, 'to': to, **(scope_params or {})}
        sql = f"""
            SELECT
                COALESCE(SUM(cost_usd), 0) AS cost,
                COALESCE(SUM(upstream_cost_usd), 0) AS upstream,
                COUNT(*) AS calls,
                COALESCE(SUM(total_tokens), 0) AS tokens,
                COUNT(DISTINCT user_id) AS active_users
            FROM usage_logs
            WHERE created_at >= :frm AND created_at <= :to{scope_clause}
        """
        r = db.session.execute(_sql_text_orm(sql), params).one()
        return {
            'cost': float(r.cost or 0),
            'upstream': float(r.upstream or 0),
            'calls': int(r.calls or 0),
            'tokens': int(r.tokens or 0),
            'active_users': int(r.active_users or 0),
        }

    @staticmethod
    def usage_previous_totals(
        frm: datetime,
        to: datetime,
        workspace_id=None,
        project_id=None,
        user_id=None,
    ) -> dict:
        """Totals for the immediately-preceding equal-length window
        ``[frm - (to - frm), frm)`` — the period-over-period baseline.

        The previous window is half-open on its upper bound (``< frm``) so the
        boundary instant isn't counted in both windows. Same shape as
        :meth:`usage_totals`.
        """
        delta = to - frm
        prev_to = frm
        prev_from = frm - delta
        scope_sql, scope_params = UsageLogModel._scope_filters(
            workspace_id, project_id, user_id
        )
        if scope_sql is None:
            return {'cost': 0.0, 'calls': 0, 'tokens': 0, 'active_users': 0}
        scope_clause = f' AND {scope_sql}' if scope_sql else ''
        params = {'frm': prev_from, 'to': prev_to, **(scope_params or {})}
        sql = f"""
            SELECT
                COALESCE(SUM(cost_usd), 0) AS cost,
                COALESCE(SUM(upstream_cost_usd), 0) AS upstream,
                COUNT(*) AS calls,
                COALESCE(SUM(total_tokens), 0) AS tokens,
                COUNT(DISTINCT user_id) AS active_users
            FROM usage_logs
            WHERE created_at >= :frm AND created_at < :to{scope_clause}
        """
        r = db.session.execute(_sql_text_orm(sql), params).one()
        return {
            'cost': float(r.cost or 0),
            'upstream': float(r.upstream or 0),
            'calls': int(r.calls or 0),
            'tokens': int(r.tokens or 0),
            'active_users': int(r.active_users or 0),
        }


# ======================================================================
# Phase 3 — SQLAlchemy 2.0 ORM model
# ======================================================================

import uuid as _uuid_orm
from datetime import datetime as _dt_orm

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    text as _sql_text_orm,
    select as _sa_select,
    func as _sa_func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models._base import SerializableMixin


class UsageLog(db.Model, SerializableMixin):
    __tablename__ = 'usage_logs'

    id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid_orm.uuid4
    )
    user_id: Mapped[_uuid_orm.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    workspace_id: Mapped[_uuid_orm.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('workspaces.id', ondelete='SET NULL'),
        nullable=True,
    )
    project_id: Mapped[_uuid_orm.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('projects.id', ondelete='SET NULL'),
        nullable=True,
    )
    model: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin: Mapped[str | None] = mapped_column(Text, nullable=True)
    feature: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=_sql_text_orm('0')
    )
    output_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=_sql_text_orm('0')
    )
    cached_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=_sql_text_orm('0')
    )
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasoning_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=_sql_text_orm('0')
    )
    image_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=_sql_text_orm('0')
    )
    web_search_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=_sql_text_orm('0')
    )
    total_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=_sql_text_orm('0')
    )
    cost_usd: Mapped[float] = mapped_column(
        Numeric(14, 8), nullable=False, server_default=_sql_text_orm('0')
    )
    upstream_cost_usd: Mapped[float | None] = mapped_column(Numeric(14, 8), nullable=True)
    tokens: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=_sql_text_orm("'{}'::jsonb")
    )
    response_usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    generation_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[_dt_orm] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_sql_text_orm('now()')
    )

    __table_args__ = (
        Index(
            'ix_usage_logs_user_created',
            'user_id',
            _sql_text_orm('created_at DESC'),
        ),
        Index(
            'ix_usage_logs_workspace_created',
            'workspace_id',
            _sql_text_orm('created_at DESC'),
        ),
        Index(
            'ix_usage_logs_project_created',
            'project_id',
            _sql_text_orm('created_at DESC'),
        ),
        Index(
            'ix_usage_logs_model_created',
            'model',
            _sql_text_orm('created_at DESC'),
        ),
        Index('ix_usage_logs_model', 'model'),
        Index(
            'ix_usage_logs_created_brin',
            'created_at',
            postgresql_using='brin',
        ),
        Index(
            'ix_usage_logs_gen_id_partial',
            'generation_id',
            unique=True,
            postgresql_where=_sql_text_orm('generation_id IS NOT NULL'),
        ),
    )
