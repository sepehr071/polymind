"""Manual credit ledger — append-only entries that fund workspace spend.

Phase 4D: PG-backed via ORM ``CreditLedger``. Legacy Mongo ``type`` enum
``top_up | adjustment | refund`` mapped to PG ``topup | adjustment | refund``
at the façade (legacy callers don't change).
"""

import uuid


_ALLOWED_TYPES_LEGACY = {'top_up', 'adjustment', 'refund'}
_ALLOWED_KINDS_PG = {'topup', 'adjustment', 'refund'}


def _to_uuid(val):
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except Exception:
        return None


def _normalize_kind(value: str) -> str:
    """Translate legacy ``top_up`` → ``topup``. Other values pass through."""
    if not value:
        raise ValueError("kind/type is required")
    if value == 'top_up':
        return 'topup'
    if value in _ALLOWED_KINDS_PG:
        return value
    raise ValueError(f"Invalid ledger kind: {value}")


class CreditLedgerModel:
    """Append-only ledger of credit movements for a workspace."""

    collection_name = 'credit_ledger'

    @staticmethod
    def add_entry(workspace_id, amount_usd: float, type: str, note: str,
                  added_by, user_id=None, commit: bool = True) -> dict:
        """Legacy signature kept verbatim. Writes a PG row via ``create()``.

        ``commit=False`` flushes the row (so the returned dict has a stable id)
        but defers the COMMIT to the caller, letting this ledger write join a
        larger atomic transaction (holding→company transfer).
        """
        kind = _normalize_kind(type)
        ws_uuid = _to_uuid(workspace_id)
        if ws_uuid is None:
            raise ValueError(f"Invalid workspace_id: {workspace_id!r}")
        added_by_uuid = _to_uuid(added_by)
        # Convert USD float → micro-USD integer (PG schema uses BigInteger).
        delta_micro = int(round(float(amount_usd or 0) * 1_000_000))
        ref = {'note': note or '', 'amount_usd': float(amount_usd or 0)}
        if user_id is not None:
            ref['user_id'] = str(_to_uuid(user_id) or user_id)

        row = CreditLedger(
            workspace_id=ws_uuid,
            delta_micro_usd=delta_micro,
            kind=kind,
            ref=ref,
            created_by_user_id=added_by_uuid,
        )
        db.session.add(row)
        if commit:
            db.session.commit()
        else:
            db.session.flush()
        return _ledger_to_dict(row)

    @staticmethod
    def create(workspace_id, delta_micro_usd: int, kind: str, ref: dict = None,
               created_by_user_id=None) -> dict:
        """New PG-native signature used by Phase 5 routes."""
        ws_uuid = _to_uuid(workspace_id)
        if ws_uuid is None:
            raise ValueError(f"Invalid workspace_id: {workspace_id!r}")
        resolved_kind = _normalize_kind(kind)
        row = CreditLedger(
            workspace_id=ws_uuid,
            delta_micro_usd=int(delta_micro_usd or 0),
            kind=resolved_kind,
            ref=ref or {},
            created_by_user_id=_to_uuid(created_by_user_id),
        )
        db.session.add(row)
        db.session.commit()
        return _ledger_to_dict(row)

    @staticmethod
    def find_by_workspace(workspace_id, limit: int = 100, skip: int = 0) -> list:
        ws_uuid = _to_uuid(workspace_id)
        if ws_uuid is None:
            return []
        rows = db.session.execute(
            select(CreditLedger)
            .where(CreditLedger.workspace_id == ws_uuid)
            .order_by(CreditLedger.created_at.desc())
            .offset(skip)
            .limit(limit)
        ).scalars().all()
        return [_ledger_to_dict(r) for r in rows]

    @staticmethod
    def sum_credits(workspace_id) -> float:
        ws_uuid = _to_uuid(workspace_id)
        if ws_uuid is None:
            return 0.0
        total_micro = db.session.execute(
            select(func.coalesce(func.sum(CreditLedger.delta_micro_usd), 0))
            .where(CreditLedger.workspace_id == ws_uuid)
        ).scalar()
        return float(total_micro or 0) / 1_000_000.0


def _ledger_to_dict(row: 'CreditLedger') -> dict:
    out = row.to_dict()
    out['workspace_id'] = str(row.workspace_id) if row.workspace_id else None
    # Legacy ``amount_usd`` field — derive from micro-USD column.
    out['amount_usd'] = float(row.delta_micro_usd or 0) / 1_000_000.0
    # Legacy ``type`` alias mirrors ``kind`` for back-compat readers.
    out['type'] = 'top_up' if row.kind == 'topup' else row.kind
    out['added_by'] = str(row.created_by_user_id) if row.created_by_user_id else None
    # Surface note from ref blob.
    if isinstance(row.ref, dict):
        out['note'] = row.ref.get('note')
    return out


# ======================================================================
# Phase 3 — SQLAlchemy 2.0 ORM model
# ======================================================================

import uuid as _uuid_orm
from datetime import datetime as _dt_orm

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    text as _sql_text_orm,
    select,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models._base import SerializableMixin


class CreditLedger(db.Model, SerializableMixin):
    __tablename__ = 'credit_ledger'

    id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid_orm.uuid4
    )
    workspace_id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('workspaces.id', ondelete='CASCADE'),
        nullable=False,
    )
    delta_micro_usd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    ref: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # POLYMORPHIC actor reference — NO FK. The workspace-owner billing route
    # writes a ``users.id`` here while the platform-admin route writes a
    # ``platform_admins.id``; no single-table FK can serve both writers, so this
    # is a free-form UUID (matching the original Mongo design). Migration 0002
    # drops the FK the 0001 baseline had pointed at ``users(id)``.
    created_by_user_id: Mapped[_uuid_orm.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    created_at: Mapped[_dt_orm] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_sql_text_orm('now()')
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('topup','adjustment','refund')",
            name='ck_credit_ledger_kind',
        ),
        Index(
            'ix_credit_ledger_workspace_created',
            'workspace_id',
            _sql_text_orm('created_at DESC'),
        ),
    )
