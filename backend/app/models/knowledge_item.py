import uuid
from datetime import datetime

from sqlalchemy import (
    ForeignKey,
    Index,
    func,
    or_,
    select,
    text,
    update as sa_update,
    delete as sa_delete,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm.attributes import flag_modified

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


class KnowledgeItem(db.Model, SerializableMixin):
    """SQLAlchemy ORM model for ``knowledge_items``."""

    __tablename__ = 'knowledge_items'

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
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
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('knowledge_folders.id', ondelete='SET NULL'),
        nullable=True,
    )
    title: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    content: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    source_type: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    source_id: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    source_ref: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tags: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    message_id: Mapped[str | None] = mapped_column(db.Text, nullable=True)
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
        Index(
            'ix_knowledge_items_user_created',
            'user_id',
            text('created_at DESC'),
        ),
        Index(
            'ix_knowledge_items_user_folder_created',
            'user_id',
            'folder_id',
            text('created_at DESC'),
        ),
        Index(
            'ix_knowledge_items_project_created',
            'project_id',
            text('created_at DESC'),
        ),
        Index(
            'ix_knowledge_items_title_trgm',
            'title',
            postgresql_using='gin',
            postgresql_ops={'title': 'gin_trgm_ops'},
        ),
        Index(
            'ix_knowledge_items_content_trgm',
            'content',
            postgresql_using='gin',
            postgresql_ops={'content': 'gin_trgm_ops'},
        ),
        Index(
            'ix_knowledge_items_notes_trgm',
            'notes',
            postgresql_using='gin',
            postgresql_ops={'notes': 'gin_trgm_ops'},
        ),
        Index(
            'ix_knowledge_items_tags_gin',
            'tags',
            postgresql_using='gin',
            postgresql_ops={'tags': 'jsonb_path_ops'},
        ),
    )


