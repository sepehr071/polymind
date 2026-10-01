"""Generated images.

Phase 4D: PG-backed via ORM ``GeneratedImage``. Legacy ``image_data`` (data
URI) maps to ``b64_payload``; legacy ``metadata`` → ``image_metadata``;
``model_id`` → ``model``. ``is_favorite``/``negative_prompt`` aren't on the
PG schema yet — stored inside ``image_metadata`` for forward-compat.
"""

import base64
import binascii
import io
import logging
import uuid
from datetime import timezone

from app.utils.credits import to_credits

logger = logging.getLogger(__name__)

# Thumbnail tuning. Grids render the small WebP straight from the list payload
# (~5-15 KB) instead of fetching the full base64 image per visible tile.
THUMB_MAX_PX = 256
THUMB_WEBP_QUALITY = 70


def decode_image_payload(image_data: str | None) -> tuple[bytes | None, str]:
    """Decode a data-URI or bare base64 payload to ``(raw_bytes, media_type)``.

    Returns ``(None, 'application/octet-stream')`` when the payload is empty
    or not valid base64. Media type is taken from a ``data:`` header when
    present; otherwise guessed from magic bytes (png/jpeg/webp/gif) with a
    PNG default.
    """
    if not image_data or not isinstance(image_data, str):
        return None, 'application/octet-stream'
    mime = 'image/png'
    payload = image_data
    if image_data.startswith('data:'):
        # data:image/png;base64,<payload>
        header, _, rest = image_data.partition(',')
        if not rest:
            return None, 'application/octet-stream'
        payload = rest
        # header = "data:image/png;base64" or "data:image/webp;base64"
        try:
            meta = header[5:]  # strip "data:"
            mime_part = meta.split(';', 1)[0].strip()
            if mime_part.startswith('image/'):
                mime = mime_part
        except Exception:  # noqa: BLE001
            pass
    try:
        raw = base64.b64decode(payload, validate=False)
    except (binascii.Error, ValueError):
        return None, 'application/octet-stream'
    if not raw:
        return None, 'application/octet-stream'
    if mime == 'image/png' or not mime.startswith('image/'):
        # Magic-byte sniff when mime missing/default.
        if raw[:8] == b'\x89PNG\r\n\x1a\n':
            mime = 'image/png'
        elif raw[:2] == b'\xff\xd8':
            mime = 'image/jpeg'
        elif raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
            mime = 'image/webp'
        elif raw[:6] in (b'GIF87a', b'GIF89a'):
            mime = 'image/gif'
        else:
            mime = mime if mime.startswith('image/') else 'image/png'
    return raw, mime


def _make_thumb_data_uri(
    image_data: str | None,
    max_px: int = THUMB_MAX_PX,
    quality: int = THUMB_WEBP_QUALITY,
) -> str | None:
    """Downscale a base64 ``data:`` image URI to a WebP ``data:`` URI.

    Returns ``data:image/webp;base64,...`` (max ``max_px`` on the longest edge,
    aspect preserved) or ``None`` when the input isn't a decodable raster image.
    ``max_px``/``quality`` default to the small-thumb tuning; the canvas preview
    endpoint passes a larger size. Best-effort: any failure (bad payload, unknown
    format, Pillow missing a codec) returns ``None`` so callers never block on it.
    """
    if not image_data or not isinstance(image_data, str):
        return None
    # Accept a bare base64 string or a ``data:<mime>;base64,<payload>`` URI.
    payload = image_data
    if image_data.startswith('data:'):
        comma = image_data.find(',')
        if comma == -1:
            return None
        payload = image_data[comma + 1:]
    try:
        raw = base64.b64decode(payload, validate=False)
    except (binascii.Error, ValueError):
        return None
    if not raw:
        return None
    try:
        from PIL import Image

        with Image.open(io.BytesIO(raw)) as im:
            im.load()
            # WebP can't encode P/LA/RGBA-with-palette cleanly across the board;
            # flatten paletted/indexed modes and keep alpha where it exists.
            if im.mode in ('P', 'LA'):
                im = im.convert('RGBA' if 'A' in im.getbands() else 'RGB')
            elif im.mode not in ('RGB', 'RGBA', 'L'):
                im = im.convert('RGB')
            im.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            im.save(out, format='WEBP', quality=quality, method=4)
        encoded = base64.b64encode(out.getvalue()).decode('ascii')
        return f'data:image/webp;base64,{encoded}'
    except Exception:  # noqa: BLE001 — never let thumbnailing break creation.
        logger.warning('thumbnail generation failed', exc_info=True)
        return None


def _to_uuid(val):
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except Exception:
        return None


