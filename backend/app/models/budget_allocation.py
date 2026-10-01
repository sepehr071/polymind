"""Hierarchical budget allocations — holding / company / team / user / member caps.

Phase 1 of the hierarchical-billing build. A ``budget_allocations`` row stores a
single configurable spend ceiling for one scope (``holding | company | team |
user``) over one period (``mtd`` = month-to-date reset, or ``absolute``). The
spend-gate consults these against ``spend_rollups`` at call time; an absent /
disabled / NULL-amount row means "unlimited" at that level.

Mirrors the repo conventions: ``BudgetAllocationModel`` façade of
``@staticmethod`` legacy-dict returners + a SQLAlchemy 2.0 ORM ``BudgetAllocation``
row class in the bottom section. The ``created_by_user_id`` column is polymorphic
(NO FK) exactly like ``credit_ledger.created_by_user_id``: a workspace-owner route
writes a ``users.id`` while a platform-admin route writes a ``platform_admins.id``.
"""

import uuid
from datetime import datetime, timezone


# Sentinel UUID used in the unique index COALESCE so a NULL ``scope_id``
# (holding scope) still collides with itself on the (scope_type, scope_id,
# period) uniqueness — Postgres treats NULLs as distinct otherwise.
_NULL_SCOPE_UUID = uuid.UUID('00000000-0000-0000-0000-000000000000')

VALID_SCOPE_TYPES = {'holding', 'company', 'team', 'user', 'member'}

# ``member`` = one user's monthly budget INSIDE one org. There is no
# memberships row id to key on, so the scope id is a deterministic uuid5 of
# ``"<workspace_id>:<user_id>"`` — never change the namespace (it would orphan
# every existing member budget + rollup).
MEMBER_SCOPE_NAMESPACE = uuid.UUID('1d07de86-a711-5671-89f2-ec0b87990f23')


def member_scope_id(workspace_id, user_id) -> uuid.UUID | None:
    """Scope id for a per-user budget inside one org; ``None`` on bad ids."""
    wid = _to_uuid(workspace_id)
    uid = _to_uuid(user_id)
    if wid is None or uid is None:
        return None
    return uuid.uuid5(MEMBER_SCOPE_NAMESPACE, f'{wid}:{uid}')
VALID_PERIODS = {'mtd', 'absolute'}


def _to_uuid(val):
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except Exception:
        return None


def _validate_scope(scope_type: str, scope_id) -> uuid.UUID | None:
    """Validate scope_type + coerce scope_id. holding allows NULL scope_id;
    every other scope requires a parseable UUID."""
    if scope_type not in VALID_SCOPE_TYPES:
        raise ValueError(
            f"Invalid scope_type: {scope_type!r}. Must be one of {sorted(VALID_SCOPE_TYPES)}"
        )
    sid = _to_uuid(scope_id)
    if scope_type != 'holding' and sid is None:
        raise ValueError(f"scope_id is required for scope_type={scope_type!r}")
    return sid


def _validate_period(period: str) -> str:
    if period not in VALID_PERIODS:
        raise ValueError(
            f"Invalid period: {period!r}. Must be one of {sorted(VALID_PERIODS)}"
        )
    return period