class KnowledgeItemModel:
    """Model for Knowledge Vault items — façade ported to SQLAlchemy."""

    collection_name = 'knowledge_items'

    @staticmethod
    def create(user_id, source_type: str, source_id: str = None, message_id: str = None,
               content: str = '', title: str = '', tags: list = None, folder_id=None,
               project_id=None, workspace_id=None,
               workflow_id: str = None, node_id: str = None,
               metadata: dict = None) -> dict:
        """Create a new knowledge item.

        ``source_ref`` is a JSONB blob that captures source-specific identifiers
        (workflow_id+node_id, routine_id, meeting_id+artifact_kind, or
        conversation_id+message_id depending on ``source_type``).
        """
        uid = _as_uuid(user_id)
        pid = _as_uuid(project_id) if project_id else None
        wid = _as_uuid(workspace_id) if workspace_id else None
        fid = _as_uuid(folder_id) if folder_id else None

        meta = metadata or {}
        if source_type == 'workflow':
            source_ref = {
                'workflow_id': str(workflow_id) if workflow_id else None,
                'node_id': node_id or None,
            }
        elif source_type == 'routine':
            source_ref = {'routine_id': str(source_id) if source_id else None}
        elif source_type == 'meeting':
            source_ref = {
                'meeting_id': str(source_id) if source_id else None,
                'artifact_kind': meta.get('artifact_kind'),
            }
        elif source_type == 'chat':
            source_ref = {
                'conversation_id': str(source_id) if source_id else None,
                'message_id': str(message_id) if message_id else None,
            }
        else:
            # arena / debate / other
            source_ref = {
                'session_id': str(source_id) if source_id else None,
                'message_id': str(message_id) if message_id else None,
            }

        row = KnowledgeItem(
            id=uuid.uuid4(),
            user_id=uid,
            workspace_id=wid,
            project_id=pid,
            folder_id=fid,
            title=title,
            content=content,
            notes='',
            source_type=source_type,
            source_id=str(source_id) if source_id else None,
            source_ref=source_ref,
            tags=tags or [],
            message_id=str(message_id) if message_id else None,
        )
        db.session.add(row)
        db.session.commit()
        out = row.to_dict()
        out['is_favorite'] = False  # legacy field — not yet on the ORM model
        return out

    # ------------------------------------------------------------------
    # List projection — list endpoints (``find_by_user`` / ``search`` /
    # ``search_scoped``) MUST NOT ship the full ``content`` Text column (up to
    # 50k chars/row). They select every column EXCEPT ``content`` plus a
    # ``func.left(content, 280)`` truncation aliased as ``content_preview``.
    # The emitted dict is byte-identical to ``to_dict()`` save for that one
    # key swap (``content`` -> ``content_preview``), so ``serialize_doc`` + the
    # frontend keep working. Single-item reads (``find_by_id``) stay
    # full-fidelity (full ``content``).
    # ------------------------------------------------------------------
    _LIST_PREVIEW_CHARS = 280

    @staticmethod
    def _list_columns():
        """Column list for list/search queries: every column except the heavy
        ``content`` blob, with a truncated ``content_preview`` in its place.
        Ordering mirrors ``KnowledgeItem.__table__.columns`` so the resulting
        dict key order matches ``to_dict()``.
        """
        cols = []
        for col in KnowledgeItem.__table__.columns:
            if col.name == 'content':
                cols.append(
                    func.left(KnowledgeItem.content, KnowledgeItemModel._LIST_PREVIEW_CHARS)
                    .label('content_preview')
                )
            else:
                cols.append(col)
        return cols

    @staticmethod
    def _row_to_list_dict(row) -> dict:
        """Serialize a projected list row to the legacy dict shape.

        Mirrors ``SerializableMixin.to_dict`` (UUID/datetime stringified +
        ``_id`` alias) but keyed off the SELECTed columns, so the ``content``
        key is absent and ``content_preview`` present.
        """
        out = dict(row._mapping)
        for k, v in list(out.items()):
            if isinstance(v, uuid.UUID):
                out[k] = str(v)
            elif isinstance(v, datetime):
                out[k] = v.isoformat()
        out['_id'] = str(out['id'])
        out['is_favorite'] = False  # legacy field — not on the ORM model
        return out

    @staticmethod
    def find_by_user(user_id, page: int = 1, limit: int = 20,
                     tag: str = None, favorite_only: bool = False,
                     folder_id=None, project_id=None,
                     include_content: bool = False):
        """List user's knowledge items, paginated.

        ``include_content=False`` (default) returns the lightweight list
        projection (``content_preview``, no full ``content``) for list/UI
        endpoints. Server-side consumers that need the FULL text — e.g. the
        workflow brand-brief injection AND its DLP scan, where a truncated
        preview would both corrupt the brief and leave secrets past the
        preview window unscanned — pass ``include_content=True`` to get full
        ``content`` rows.
        """
        uid = _as_uuid(user_id)
        if uid is None:
            return [], 0

        if include_content:
            stmt = select(KnowledgeItem).where(KnowledgeItem.user_id == uid)
        else:
            stmt = select(*KnowledgeItemModel._list_columns()).where(KnowledgeItem.user_id == uid)
        count_stmt = select(func.count()).select_from(KnowledgeItem).where(KnowledgeItem.user_id == uid)

        if tag:
            # JSONB array contains tag string
            stmt = stmt.where(KnowledgeItem.tags.op('?')(tag))
            count_stmt = count_stmt.where(KnowledgeItem.tags.op('?')(tag))

        if folder_id is not None:
            if folder_id == 'root':
                stmt = stmt.where(KnowledgeItem.folder_id.is_(None))
                count_stmt = count_stmt.where(KnowledgeItem.folder_id.is_(None))
            else:
                fid = _as_uuid(folder_id)
                stmt = stmt.where(KnowledgeItem.folder_id == fid)
                count_stmt = count_stmt.where(KnowledgeItem.folder_id == fid)

        if project_id == NULL_PROJECT_SENTINEL or project_id == 'null':
            stmt = stmt.where(KnowledgeItem.project_id.is_(None))
            count_stmt = count_stmt.where(KnowledgeItem.project_id.is_(None))
        elif project_id is not None:
            pid = _as_uuid(project_id)
            stmt = stmt.where(KnowledgeItem.project_id == pid)
            count_stmt = count_stmt.where(KnowledgeItem.project_id == pid)

        # favorite_only is not yet a first-class column; legacy data lived in
        # ``is_favorite`` on the Mongo doc. Ignore silently until the column
        # is added.

        total = int(db.session.execute(count_stmt).scalar_one() or 0)
        skip = (page - 1) * limit
        stmt = stmt.order_by(KnowledgeItem.created_at.desc()).offset(skip).limit(limit)
        if include_content:
            rows = db.session.execute(stmt).scalars().all()
            return [r.to_dict() for r in rows], total
        rows = db.session.execute(stmt).all()
        return [KnowledgeItemModel._row_to_list_dict(r) for r in rows], total

    @staticmethod
    def find_by_id(item_id) -> dict | None:
        """Get a single knowledge item by ID."""
        iid = _as_uuid(item_id)
        if iid is None:
            return None
        row = db.session.execute(
            select(KnowledgeItem).where(KnowledgeItem.id == iid)
        ).scalar_one_or_none()
        return row.to_dict() if row else None

    @staticmethod
    def update(item_id, user_id, updates: dict) -> bool:
        """Update a knowledge item.

        Raises ValueError('cannot_reassign_project') on attempted project mutation.
        """
        iid = _as_uuid(item_id)
        uid = _as_uuid(user_id)
        if iid is None or uid is None:
            return False
        if 'project_id' in updates:
            raise ValueError('cannot_reassign_project')

        allowed = {'title', 'tags', 'notes', 'folder_id'}
        clean = {}
        for k, v in (updates or {}).items():
            if k not in allowed:
                continue
            if k == 'folder_id':
                clean[k] = _as_uuid(v) if v else None
            else:
                clean[k] = v
        if not clean:
            return False
        clean['updated_at'] = datetime.utcnow()
        result = db.session.execute(
            sa_update(KnowledgeItem)
            .where(KnowledgeItem.id == iid, KnowledgeItem.user_id == uid)
            .values(**clean)
        )
        db.session.commit()
        return (result.rowcount or 0) > 0

    @staticmethod
    def delete(item_id, user_id) -> bool:
        """Delete a knowledge item."""
        iid = _as_uuid(item_id)
        uid = _as_uuid(user_id)
        if iid is None or uid is None:
            return False
        result = db.session.execute(
            sa_delete(KnowledgeItem).where(
                KnowledgeItem.id == iid,
                KnowledgeItem.user_id == uid,
            )
        )
        db.session.commit()
        return (result.rowcount or 0) > 0

    @staticmethod
    def search(user_id, query: str, page: int = 1, limit: int = 20):
        """Substring search across title / content / notes using ILIKE.

        Mongo's ``$text`` index isn't portable; trigram GIN indexes on the
        three text columns power this query at scale.
        """
        uid = _as_uuid(user_id)
        if uid is None or not query:
            return [], 0
        pattern = f'%{query}%'
        text_cond = or_(
            KnowledgeItem.title.ilike(pattern),
            KnowledgeItem.content.ilike(pattern),
            KnowledgeItem.notes.ilike(pattern),
        )
        base = select(*KnowledgeItemModel._list_columns()).where(
            KnowledgeItem.user_id == uid,
            text_cond,
        )
        total = int(db.session.execute(
            select(func.count()).select_from(KnowledgeItem).where(
                KnowledgeItem.user_id == uid,
                text_cond,
            )
        ).scalar_one() or 0)
        skip = (page - 1) * limit
        rows = db.session.execute(
            base.order_by(KnowledgeItem.created_at.desc()).offset(skip).limit(limit)
        ).all()
        return [KnowledgeItemModel._row_to_list_dict(r) for r in rows], total

    @staticmethod
    def search_scoped(user_id, query: str, accessible_project_ids,
                      project_id=None, page: int = 1, limit: int = 20):
        """Search with project-scope filtering.

        ``accessible_project_ids`` is the union of projects the caller may
        currently view. Hits with ``project_id IS NULL`` (personal scope)
        OR ``project_id IN accessible`` are returned.

        ``project_id`` overrides — when set to ``NULL_PROJECT_SENTINEL`` only
        personal-scope items match; when set to a UUID/str only that exact
        project matches (must also be in ``accessible``).
        """
        uid = _as_uuid(user_id)
        if uid is None or not query:
            return [], 0
        pattern = f'%{query}%'
        text_cond = or_(
            KnowledgeItem.title.ilike(pattern),
            KnowledgeItem.content.ilike(pattern),
            KnowledgeItem.notes.ilike(pattern),
        )

        conds = [KnowledgeItem.user_id == uid, text_cond]

        accessible_uuids = []
        for a in accessible_project_ids or []:
            au = _as_uuid(a)
            if au is not None:
                accessible_uuids.append(au)

        if project_id == NULL_PROJECT_SENTINEL:
            conds.append(KnowledgeItem.project_id.is_(None))
        elif project_id:
            pid = _as_uuid(project_id)
            if pid is None:
                return [], 0
            conds.append(KnowledgeItem.project_id == pid)
        else:
            if accessible_uuids:
                conds.append(or_(
                    KnowledgeItem.project_id.is_(None),
                    KnowledgeItem.project_id.in_(accessible_uuids),
                ))
            else:
                conds.append(KnowledgeItem.project_id.is_(None))

        total = int(db.session.execute(
            select(func.count()).select_from(KnowledgeItem).where(*conds)
        ).scalar_one() or 0)
        skip = (page - 1) * limit
        rows = db.session.execute(
            select(*KnowledgeItemModel._list_columns())
            .where(*conds)
            .order_by(KnowledgeItem.created_at.desc())
            .offset(skip)
            .limit(limit)
        ).all()
        return [KnowledgeItemModel._row_to_list_dict(r) for r in rows], total

    @staticmethod
    def get_user_tags(user_id) -> list:
        """Distinct tags across a user's items (de-duplicated)."""
        return KnowledgeItemModel.distinct_tags(user_id)

    @staticmethod
    def distinct_tags(user_id) -> list:
        """SQL replacement for the Mongo ``distinct('tags')`` call.

        ``jsonb_array_elements_text`` flattens the JSONB array column then we
        de-dupe + sort in Python.
        """
        uid = _as_uuid(user_id)
        if uid is None:
            return []
        rows = db.session.execute(
            select(func.jsonb_array_elements_text(KnowledgeItem.tags).label('tag'))
            .where(KnowledgeItem.user_id == uid)
        ).all()
        return sorted({r.tag for r in rows if r.tag})

    @staticmethod
    def count_by_user(user_id) -> int:
        """Count total knowledge items for a user."""
        uid = _as_uuid(user_id)
        if uid is None:
            return 0
        return int(db.session.execute(
            select(func.count()).select_from(KnowledgeItem)
            .where(KnowledgeItem.user_id == uid)
        ).scalar_one() or 0)

    @staticmethod
    def count_by_folder(user_id, folder_id=None) -> int:
        """Count knowledge items in a folder."""
        uid = _as_uuid(user_id)
        if uid is None:
            return 0
        stmt = select(func.count()).select_from(KnowledgeItem).where(
            KnowledgeItem.user_id == uid
        )
        if folder_id is None or folder_id == 'root':
            stmt = stmt.where(KnowledgeItem.folder_id.is_(None))
        else:
            stmt = stmt.where(KnowledgeItem.folder_id == _as_uuid(folder_id))
        return int(db.session.execute(stmt).scalar_one() or 0)

    @staticmethod
    def counts_by_folder(user_id) -> dict:
        """Item counts for ALL of a user's folders in one grouped query.

        Returns ``{str(folder_id): count}``. Foldered items only (rows with a
        non-null ``folder_id``); the unfiled/'root' bucket is counted
        separately via ``count_by_folder(user_id, 'root')``. Replaces the
        per-folder N+1 the folder-list route used to issue.
        """
        uid = _as_uuid(user_id)
        if uid is None:
            return {}
        rows = db.session.execute(
            select(
                KnowledgeItem.folder_id,
                func.count().label('cnt'),
            )
            .where(
                KnowledgeItem.user_id == uid,
                KnowledgeItem.folder_id.isnot(None),
            )
            .group_by(KnowledgeItem.folder_id)
        ).all()
        return {str(r.folder_id): int(r.cnt or 0) for r in rows}

    @staticmethod
    def move_to_folder(item_ids: list, user_id, folder_id=None,
                       sync_project: bool = False, project_id=None,
                       workspace_id=None) -> int:
        """Move knowledge items to a folder.

        When ``sync_project`` is True, also write the supplied project_id +
        workspace_id (either may be None to clear).
        """
        uid = _as_uuid(user_id)
        if uid is None:
            return 0
        uuids = [_as_uuid(i) for i in (item_ids or [])]
        uuids = [u for u in uuids if u is not None]
        if not uuids:
            return 0
        fid = _as_uuid(folder_id) if folder_id else None
        values = {'folder_id': fid, 'updated_at': datetime.utcnow()}
        if sync_project:
            values['project_id'] = _as_uuid(project_id) if project_id else None
            values['workspace_id'] = _as_uuid(workspace_id) if workspace_id else None
        result = db.session.execute(
            sa_update(KnowledgeItem)
            .where(KnowledgeItem.id.in_(uuids), KnowledgeItem.user_id == uid)
            .values(**values)
        )
        db.session.commit()
        return int(result.rowcount or 0)

    # ------------------------------------------------------------------
    # Tag mutators — JSONB array column. ``flag_modified`` ensures the
    # session writes the field back even though we mutate a Python list.
    # ------------------------------------------------------------------

    @staticmethod
    def _load(item_id, user_id=None):
        iid = _as_uuid(item_id)
        if iid is None:
            return None
        stmt = select(KnowledgeItem).where(KnowledgeItem.id == iid)
        if user_id is not None:
            uid = _as_uuid(user_id)
            stmt = stmt.where(KnowledgeItem.user_id == uid)
        return db.session.execute(stmt).scalar_one_or_none()

    @staticmethod
    def add_tags(item_id, tag_list: list, user_id=None) -> bool:
        row = KnowledgeItemModel._load(item_id, user_id=user_id)
        if row is None:
            return False
        existing = list(row.tags or [])
        # Preserve insertion order while de-duping.
        row.tags = list(dict.fromkeys(existing + (tag_list or [])))
        flag_modified(row, 'tags')
        row.updated_at = datetime.utcnow()
        db.session.commit()
        return True

    @staticmethod
    def remove_tags(item_id, tag_list: list, user_id=None) -> bool:
        row = KnowledgeItemModel._load(item_id, user_id=user_id)
        if row is None:
            return False
        drop = set(tag_list or [])
        row.tags = [t for t in (row.tags or []) if t not in drop]
        flag_modified(row, 'tags')
        row.updated_at = datetime.utcnow()
        db.session.commit()
        return True

    @staticmethod
    def replace_tags(item_id, tag_list: list, user_id=None) -> bool:
        row = KnowledgeItemModel._load(item_id, user_id=user_id)
        if row is None:
            return False
        # De-dupe while preserving caller order.
        row.tags = list(dict.fromkeys(tag_list or []))
        flag_modified(row, 'tags')
        row.updated_at = datetime.utcnow()
        db.session.commit()
        return True
