"""
DLP event model — stores detection events from DLP scans.

Post Phase 4-C cutover the canonical store is Postgres. The ``matches[]``
embedded array becomes a sibling child table (``dlp_event_matches``); event
rows hold per-event aggregate fields only (``highest_action``,
``highest_severity``, ``status``, ``text_sha256``, ``source_ref``).
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

from bson import ObjectId
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    func,
    select,
    text,
    update as sa_update,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models._base import SerializableMixin

logger = logging.getLogger(__name__)


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


class DLPEvent(db.Model, SerializableMixin):
    """SQLAlchemy ORM model for ``dlp_events``."""

    __tablename__ = 'dlp_events'

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
    source: Mapped[str] = mapped_column(db.Text, nullable=False)
    status: Mapped[str] = mapped_column(db.Text, nullable=False)
    highest_action: Mapped[str] = mapped_column(db.Text, nullable=False)
    highest_severity: Mapped[str] = mapped_column(db.Text, nullable=False)
    text_sha256: Mapped[str] = mapped_column(db.Text, nullable=False)
    source_ref: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    # Review-workflow fields — distinct from the outcome ``status`` column.
    review_status: Mapped[str] = mapped_column(
        db.Text, nullable=False, server_default='open'
    )
    review_note: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "source IN ('chat','arena','workflow','helper',"
            "'image_prompt','meeting','debate','automate','assistant',"
            "'presentation','agent','ocr')",
            name='ck_dlp_events_source',
        ),
        CheckConstraint(
            "status IN ('blocked','confirmed','warned','allowed','redacted')",
            name='ck_dlp_events_status',
        ),
        CheckConstraint(
            "highest_action IN ('block','require_confirm','warn','allow','redact')",
            name='ck_dlp_events_highest_action',
        ),
        CheckConstraint(
            "highest_severity IN ('critical','high','medium','low','none')",
            name='ck_dlp_events_highest_severity',
        ),
        CheckConstraint(
            "review_status IN ('open','reviewed','dismissed','escalated')",
            name='ck_dlp_events_review_status',
        ),
        Index(
            'ix_dlp_events_workspace_created',
            'workspace_id',
            text('created_at DESC'),
        ),
        Index(
            'ix_dlp_events_workspace_status_created',
            'workspace_id',
            'status',
            text('created_at DESC'),
        ),
        Index(
            'ix_dlp_events_user_created',
            'user_id',
            text('created_at DESC'),
        ),
        Index(
            'ix_dlp_events_action_created',
            'highest_action',
            text('created_at DESC'),
        ),
        Index(
            'ix_dlp_events_source_ref_conv',
            text("(source_ref->>'conversation_id')"),
            postgresql_where=text("source_ref ? 'conversation_id'"),
        ),
        Index(
            'ix_dlp_events_source_ref_workflow',
            text("(source_ref->>'workflow_id')"),
            postgresql_where=text("source_ref ? 'workflow_id'"),
        ),
        Index(
            'ix_dlp_events_source_ref_run',
            text("(source_ref->>'run_id')"),
            postgresql_where=text("source_ref ? 'run_id'"),
        ),
    )


class DLPEventMatch(db.Model, SerializableMixin):
    """Per-rule match row for a DLP event.

    Replaces the Mongo embedded array ``dlp_events.matches[]``. Raw text is
    never persisted; only ``excerpt_masked`` (already redacted by the
    scanner) and the start/end span offsets.
    """

    __tablename__ = 'dlp_event_matches'

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('dlp_events.id', ondelete='CASCADE'),
        nullable=False,
    )
    rule_id: Mapped[str] = mapped_column(db.Text, nullable=False)
    category: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    severity: Mapped[str] = mapped_column(db.Text, nullable=False)
    action: Mapped[str] = mapped_column(db.Text, nullable=False)
    description: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    source_type: Mapped[str] = mapped_column(db.Text, nullable=False)
    span_start: Mapped[int | None] = mapped_column(db.Integer, nullable=True)
    span_end: Mapped[int | None] = mapped_column(db.Integer, nullable=True)
    excerpt_masked: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "severity IN ('critical','high','medium','low','none')",
            name='ck_dlp_event_matches_severity',
        ),
        CheckConstraint(
            "action IN ('block','require_confirm','warn','allow')",
            name='ck_dlp_event_matches_action',
        ),
        CheckConstraint(
            "source_type IN ('builtin','custom','hostname','llm')",
            name='ck_dlp_event_matches_source_type',
        ),
        # Covers the matches->events join in DLP stats (top_rules) and the
        # per-event match hydration in _load_matches_for.
        Index(
            'ix_dlp_event_matches_event',
            'event_id',
        ),
    )


# Whitelist of allowed `source_ref` top-level keys.
_ALLOWED_SOURCE_REF_KEYS = frozenset({
    'workflow_id',
    'node_id',
    'field',
    'meeting_id',
    'phase',
    'artifact',
    'session_id',
    'route',
    'preflight',
    'task_id',
    'knowledge_folder_id',
    'kind',
    'feature',
    'model',
    'conversation_id',
    'message_id',
    'run_id',
})

# Hard cap on the JSON-serialized size of `source_ref`.
_SOURCE_REF_MAX_BYTES = 512


def _sanitize_source_ref(d: Optional[dict]) -> dict:
    """Whitelist + bound-size ``source_ref`` before persisting."""
    if not d or not isinstance(d, dict):
        return {}

    clean: dict = {}
    for key, value in d.items():
        if key in _ALLOWED_SOURCE_REF_KEYS:
            clean[key] = value
        else:
            logger.debug("DLP source_ref: dropping unknown key %r", key)

    try:
        size = len(json.dumps(clean, default=str).encode('utf-8'))
    except (TypeError, ValueError):
        clean = {k: str(v) for k, v in clean.items()}
        size = len(json.dumps(clean).encode('utf-8'))

    if size <= _SOURCE_REF_MAX_BYTES:
        return clean

    for _ in range(32):
        str_keys = [k for k, v in clean.items() if isinstance(v, str)]
        if not str_keys:
            break
        longest = max(str_keys, key=lambda k: len(clean[k]))
        if len(clean[longest]) <= 8:
            break
        clean[longest] = clean[longest][: max(8, len(clean[longest]) // 2)]
        try:
            size = len(json.dumps(clean, default=str).encode('utf-8'))
        except (TypeError, ValueError):
            break
        if size <= _SOURCE_REF_MAX_BYTES:
            break

    return clean


VALID_STATUSES = {'open', 'reviewed', 'dismissed', 'escalated'}
# PG check-constraint uses the narrower outcome enum.
_VALID_EVENT_STATUSES_PG = {'blocked', 'confirmed', 'warned', 'allowed', 'redacted'}
VALID_SOURCES = {
    'chat',
    'arena',
    'workflow',
    'helper',
    'image_prompt',
    'meeting',
    'debate',
    'automate',
    'assistant',
    'presentation',
    'agent',
    'ocr',
    'research',
    'email_writer',
    'contract',
    'tender',
    'cv_checker',
    'shop',
}
VALID_ACTIONS = {'allow', 'warn', 'require_confirm', 'block', 'redact'}
VALID_SEVERITIES = {'low', 'medium', 'high', 'critical'}


# --- Helpers ----------------------------------------------------------------


def _highest_severity_of(matches: list[dict]) -> str:
    """Pick the strongest severity across the matches list."""
    rank = {'none': 0, 'low': 1, 'medium': 2, 'high': 3, 'critical': 4}
    best = 'none'
    for m in matches or []:
        sev = m.get('severity', 'none')
        if rank.get(sev, 0) > rank.get(best, 0):
            best = sev
    return best


def _row_to_legacy_dict(row: DLPEvent, matches: list[dict] | None = None) -> dict:
    """Emit legacy Mongo-shaped doc with ``matches[]`` inlined."""
    d = row.to_dict()
    d['matches'] = matches or []
    # Legacy doc had these flags; the PG schema folds them into status, so
    # surface sensible defaults for back-compat consumers.
    d.setdefault('was_sent', d.get('status') in ('confirmed', 'warned', 'allowed'))
    d.setdefault('user_acknowledged', d.get('status') == 'confirmed')
    return d


def _load_matches_for(event_ids: list) -> dict[uuid.UUID, list[dict]]:
    """Bulk-load matches for a set of event ids."""
    if not event_ids:
        return {}
    rows = db.session.execute(
        select(DLPEventMatch).where(DLPEventMatch.event_id.in_(event_ids))
    ).scalars().all()
    out: dict[uuid.UUID, list[dict]] = {}
    for m in rows:
        d = m.to_dict()
        # Map back to legacy match shape: rule_name + snippet + offsets.
        d['rule_name'] = d.get('rule_id')
        d['snippet'] = d.get('excerpt_masked')
        d['offset_start'] = d.get('span_start')
        d['offset_end'] = d.get('span_end')
        d['action_taken'] = d.get('action')
        out.setdefault(m.event_id, []).append(d)
    return out


class DLPEventModel:
    COLLECTION = 'dlp_events'

    # Dedup window — pre-flight `/dlp/scan` + downstream chokepoint
    # (chat_stream etc.) both call create() for the same single user action
    # with the same text_sha256. Within this window we merge into the
    # existing row instead of writing a second one.
    _DEDUP_WINDOW_SECONDS = 60

    sanitize_source_ref = staticmethod(_sanitize_source_ref)

    # ------------------------------------------------------------------
    # Status mapping — legacy "status" enum {open,reviewed,dismissed,
    # escalated} is the review-workflow status while the PG enum
    # {blocked,confirmed,warned,allowed} captures user-action outcome.
    # The transition keeps both: routes that call create() pass an outcome
    # via the highest_action/was_sent/user_acknowledged combination, which
    # we collapse to one of the PG-enum values; routes that update_review()
    # operate on the review-workflow status separately. To keep the
    # surface small we store the PG enum in the ``status`` column and
    # surface review state as a JSON-ish derivation; legacy review
    # tracking is dropped (rarely used; Phase 7 will model it).
    # ------------------------------------------------------------------

    @staticmethod
    def _outcome_status(*, highest_action: str, was_sent: bool,
                        user_acknowledged: bool) -> str:
        if highest_action == 'redact':
            return 'redacted'
        if highest_action == 'block':
            return 'blocked'
        if user_acknowledged:
            return 'confirmed'
        if was_sent:
            return 'warned'
        return 'allowed'

    @staticmethod
    def create(
        *,
        user_id,
        workspace_id,
        project_id,
        source: str,
        source_ref: dict,
        matches: list[dict],
        highest_action: str,
        was_sent: bool,
        text_sha256: str,
        text_length: int,
        user_acknowledged: bool = False,
        status: str = 'open',
        highest_severity: Optional[str] = None,
    ) -> dict:
        """Insert a new DLP event and return the inserted document.

        Dedup: within ``_DEDUP_WINDOW_SECONDS`` of an existing event with
        the same ``(user_id, workspace_id, source, text_sha256)``, merge into
        the existing row instead of writing a second one. ``was_sent`` is
        OR-merged (True wins). ``user_acknowledged`` is OR-merged.

        ``status`` is the review-workflow enum (``open|reviewed|dismissed|
        escalated``) and is the caller's hint only — the persisted ``status``
        column always holds the PG outcome enum derived from
        ``highest_action`` via :meth:`_outcome_status`. Callers MAY pass a PG
        outcome value (e.g. ``'redacted'``) for self-documentation; it is
        tolerated and likewise ignored in favor of the derived value.

        ``highest_severity`` overrides the value otherwise computed from
        ``matches`` — used by the redact gate, which already knows the floor.

        ``require_confirm`` is not a live action. It is stored as ``block`` so
        new rows never persist that value. ``VALID_ACTIONS`` still lists it so
        historical rows load.
        """
        from app.services.dlp_service import collapse_action
        highest_action = collapse_action(highest_action)
        coerced_matches = []
        for match in matches or []:
            if isinstance(match, dict):
                raw_action = match.get('action') or match.get('action_taken') or 'warn'
                coerced_matches.append({**match, 'action': collapse_action(raw_action)})
            else:
                coerced_matches.append(match)
        matches = coerced_matches

        if source not in VALID_SOURCES:
            raise ValueError(f"Invalid source: {source!r}. Must be one of {VALID_SOURCES}")
        if highest_action not in VALID_ACTIONS:
            raise ValueError(f"Invalid highest_action: {highest_action!r}")
        # Accept the review-workflow enum OR a PG outcome value (the latter is
        # self-documentation only; the column value is derived below).
        if status not in VALID_STATUSES and status not in _VALID_EVENT_STATUSES_PG:
            raise ValueError(f"Invalid status: {status!r}")

        existing = DLPEventModel.find_or_create_within_window(
            user_id=user_id,
            workspace_id=workspace_id,
            source=source,
            text_sha256=str(text_sha256),
        )
        if existing is not None:
            # Merge action / sent / ack flags. ``redact`` ranks just under
            # ``block`` — a redacted send is a real mitigation, stronger than a
            # warn/confirm but never overriding a hard block.
            action_rank = {'allow': 0, 'warn': 1, 'require_confirm': 2, 'redact': 2, 'block': 3}
            cur_action = existing.get('highest_action', 'allow')
            new_action = highest_action if (
                action_rank.get(highest_action, 0) > action_rank.get(cur_action, 0)
            ) else cur_action
            cur_sent = bool(existing.get('was_sent', False)) or bool(was_sent)
            cur_ack = bool(existing.get('user_acknowledged', False)) or bool(user_acknowledged)
            new_outcome = DLPEventModel._outcome_status(
                highest_action=new_action, was_sent=cur_sent,
                user_acknowledged=cur_ack,
            )
            updates = {}
            if new_action != cur_action:
                updates['highest_action'] = new_action
            if existing.get('status') != new_outcome:
                updates['status'] = new_outcome
            if updates:
                db.session.execute(
                    sa_update(DLPEvent)
                    .where(DLPEvent.id == _as_uuid(existing['_id']))
                    .values(**updates)
                )
                db.session.commit()
                existing.update(updates)
            existing['was_sent'] = cur_sent
            existing['user_acknowledged'] = cur_ack
            return existing

        event = DLPEvent(
            id=uuid.uuid4(),
            user_id=_as_uuid(user_id),
            workspace_id=_as_uuid(workspace_id),
            project_id=_as_uuid(project_id),
            source=source,
            status=DLPEventModel._outcome_status(
                highest_action=highest_action,
                was_sent=was_sent,
                user_acknowledged=user_acknowledged,
            ),
            highest_action=highest_action,
            highest_severity=highest_severity or _highest_severity_of(matches),
            text_sha256=str(text_sha256),
            source_ref=_sanitize_source_ref(source_ref),
        )
        db.session.add(event)
        db.session.flush()  # need event.id for the matches FK

        match_rows = []
        for m in (matches or []):
            match_rows.append(DLPEventMatch(
                id=uuid.uuid4(),
                event_id=event.id,
                rule_id=str(m.get('rule_id') or m.get('rule_name') or 'unknown'),
                category=m.get('category'),
                severity=str(m.get('severity', 'low')),
                action=str(m.get('action') or m.get('action_taken') or 'warn'),
                description=m.get('description'),
                source_type=str(m.get('source') or m.get('source_type') or 'builtin'),
                span_start=m.get('offset_start') or m.get('span_start'),
                span_end=m.get('offset_end') or m.get('span_end'),
                excerpt_masked=m.get('snippet') or m.get('excerpt_masked'),
            ))
        if match_rows:
            db.session.add_all(match_rows)

        db.session.commit()

        out = _row_to_legacy_dict(event, matches=[mr.to_dict() for mr in match_rows])
        out['text_length'] = int(text_length)
        out['user_acknowledged'] = bool(user_acknowledged)
        out['was_sent'] = bool(was_sent)
        return out

    @staticmethod
    def find_or_create_within_window(
        *, user_id, workspace_id, source: str, text_sha256: str,
    ) -> dict | None:
        """Dedup query — find a matching event within the configured window."""
        cutoff = datetime.utcnow() - timedelta(seconds=DLPEventModel._DEDUP_WINDOW_SECONDS)
        row = db.session.execute(
            select(DLPEvent)
            .where(
                DLPEvent.user_id == _as_uuid(user_id),
                DLPEvent.workspace_id == _as_uuid(workspace_id),
                DLPEvent.source == source,
                DLPEvent.text_sha256 == str(text_sha256),
                DLPEvent.created_at >= cutoff,
            )
            .order_by(DLPEvent.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if row is None:
            return None
        matches = _load_matches_for([row.id]).get(row.id, [])
        return _row_to_legacy_dict(row, matches=matches)

    @staticmethod
    def find_by_id(event_id) -> Optional[dict]:
        eid = _as_uuid(event_id)
        if eid is None:
            return None
        row = db.session.execute(
            select(DLPEvent).where(DLPEvent.id == eid)
        ).scalar_one_or_none()
        if row is None:
            return None
        matches = _load_matches_for([row.id]).get(row.id, [])
        return _row_to_legacy_dict(row, matches=matches)

    @staticmethod
    def _build_filters(
        stmt,
        *,
        user_id=None,
        workspace_id=None,
        severity: Optional[str] = None,
        source: Optional[str] = None,
        status: Optional[str] = None,
        action: Optional[str] = None,
        from_dt=None,
        to_dt=None,
    ):
        if workspace_id is not None:
            stmt = stmt.where(DLPEvent.workspace_id == _as_uuid(workspace_id))
        if user_id is not None:
            stmt = stmt.where(DLPEvent.user_id == _as_uuid(user_id))
        if severity is not None:
            stmt = stmt.where(DLPEvent.highest_severity == severity)
        if source is not None:
            stmt = stmt.where(DLPEvent.source == source)
        if status is not None:
            stmt = stmt.where(DLPEvent.status == status)
        if action is not None:
            stmt = stmt.where(DLPEvent.highest_action == action)
        if from_dt is not None:
            if isinstance(from_dt, str):
                from_dt = datetime.fromisoformat(from_dt)
            stmt = stmt.where(DLPEvent.created_at >= from_dt)
        if to_dt is not None:
            if isinstance(to_dt, str):
                to_dt = datetime.fromisoformat(to_dt)
            stmt = stmt.where(DLPEvent.created_at <= to_dt)
        return stmt

    @staticmethod
    def list_for_workspace(
        workspace_id,
        *,
        user_id=None,
        severity: Optional[str] = None,
        source: Optional[str] = None,
        status: Optional[str] = None,
        action: Optional[str] = None,
        from_dt=None,
        to_dt=None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[dict], int]:
        """List events for a workspace, newest first."""
        base = select(DLPEvent)
        count_base = select(func.count()).select_from(DLPEvent)
        filtered = DLPEventModel._build_filters(
            base, workspace_id=workspace_id, user_id=user_id, severity=severity,
            source=source, status=status, action=action, from_dt=from_dt, to_dt=to_dt,
        )
        filtered_count = DLPEventModel._build_filters(
            count_base, workspace_id=workspace_id, user_id=user_id, severity=severity,
            source=source, status=status, action=action, from_dt=from_dt, to_dt=to_dt,
        )
        total = int(db.session.execute(filtered_count).scalar_one() or 0)
        events = db.session.execute(
            filtered.order_by(DLPEvent.created_at.desc()).offset(skip).limit(limit)
        ).scalars().all()
        matches_by_event = _load_matches_for([e.id for e in events])
        return [_row_to_legacy_dict(e, matches=matches_by_event.get(e.id, [])) for e in events], total

    # Legacy alias for the public API.
    find_by_workspace = list_for_workspace

    @staticmethod
    def find_all(
        *,
        user_id=None,
        workspace_id=None,
        severity: Optional[str] = None,
        source: Optional[str] = None,
        status: Optional[str] = None,
        action: Optional[str] = None,
        from_dt=None,
        to_dt=None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[dict], int]:
        """Cross-workspace variant for platform admin."""
        base = select(DLPEvent)
        count_base = select(func.count()).select_from(DLPEvent)
        filtered = DLPEventModel._build_filters(
            base, workspace_id=workspace_id, user_id=user_id, severity=severity,
            source=source, status=status, action=action, from_dt=from_dt, to_dt=to_dt,
        )
        filtered_count = DLPEventModel._build_filters(
            count_base, workspace_id=workspace_id, user_id=user_id, severity=severity,
            source=source, status=status, action=action, from_dt=from_dt, to_dt=to_dt,
        )
        total = int(db.session.execute(filtered_count).scalar_one() or 0)
        events = db.session.execute(
            filtered.order_by(DLPEvent.created_at.desc()).offset(skip).limit(limit)
        ).scalars().all()
        matches_by_event = _load_matches_for([e.id for e in events])
        return [_row_to_legacy_dict(e, matches=matches_by_event.get(e.id, [])) for e in events], total

    @staticmethod
    def update_review(
        event_id,
        *,
        reviewer_id,
        status: str,
        review_note: Optional[str] = None,
    ) -> Optional[dict]:
        """Persist review-workflow fields on a DLP event.

        ``status`` is the review-workflow enum (``open|reviewed|dismissed|
        escalated``) and is stored on the dedicated ``review_status`` column
        (NOT the outcome ``status`` column). We still flip the outcome
        ``status`` to ``allowed`` on an explicit ``dismissed`` request so the
        admin UI stays sane; the other review states leave the outcome alone.
        Returns the refreshed legacy dict (the new columns surface via
        ``to_dict`` — ``reviewed_by_user_id`` stringified, ``reviewed_at``
        isoformatted), or ``None`` if the event does not exist.
        """
        eid = _as_uuid(event_id)
        if eid is None:
            return None
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {status!r}. Must be one of {VALID_STATUSES}")

        update_values: dict = {
            'review_status': status,
            'review_note': str(review_note)[:1000] if review_note else None,
            'reviewed_by_user_id': _as_uuid(reviewer_id),
            'reviewed_at': datetime.utcnow(),
        }
        # Map ``dismissed`` to the outcome column so the event reads as allowed.
        if status == 'dismissed':
            update_values['status'] = 'allowed'

        db.session.execute(
            sa_update(DLPEvent).where(DLPEvent.id == eid).values(**update_values)
        )
        db.session.commit()

        # Refetch so the serialized row reflects the persisted review fields.
        row = db.session.execute(
            select(DLPEvent).where(DLPEvent.id == eid)
        ).scalar_one_or_none()
        if row is None:
            return None
        matches = _load_matches_for([row.id]).get(row.id, [])
        out = _row_to_legacy_dict(row, matches=matches)
        # Legacy alias kept for back-compat consumers / tests that read the
        # flat ``reviewed_by`` key (the column emits ``reviewed_by_user_id``).
        out['reviewed_by'] = out.get('reviewed_by_user_id')
        return out

    @staticmethod
    def aggregate_workspace_stats(workspace_id, days: int = 7) -> dict:
        """Return rollup stats for one workspace over the trailing ``days``."""
        wid = _as_uuid(workspace_id)
        since = datetime.utcnow() - timedelta(days=days)

        base = lambda: select(DLPEvent).where(  # noqa: E731
            DLPEvent.workspace_id == wid,
            DLPEvent.created_at >= since,
        )

        total = int(db.session.execute(
            select(func.count()).select_from(DLPEvent).where(
                DLPEvent.workspace_id == wid,
                DLPEvent.created_at >= since,
            )
        ).scalar_one() or 0)

        # by_severity — group on the per-event highest_severity column.
        sev_rows = db.session.execute(
            select(DLPEvent.highest_severity, func.count())
            .where(DLPEvent.workspace_id == wid, DLPEvent.created_at >= since)
            .group_by(DLPEvent.highest_severity)
        ).all()
        by_severity = {s: 0 for s in VALID_SEVERITIES}
        for sev, cnt in sev_rows:
            if sev in by_severity:
                by_severity[sev] = int(cnt)

        # by_source
        src_rows = db.session.execute(
            select(DLPEvent.source, func.count())
            .where(DLPEvent.workspace_id == wid, DLPEvent.created_at >= since)
            .group_by(DLPEvent.source)
        ).all()
        by_source = {s: 0 for s in VALID_SOURCES}
        for s, cnt in src_rows:
            if s in by_source:
                by_source[s] = int(cnt)

        # top_users
        user_rows = db.session.execute(
            select(DLPEvent.user_id, func.count().label('count'))
            .where(DLPEvent.workspace_id == wid, DLPEvent.created_at >= since)
            .group_by(DLPEvent.user_id)
            .order_by(func.count().desc())
            .limit(10)
        ).all()
        top_users = [{'user_id': str(uid) if uid else None, 'count': int(cnt)} for uid, cnt in user_rows]

        # top_rules — join matches.
        rule_rows = db.session.execute(
            select(DLPEventMatch.rule_id, func.count().label('count'))
            .join(DLPEvent, DLPEventMatch.event_id == DLPEvent.id)
            .where(DLPEvent.workspace_id == wid, DLPEvent.created_at >= since)
            .group_by(DLPEventMatch.rule_id)
            .order_by(func.count().desc())
            .limit(10)
        ).all()
        top_rules = [{'rule_id': r, 'count': int(c)} for r, c in rule_rows]

        # daily buckets
        daily_rows = db.session.execute(
            select(
                func.to_char(DLPEvent.created_at, 'YYYY-MM-DD').label('day'),
                func.count().label('count'),
            )
            .where(DLPEvent.workspace_id == wid, DLPEvent.created_at >= since)
            .group_by('day')
            .order_by('day')
        ).all()
        daily = [{'date': d, 'count': int(c)} for d, c in daily_rows]

        return {
            'total': total,
            'by_severity': by_severity,
            'by_source': by_source,
            'top_users': top_users,
            'top_rules': top_rules,
            'daily': daily,
        }

    @staticmethod
    def aggregate_global_stats(days: int = 7) -> dict:
        """Cross-workspace stats for platform admin."""
        since = datetime.utcnow() - timedelta(days=days)
        total = int(db.session.execute(
            select(func.count()).select_from(DLPEvent).where(DLPEvent.created_at >= since)
        ).scalar_one() or 0)

        sev_rows = db.session.execute(
            select(DLPEvent.highest_severity, func.count())
            .where(DLPEvent.created_at >= since)
            .group_by(DLPEvent.highest_severity)
        ).all()
        by_severity = {s: 0 for s in VALID_SEVERITIES}
        for sev, cnt in sev_rows:
            if sev in by_severity:
                by_severity[sev] = int(cnt)

        src_rows = db.session.execute(
            select(DLPEvent.source, func.count())
            .where(DLPEvent.created_at >= since)
            .group_by(DLPEvent.source)
        ).all()
        by_source = {s: 0 for s in VALID_SOURCES}
        for s, cnt in src_rows:
            if s in by_source:
                by_source[s] = int(cnt)

        action_rows = db.session.execute(
            select(DLPEvent.highest_action, func.count())
            .where(DLPEvent.created_at >= since)
            .group_by(DLPEvent.highest_action)
        ).all()
        by_action = {a: 0 for a in ('block', 'require_confirm', 'warn')}
        for a, cnt in action_rows:
            if a in by_action:
                by_action[a] = int(cnt)

        user_rows = db.session.execute(
            select(DLPEvent.user_id, func.count().label('count'))
            .where(DLPEvent.created_at >= since)
            .group_by(DLPEvent.user_id)
            .order_by(func.count().desc())
            .limit(10)
        ).all()
        top_users = [{'user_id': str(uid) if uid else None, 'count': int(cnt)} for uid, cnt in user_rows]

        rule_rows = db.session.execute(
            select(DLPEventMatch.rule_id, func.count().label('count'))
            .join(DLPEvent, DLPEventMatch.event_id == DLPEvent.id)
            .where(DLPEvent.created_at >= since)
            .group_by(DLPEventMatch.rule_id)
            .order_by(func.count().desc())
            .limit(10)
        ).all()
        top_rules = [{'rule_id': r, 'count': int(c)} for r, c in rule_rows]

        daily_rows = db.session.execute(
            select(
                func.to_char(DLPEvent.created_at, 'YYYY-MM-DD').label('day'),
                func.count().label('count'),
            )
            .where(DLPEvent.created_at >= since)
            .group_by('day')
            .order_by('day')
        ).all()
        daily = [{'date': d, 'count': int(c)} for d, c in daily_rows]

        ws_rows = db.session.execute(
            select(DLPEvent.workspace_id, func.count().label('count'))
            .where(DLPEvent.created_at >= since)
            .group_by(DLPEvent.workspace_id)
            .order_by(func.count().desc())
            .limit(10)
        ).all()
        top_workspaces = [
            {'workspace_id': str(wid) if wid else None, 'name': '', 'count': int(c)}
            for wid, c in ws_rows
        ]

        return {
            'total': total,
            'by_severity': by_severity,
            'by_source': by_source,
            'by_action': by_action,
            'top_users': top_users,
            'top_rules': top_rules,
            'daily': daily,
            'top_workspaces': top_workspaces,
        }
