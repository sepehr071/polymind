"""Audit log — administrative actions trail.

Phase 4D: PG-backed via ORM ``AuditLog``. Mongo dict shape preserved on read.
"""

import uuid
from datetime import datetime


def _to_uuid(val):
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except Exception:
        return None


class AuditLogModel:
    """Model for tracking administrative actions"""
    collection_name = 'audit_logs'

    @staticmethod
    def create(action, admin_id, target_id=None, target_type=None,
               details=None, ip_address=None, category='app'):
        """Insert an audit row. Returns the inserted dict."""
        admin_uuid = _to_uuid(admin_id)
        # target_id stored as TEXT — allow either UUID hex or arbitrary string.
        target_str = str(target_id) if target_id is not None else None
        merged_details = dict(details or {})
        if ip_address is not None:
            merged_details.setdefault('ip_address', ip_address)
        row = AuditLog(
            admin_user_id=admin_uuid,
            action=action,
            target_id=target_str,
            target_type=target_type,
            details=merged_details,
            category=category,
        )
        db.session.add(row)
        db.session.commit()
        return _audit_to_dict(row)

    @staticmethod
    def find_all(skip: int = 0, limit: int = 50, action=None, admin_id=None):
        stmt = select(AuditLog)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        if admin_id:
            au = _to_uuid(admin_id)
            if au is not None:
                stmt = stmt.where(AuditLog.admin_user_id == au)
            else:
                return []
        stmt = stmt.order_by(AuditLog.created_at.desc()).offset(skip).limit(limit)
        rows = db.session.execute(stmt).scalars().all()
        return [_audit_to_dict(r) for r in rows]

    @staticmethod
    def count(action=None, admin_id=None) -> int:
        stmt = select(func.count(AuditLog.id))
        if action:
            stmt = stmt.where(AuditLog.action == action)
        if admin_id:
            au = _to_uuid(admin_id)
            if au is not None:
                stmt = stmt.where(AuditLog.admin_user_id == au)
            else:
                return 0
        return int(db.session.execute(stmt).scalar() or 0)

    @staticmethod
    def find_by_workspace(workspace_id, limit: int = 50, before=None,
                          actor_id=None, action=None):
        """List entries scoped to a workspace.

        Mongo stored workspace_id under various positions (``details.workspace_id``
        or ``target_id`` w/ ``target_type='workspace'``). PG mirrors this:
            details->>'workspace_id' = :wid
            OR (target_id = :wid AND target_type = 'workspace')
        """
        wid_str = str(workspace_id)
        stmt = select(AuditLog).where(
            db.or_(
                AuditLog.details['workspace_id'].astext == wid_str,
                db.and_(
                    AuditLog.target_id == wid_str,
                    AuditLog.target_type == 'workspace',
                ),
            )
        )
        if before is not None and isinstance(before, datetime):
            stmt = stmt.where(AuditLog.created_at < before)
        if actor_id is not None:
            au = _to_uuid(actor_id)
            if au is None:
                return []
            stmt = stmt.where(AuditLog.admin_user_id == au)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        stmt = stmt.order_by(AuditLog.created_at.desc()).limit(int(limit))
        rows = db.session.execute(stmt).scalars().all()
        return [_audit_to_dict(r) for r in rows]


def _audit_to_dict(row: 'AuditLog') -> dict:
    out = row.to_dict()
    out['admin_id'] = str(row.admin_user_id) if row.admin_user_id else None
    out['category'] = row.category
    # Surface ip_address back to the top level for legacy readers.
    if isinstance(row.details, dict):
        if 'ip_address' in row.details:
            out['ip_address'] = row.details.get('ip_address')
    return out


# ======================================================================
# Phase 3 — SQLAlchemy 2.0 ORM model
# ======================================================================

import uuid as _uuid_orm
from datetime import datetime as _dt_orm

from sqlalchemy import (
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


class AuditLog(db.Model, SerializableMixin):
    __tablename__ = 'audit_logs'

    id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid_orm.uuid4
    )
    admin_user_id: Mapped[_uuid_orm.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Discriminator separating super-admin ('app') from holding/operator
    # ('holding') trail rows after the platform-admin merge (migration 0017).
    category: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=_sql_text_orm("'app'")
    )
    details: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, server_default=_sql_text_orm("'{}'::jsonb")
    )
    created_at: Mapped[_dt_orm] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_sql_text_orm('now()')
    )

    __table_args__ = (
        Index('ix_audit_logs_action', 'action'),
        Index('ix_audit_logs_admin', 'admin_user_id'),
        Index('ix_audit_logs_target', 'target_id'),
        Index('ix_audit_logs_category', 'category'),
        Index(
            'ix_audit_logs_created_brin',
            'created_at',
            postgresql_using='brin',
        ),
    )
