from datetime import datetime
import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    UniqueConstraint,
    delete,
    func,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm.attributes import flag_modified

from app.extensions import db
from app.models._base import SerializableMixin


# ---------------------------------------------------------------------------
# Façade helpers
# ---------------------------------------------------------------------------


def _coerce_uuid(value):
    """See conversation._coerce_uuid; duplicated to avoid a circular import."""
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


def _serialize_message(obj) -> dict:
    """Return Mongo-shaped dict from a Message ORM row.

    Aliases the SQLAlchemy-reserved ``message_metadata`` column back to the
    legacy ``metadata`` key the route layer reads.
    """
    if obj is None:
        return None
    out = obj.to_dict()
    out['metadata'] = out.pop('message_metadata', {}) or {}
    return out


def _attach_senders(messages: list) -> list:
    """Enrich serialized message dicts with a compact ``sender`` object for
    rows carrying a ``sender_user_id`` (collaborative team chats).

    ``sender`` shape: ``{id, name, avatar_url}``. One bulk user fetch keyed off
    the distinct sender ids — no N+1. Rows without a sender (assistant turns,
    single-author chats) are left untouched, so private chats are unaffected.
    """
    ids = {m.get('sender_user_id') for m in messages if m and m.get('sender_user_id')}
    if not ids:
        return messages
    from app.models.user import UserModel
    by_id = {}
    for u in UserModel.find_by_ids(list(ids)):
        profile = u.get('profile') or {}
        by_id[str(u['_id'])] = {
            'id': str(u['_id']),
            'name': (
                u.get('display_name')
                or profile.get('display_name')
                or (u.get('email') or '').split('@')[0]
                or 'User'
            ),
            'avatar_url': u.get('avatar_url') or profile.get('avatar_url'),
        }
    for m in messages:
        sid = m.get('sender_user_id') if m else None
        if sid and str(sid) in by_id:
            m['sender'] = by_id[str(sid)]
    return messages


def sender_public(message: dict) -> dict | None:
    """Coarse, PII-free sender for a FROZEN link snapshot (cross-tenant readable).

    The full ``sender`` ({id, name, avatar_url}) leaks a user id + an
    email-derived name + avatar to ANY authenticated viewer of a share link, so
    it must NEVER be baked into the snapshot. This returns only a role-based
    label with no id / email-derived value / avatar:

      * ``user``      -> ``{'name': 'You'}``  (generic author chip)
      * everything else (assistant/system/tool) -> ``None`` (assistant turns
        render flush; any model label lives in the snapshot's ``model`` field).

    ``display_name`` is unusable as a "real name" signal here: the user model
    backfills it from ``email.split('@')[0]`` at creation, so it cannot be told
    apart from the email local-part downstream — hence a fixed generic label.
    """
    role = (message or {}).get('role')
    if role == 'user':
        return {'name': 'You'}
    return None


