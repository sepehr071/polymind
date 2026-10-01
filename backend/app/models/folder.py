from datetime import datetime
import uuid

from sqlalchemy import (
    ForeignKey,
    Index,
    delete,
    func,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models._base import SerializableMixin


# Sentinel string the route layer translates `?project_id=null` into. Lets
# callers distinguish "no filter" (None) from "filter where project_id is
# null/missing" (the sentinel).
NULL_PROJECT_SENTINEL = '__null__'


def _coerce_uuid(value):
    if value in (None, '', b''):
        return None
    if isinstance(value, uuid.UUID):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode('utf-8', 'replace')
    if isinstance(value, str):
        try:
            return uuid.UUID(value)
        except (ValueError, AttributeError):
            return None
    return None


def _serialize_folder(obj) -> dict:
    """Emit Mongo-shaped folder dict from a Folder ORM row.

    Bridges:
      - ``position`` (ORM) → ``order`` (legacy wire-name routes sort on).
      - ``color`` / ``icon`` are not modelled in the ORM; fill with the
        legacy defaults so consumers reading ``folder['color']`` keep
        working.
    """
    if obj is None:
        return None
    out = obj.to_dict()
    out['order'] = out.get('position', 0)
    out.setdefault('color', '#5c9aed')
    out.setdefault('icon', None)
    return out


class FolderModel:
    collection_name = 'folders'

    @staticmethod
    def create(user_id, name, color='#5c9aed', icon=None, parent_id=None,
               project_id=None):
        """Create a new folder. ``color`` and ``icon`` are accepted but not
        persisted (ORM column-set lacks them — Phase 5 schema decision)."""
        uid = _coerce_uuid(user_id)
        if uid is None:
            raise ValueError('user_id must coerce to UUID')

        pid = _coerce_uuid(project_id) if project_id else None
        parent = _coerce_uuid(parent_id) if parent_id else None

        # Next position scoped to (user, parent, project).
        last_position_row = db.session.execute(
            select(func.max(Folder.position)).where(
                Folder.user_id == uid,
                Folder.parent_id.is_(parent) if parent is None else Folder.parent_id == parent,
                Folder.project_id.is_(pid) if pid is None else Folder.project_id == pid,
            )
        ).scalar()
        next_pos = (int(last_position_row) + 1) if last_position_row is not None else 0

        folder = Folder(
            user_id=uid,
            name=name,
            parent_id=parent,
            project_id=pid,
            position=next_pos,
        )
        db.session.add(folder)
        db.session.commit()
        return _serialize_folder(folder)

    @staticmethod
    def find_by_id(folder_id):
        fid = _coerce_uuid(folder_id)
        if fid is None:
            return None
        obj = db.session.get(Folder, fid)
        return _serialize_folder(obj) if obj is not None else None

    @staticmethod
    def find_by_user(user_id, parent_id=None, project_id=None):
        """Find folders for a user. Project tri-state mirrors ConversationModel."""
        uid = _coerce_uuid(user_id)
        if uid is None:
            return []

        stmt = select(Folder).where(Folder.user_id == uid)
        if parent_id:
            parent = _coerce_uuid(parent_id)
            if parent is None:
                return []
            stmt = stmt.where(Folder.parent_id == parent)
        else:
            stmt = stmt.where(Folder.parent_id.is_(None))

        if project_id == NULL_PROJECT_SENTINEL:
            stmt = stmt.where(Folder.project_id.is_(None))
        elif project_id is not None:
            pid = _coerce_uuid(project_id)
            if pid is None:
                return []
            stmt = stmt.where(Folder.project_id == pid)

        stmt = stmt.order_by(Folder.position.asc())
        rows = db.session.execute(stmt).scalars().all()
        return [_serialize_folder(r) for r in rows]

    @staticmethod
    def find_all_by_user(user_id, project_id=None):
        """Find all folders for a user (flat list)."""
        uid = _coerce_uuid(user_id)
        if uid is None:
            return []

        stmt = select(Folder).where(Folder.user_id == uid)
        if project_id == NULL_PROJECT_SENTINEL:
            stmt = stmt.where(Folder.project_id.is_(None))
        elif project_id is not None:
            pid = _coerce_uuid(project_id)
            if pid is None:
                return []
            stmt = stmt.where(Folder.project_id == pid)
        stmt = stmt.order_by(Folder.position.asc())
        rows = db.session.execute(stmt).scalars().all()
        return [_serialize_folder(r) for r in rows]

    @staticmethod
    def update(folder_id, update_data):
        """Update folder fields. Maps legacy ``order`` → ORM ``position``."""
        fid = _coerce_uuid(folder_id)
        if fid is None:
            return None
        obj = db.session.get(Folder, fid)
        if obj is None:
            return None
        for k, v in update_data.items():
            if k == 'order':
                obj.position = int(v)
                continue
            if k in ('color', 'icon'):
                # Not modelled in ORM; ignore so legacy callers don't crash.
                continue
            if k in ('parent_id', 'project_id') and v is not None:
                v = _coerce_uuid(v)
            if hasattr(obj, k):
                setattr(obj, k, v)
        obj.updated_at = datetime.utcnow()
        db.session.commit()
        return obj

    @staticmethod
    def reorder(user_id, folder_orders):
        """Reorder folders: list of {id, order}."""
        uid = _coerce_uuid(user_id)
        if uid is None:
            return
        for item in folder_orders:
            fid = _coerce_uuid(item.get('id'))
            if fid is None:
                continue
            db.session.execute(
                update(Folder)
                .where(Folder.id == fid, Folder.user_id == uid)
                .values(position=int(item['order']), updated_at=datetime.utcnow())
            )
        db.session.commit()

    @staticmethod
    def delete(folder_id):
        fid = _coerce_uuid(folder_id)
        if fid is None:
            return None
        result = db.session.execute(delete(Folder).where(Folder.id == fid))
        db.session.commit()
        return result

    @staticmethod
    def null_project_for_project(project_id):
        """Set ``project_id`` to NULL on all folders carrying *project_id*.
        Used during project delete cascade — folders revert to personal scope."""
        pid = _coerce_uuid(project_id)
        if pid is None:
            return 0
        result = db.session.execute(
            update(Folder)
            .where(Folder.project_id == pid)
            .values(project_id=None, updated_at=datetime.utcnow())
        )
        db.session.commit()
        return result.rowcount or 0

    @staticmethod
    def null_parent_for_children(parent_id):
        """Set ``parent_id`` to NULL on all folders whose parent is
        *parent_id*. Used when a folder is deleted — its direct children
        bubble up to root instead of becoming orphans."""
        pid = _coerce_uuid(parent_id)
        if pid is None:
            return 0
        result = db.session.execute(
            update(Folder)
            .where(Folder.parent_id == pid)
            .values(parent_id=None, updated_at=datetime.utcnow())
        )
        db.session.commit()
        return result.rowcount or 0

    @staticmethod
    def count_by_user(user_id):
        uid = _coerce_uuid(user_id)
        if uid is None:
            return 0
        return int(
            db.session.execute(
                select(func.count()).select_from(Folder).where(Folder.user_id == uid)
            ).scalar()
            or 0
        )


# ---------------------------------------------------------------------------
# Phase 3 — SQLAlchemy 2.0 ORM model.
# ---------------------------------------------------------------------------


class Folder(db.Model, SerializableMixin):
    __tablename__ = 'folders'

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('projects.id', ondelete='SET NULL'),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(db.Text, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('folders.id', ondelete='CASCADE'),
        nullable=True,
    )
    position: Mapped[int] = mapped_column(
        db.Integer, nullable=False, server_default=text('0')
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index('ix_folders_user_parent', 'user_id', 'parent_id'),
        Index('ix_folders_user_position', 'user_id', 'position'),
        Index(
            'ix_folders_user_project_parent',
            'user_id', 'project_id', 'parent_id',
        ),
    )
