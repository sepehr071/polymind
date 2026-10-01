"""Login attempt tracker — PG-backed throttle storage.

Replaces the legacy Mongo ``login_attempt_log`` collection. Rows are GC'd
via the explicit ``LoginAttemptModel.sweep_older_than(minutes)`` sweep
(no Mongo TTL index equivalent on PG without pg_cron).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Index,
    Text,
    delete as sa_delete,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models._base import SerializableMixin


class LoginAttempt(db.Model, SerializableMixin):
    __tablename__ = 'login_attempt_log'

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ip: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index('ix_login_attempt_ip_email_at', 'ip', 'email', 'at'),
        Index('ix_login_attempt_at', 'at'),
    )


class LoginAttemptModel:
    @staticmethod
    def record(ip: str, email: str) -> None:
        try:
            row = LoginAttempt(
                id=uuid.uuid4(),
                ip=(ip or '').strip(),
                email=(email or '').strip().lower(),
                at=datetime.now(timezone.utc),
            )
            db.session.add(row)
            db.session.commit()
        except Exception:
            db.session.rollback()

    @staticmethod
    def count_recent(ip: str, email: str, window_seconds: int) -> int:
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
            return int(db.session.execute(
                select(func.count())
                .select_from(LoginAttempt)
                .where(
                    LoginAttempt.ip == (ip or '').strip(),
                    LoginAttempt.email == (email or '').strip().lower(),
                    LoginAttempt.at >= cutoff,
                )
            ).scalar() or 0)
        except Exception:
            return 0

    @staticmethod
    def clear_for_email(email: str) -> None:
        try:
            db.session.execute(
                sa_delete(LoginAttempt).where(
                    LoginAttempt.email == (email or '').strip().lower()
                )
            )
            db.session.commit()
        except Exception:
            db.session.rollback()

    @staticmethod
    def sweep_older_than(minutes: int = 15) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        try:
            result = db.session.execute(
                sa_delete(LoginAttempt).where(LoginAttempt.at < cutoff)
            )
            db.session.commit()
            return result.rowcount or 0
        except Exception:
            db.session.rollback()
            return 0
