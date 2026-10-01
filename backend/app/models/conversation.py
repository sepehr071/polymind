from datetime import datetime
import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    UniqueConstraint,
    and_,
    delete,
    func,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import (
    JSONB,
    TIMESTAMP,
    UUID as PG_UUID,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm.attributes import flag_modified

from app.extensions import db
from app.models._base import SerializableMixin


# Sentinel string the route layer translates `?project_id=null` into. Lets
# callers distinguish "no filter" (None) from "filter where project_id is
# null/missing" (the sentinel).
NULL_PROJECT_SENTINEL = '__null__'


# ---------------------------------------------------------------------------
# Helpers for the façade. The Mongo wire shape used ObjectId for ids, dict
# blobs for embedded ``branches`` / ``token_count`` etc. The ORM uses UUID
# strings + child tables. These helpers bridge the two so callers see the
# legacy dict shape.
# ---------------------------------------------------------------------------


def _coerce_uuid(value):
    """Coerce arbitrary id input (str, bytes, UUID, ObjectId) to UUID.

    Returns ``None`` on falsy input. The legacy façade accepted ObjectId hex
    strings; routes still pass them. Postgres stores UUIDs, so anything that
    is *already* a UUID-like string passes through; ObjectId-hex strings get
    NULL'd because they can't address Postgres rows.
    """
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


def _serialize_conversation(obj: 'Conversation', branch_map=None,
                            include_branches=True) -> dict:
    """Emit a dict matching the legacy Mongo wire shape.

    - ``_id`` mirrors ``id`` as a string (legacy code does ``conv['_id']``).
    - ``branches`` is rehydrated from the child ``conversation_branches``
      table into the embedded array shape Mongo used.

    ``branch_map`` (``dict[conversation_id -> list[ConversationBranch]]``) lets
    list callers pre-fetch every conversation's branches in ONE query and pass
    the bucket in, avoiding the per-row SELECT (the N+1 in ``find_by_user``).
    When ``None`` the per-conversation SELECT is issued (single-conversation
    callers keep their existing behaviour).

    ``include_branches=False`` skips branch hydration entirely (no extra SELECT)
    and falls back to the synthetic single ``main`` branch shape. Hot single-row
    callers (the chat stream pre-flight) that never read ``branches`` use this to
    drop a per-turn ``conversation_branches`` query.
    """
    if obj is None:
        return None
    out = obj.to_dict()
    # Branches: fetch child rows + reshape into legacy embedded format. Use the
    # pre-fetched bucket when supplied; otherwise issue the per-row SELECT.
    # ``include_branches=False`` short-circuits to the synthetic ``main`` shape
    # below (the ``or [...]`` fallback) without touching the DB.
    if not include_branches:
        branches = []
    elif branch_map is not None:
        branches = branch_map.get(obj.id, [])
    else:
        branches = (
            db.session.execute(
                select(ConversationBranch).where(
                    ConversationBranch.conversation_id == obj.id
                )
            )
            .scalars()
            .all()
        )
    out['branches'] = [
        {
            'id': b.branch_key,
            'name': b.name,
            'parent_branch': b.parent_branch_key,
            'branch_point_message_id': (
                str(b.branch_point_message_id)
                if b.branch_point_message_id is not None
                else None
            ),
            'created_at': b.created_at.isoformat() if b.created_at else None,
        }
        for b in branches
    ] or [
        {
            'id': 'main',
            'name': 'Main',
            'parent_branch': None,
            'branch_point_message_id': None,
            'created_at': out.get('created_at'),
        }
    ]
    return out


def _branch_map_for(conversation_ids):
    """Fetch every branch for *conversation_ids* in ONE query, bucketed by
    ``conversation_id``. Replaces the per-conversation SELECT in list paths.

    Buckets are insertion-ordered to match the per-row SELECT (which had no
    explicit ``ORDER BY``); rows are returned in primary-key order so the
    embedded ``branches`` array shape stays identical to the pre-fetch path.
    """
    ids = [c for c in conversation_ids if c is not None]
    if not ids:
        return {}
    rows = (
        db.session.execute(
            select(ConversationBranch).where(
                ConversationBranch.conversation_id.in_(ids)
            )
        )
        .scalars()
        .all()
    )
    bucket: dict = {}
    for b in rows:
        bucket.setdefault(b.conversation_id, []).append(b)
    return bucket


class ConversationModel:
    collection_name = 'conversations'

    @staticmethod
    def create(user_id, config_id, title='New conversation', folder_id=None,
               project_id=None, kind='chat', workspace_id=None):
        """Create a new conversation in Postgres + a default 'main' branch row.

        ``workspace_id`` is the org the chat belongs to (the caller's active
        workspace). When ``project_id`` is set the project's own workspace
        wins, so a team chat can never be stamped into a different org.
        """
        uid = _coerce_uuid(user_id)
        if uid is None:
            raise ValueError('user_id must coerce to UUID')

        # config_id is polymorphic: keep as a string in the column.
        cfg = str(config_id) if config_id is not None else None

        fid = _coerce_uuid(folder_id) if folder_id else None
        pid = _coerce_uuid(project_id) if project_id else None
        wid = _coerce_uuid(workspace_id) if workspace_id else None
        if pid is not None:
            from app.models.project import Project
            project_ws = db.session.execute(
                select(Project.workspace_id).where(Project.id == pid)
            ).scalar_one_or_none()
            if project_ws is not None:
                wid = project_ws

        now = datetime.utcnow()
        conv = Conversation(
            user_id=uid,
            workspace_id=wid,
            project_id=pid,
            folder_id=fid,
            config_id=cfg,
            title=title,
            tags=[],
            summary=None,
            message_count=0,
            token_count={'input': 0, 'output': 0, 'total': 0},
            last_message_at=now,
            is_pinned=False,
            is_archived=False,
            active_branch='main',
            seq_counter=0,
            kind=kind,
        )
        db.session.add(conv)
        db.session.flush()  # populate conv.id

        db.session.add(
            ConversationBranch(
                conversation_id=conv.id,
                branch_key='main',
                name='Main',
                parent_branch_key=None,
                branch_point_message_id=None,
            )
        )
        db.session.commit()
        return _serialize_conversation(conv)

    @staticmethod
    def find_by_id(conversation_id, include_branches: bool = True):
        """Find conversation by ID. Returns legacy dict shape or None.

        ``include_branches=False`` skips the extra ``conversation_branches``
        SELECT for callers that never read ``conv['branches']`` (e.g. the chat
        stream pre-flight, which fires on every turn). Default ``True`` keeps
        every existing caller's behaviour unchanged.
        """
        cid = _coerce_uuid(conversation_id)
        if cid is None:
            return None
        obj = db.session.get(Conversation, cid)
        return (
            _serialize_conversation(obj, include_branches=include_branches)
            if obj is not None
            else None
        )

    @staticmethod
    def find_by_user(user_id, folder_id=None, archived=False, search=None,
                     skip=0, limit=20, sort_by='last_message_at',
                     project_id=None, kind=None, workspace_id=None):
        """Find conversations for a user (paged).

        ``workspace_id`` (optional) restricts to one org's chats.

        project_id semantics:
            None              -> no project filter (legacy behavior preserved)
            NULL_PROJECT_SENTINEL ('__null__') -> filter where project_id is null
            UUID / str        -> exact match

        kind semantics:
            None              -> no kind filter (returns chat + data + agent)
            'chat' / 'data' / 'agent' -> exact match on the discriminator
        """
        uid = _coerce_uuid(user_id)
        if uid is None:
            return []

        stmt = select(Conversation).where(
            Conversation.user_id == uid,
            Conversation.is_archived == bool(archived),
        )

        if kind is not None:
            stmt = stmt.where(Conversation.kind == kind)

        if workspace_id is not None:
            wid = _coerce_uuid(workspace_id)
            if wid is None:
                return []
            stmt = stmt.where(Conversation.workspace_id == wid)

        if folder_id:
            fid = _coerce_uuid(folder_id)
            if fid is None:
                return []
            stmt = stmt.where(Conversation.folder_id == fid)

        if project_id == NULL_PROJECT_SENTINEL:
            stmt = stmt.where(Conversation.project_id.is_(None))
        elif project_id is not None:
            pid = _coerce_uuid(project_id)
            if pid is None:
                return []
            stmt = stmt.where(Conversation.project_id == pid)

        if search:
            # GIN trgm index on title accelerates ILIKE prefix/contains.
            stmt = stmt.where(Conversation.title.ilike(f'%{search}%'))

        sort_col = getattr(Conversation, sort_by, Conversation.last_message_at)
        stmt = stmt.order_by(sort_col.desc().nullslast()).offset(skip).limit(limit)

        rows = db.session.execute(stmt).scalars().all()
        # One bulk SELECT for every page row's branches (kills the 1+N).
        branch_map = _branch_map_for([r.id for r in rows])
        return [_serialize_conversation(r, branch_map=branch_map) for r in rows]

    @staticmethod
    def find_for_user_in_scope(user_id, project_id, archived=False, search=None,
                               skip=0, limit=20, sort_by='last_message_at',
                               kind=None, workspace_id=None):
        """List conversations visible to *user_id* within a TEAM scope.

        Union of (a) the user's own chats filed in ``project_id`` and (b) chats
        a colleague has shared into ``project_id`` (active team grant). The
        caller must already have verified the user can access ``project_id``.
        Personal / null scope does NOT use this method — shares never surface
        there; that path stays the owner-only ``find_by_user``.
        """
        from app.models.conversation_share import ConversationShare
        uid = _coerce_uuid(user_id)
        pid = _coerce_uuid(project_id)
        if uid is None or pid is None:
            return []

        share_match = and_(
            ConversationShare.conversation_id == Conversation.id,
            ConversationShare.share_type == 'team',
            ConversationShare.project_id == pid,
            ConversationShare.revoked_at.is_(None),
        )
        visible = or_(
            and_(Conversation.user_id == uid, Conversation.project_id == pid),
            ConversationShare.id.isnot(None),
        )
        stmt = (
            select(Conversation)
            .outerjoin(ConversationShare, share_match)
            .where(Conversation.is_archived == bool(archived), visible)
        )
        if kind is not None:
            stmt = stmt.where(Conversation.kind == kind)
        if workspace_id is not None:
            wid = _coerce_uuid(workspace_id)
            if wid is None:
                return []
            stmt = stmt.where(Conversation.workspace_id == wid)
        if search:
            stmt = stmt.where(Conversation.title.ilike(f'%{search}%'))
        sort_col = getattr(Conversation, sort_by, Conversation.last_message_at)
        stmt = (
            stmt.distinct()
            .order_by(sort_col.desc().nullslast())
            .offset(skip)
            .limit(limit)
        )
        rows = db.session.execute(stmt).scalars().all()
        branch_map = _branch_map_for([r.id for r in rows])
        return [_serialize_conversation(r, branch_map=branch_map) for r in rows]

    @staticmethod
    def count_for_user_in_scope(user_id, project_id, archived=False, kind=None,
                                workspace_id=None):
        """Total visible (own + shared-in) conversations for a team scope."""
        from app.models.conversation_share import ConversationShare
        uid = _coerce_uuid(user_id)
        pid = _coerce_uuid(project_id)
        if uid is None or pid is None:
            return 0
        share_match = and_(
            ConversationShare.conversation_id == Conversation.id,
            ConversationShare.share_type == 'team',
            ConversationShare.project_id == pid,
            ConversationShare.revoked_at.is_(None),
        )
        visible = or_(
            and_(Conversation.user_id == uid, Conversation.project_id == pid),
            ConversationShare.id.isnot(None),
        )
        stmt = (
            select(func.count(func.distinct(Conversation.id)))
            .select_from(Conversation)
            .outerjoin(ConversationShare, share_match)
            .where(Conversation.is_archived == bool(archived), visible)
        )
        if kind is not None:
            stmt = stmt.where(Conversation.kind == kind)
        if workspace_id is not None:
            wid = _coerce_uuid(workspace_id)
            if wid is None:
                return 0
            stmt = stmt.where(Conversation.workspace_id == wid)
        return int(db.session.execute(stmt).scalar() or 0)

    @staticmethod
    def update(conversation_id, update_data):
        """Generic field update; mirrors Mongo $set."""
        cid = _coerce_uuid(conversation_id)
        if cid is None:
            return None
        obj = db.session.get(Conversation, cid)
        if obj is None:
            return None
        # Coerce id-bearing fields where ORM expects UUID.
        for k, v in update_data.items():
            if k in ('folder_id', 'project_id', 'workspace_id') and v is not None:
                v = _coerce_uuid(v)
            if hasattr(obj, k):
                setattr(obj, k, v)
        obj.updated_at = datetime.utcnow()
        db.session.commit()
        return obj

    @staticmethod
    def update_title(conversation_id, title):
        return ConversationModel.update(conversation_id, {'title': title})

    @staticmethod
    def move_to_project(conversation_id, project_id):
        return ConversationModel.update(conversation_id, {'project_id': project_id})

    @staticmethod
    def null_project_for_project(project_id):
        """Set ``project_id`` to NULL on all conversations carrying *project_id*.
        Used during project delete cascade."""
        from sqlalchemy import update as _sa_update
        pid = _coerce_uuid(project_id)
        if pid is None:
            return 0
        result = db.session.execute(
            _sa_update(Conversation)
            .where(Conversation.project_id == pid)
            .values(project_id=None, updated_at=datetime.utcnow())
        )
        db.session.commit()
        return result.rowcount or 0

    @staticmethod
    def set_message_count(conversation_id, count: int):
        """Overwrite ``message_count`` + bump ``last_message_at``/``updated_at``
        to now. Used after bulk-copy operations (branch / spawn)."""
        from sqlalchemy import update as _sa_update
        cid = _coerce_uuid(conversation_id)
        if cid is None:
            return 0
        now = datetime.utcnow()
        result = db.session.execute(
            _sa_update(Conversation)
            .where(Conversation.id == cid)
            .values(
                message_count=int(count),
                last_message_at=now,
                updated_at=now,
            )
        )
        db.session.commit()
        return result.rowcount or 0

    @staticmethod
    def null_folder_for_folder(folder_id):
        """Set ``folder_id`` to NULL on all conversations whose folder_id
        matches *folder_id*. Used during folder delete cascade."""
        from sqlalchemy import update as _sa_update
        fid = _coerce_uuid(folder_id)
        if fid is None:
            return 0
        result = db.session.execute(
            _sa_update(Conversation)
            .where(Conversation.folder_id == fid)
            .values(folder_id=None, updated_at=datetime.utcnow())
        )
        db.session.commit()
        return result.rowcount or 0

    @staticmethod
    def toggle_archive(conversation_id, archived=True):
        return ConversationModel.update(conversation_id, {'is_archived': bool(archived)})

    @staticmethod
    def increment_message_count(conversation_id, input_tokens=0, output_tokens=0):
        """Atomic counter + JSONB token-count $inc.

        ``message_count`` uses SQL-side ``col + 1`` for atomicity. ``token_count``
        is a JSONB blob; fetch + mutate + flag_modified (no native nested $inc).
        """
        cid = _coerce_uuid(conversation_id)
        if cid is None:
            return None
        total = (input_tokens or 0) + (output_tokens or 0)
        # 1) Atomic message_count + last_message_at via SQL expression.
        now = datetime.utcnow()
        db.session.execute(
            update(Conversation)
            .where(Conversation.id == cid)
            .values(
                message_count=Conversation.message_count + 1,
                last_message_at=now,
                updated_at=now,
            )
        )
        # 2) JSONB mutate in Python (no portable nested $inc in SQLAlchemy ORM).
        obj = db.session.get(Conversation, cid)
        if obj is not None:
            tc = dict(obj.token_count or {})
            tc['input'] = int(tc.get('input') or 0) + int(input_tokens or 0)
            tc['output'] = int(tc.get('output') or 0) + int(output_tokens or 0)
            tc['total'] = int(tc.get('total') or 0) + int(total or 0)
            obj.token_count = tc
            flag_modified(obj, 'token_count')
        db.session.commit()
        return obj

    @staticmethod
    def delete(conversation_id):
        """Delete a conversation row. Branches + messages cascade via FK."""
        cid = _coerce_uuid(conversation_id)
        if cid is None:
            return None
        result = db.session.execute(
            delete(Conversation).where(Conversation.id == cid)
        )
        db.session.commit()
        return result

    @staticmethod
    def count_by_user(user_id, archived=False, project_id=None, kind=None,
                      workspace_id=None):
        """Count conversations for a user.

        project_id tri-state mirrors ``find_by_user``; ``kind`` (None | 'chat' |
        'data') filters on the discriminator, None meaning no filter.
        """
        uid = _coerce_uuid(user_id)
        if uid is None:
            return 0
        stmt = select(func.count()).select_from(Conversation).where(
            Conversation.user_id == uid,
            Conversation.is_archived == bool(archived),
        )
        if kind is not None:
            stmt = stmt.where(Conversation.kind == kind)
        if workspace_id is not None:
            wid = _coerce_uuid(workspace_id)
            if wid is None:
                return 0
            stmt = stmt.where(Conversation.workspace_id == wid)
        if project_id == NULL_PROJECT_SENTINEL:
            stmt = stmt.where(Conversation.project_id.is_(None))
        elif project_id is not None:
            pid = _coerce_uuid(project_id)
            if pid is None:
                return 0
            stmt = stmt.where(Conversation.project_id == pid)
        return int(db.session.execute(stmt).scalar() or 0)

    @staticmethod
    def count_active_and_archived_by_user(user_id):
        """Return ``(active, archived)`` conversation counts in ONE query.

        Collapses the two separate ``count_by_user`` calls the ``/users/stats``
        route issued into a single scan using filtered aggregates: ``count(*)
        FILTER (WHERE NOT is_archived)`` for the active subset and ``count(*)
        FILTER (WHERE is_archived)`` for the archived subset. The stats panel
        labels the first value "Conversations" (active only); archived is
        surfaced separately, so the two are disjoint — not total/subset.
        """
        uid = _coerce_uuid(user_id)
        if uid is None:
            return 0, 0
        row = db.session.execute(
            select(
                func.count().filter(Conversation.is_archived.is_(False)),
                func.count().filter(Conversation.is_archived.is_(True)),
            ).where(Conversation.user_id == uid)
        ).one()
        active, archived = row
        return int(active or 0), int(archived or 0)

    @staticmethod
    def get_by_user_for_admin(user_id, skip=0, limit=50):
        """Get all conversations for a user (admin view)."""
        uid = _coerce_uuid(user_id)
        if uid is None:
            return []
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == uid)
            .order_by(Conversation.last_message_at.desc().nullslast())
            .offset(skip)
            .limit(limit)
        )
        rows = db.session.execute(stmt).scalars().all()
        branch_map = _branch_map_for([r.id for r in rows])
        return [_serialize_conversation(r, branch_map=branch_map) for r in rows]

    @staticmethod
    def add_branch(conversation_id, branch_data):
        """Add a new branch row; mirrors the legacy embedded $push."""
        cid = _coerce_uuid(conversation_id)
        if cid is None:
            return False

        branch_key = branch_data['id']
        bp_msg = branch_data.get('branch_point_message_id')
        bp_msg_uuid = _coerce_uuid(bp_msg) if bp_msg else None

        try:
            db.session.add(
                ConversationBranch(
                    conversation_id=cid,
                    branch_key=branch_key,
                    name=branch_data.get('name', f"Branch {str(branch_key)[:8]}"),
                    parent_branch_key=branch_data.get('parent_branch', 'main'),
                    branch_point_message_id=bp_msg_uuid,
                )
            )
            # Touch conversation.updated_at for cache invalidation parity.
            db.session.execute(
                update(Conversation)
                .where(Conversation.id == cid)
                .values(updated_at=datetime.utcnow())
            )
            db.session.commit()
            return True
        except Exception:
            db.session.rollback()
            return False

    @staticmethod
    def set_active_branch(conversation_id, branch_id):
        cid = _coerce_uuid(conversation_id)
        if cid is None:
            return False
        result = db.session.execute(
            update(Conversation)
            .where(Conversation.id == cid)
            .values(active_branch=branch_id, updated_at=datetime.utcnow())
        )
        db.session.commit()
        return (result.rowcount or 0) > 0

    @staticmethod
    def remove_branch(conversation_id, branch_id):
        """Remove a branch from a conversation (cannot remove 'main')."""
        if branch_id == 'main':
            return False
        cid = _coerce_uuid(conversation_id)
        if cid is None:
            return False
        obj = db.session.get(Conversation, cid)
        if obj is None:
            return False
        result = db.session.execute(
            delete(ConversationBranch).where(
                ConversationBranch.conversation_id == cid,
                ConversationBranch.branch_key == branch_id,
            )
        )
        new_active = obj.active_branch
        if obj.active_branch == branch_id:
            new_active = 'main'
        db.session.execute(
            update(Conversation)
            .where(Conversation.id == cid)
            .values(active_branch=new_active, updated_at=datetime.utcnow())
        )
        db.session.commit()
        return (result.rowcount or 0) > 0

    @staticmethod
    def update_branch_name(conversation_id, branch_id, new_name):
        cid = _coerce_uuid(conversation_id)
        if cid is None:
            return False
        result = db.session.execute(
            update(ConversationBranch)
            .where(
                ConversationBranch.conversation_id == cid,
                ConversationBranch.branch_key == branch_id,
            )
            .values(name=new_name)
        )
        db.session.commit()
        return (result.rowcount or 0) > 0

    @staticmethod
    def get_branch(conversation_id, branch_id):
        cid = _coerce_uuid(conversation_id)
        if cid is None:
            return None
        row = db.session.execute(
            select(ConversationBranch).where(
                ConversationBranch.conversation_id == cid,
                ConversationBranch.branch_key == branch_id,
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return {
            'id': row.branch_key,
            'name': row.name,
            'parent_branch': row.parent_branch_key,
            'branch_point_message_id': (
                str(row.branch_point_message_id)
                if row.branch_point_message_id is not None
                else None
            ),
            'created_at': row.created_at.isoformat() if row.created_at else None,
        }


# ---------------------------------------------------------------------------
# Phase 3 — SQLAlchemy 2.0 ORM models (Postgres).
#
# These live alongside the legacy Mongo `*Model` classes above during the
# strangler-fig migration. ``db.metadata`` registers them so Alembic can
# autogenerate ``0001_initial``. Phase 4 ports the classmethods to ``db.session``.
# ---------------------------------------------------------------------------


class Conversation(db.Model, SerializableMixin):
    __tablename__ = 'conversations'

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    # Owning org (team workspace). Stamped at create from the caller's active
    # workspace (the project's workspace wins). Deleting the org deletes it.
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('workspaces.id', ondelete='CASCADE', name='fk_conversations_workspace_id'),
        nullable=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('projects.id', ondelete='SET NULL'),
        nullable=True,
    )
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('folders.id', ondelete='SET NULL'),
        nullable=True,
    )
    # Polymorphic: stores `quick:*` synthetic IDs OR a UUID-as-string for a
    # real ``llm_configs`` row. Not a real FK because of the mixed shape.
    config_id: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    title: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    tags: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    message_count: Mapped[int] = mapped_column(
        db.Integer, nullable=False, server_default=text('0')
    )
    token_count: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    last_message_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    is_pinned: Mapped[bool] = mapped_column(
        db.Boolean, nullable=False, server_default=text('false')
    )
    is_archived: Mapped[bool] = mapped_column(
        db.Boolean, nullable=False, server_default=text('false')
    )
    active_branch: Mapped[str] = mapped_column(
        db.Text, nullable=False, server_default=text("'main'")
    )
    seq_counter: Mapped[int] = mapped_column(
        db.BigInteger, nullable=False, server_default=text('0')
    )
    # Discriminates normal chat (``'chat'``) from Data-Analyzer conversations
    # (``'data'``) so the chat sidebar filters out the latter (dedicated page).
    kind: Mapped[str] = mapped_column(
        db.Text, nullable=False, server_default=text("'chat'")
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
        Index(
            'ix_conversations_user_last_message_at',
            'user_id',
            text('last_message_at DESC NULLS LAST'),
        ),
        Index('ix_conversations_user_folder', 'user_id', 'folder_id'),
        Index(
            'ix_conversations_user_project_last_message_at',
            'user_id',
            'project_id',
            text('last_message_at DESC NULLS LAST'),
        ),
        Index('ix_conversations_user_archived', 'user_id', 'is_archived'),
        Index(
            'ix_conversations_user_kind_last_message_at',
            'user_id',
            'kind',
            text('last_message_at DESC NULLS LAST'),
        ),
        Index(
            'ix_conversations_user_ws_kind_last_message_at',
            'user_id',
            'workspace_id',
            'kind',
            text('last_message_at DESC NULLS LAST'),
        ),
        Index(
            'ix_conversations_title_trgm',
            'title',
            postgresql_using='gin',
            postgresql_ops={'title': 'gin_trgm_ops'},
        ),
        CheckConstraint(
            "kind IN ('chat','data','agent')",
            name='ck_conversations_kind',
        ),
    )


class ConversationBranch(db.Model, SerializableMixin):
    __tablename__ = 'conversation_branches'

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('conversations.id', ondelete='CASCADE'),
        nullable=False,
    )
    branch_key: Mapped[str] = mapped_column(db.Text, nullable=False)
    name: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    parent_branch_key: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    branch_point_message_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            'conversation_id',
            'branch_key',
            name='uq_conversation_branches_conv_key',
        ),
    )
