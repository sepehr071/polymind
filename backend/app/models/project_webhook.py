"""Project Webhooks model.

A webhook is a single outbound HTTP target that fires on project events.
The ``secret`` is shown to the caller exactly once on creation (and on
``rotate-secret``); list endpoints MUST omit it.
"""

import hashlib
import secrets
from datetime import datetime

from sqlalchemy import select, update as sa_update, delete as sa_delete
from sqlalchemy.orm.attributes import flag_modified

from app.extensions import db
from app.utils.ids import to_uuid, maybe_to_uuid


def _hook_to_legacy_dict(h, *, secret: str | None = None) -> dict | None:
    if h is None:
        return None
    d = h.to_dict()
    # Legacy fields the Mongo body emitted but the ORM doesn't track.
    d.setdefault('name', None)
    d.setdefault('last_fired_at', None)
    d.setdefault('last_status', None)
    d.setdefault('created_by', None)
    d.setdefault('updated_at', None)
    if secret is not None:
        d['secret'] = secret  # one-time exposure on create / rotate_secret
    return d


class ProjectWebhookModel:
    """Model for project_webhooks collection."""

    collection_name = 'project_webhooks'

    _ALLOWED_UPDATE_FIELDS = {'name', 'url', 'events', 'enabled'}

    @staticmethod
    def _hash_secret(secret: str) -> bytes:
        return hashlib.sha256(secret.encode('utf-8')).digest()

    @staticmethod
    def create(project_id, name: str, url: str, events=None, created_by=None) -> dict:
        from app.models.project_webhook import ProjectWebhook
        pid = to_uuid(project_id)
        _creator = maybe_to_uuid(created_by)  # not persisted; kept for API parity

        if not events:
            events = ['*']
        else:
            events = [str(e).strip() for e in events if str(e).strip()]
            if not events:
                events = ['*']

        secret = secrets.token_urlsafe(32)
        now = datetime.utcnow()
        h = ProjectWebhook(
            project_id=pid,
            url=url,
            events=events,
            secret_hash=ProjectWebhookModel._hash_secret(secret),
            enabled=True,
            created_at=now,
        )
        db.session.add(h)
        db.session.commit()
        d = _hook_to_legacy_dict(h, secret=secret)
        d['name'] = name
        return d

    @staticmethod
    def find_by_project(project_id) -> list:
        from app.models.project_webhook import ProjectWebhook
        try:
            pid = to_uuid(project_id)
        except (ValueError, TypeError):
            return []
        rows = db.session.execute(
            select(ProjectWebhook)
            .where(ProjectWebhook.project_id == pid)
            .order_by(ProjectWebhook.created_at.desc())
        ).scalars().all()
        return [_hook_to_legacy_dict(h) for h in rows]

    @staticmethod
    def find_by_id(webhook_id) -> dict:
        from app.models.project_webhook import ProjectWebhook
        try:
            hid = to_uuid(webhook_id)
        except (ValueError, TypeError):
            return None
        h = db.session.execute(
            select(ProjectWebhook).where(ProjectWebhook.id == hid)
        ).scalar_one_or_none()
        return _hook_to_legacy_dict(h)

    @staticmethod
    def update(webhook_id, update_data: dict) -> bool:
        from app.models.project_webhook import ProjectWebhook
        hid = to_uuid(webhook_id)
        clean = {
            k: v for k, v in (update_data or {}).items()
            if k in ProjectWebhookModel._ALLOWED_UPDATE_FIELDS
        }
        if not clean:
            return False

        if 'events' in clean:
            value = clean['events']
            if not isinstance(value, list):
                raise ValueError('events must be a list of strings')
            cleaned = [str(e).strip() for e in value if str(e).strip()]
            clean['events'] = cleaned or ['*']
        if 'enabled' in clean:
            clean['enabled'] = bool(clean['enabled'])

        h = db.session.execute(
            select(ProjectWebhook).where(ProjectWebhook.id == hid)
        ).scalar_one_or_none()
        if h is None:
            return False

        for k, v in clean.items():
            if k == 'url':
                h.url = v
            elif k == 'events':
                h.events = v
                flag_modified(h, 'events')
            elif k == 'enabled':
                h.enabled = v
            # `name` has no column — drop silently (kept in API surface only).
        db.session.commit()
        return True

    @staticmethod
    def delete(webhook_id) -> bool:
        from app.models.project_webhook import ProjectWebhook
        try:
            hid = to_uuid(webhook_id)
        except (ValueError, TypeError):
            return False
        result = db.session.execute(
            sa_delete(ProjectWebhook).where(ProjectWebhook.id == hid)
        )
        db.session.commit()
        return (result.rowcount or 0) > 0

    @staticmethod
    def rotate_secret(webhook_id) -> str:
        """Generate + persist a new secret. Returns the new plaintext secret."""
        from app.models.project_webhook import ProjectWebhook
        hid = to_uuid(webhook_id)
        new_secret = secrets.token_urlsafe(32)
        db.session.execute(
            sa_update(ProjectWebhook)
            .where(ProjectWebhook.id == hid)
            .values(secret_hash=ProjectWebhookModel._hash_secret(new_secret))
        )
        db.session.commit()
        return new_secret


# ---------------------------------------------------------------------------
# SQLAlchemy ORM model (Phase 3 strangler-fig).
# ---------------------------------------------------------------------------
import uuid as _uuid  # noqa: E402
from datetime import datetime as _datetime  # noqa: E402

from sqlalchemy import (  # noqa: E402
    Boolean,
    ForeignKey,
    Index,
    LargeBinary,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import (  # noqa: E402
    JSONB,
    TIMESTAMP,
    UUID as PG_UUID,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship  # noqa: E402

from app.models._base import SerializableMixin  # noqa: E402


class ProjectWebhook(db.Model, SerializableMixin):
    __tablename__ = 'project_webhooks'
    _serialize_exclude = ('secret_hash',)

    id: Mapped[_uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    project_id: Mapped[_uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('projects.id', ondelete='CASCADE'),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    events: Mapped[list] = mapped_column(JSONB, nullable=False, server_default='[]')
    secret_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text('true')
    )
    created_at: Mapped[_datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped['Project'] = relationship(  # noqa: F821
        back_populates='webhooks'
    )

    __table_args__ = (
        Index(
            'ix_project_webhooks_project_created',
            'project_id',
            text('created_at DESC'),
        ),
    )