class GeneratedImageModel:
    """Model for AI-generated images"""

    @staticmethod
    def create(user_id, prompt, model_id, image_data, negative_prompt='',
               settings=None, metadata=None, conversation_id=None,
               parent_image_id=None):
        uid = _to_uuid(user_id)
        if uid is None:
            raise ValueError(f"Invalid user_id: {user_id!r}")
        merged_meta = dict(metadata or {})
        if negative_prompt:
            merged_meta.setdefault('negative_prompt', negative_prompt)
        merged_meta.setdefault('is_favorite', False)
        row = GeneratedImage(
            user_id=uid,
            prompt=prompt,
            model=model_id,
            url=None,
            b64_payload=image_data,
            thumb_b64=_make_thumb_data_uri(image_data),
            image_metadata=merged_meta,
            settings=settings or {
                'input_images_count': 0,
                'has_input_images': False,
            },
            conversation_id=_to_uuid(conversation_id),
            parent_image_id=_to_uuid(parent_image_id),
        )
        db.session.add(row)
        db.session.commit()
        return _image_to_dict(row)

    @staticmethod
    def find_by_id(image_id):
        iid = _to_uuid(image_id)
        if iid is None:
            return None
        row = db.session.get(GeneratedImage, iid)
        return _image_to_dict(row) if row else None

    @staticmethod
    def find_by_user(user_id, skip: int = 0, limit: int = 20,
                     favorites_only: bool = False, include_payload: bool = True,
                     search: str | None = None):
        uid = _to_uuid(user_id)
        if uid is None:
            return []
        stmt = select(GeneratedImage).where(GeneratedImage.user_id == uid)
        if favorites_only:
            stmt = stmt.where(
                GeneratedImage.image_metadata['is_favorite'].astext == 'true'
            )
        if search:
            stmt = stmt.where(GeneratedImage.prompt.ilike(f"%{search}%"))
        # ``b64_payload`` is a multi-MB ``Text`` column. When the caller won't
        # serialize it (``include_payload=False``), defer it so PG never ships
        # the bytes over the wire — otherwise a list page transfers tens of MB
        # only to drop the column in Python. ``thumb_b64`` (small WebP) is kept.
        if not include_payload:
            stmt = stmt.options(defer(GeneratedImage.b64_payload))
        stmt = stmt.order_by(GeneratedImage.created_at.desc()).offset(skip).limit(limit)
        rows = db.session.execute(stmt).scalars().all()
        return [_image_to_dict(r, include_payload=include_payload) for r in rows]

    @staticmethod
    def find_by_conversation(conversation_id, user_id, include_payload: bool = False):
        """Ordered turns of an image thread (oldest → newest), owner-scoped."""
        cid = _to_uuid(conversation_id)
        uid = _to_uuid(user_id)
        if cid is None or uid is None:
            return []
        stmt = (
            select(GeneratedImage)
            .where(
                GeneratedImage.conversation_id == cid,
                GeneratedImage.user_id == uid,
            )
            .order_by(GeneratedImage.created_at.asc())
        )
        rows = db.session.execute(stmt).scalars().all()
        return [_image_to_dict(r, include_payload=include_payload) for r in rows]

    @staticmethod
    def count_by_user(user_id, favorites_only: bool = False,
                      search: str | None = None) -> int:
        uid = _to_uuid(user_id)
        if uid is None:
            return 0
        stmt = select(func.count(GeneratedImage.id)).where(GeneratedImage.user_id == uid)
        if favorites_only:
            stmt = stmt.where(
                GeneratedImage.image_metadata['is_favorite'].astext == 'true'
            )
        if search:
            stmt = stmt.where(GeneratedImage.prompt.ilike(f"%{search}%"))
        return int(db.session.execute(stmt).scalar() or 0)

    @staticmethod
    def toggle_favorite(image_id):
        iid = _to_uuid(image_id)
        if iid is None:
            return None
        row = db.session.get(GeneratedImage, iid)
        if not row:
            return None
        meta = dict(row.image_metadata or {})
        new_value = not bool(meta.get('is_favorite', False))
        meta['is_favorite'] = new_value
        row.image_metadata = meta
        flag_modified(row, 'image_metadata')
        db.session.commit()
        return new_value

    @staticmethod
    def delete(image_id) -> bool:
        iid = _to_uuid(image_id)
        if iid is None:
            return False
        result = db.session.execute(
            delete(GeneratedImage).where(GeneratedImage.id == iid)
        )
        db.session.commit()
        return result.rowcount > 0

    @staticmethod
    def delete_many(image_ids, user_id) -> int:
        uid = _to_uuid(user_id)
        if uid is None:
            return 0
        uuids = [u for u in (_to_uuid(i) for i in (image_ids or [])) if u is not None]
        if not uuids:
            return 0
        result = db.session.execute(
            delete(GeneratedImage).where(
                GeneratedImage.id.in_(uuids),
                GeneratedImage.user_id == uid,
            )
        )
        db.session.commit()
        return result.rowcount


