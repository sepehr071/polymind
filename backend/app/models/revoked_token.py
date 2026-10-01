"""Revoked-token blocklist.

Phase 4D: PG-backed via ORM ``RevokedToken``. Adds a thin façade
(``RevokedTokenModel``) so the JWT blocklist callback in
``app/extensions.py`` can swap from direct ``mongo.db.revoked_tokens``
queries to a single method call. Auth routes still write to Mongo directly
today; Phase 5 swaps them.
"""

import uuid
from datetime import datetime, timezone


def _to_uuid(val):
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except Exception:
        return None


class RevokedTokenModel:
    """Façade on the ``revoked_tokens`` PG table."""

    collection_name = 'revoked_tokens'

    @staticmethod
    def add(jti: str, user_id=None) -> bool:
        """Idempotent insert. Duplicate jti is silently ignored."""
        if not jti:
            return False
        stmt = pg_insert(RevokedToken).values(
            jti=jti,
            user_id=_to_uuid(user_id),
        ).on_conflict_do_nothing(index_elements=['jti'])
        db.session.execute(stmt)
        db.session.commit()
        return True

    @staticmethod
    def is_revoked(jti: str) -> bool:
        if not jti:
            return False
        row_id = db.session.execute(
            select(RevokedToken.id).where(RevokedToken.jti == jti).limit(1)
        ).scalar_one_or_none()
        return row_id is not None

    @staticmethod
    def sweep_older_than(days: int = 35) -> int:
        """Garbage-collect rows older than ``days``. Returns deleted count.

        Mongo previously did this via a TTL index; PG needs an explicit
        sweep — Phase 4 adds a daily timer in ``app/__init__.py``.
        """
        cutoff = datetime.now(timezone.utc) - _timedelta(days=int(days))
        result = db.session.execute(
            delete(RevokedToken).where(RevokedToken.created_at < cutoff)
        )
        db.session.commit()
        return result.rowcount


# ======================================================================
# Phase 3 — SQLAlchemy 2.0 ORM model
# ======================================================================

import uuid as _uuid_orm
from datetime import datetime as _dt_orm
from datetime import timedelta as _timedelta

from sqlalchemy import (
    DateTime,
    Index,
    Text,
    UniqueConstraint,
    text as _sql_text_orm,
    select,
    delete,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models._base import SerializableMixin


class RevokedToken(db.Model, SerializableMixin):
    __tablename__ = 'revoked_tokens'

    id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid_orm.uuid4
    )
    jti: Mapped[str] = mapped_column(Text, nullable=False)
    # Polymorphic actor id — a users.id, a platform_admins.id, OR a raw
    # Keycloak sub. NO FK (migration 0011; mirrors credit_ledger's
    # created_by_user_id). Revocation keys on jti only; this is audit info.
    user_id: Mapped[_uuid_orm.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    created_at: Mapped[_dt_orm] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_sql_text_orm('now()')
    )

    __table_args__ = (
        UniqueConstraint('jti', name='uq_revoked_tokens_jti'),
        Index('ix_revoked_tokens_created', 'created_at'),
    )
