import uuid
from datetime import datetime

from sqlalchemy import (
    ForeignKey,
    Index,
    UniqueConstraint,
    func,
    select,
    text,
    update as sa_update,
    delete as sa_delete,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models._base import SerializableMixin
from bson import ObjectId


# Sentinel string the route layer translates `?project_id=null` into. Lets
# callers distinguish "no filter" (None) from "filter where project_id is
# null/missing" (the sentinel).
NULL_PROJECT_SENTINEL = '__null__'


def _as_uuid(v):
    """Coerce str / UUID / ObjectId to ``uuid.UUID`` or ``None``."""
    if v is None:
        return None
    if isinstance(v, uuid.UUID):
        return v
    if isinstance(v, ObjectId):
        return None
    try:
        return uuid.UUID(str(v))
    except (ValueError, AttributeError):
        return None


class KnowledgeFolder(db.Model, SerializableMixin):
    """SQLAlchemy ORM model for ``knowledge_folders``.

    ``scope_key`` is computed at create-time (``u:<user>`` or
    ``p:<project>``) and enforced unique with ``name`` so a user can't have
    two folders named the same thing inside the same scope.
    """

    __tablename__ = 'knowledge_folders'

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=True,
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('workspaces.id', ondelete='CASCADE'),
        nullable=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('projects.id', ondelete='SET NULL'),
        nullable=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('knowledge_folders.id', ondelete='CASCADE'),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(db.Text, nullable=False)
    scope_key: Mapped[str] = mapped_column(db.Text, nullable=False)
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
        UniqueConstraint(
            'scope_key', 'name', name='uq_knowledge_folders_scope_name'
        ),
        Index('ix_knowledge_folders_user_position', 'user_id', 'position'),
        Index(
            'ix_knowledge_folders_project_position',
            'project_id',
            'position',
        ),
    )