class BudgetAllocationModel:
    """Façade for ``budget_allocations`` — hierarchical spend caps."""

    collection_name = 'budget_allocations'

    @staticmethod
    def get_active(scope_type: str, scope_id, period: str = 'mtd') -> dict | None:
        """Return the ENABLED allocation for a scope+period, or ``None``."""
        sid = _validate_scope(scope_type, scope_id)
        _validate_period(period)
        row = db.session.execute(
            select(BudgetAllocation).where(
                BudgetAllocation.scope_type == scope_type,
                _scope_id_match(sid),
                BudgetAllocation.period == period,
                BudgetAllocation.enabled.is_(True),
            )
        ).scalar_one_or_none()
        return _alloc_to_dict(row) if row is not None else None

    @staticmethod
    def get_any(scope_type: str, scope_id, period: str = 'mtd') -> dict | None:
        """Return the allocation for a scope+period regardless of ``enabled``."""
        sid = _validate_scope(scope_type, scope_id)
        _validate_period(period)
        row = db.session.execute(
            select(BudgetAllocation).where(
                BudgetAllocation.scope_type == scope_type,
                _scope_id_match(sid),
                BudgetAllocation.period == period,
            )
        ).scalar_one_or_none()
        return _alloc_to_dict(row) if row is not None else None

    @staticmethod
    def set_budget(
        scope_type: str,
        scope_id,
        amount_usd: float,
        *,
        period: str = 'mtd',
        enabled: bool = True,
        by=None,
        parent_scope_type: str | None = None,
        parent_scope_id=None,
    ) -> dict:
        """UPSERT a budget on the (scope_type, scope_id, period) unique index.

        Updates ``amount_usd`` / ``enabled`` / parent linkage / ``updated_at``
        on conflict. Returns the persisted legacy dict.
        """
        sid = _validate_scope(scope_type, scope_id)
        _validate_period(period)
        amount = float(amount_usd or 0)
        if amount < 0:
            raise ValueError("amount_usd must be >= 0")
        now = datetime.now(timezone.utc)
        coalesced = sid if sid is not None else _NULL_SCOPE_UUID
        values = {
            'id': uuid.uuid4(),
            'scope_type': scope_type,
            'scope_id': sid,
            'period': period,
            'amount_usd': amount,
            'enabled': bool(enabled),
            'parent_scope_type': parent_scope_type,
            'parent_scope_id': _to_uuid(parent_scope_id),
            'created_by_user_id': _to_uuid(by),
            'created_at': now,
            'updated_at': now,
        }
        stmt = pg_insert(BudgetAllocation).values(**values).on_conflict_do_update(
            index_elements=[
                BudgetAllocation.scope_type,
                func.coalesce(BudgetAllocation.scope_id, _NULL_SCOPE_UUID),
                BudgetAllocation.period,
            ],
            set_={
                'amount_usd': amount,
                'enabled': bool(enabled),
                'parent_scope_type': parent_scope_type,
                'parent_scope_id': _to_uuid(parent_scope_id),
                'updated_at': now,
            },
        )
        db.session.execute(stmt)
        db.session.commit()
        # Read back the now-current row so the returned dict reflects the merge.
        row = db.session.execute(
            select(BudgetAllocation).where(
                BudgetAllocation.scope_type == scope_type,
                _scope_id_match(sid),
                BudgetAllocation.period == period,
            )
        ).scalar_one()
        # Silence the unused-local warning for ``coalesced`` (kept for clarity).
        _ = coalesced
        return _alloc_to_dict(row)

    @staticmethod
    def clear_budget(scope_type: str, scope_id, period: str = 'mtd') -> bool:
        """Delete the allocation row. Returns ``True`` when a row was removed."""
        sid = _validate_scope(scope_type, scope_id)
        _validate_period(period)
        result = db.session.execute(
            sa_delete(BudgetAllocation).where(
                BudgetAllocation.scope_type == scope_type,
                _scope_id_match(sid),
                BudgetAllocation.period == period,
            )
        )
        db.session.commit()
        return bool(result.rowcount)

    @staticmethod
    def list_for_scope_ids(
        scope_type: str, scope_ids: list, period: str = 'mtd'
    ) -> dict:
        """Bulk-load enabled allocations for many ids of one scope_type.

        Returns ``{str(scope_id): dict}`` keyed by the stringified scope id.
        """
        if scope_type not in VALID_SCOPE_TYPES:
            raise ValueError(f"Invalid scope_type: {scope_type!r}")
        _validate_period(period)
        ids = [_to_uuid(s) for s in (scope_ids or [])]
        ids = [s for s in ids if s is not None]
        if not ids:
            return {}
        rows = db.session.execute(
            select(BudgetAllocation).where(
                BudgetAllocation.scope_type == scope_type,
                BudgetAllocation.scope_id.in_(ids),
                BudgetAllocation.period == period,
                BudgetAllocation.enabled.is_(True),
            )
        ).scalars().all()
        return {str(r.scope_id): _alloc_to_dict(r) for r in rows}