def _image_to_dict(row: 'GeneratedImage', include_payload: bool = True) -> dict:
    """Serialize a row to the legacy dict shape.

    ``include_payload=False`` omits the heavy base64 ``image_data``/``b64_payload``
    (data URI, often MBs each) while keeping all metadata — used by the LIST
    endpoint so a grid page isn't tens of MB of JSON. The full payload is then
    fetched per-id via the single-image endpoint.
    """
    out = row.to_dict()
    out['user_id'] = str(row.user_id) if row.user_id else None
    out['conversation_id'] = str(row.conversation_id) if row.conversation_id else None
    out['parent_image_id'] = str(row.parent_image_id) if row.parent_image_id else None
    # Legacy field aliases.
    out['model_id'] = row.model
    meta = row.image_metadata or {}
    out['metadata'] = meta
    out['negative_prompt'] = meta.get('negative_prompt', '')
    out['is_favorite'] = bool(meta.get('is_favorite', False))
    # Per-image price + tokens (persisted at generation time). Null on rows
    # created before this field existed → UI shows an em-dash / hides the row.
    out['cost_usd'] = meta.get('cost_usd')
    # Polymind Credits = the normalized, non-$ display unit for the price (profit
    # redesign 2026-06-29). Computed on read so the dollar figure never has to
    # leave the backend for non-$ viewers. ``to_credits`` maps None/non-numeric
    # → 0. No batch-total field on this row, so only the per-image credits apply.
    out['credits'] = to_credits(out.get('cost_usd'))
    _tok = meta.get('tokens') or {}
    _usage = meta.get('usage') or {}
    out['tokens'] = {
        'total': _tok.get('total') if _tok.get('total') is not None else _usage.get('total_tokens'),
        'image': _tok.get('image') if _tok.get('image') is not None else _usage.get('image_tokens'),
    }
    # Always expose the small thumbnail under ``thumb`` and drop the raw column
    # key. ``None`` for un-backfilled rows -> the frontend falls back to the
    # lazy full-by-id fetch for that tile.
    out['thumb'] = row.thumb_b64
    out.pop('thumb_b64', None)
    if include_payload:
        out['image_data'] = row.b64_payload
    else:
        # Drop both the alias and the raw column so the list response carries
        # zero full-res base64 — only the lightweight ``thumb``. Consumers fetch
        # the full image by id when needed.
        out.pop('image_data', None)
        out.pop('b64_payload', None)
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
    delete,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, defer, mapped_column
from sqlalchemy.orm.attributes import flag_modified

from app.extensions import db
from app.models._base import SerializableMixin


class GeneratedImage(db.Model, SerializableMixin):
    __tablename__ = 'generated_images'

    id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid_orm.uuid4
    )
    user_id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    b64_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Small downscaled WebP ``data:`` URI (max 256px). Nullable so existing rows
    # are valid pre-backfill; populated at create-time + via the backfill script.
    thumb_b64: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_metadata: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, server_default=_sql_text_orm("'{}'::jsonb")
    )
    settings: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, server_default=_sql_text_orm("'{}'::jsonb")
    )
    # Conversational editing: rows sharing a ``conversation_id`` form an ordered
    # edit thread. ``parent_image_id`` records which prior image this turn edited
    # (the one fed back in as the input/edit base). Both nullable so one-shot
    # generations and all legacy rows stay valid. FK is SET NULL so deleting a
    # thread row never orphans-cascade unexpectedly (thread delete removes its
    # images explicitly via the facade).
    conversation_id: Mapped[_uuid_orm.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('image_conversations.id', ondelete='SET NULL'),
        nullable=True,
    )
    parent_image_id: Mapped[_uuid_orm.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[_dt_orm] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_sql_text_orm('now()')
    )

    __table_args__ = (
        Index('ix_generated_images_user', 'user_id'),
        Index('ix_generated_images_created', _sql_text_orm('created_at DESC')),
        Index('ix_generated_images_conversation', 'conversation_id'),
    )