class MessageModel:
    collection_name = 'messages'

    @staticmethod
    def _next_seq(conversation_id) -> int:
        """Atomic per-conversation monotonic counter.

        Postgres ``UPDATE … SET seq_counter = seq_counter + 1 RETURNING …``
        gives us a single-statement atomic increment without advisory locks.
        """
        from app.models.conversation import Conversation

        cid = _coerce_uuid(conversation_id)
        if cid is None:
            return 0
        row = db.session.execute(
            update(Conversation)
            .where(Conversation.id == cid)
            .values(seq_counter=Conversation.seq_counter + 1)
            .returning(Conversation.seq_counter)
        ).first()
        # NB: callers commit at the end of the wider create() flow; we flush
        # to make the new seq visible within this txn.
        db.session.flush()
        return int(row[0]) if row else 0

    @staticmethod
    def create(conversation_id, role, content, attachments=None, metadata=None,
               branch_id='main', sender_user_id=None):
        """Insert a new message row in Postgres.

        ``sender_user_id`` records the human author of a USER turn in a
        collaborative (team-shared) chat; NULL on assistant/system rows and on
        single-author conversations.
        """
        cid = _coerce_uuid(conversation_id)
        if cid is None:
            raise ValueError('conversation_id must coerce to UUID')

        seq = MessageModel._next_seq(cid)
        msg = Message(
            conversation_id=cid,
            sender_user_id=_coerce_uuid(sender_user_id),
            role=role,
            content=content,
            attachments=attachments or [],
            message_metadata=metadata or {},
            branch_id=branch_id,
            is_error=False,
            error_message=None,
            seq=seq,
        )
        db.session.add(msg)
        db.session.commit()
        return _serialize_message(msg)

    @staticmethod
    def create_user_message(conversation_id, content, attachments=None,
                            branch_id='main', metadata=None, sender_user_id=None):
        return MessageModel.create(
            conversation_id=conversation_id,
            role='user',
            content=content,
            attachments=attachments,
            metadata=metadata,
            branch_id=branch_id,
            sender_user_id=sender_user_id,
        )

    @staticmethod
    def create_assistant_message(conversation_id, content, model_id=None,
                                  prompt_tokens=0, completion_tokens=0,
                                  generation_time_ms=0, finish_reason='stop',
                                  branch_id='main'):
        metadata = {
            'model_id': model_id,
            'tokens': {
                'prompt': prompt_tokens,
                'completion': completion_tokens,
            },
            'generation_time_ms': generation_time_ms,
            'finish_reason': finish_reason,
        }
        return MessageModel.create(
            conversation_id=conversation_id,
            role='assistant',
            content=content,
            metadata=metadata,
            branch_id=branch_id,
        )

    @staticmethod
    def create_error_message(conversation_id, error_message, model_id=None,
                             branch_id='main'):
        cid = _coerce_uuid(conversation_id)
        if cid is None:
            raise ValueError('conversation_id must coerce to UUID')

        seq = MessageModel._next_seq(cid)
        msg = Message(
            conversation_id=cid,
            role='assistant',
            content='',
            attachments=[],
            message_metadata={'model_id': model_id},
            branch_id=branch_id,
            is_error=True,
            error_message=error_message,
            seq=seq,
        )
        db.session.add(msg)
        db.session.commit()
        return _serialize_message(msg)

    @staticmethod
    def find_by_conversation(conversation_id, skip=0, limit=100, branch_id=None):
        """Get messages for a conversation, optionally filtered by branch.

        Ordering: ``created_at ASC, seq ASC`` for deterministic tiebreak on
        same-millisecond inserts.
        """
        cid = _coerce_uuid(conversation_id)
        if cid is None:
            return []

        stmt = select(Message).where(Message.conversation_id == cid)
        if branch_id is not None:
            stmt = stmt.where(Message.branch_id == branch_id)
        stmt = (
            stmt.order_by(Message.created_at.asc(), Message.seq.asc())
            .offset(skip)
            .limit(limit)
        )
        rows = db.session.execute(stmt).scalars().all()
        return _attach_senders([_serialize_message(r) for r in rows])

    @staticmethod
    def find_by_id(message_id):
        mid = _coerce_uuid(message_id)
        if mid is None:
            return None
        obj = db.session.get(Message, mid)
        return _serialize_message(obj) if obj is not None else None

    @staticmethod
    def update_content(message_id, content):
        """Update message content (for streaming finalization)."""
        mid = _coerce_uuid(message_id)
        if mid is None:
            return None
        result = db.session.execute(
            update(Message)
            .where(Message.id == mid)
            .values(content=content)
        )
        db.session.commit()
        return result

    @staticmethod
    def update_with_edit_history(message_id, content, edit_history):
        """Update message content + store edit history in metadata JSONB.

        Legacy doc held top-level ``edit_history`` / ``is_edited`` / ``edited_at``.
        ORM has no dedicated columns; stash inside ``message_metadata`` so the
        wire shape stays close (route's ``message['metadata']['edit_history']``).
        """
        mid = _coerce_uuid(message_id)
        if mid is None:
            return None
        obj = db.session.get(Message, mid)
        if obj is None:
            return None
        obj.content = content
        meta = dict(obj.message_metadata or {})
        meta['edit_history'] = edit_history
        meta['is_edited'] = True
        meta['edited_at'] = datetime.utcnow().isoformat()
        obj.message_metadata = meta
        flag_modified(obj, 'message_metadata')
        db.session.commit()
        return obj

    @staticmethod
    def find_meeting_seed(meeting_id: str):
        """Find the system ``meeting`` seed message for *meeting_id*.

        Idempotency key for the Discuss-this-meeting spawn flow: returns the
        oldest message whose ``message_metadata.source == 'meeting'`` and
        ``message_metadata.meeting_id == <meeting_id>``. Returns the legacy
        dict shape (with ``conversation_id`` as a UUID str) or None.
        """
        from sqlalchemy import select as _sa_select
        stmt = (
            _sa_select(Message)
            .where(
                Message.role == 'system',
                Message.message_metadata['source'].astext == 'meeting',
                Message.message_metadata['meeting_id'].astext == str(meeting_id),
            )
            .order_by(Message.created_at.asc())
            .limit(1)
        )
        obj = db.session.execute(stmt).scalar_one_or_none()
        return _serialize_message(obj) if obj is not None else None

    @staticmethod
    def mark_error(message_id, error_msg: str):
        """Flip is_error=True + populate error_message column."""
        mid = _coerce_uuid(message_id)
        if mid is None:
            return None
        result = db.session.execute(
            update(Message)
            .where(Message.id == mid)
            .values(is_error=True, error_message=error_msg)
        )
        db.session.commit()
        return result

    @staticmethod
    def update_content_and_metadata(message_id, content, metadata):
        """Atomic content + metadata replacement for streaming finalization."""
        mid = _coerce_uuid(message_id)
        if mid is None:
            return None
        result = db.session.execute(
            update(Message)
            .where(Message.id == mid)
            .values(content=content, message_metadata=metadata or {})
        )
        db.session.commit()
        return result

    @staticmethod
    def update_metadata(message_id, metadata):
        """Replace metadata blob wholesale."""
        mid = _coerce_uuid(message_id)
        if mid is None:
            return None
        result = db.session.execute(
            update(Message)
            .where(Message.id == mid)
            .values(message_metadata=metadata or {})
        )
        db.session.commit()
        return result

    @staticmethod
    def merge_metadata(message_id, patch):
        """Shallow-merge ``patch`` into the existing metadata JSONB.

        Unlike :meth:`update_metadata` (wholesale replace), this preserves the
        already-stored keys (model_id, tokens, …) and only overwrites/adds the
        keys present in ``patch`` — used to persist assistant ``annotations``
        without clobbering the completion metadata. Uses the fetch → mutate →
        reassign → ``flag_modified`` → commit pattern required for JSONB.
        """
        mid = _coerce_uuid(message_id)
        if mid is None or not patch:
            return None
        obj = db.session.get(Message, mid)
        if obj is None:
            return None
        meta = dict(obj.message_metadata or {})
        meta.update(patch)
        obj.message_metadata = meta
        flag_modified(obj, 'message_metadata')
        db.session.commit()
        return obj

    @staticmethod
    def update_attachments(message_id, attachments):
        """Replace the message's ``attachments`` JSONB array.

        Mirrors the JSONB-update helpers (fetch → reassign → ``flag_modified``
        → commit). Used to backfill an attachment list (e.g. enriched with
        extraction status) after the row is created.
        """
        mid = _coerce_uuid(message_id)
        if mid is None:
            return None
        obj = db.session.get(Message, mid)
        if obj is None:
            return None
        obj.attachments = attachments or []
        flag_modified(obj, 'attachments')
        db.session.commit()
        return obj

    @staticmethod
    def delete(message_id):
        mid = _coerce_uuid(message_id)
        if mid is None:
            return None
        result = db.session.execute(
            delete(Message).where(Message.id == mid)
        )
        db.session.commit()
        return result

    @staticmethod
    def delete_by_conversation(conversation_id):
        cid = _coerce_uuid(conversation_id)
        if cid is None:
            return None
        result = db.session.execute(
            delete(Message).where(Message.conversation_id == cid)
        )
        db.session.commit()
        return result

    @staticmethod
    def count_by_conversation(conversation_id):
        cid = _coerce_uuid(conversation_id)
        if cid is None:
            return 0
        return int(
            db.session.execute(
                select(func.count()).select_from(Message).where(
                    Message.conversation_id == cid
                )
            ).scalar()
            or 0
        )

    @staticmethod
    def get_context_messages(conversation_id, limit=20, branch_id=None):
        """Get recent non-error messages for AI context (chronological)."""
        cid = _coerce_uuid(conversation_id)
        if cid is None:
            return []
        stmt = select(Message).where(
            Message.conversation_id == cid,
            Message.is_error.is_(False),
        )
        if branch_id is not None:
            stmt = stmt.where(Message.branch_id == branch_id)
        # Tail N: sort desc, limit, reverse.
        stmt = stmt.order_by(
            Message.created_at.desc(), Message.seq.desc()
        ).limit(limit)
        rows = list(db.session.execute(stmt).scalars().all())
        rows.reverse()
        return [_serialize_message(r) for r in rows]

    @staticmethod
    def search_in_conversations(user_conversation_ids, query, limit=50):
        """ILIKE search across multiple conversations (trgm-accelerated).

        Returns dicts with the legacy projection: ``_id``, ``conversation_id``,
        ``role``, ``content``, ``created_at``, ``score``, ``conversation_title``.
        """
        if not query or not user_conversation_ids:
            return []
        from app.models.conversation import Conversation

        cids = [
            _coerce_uuid(c) for c in user_conversation_ids
        ]
        cids = [c for c in cids if c is not None]
        if not cids:
            return []

        stmt = (
            select(
                Message.id,
                Message.conversation_id,
                Message.role,
                Message.content,
                Message.created_at,
                Conversation.title.label('conversation_title'),
            )
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.conversation_id.in_(cids),
                Message.content.ilike(f'%{query}%'),
            )
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        rows = db.session.execute(stmt).all()
        return [
            {
                '_id': str(r.id),
                'conversation_id': str(r.conversation_id),
                'role': r.role,
                'content': r.content,
                'created_at': r.created_at.isoformat() if r.created_at else None,
                'score': 1.0,
                'conversation_title': r.conversation_title,
            }
            for r in rows
        ]

    @staticmethod
    def search_in_user_conversations(user_id, query, accessible_project_ids,
                                     limit=50):
        """ILIKE message search scoped by JOIN to the owning conversation.

        Replaces the route-layer "enumerate up to 1000 conversation ids then
        pass them as an IN list" pattern (silent scope cap + index-defeating).
        Filters in SQL:
            * ``conversations.user_id == user_id`` (ownership)
            * personal-scope (``conversations.project_id IS NULL``) OR
              ``project_id IN accessible_project_ids`` (project ACL — a user
              removed from a project no longer surfaces its message text)
        The trgm GIN index on ``messages.content`` drives the ILIKE; there's
        no longer a 1000-conversation ceiling.

        Returns the same legacy projection as
        :meth:`search_in_conversations`.
        """
        if not query:
            return []
        from sqlalchemy import or_
        from app.models.conversation import Conversation

        uid = _coerce_uuid(user_id)
        if uid is None:
            return []

        accessible_uuids = []
        for a in accessible_project_ids or []:
            au = _coerce_uuid(a)
            if au is not None:
                accessible_uuids.append(au)

        # Visibility: personal-scope always, project-scope only when accessible.
        if accessible_uuids:
            scope_cond = or_(
                Conversation.project_id.is_(None),
                Conversation.project_id.in_(accessible_uuids),
            )
        else:
            scope_cond = Conversation.project_id.is_(None)

        stmt = (
            select(
                Message.id,
                Message.conversation_id,
                Message.role,
                Message.content,
                Message.created_at,
                Conversation.title.label('conversation_title'),
            )
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Conversation.user_id == uid,
                scope_cond,
                Message.content.ilike(f'%{query}%'),
            )
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        rows = db.session.execute(stmt).all()
        return [
            {
                '_id': str(r.id),
                'conversation_id': str(r.conversation_id),
                'role': r.role,
                'content': r.content,
                'created_at': r.created_at.isoformat() if r.created_at else None,
                'score': 1.0,
                'conversation_title': r.conversation_title,
            }
            for r in rows
        ]

    @staticmethod
    def delete_after_message(conversation_id, message_id, branch_id=None):
        """Delete all messages strictly after a target message (for edit/regen)."""
        cid = _coerce_uuid(conversation_id)
        mid = _coerce_uuid(message_id)
        if cid is None or mid is None:
            return 0
        target = db.session.get(Message, mid)
        if target is None:
            return 0
        stmt = delete(Message).where(
            Message.conversation_id == cid,
            Message.created_at > target.created_at,
        )
        if branch_id is not None:
            stmt = stmt.where(Message.branch_id == branch_id)
        result = db.session.execute(stmt)
        db.session.commit()
        return int(result.rowcount or 0)

    @staticmethod
    def find_up_to(conversation_id, message_id, branch_id='main'):
        """All messages up to and including target_id, in chronological order."""
        cid = _coerce_uuid(conversation_id)
        mid = _coerce_uuid(message_id)
        if cid is None or mid is None:
            return []
        target = db.session.get(Message, mid)
        if target is None:
            return []
        stmt = select(Message).where(
            Message.conversation_id == cid,
            Message.created_at <= target.created_at,
            Message.branch_id == branch_id,
        ).order_by(Message.created_at.asc(), Message.seq.asc())
        rows = db.session.execute(stmt).scalars().all()
        return [_serialize_message(r) for r in rows]

    @staticmethod
    def _build_branch_copy(message, new_branch_id, seq):
        """Construct (not persist) a ``Message`` row cloning *message* into a
        new branch with the supplied ``seq``.

        Shared by :meth:`copy_to_branch` (single) and
        :meth:`copy_many_to_branch` (bulk) so both paths build rows identically;
        the only difference is seq allocation + commit batching. Returns the
        ORM row (unattached to the session).
        """
        cid = _coerce_uuid(message.get('conversation_id'))
        if cid is None:
            raise ValueError('source message missing conversation_id')

        meta = dict(message.get('metadata') or {})
        # Preserve edit-history fields stashed at root in legacy docs.
        if message.get('is_edited'):
            meta['is_edited'] = message['is_edited']
        if message.get('edit_history'):
            meta['edit_history'] = message['edit_history']
        if message.get('edited_at'):
            meta['edited_at'] = (
                message['edited_at'].isoformat()
                if isinstance(message['edited_at'], datetime)
                else message['edited_at']
            )

        msg = Message(
            conversation_id=cid,
            role=message['role'],
            content=message.get('content'),
            attachments=message.get('attachments') or [],
            message_metadata=meta,
            branch_id=new_branch_id,
            is_error=bool(message.get('is_error')),
            error_message=message.get('error_message'),
            seq=seq,
        )
        # Preserve original timestamp where ORM lets us (server_default kicks
        # in only when ``created_at`` is None; explicit value wins).
        if message.get('created_at'):
            created = message['created_at']
            if isinstance(created, str):
                try:
                    created = datetime.fromisoformat(created.replace('Z', '+00:00'))
                except Exception:
                    created = None
            if created is not None:
                msg.created_at = created
        return msg

    @staticmethod
    def copy_to_branch(message, new_branch_id):
        """Copy a message dict (legacy shape) into a new branch row.

        Always allocates a FRESH monotonic ``seq`` via ``_next_seq``: the
        source ``seq`` is unique per ``conversation_id`` (``uq_messages_conv_seq``),
        so reusing it collides on any in-conversation branch copy. The new seq
        is strictly greater than every existing one, so insertion order is
        preserved and the copied rows sort after the originals.
        """
        cid = _coerce_uuid(message.get('conversation_id'))
        if cid is None:
            raise ValueError('source message missing conversation_id')

        # Always allocate a fresh seq — the source seq collides with the
        # (conversation_id, seq) unique constraint on in-conversation copies.
        seq = MessageModel._next_seq(cid)
        msg = MessageModel._build_branch_copy(message, new_branch_id, seq)
        db.session.add(msg)
        db.session.commit()
        return _serialize_message(msg)

    @staticmethod
    def copy_many_to_branch(messages, new_branch_id):
        """Bulk-copy a list of message dicts into a new branch in ONE commit.

        Branch creation previously committed once per copied message (N
        ``_next_seq`` UPDATE+flush+commit cycles). This allocates a contiguous
        block of ``seq`` values in a single atomic increment, builds all rows,
        ``add_all``s them, and commits ONCE.

        All messages MUST belong to the same conversation (they always do —
        callers copy ``find_up_to`` output, scoped to one conversation). Seqs
        are assigned in input order, strictly greater than every existing seq,
        so chronological ordering is preserved (rows sort after the originals).
        Returns the serialized copied messages in input order.
        """
        msgs = list(messages or [])
        if not msgs:
            return []

        cid = _coerce_uuid(msgs[0].get('conversation_id'))
        if cid is None:
            raise ValueError('source message missing conversation_id')

        # Allocate N contiguous seqs atomically. The RETURNING value is the new
        # max counter; the block spans (new_max - N + 1) .. new_max inclusive.
        from app.models.conversation import Conversation

        n = len(msgs)
        row = db.session.execute(
            update(Conversation)
            .where(Conversation.id == cid)
            .values(seq_counter=Conversation.seq_counter + n)
            .returning(Conversation.seq_counter)
        ).first()
        db.session.flush()
        new_max = int(row[0]) if row else 0
        first_seq = new_max - n + 1

        built = [
            MessageModel._build_branch_copy(message, new_branch_id, first_seq + i)
            for i, message in enumerate(msgs)
        ]
        db.session.add_all(built)
        db.session.commit()
        return [_serialize_message(m) for m in built]

    @staticmethod
    def delete_by_branch(conversation_id, branch_id):
        cid = _coerce_uuid(conversation_id)
        if cid is None:
            return 0
        result = db.session.execute(
            delete(Message).where(
                Message.conversation_id == cid,
                Message.branch_id == branch_id,
            )
        )
        db.session.commit()
        return int(result.rowcount or 0)


