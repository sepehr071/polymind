"""Spend rollups — incrementally-maintained spend counters per scope+month.

Phase 1 of the hierarchical-billing build. ``spend_rollups`` holds a running
``spent_usd`` + ``calls`` total per ``(scope_type, scope_id, period_month)`` so
the spend-gate can answer "how much has this user/team/company spent this month?"
WITHOUT a ``SUM(usage_logs)`` scan on the hot path.

Each ``OpenRouterService._record_usage`` write bumps the relevant rollups
(company current-month + company LIFETIME sentinel, team current-month, user
current-month). The LIFETIME sentinel (``period_month == 1970-01-01``, company
scope only) accumulates all-time company spend — used to reconcile against the
prepaid credit wallet.

Surrogate UUID PK (the repo has no composite-PK precedent); the real upsert
target is the ``(scope_type, scope_id, period_month)`` unique constraint.
"""

import uuid
from datetime import date, datetime, timezone


def _to_uuid(val):
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except Exception:
        return None


VALID_SCOPE_TYPES = {'company', 'team', 'user', 'member'}


class SpendRollupModel:
    """Façade for ``spend_rollups`` — per-scope/month spend counters."""

    collection_name = 'spend_rollups'

    # period_month sentinel marking the all-time (lifetime) company bucket.
    LIFETIME = date(1970, 1, 1)

    @staticmethod
    def current_period_month() -> date:
        """First-of-month (UTC) for the current month — the MTD bucket key."""
        now = datetime.now(timezone.utc)
        return date(now.year, now.month, 1)

    @staticmethod
    def bump(
        scope_type: str,
        scope_id,
        period_month: date,
        cost_usd: float,
        calls: int = 1,
        commit: bool = False,
    ) -> None:
        """Increment ``spent_usd`` + ``calls`` for one scope+month, upserting.

        Idempotent at the row level: creates the row on first call, atomically
        adds on subsequent calls (``spent_usd = spent_usd + :cost``). When
        ``commit`` is False the caller is responsible for committing — the
        metering path bumps several rollups then commits once.
        """
        if scope_type not in VALID_SCOPE_TYPES:
            raise ValueError(
                f"Invalid scope_type: {scope_type!r}. Must be one of {sorted(VALID_SCOPE_TYPES)}"
            )
        sid = _to_uuid(scope_id)
        if sid is None:
            # Skip-and-return (mirrors UsageLogModel.create's NULL-on-bad-id):
            # a bad/non-UUID scope_id (e.g. an unvalidated body project_id on the
            # /workflow/generate path) must NEVER raise — raising here would
            # discard the company + LIFETIME bumps already executed by the caller
            # before its single commit, under-counting the gate's LIFETIME spend
            # and permitting overspend. A bumped scope simply gets no row.
            return
        cost = float(cost_usd or 0)
        n_calls = int(calls or 0)
        now = datetime.now(timezone.utc)

        stmt = pg_insert(SpendRollup).values(
            id=uuid.uuid4(),
            scope_type=scope_type,
            scope_id=sid,
            period_month=period_month,
            spent_usd=cost,
            calls=n_calls,
            updated_at=now,
        ).on_conflict_do_update(
            index_elements=['scope_type', 'scope_id', 'period_month'],
            set_={
                'spent_usd': SpendRollup.spent_usd + cost,
                'calls': SpendRollup.calls + n_calls,
                'updated_at': now,
            },
        )
        db.session.execute(stmt)
        if commit:
            db.session.commit()

    @staticmethod
    def get_spent(scope_type: str, scope_id, period_month: date) -> float:
        """Return ``spent_usd`` for one scope+month — ``0.0`` when absent."""
        sid = _to_uuid(scope_id)
        if sid is None:
            return 0.0
        row = db.session.execute(
            select(SpendRollup.spent_usd).where(
                SpendRollup.scope_type == scope_type,
                SpendRollup.scope_id == sid,
                SpendRollup.period_month == period_month,
            )
        ).scalar_one_or_none()
        return float(row) if row is not None else 0.0

    @staticmethod
    def get_spent_bulk(scope_type: str, scope_ids, period_month: date) -> dict:
        """Batched ``get_spent`` for many ids of one scope+month — ONE IN-query.

        Returns ``{str(scope_id): spent_usd}`` keyed by the stringified scope id;
        ids with no rollup row are simply absent (caller defaults to ``0.0``).
        Replaces a per-id ``get_spent`` loop (N round-trips) — mirrors the
        batched company-LIFETIME read at ``admin.py``.
        """
        ids = [_to_uuid(s) for s in (scope_ids or [])]
        ids = [s for s in ids if s is not None]
        if not ids:
            return {}
        rows = db.session.execute(
            select(SpendRollup.scope_id, SpendRollup.spent_usd).where(
                SpendRollup.scope_type == scope_type,
                SpendRollup.scope_id.in_(ids),
                SpendRollup.period_month == period_month,
            )
        ).all()
        return {str(scope_id): float(spent or 0) for scope_id, spent in rows}


# ======================================================================
# SQLAlchemy 2.0 ORM model
# ======================================================================

import uuid as _uuid_orm
from datetime import date as _date_orm
from datetime import datetime as _dt_orm

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    select,
    text as _sql_text_orm,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models._base import SerializableMixin


class SpendRollup(db.Model, SerializableMixin):
    __tablename__ = 'spend_rollups'

    id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid_orm.uuid4
    )
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope_id: Mapped[_uuid_orm.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # First-of-month (UTC) bucket; 1970-01-01 = LIFETIME sentinel (company only).
    period_month: Mapped[_date_orm] = mapped_column(Date, nullable=False)
    spent_usd: Mapped[float] = mapped_column(
        Numeric(14, 8), nullable=False, server_default=_sql_text_orm('0')
    )
    calls: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=_sql_text_orm('0')
    )
    updated_at: Mapped[_dt_orm] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_sql_text_orm('now()')
    )

    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('company','team','user','member')",
            name='ck_spend_rollups_scope_type',
        ),
        UniqueConstraint(
            'scope_type', 'scope_id', 'period_month',
            name='uq_spend_rollups_scope_period',
        ),
        Index('ix_spend_rollups_scope', 'scope_type', 'scope_id'),
    )