# ======================================================================
# Image edit conversations (threads) — a lightweight container so a series
# of edits ("make it blue", "now add a hat") groups, lists, and renames.
# Each ``generated_images`` row IS a turn; there is intentionally no separate
# messages table.
# ======================================================================
class ImageConversation(db.Model, SerializableMixin):
    __tablename__ = 'image_conversations'

    id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid_orm.uuid4
    )
    user_id: Mapped[_uuid_orm.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Polymorphic, FK-free (mirrors ``conversations.config_id``): the image
    # assistant (LLMConfig id) this thread is bound to, when any.
    config_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    workspace_id: Mapped[_uuid_orm.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    project_id: Mapped[_uuid_orm.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[_dt_orm] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_sql_text_orm('now()')
    )
    updated_at: Mapped[_dt_orm] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_sql_text_orm('now()')
    )

    __table_args__ = (
        Index('ix_image_conversations_user', 'user_id'),
        Index('ix_image_conversations_updated', _sql_text_orm('updated_at DESC')),
    )


class ImageConversationModel:
    """Facade for image edit threads (legacy dict returns)."""

    @staticmethod
    def create(user_id, title=None, config_id=None, workspace_id=None,
               project_id=None):
        uid = _to_uuid(user_id)
        if uid is None:
            raise ValueError(f"Invalid user_id: {user_id!r}")
        row = ImageConversation(
            user_id=uid,
            title=(title or None),
            config_id=(str(config_id) if config_id else None),
            workspace_id=_to_uuid(workspace_id),
            project_id=_to_uuid(project_id),
        )
        db.session.add(row)
        db.session.commit()
        return _conversation_to_dict(row)

    @staticmethod
    def find_by_id(conversation_id):
        cid = _to_uuid(conversation_id)
        if cid is None:
            return None
        row = db.session.get(ImageConversation, cid)
        return _conversation_to_dict(row) if row else None

    @staticmethod
    def find_by_user(user_id, skip: int = 0, limit: int = 50):
        """List a user's threads (newest activity first) with cover + count.

        Cover = the thread's latest image thumbnail; count = number of turns.
        N+1 over a capped page of threads is acceptable here (thread counts are
        small and the page is bounded).
        """
        uid = _to_uuid(user_id)
        if uid is None:
            return []
        stmt = (
            select(ImageConversation)
            .where(ImageConversation.user_id == uid)
            .order_by(ImageConversation.updated_at.desc())
            .offset(skip)
            .limit(limit)
        )
        rows = db.session.execute(stmt).scalars().all()
        out = []
        for row in rows:
            doc = _conversation_to_dict(row)
            count = int(db.session.execute(
                select(func.count(GeneratedImage.id)).where(
                    GeneratedImage.conversation_id == row.id
                )
            ).scalar() or 0)
            cover = db.session.execute(
                select(GeneratedImage.thumb_b64).where(
                    GeneratedImage.conversation_id == row.id
                ).order_by(GeneratedImage.created_at.desc()).limit(1)
            ).scalar()
            doc['image_count'] = count
            doc['cover_thumb'] = cover
            out.append(doc)
        return out

    @staticmethod
    def count_by_user(user_id) -> int:
        uid = _to_uuid(user_id)
        if uid is None:
            return 0
        return int(db.session.execute(
            select(func.count(ImageConversation.id)).where(
                ImageConversation.user_id == uid
            )
        ).scalar() or 0)

    @staticmethod
    def rename(conversation_id, user_id, title):
        cid = _to_uuid(conversation_id)
        uid = _to_uuid(user_id)
        if cid is None or uid is None:
            return None
        row = db.session.get(ImageConversation, cid)
        if not row or row.user_id != uid:
            return None
        row.title = (title or None)
        row.updated_at = _dt_orm.now(timezone.utc)
        db.session.commit()
        return _conversation_to_dict(row)

    @staticmethod
    def touch(conversation_id):
        """Bump ``updated_at`` after a new turn lands in the thread."""
        cid = _to_uuid(conversation_id)
        if cid is None:
            return
        row = db.session.get(ImageConversation, cid)
        if row:
            row.updated_at = _dt_orm.now(timezone.utc)
            db.session.commit()

    @staticmethod
    def delete(conversation_id, user_id) -> bool:
        """Delete a thread AND its images (owner-scoped)."""
        cid = _to_uuid(conversation_id)
        uid = _to_uuid(user_id)
        if cid is None or uid is None:
            return False
        row = db.session.get(ImageConversation, cid)
        if not row or row.user_id != uid:
            return False
        db.session.execute(
            delete(GeneratedImage).where(
                GeneratedImage.conversation_id == cid,
                GeneratedImage.user_id == uid,
            )
        )
        db.session.execute(
            delete(ImageConversation).where(ImageConversation.id == cid)
        )
        db.session.commit()
        return True


def _conversation_to_dict(row: 'ImageConversation') -> dict:
    out = row.to_dict()
    out['user_id'] = str(row.user_id) if row.user_id else None
    out['workspace_id'] = str(row.workspace_id) if row.workspace_id else None
    out['project_id'] = str(row.project_id) if row.project_id else None
    return out