# ---------------------------------------------------------------------------
# Phase 3 — SQLAlchemy 2.0 ORM model.
#
# `metadata` is reserved on SQLAlchemy declarative base; the column is named
# ``message_metadata`` (façade aliases back to ``metadata`` on output).
# ---------------------------------------------------------------------------


class Message(db.Model, SerializableMixin):
    __tablename__ = 'messages'

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('conversations.id', ondelete='CASCADE'),
        nullable=False,
    )
    # Author of a USER message in a collaborative (team-shared) chat. NULL on
    # assistant/system rows and on legacy/owner-authored messages — resolved to
    # the conversation owner at read time.
    sender_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    role: Mapped[str] = mapped_column(db.Text, nullable=False)
    content: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    attachments: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    # Column intentionally renamed from `metadata` (SQLAlchemy reserved) to
    # `message_metadata`. Façade re-aliases on read.
    message_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    branch_id: Mapped[str] = mapped_column(
        db.Text, nullable=False, server_default=text("'main'")
    )
    is_error: Mapped[bool] = mapped_column(
        db.Boolean, nullable=False, server_default=text('false')
    )
    error_message: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    seq: Mapped[int] = mapped_column(db.BigInteger, nullable=False)
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
        CheckConstraint(
            "role IN ('user','assistant','system','tool')",
            name='ck_messages_role',
        ),
        UniqueConstraint(
            'conversation_id', 'seq', name='uq_messages_conv_seq'
        ),
        Index(
            'ix_messages_conv_created_seq',
            'conversation_id', 'created_at', 'seq',
        ),
        Index(
            'ix_messages_conv_branch_created',
            'conversation_id', 'branch_id', 'created_at',
        ),
        Index('ix_messages_sender_user', 'sender_user_id'),
        Index(
            'ix_messages_content_trgm',
            'content',
            postgresql_using='gin',
            postgresql_ops={'content': 'gin_trgm_ops'},
        ),
    )