def member_budgets_bulk(workspace_id, user_ids) -> dict:
    """Per-user monthly budget inside one org, batched (2 IN-queries, no N+1).

    Returns ``{str(user_id): {amount_usd, spent_mtd_usd, remaining_usd}}`` for
    EVERY requested user; ``amount_usd``/``remaining_usd`` are ``None`` when the
    user has no (enabled) member budget there = unlimited.
    """
    from app.models.spend_rollup import SpendRollupModel

    by_sid: dict = {}
    for uid in user_ids or []:
        sid = member_scope_id(workspace_id, uid)
        if sid is not None:
            by_sid[str(sid)] = str(uid)
    if not by_sid:
        return {}
    allocs = BudgetAllocationModel.list_for_scope_ids('member', list(by_sid.keys()))
    spent = SpendRollupModel.get_spent_bulk(
        'member', list(by_sid.keys()), SpendRollupModel.current_period_month()
    )
    out: dict = {}
    for sid, uid in by_sid.items():
        amount = (allocs.get(sid) or {}).get('amount_usd')
        spent_mtd = float(spent.get(sid, 0.0))
        out[uid] = {
            'amount_usd': amount,
            'spent_mtd_usd': spent_mtd,
            'remaining_usd': (
                round(max(0.0, amount - spent_mtd), 8) if amount is not None else None
            ),
        }
    return out


def _scope_id_match(sid: uuid.UUID | None):
    """WHERE clause fragment that matches the (possibly-NULL) scope_id."""
    if sid is None:
        return BudgetAllocation.scope_id.is_(None)
    return BudgetAllocation.scope_id == sid


def _alloc_to_dict(row: 'BudgetAllocation') -> dict:
    out = row.to_dict()
    out['scope_id'] = str(row.scope_id) if row.scope_id else None
    out['parent_scope_id'] = str(row.parent_scope_id) if row.parent_scope_id else None
    out['created_by_user_id'] = (
        str(row.created_by_user_id) if row.created_by_user_id else None
    )
    out['amount_usd'] = float(row.amount_usd) if row.amount_usd is not None else None
    return out


# ======================================================================
# SQLAlchemy 2.0 ORM model
# ======================================================================

import uuid as _uuid_orm
from datetime import datetime as _dt_orm

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Numeric,
    Text,
    delete as sa_delete,
    func,
    select,
    text as _sql_text_orm,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models._base import SerializableMixin


class BudgetAllocation(db.Model, SerializableMixin):
    __tablename__ = 'budget_allocations'

    id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid_orm.uuid4
    )
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    # NULL only legal for the holding scope (enforced by ck_..._scope_id).
    scope_id: Mapped[_uuid_orm.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    period: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=_sql_text_orm("'mtd'")
    )
    amount_usd: Mapped[float] = mapped_column(Numeric(14, 8), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=_sql_text_orm('true')
    )
    parent_scope_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_scope_id: Mapped[_uuid_orm.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # POLYMORPHIC actor reference — NO FK (mirrors credit_ledger): a workspace
    # owner writes a ``users.id`` while a platform admin writes a
    # ``platform_admins.id``; no single-table FK can serve both.
    created_by_user_id: Mapped[_uuid_orm.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[_dt_orm] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_sql_text_orm('now()')
    )
    updated_at: Mapped[_dt_orm] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_sql_text_orm('now()')
    )

    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('holding','company','team','user','member')",
            name='ck_budget_allocations_scope_type',
        ),
        CheckConstraint(
            "scope_id IS NOT NULL OR scope_type = 'holding'",
            name='ck_budget_allocations_scope_id',
        ),
        CheckConstraint(
            "period IN ('mtd','absolute')",
            name='ck_budget_allocations_period',
        ),
        CheckConstraint(
            'amount_usd >= 0',
            name='ck_budget_allocations_amount',
        ),
        # UPSERT target — COALESCE the NULL scope_id to the zero UUID so a
        # holding row is unique on (scope_type, period) too.
        Index(
            'uq_budget_alloc_scope_period',
            'scope_type',
            _sql_text_orm(
                "COALESCE(scope_id, '00000000-0000-0000-0000-000000000000'::uuid)"
            ),
            'period',
            unique=True,
        ),
        # Hot-path lookup for the spend gate (enabled rows only).
        Index(
            'ix_budget_alloc_scope_enabled',
            'scope_type',
            'scope_id',
            postgresql_where=_sql_text_orm('enabled'),
        ),
    )