class KnowledgeFolderModel:
    """Model for Knowledge Vault folders — façade ported to SQLAlchemy."""

    collection_name = 'knowledge_folders'

    @staticmethod
    def find_by_user_scope_name(user_id, name: str, project_id=None) -> dict | None:
        """Look up a folder by ``(scope_key, name)``. Used by the meetings
        save-artifact route to find-or-create a per-meeting folder."""
        scope_key = KnowledgeFolderModel._compute_scope_key(user_id, project_id)
        row = db.session.execute(
            select(KnowledgeFolder).where(
                KnowledgeFolder.scope_key == scope_key,
                KnowledgeFolder.name == name,
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return row.to_dict()

    @staticmethod
    def _compute_scope_key(user_id, project_id) -> str:
        """Build the scope_key used by the unique (scope_key, name) index.

        Project-scoped folders share their project's namespace under a
        ``p:<project_id>`` prefix; un-scoped folders are isolated per user
        under ``u:<user_id>``.
        """
        if project_id:
            return f'p:{str(project_id)}'
        return f'u:{str(user_id)}'

    @staticmethod
    def create(user_id, name: str, color: str = '#5c9aed',
               project_id=None, workspace_id=None) -> dict:
        """Create a new knowledge folder.

        Color is preserved in the legacy dict payload but is not currently a
        first-class column on the ORM model — callers that need colour can
        fold it back when the schema gains the column.
        """
        uid = _as_uuid(user_id)
        pid = _as_uuid(project_id) if project_id else None
        wid = _as_uuid(workspace_id) if workspace_id else None

        # Position is per-user (cosmetic).
        max_pos = db.session.execute(
            select(func.max(KnowledgeFolder.position))
            .where(KnowledgeFolder.user_id == uid)
        ).scalar_one()
        next_pos = (int(max_pos) + 1) if max_pos is not None else 0

        scope_key = KnowledgeFolderModel._compute_scope_key(uid, pid)

        row = KnowledgeFolder(
            id=uuid.uuid4(),
            user_id=uid,
            workspace_id=wid,
            project_id=pid,
            name=name[:100],
            scope_key=scope_key,
            position=next_pos,
        )
        db.session.add(row)
        db.session.commit()
        out = row.to_dict()
        # Echo `color` so callers expecting the legacy shape don't break.
        out['color'] = color
        out['order'] = next_pos
        return out

    @staticmethod
    def find_by_user(user_id, project_id=None) -> list:
        """List folders for a user.

        project_id semantics:
            None                                -> no project filter
            NULL_PROJECT_SENTINEL ('__null__')  -> only un-scoped folders
            'null'                              -> alias of the sentinel
            UUID / str                          -> exact match
        """
        uid = _as_uuid(user_id)
        stmt = select(KnowledgeFolder).where(KnowledgeFolder.user_id == uid)

        if project_id == NULL_PROJECT_SENTINEL or project_id == 'null':
            stmt = stmt.where(KnowledgeFolder.project_id.is_(None))
        elif project_id is not None:
            stmt = stmt.where(KnowledgeFolder.project_id == _as_uuid(project_id))

        rows = db.session.execute(
            stmt.order_by(KnowledgeFolder.position.asc())
        ).scalars().all()
        return [r.to_dict() for r in rows]

    @staticmethod
    def find_by_id(folder_id) -> dict | None:
        """Get a single folder by ID."""
        fid = _as_uuid(folder_id)
        if fid is None:
            return None
        row = db.session.execute(
            select(KnowledgeFolder).where(KnowledgeFolder.id == fid)
        ).scalar_one_or_none()
        return row.to_dict() if row else None

    @staticmethod
    def update(folder_id, user_id, updates: dict) -> bool:
        """Update a folder.

        Raises:
            ValueError('cannot_reassign_project'): refused.
            ValueError('duplicate_name'): another folder in this scope owns
                the new name.
        """
        fid = _as_uuid(folder_id)
        uid = _as_uuid(user_id)
        if fid is None or uid is None:
            return False

        if 'project_id' in updates:
            raise ValueError('cannot_reassign_project')

        allowed = {'name'}
        clean = {k: v for k, v in (updates or {}).items() if k in allowed}
        if not clean:
            return False

        if 'name' in clean:
            new_name = clean['name'][:100]
            clean['name'] = new_name
            current = db.session.execute(
                select(KnowledgeFolder).where(
                    KnowledgeFolder.id == fid,
                    KnowledgeFolder.user_id == uid,
                )
            ).scalar_one_or_none()
            if current is None:
                return False
            collision = db.session.execute(
                select(KnowledgeFolder).where(
                    KnowledgeFolder.scope_key == current.scope_key,
                    KnowledgeFolder.name == new_name,
                    KnowledgeFolder.id != fid,
                )
            ).scalar_one_or_none()
            if collision is not None:
                raise ValueError('duplicate_name')

        clean['updated_at'] = datetime.utcnow()
        result = db.session.execute(
            sa_update(KnowledgeFolder)
            .where(KnowledgeFolder.id == fid, KnowledgeFolder.user_id == uid)
            .values(**clean)
        )
        db.session.commit()
        return (result.rowcount or 0) > 0

    @staticmethod
    def delete(folder_id, user_id) -> bool:
        """Delete a folder. Items in this folder have folder_id reset to NULL."""
        fid = _as_uuid(folder_id)
        uid = _as_uuid(user_id)
        if fid is None or uid is None:
            return False

        # Reset folder_id on owned items.
        from app.models.knowledge_item import KnowledgeItem
        db.session.execute(
            sa_update(KnowledgeItem)
            .where(KnowledgeItem.user_id == uid, KnowledgeItem.folder_id == fid)
            .values(folder_id=None, updated_at=datetime.utcnow())
        )

        result = db.session.execute(
            sa_delete(KnowledgeFolder).where(
                KnowledgeFolder.id == fid,
                KnowledgeFolder.user_id == uid,
            )
        )
        db.session.commit()
        return (result.rowcount or 0) > 0

    @staticmethod
    def reorder(user_id, folder_orders: list) -> bool:
        """Reorder folders for a user."""
        uid = _as_uuid(user_id)
        if uid is None:
            return False
        now = datetime.utcnow()
        for item in folder_orders or []:
            fid = _as_uuid(item.get('folder_id') or item.get('id'))
            if fid is None:
                continue
            db.session.execute(
                sa_update(KnowledgeFolder)
                .where(KnowledgeFolder.id == fid, KnowledgeFolder.user_id == uid)
                .values(position=int(item.get('order', 0)), updated_at=now)
            )
        db.session.commit()
        return True

    @staticmethod
    def count_by_user(user_id) -> int:
        """Count total folders for a user."""
        uid = _as_uuid(user_id)
        if uid is None:
            return 0
        return db.session.execute(
            select(func.count()).select_from(KnowledgeFolder)
            .where(KnowledgeFolder.user_id == uid)
        ).scalar_one() or 0

    @staticmethod
    def exists(folder_id, user_id) -> bool:
        """Check if a folder exists and belongs to user."""
        fid = _as_uuid(folder_id)
        uid = _as_uuid(user_id)
        if fid is None or uid is None:
            return False
        row = db.session.execute(
            select(KnowledgeFolder.id).where(
                KnowledgeFolder.id == fid,
                KnowledgeFolder.user_id == uid,
            )
        ).scalar_one_or_none()
        return row is not None
