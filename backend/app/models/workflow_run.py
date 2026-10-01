import uuid
from datetime import datetime

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


def _as_uuid(v):
    """Coerce str / UUID / ObjectId to ``uuid.UUID`` or ``None``."""
    if v is None:
        return None
    if isinstance(v, uuid.UUID):
        return v
    try:
        return uuid.UUID(str(v))
    except (ValueError, AttributeError):
        return None


class WorkflowRun(db.Model, SerializableMixin):
    """SQLAlchemy ORM model for ``workflow_runs``.

    Embedded ``node_results[]`` array in Mongo is normalised to the
    sibling ``WorkflowRunNodeResult`` child table below.
    """

    __tablename__ = 'workflow_runs'

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('workflows.id', ondelete='CASCADE'),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(db.Text, nullable=False)
    execution_mode: Mapped[str] = mapped_column(db.Text, nullable=False)
    start_node_id: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    error: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','completed','failed','cancelled')",
            name='ck_workflow_runs_status',
        ),
        CheckConstraint(
            "execution_mode IN ('full','single','from')",
            name='ck_workflow_runs_execution_mode',
        ),
        Index(
            'ix_workflow_runs_workflow_started',
            'workflow_id',
            text('started_at DESC NULLS LAST'),
        ),
    )


class WorkflowRunNodeResult(db.Model, SerializableMixin):
    """Per-node execution result row.

    Replaces the Mongo embedded array ``workflow_runs.node_results[]``.
    ``order_idx`` preserves topological order — frontend consumers replay
    runs in this sequence.
    """

    __tablename__ = 'workflow_run_node_results'

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('workflow_runs.id', ondelete='CASCADE'),
        nullable=False,
    )
    node_id: Mapped[str] = mapped_column(db.Text, nullable=False)
    order_idx: Mapped[int] = mapped_column(db.Integer, nullable=False)
    status: Mapped[str] = mapped_column(db.Text, nullable=False)
    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','completed','failed','skipped')",
            name='ck_workflow_run_node_results_status',
        ),
        Index(
            'ix_workflow_run_node_results_run_order',
            'run_id',
            'order_idx',
        ),
    )


# Columns hoisted out of the legacy free-form `result` dict into JSONB. Anything
# not in this set goes into ``output``.
_FIRST_CLASS_NODE_RESULT_COLUMNS = {'status', 'error', 'started_at', 'completed_at'}


class WorkflowRunModel:
    """Façade — internals ported to SQLAlchemy (Phase 4-C)."""

    @classmethod
    def create(cls, workflow_id, user_id, execution_mode, start_node_id=None):
        """Create a new workflow run."""
        row = WorkflowRun(
            id=uuid.uuid4(),
            workflow_id=_as_uuid(workflow_id),
            user_id=_as_uuid(user_id),
            status='running',
            execution_mode=execution_mode,
            start_node_id=start_node_id,
            started_at=datetime.utcnow(),
        )
        db.session.add(row)
        db.session.commit()
        return str(row.id)

    @classmethod
    def get_by_id(cls, run_id):
        """Get workflow run by ID (with embedded node_results for back-compat)."""
        rid = _as_uuid(run_id)
        if rid is None:
            return None
        row = db.session.execute(
            select(WorkflowRun).where(WorkflowRun.id == rid)
        ).scalar_one_or_none()
        if row is None:
            return None
        out = row.to_dict()
        # Inline node_results for callers that still expect the Mongo shape.
        out['node_results'] = cls._list_node_results(rid)
        return out

    @classmethod
    def _serialize_runs(cls, rows):
        """Serialize a page of run rows + their node_results.

        One bulk SELECT hydrates every run's node_results (kills the 1+R N+1).
        Output dict shape is identical to the prior per-run loop.
        """
        node_results_map = cls._node_results_map([r.id for r in rows])
        out = []
        for r in rows:
            d = r.to_dict()
            d['node_results'] = node_results_map.get(r.id, [])
            out.append(d)
        return out

    @classmethod
    def get_by_workflow(cls, workflow_id, user_id, limit=None, skip=0):
        """Get runs for a workflow (creator-filtered), newest first.

        ``limit=None`` keeps the legacy unbounded behaviour; callers that
        page (``get_workflow_runs``) pass an explicit cap.
        """
        wid = _as_uuid(workflow_id)
        uid = _as_uuid(user_id)
        if wid is None or uid is None:
            return []
        stmt = (
            select(WorkflowRun)
            .where(WorkflowRun.workflow_id == wid, WorkflowRun.user_id == uid)
            .order_by(WorkflowRun.started_at.desc().nulls_last())
        )
        if skip:
            stmt = stmt.offset(skip)
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = db.session.execute(stmt).scalars().all()
        return cls._serialize_runs(rows)

    @classmethod
    def find_by_workflow_id(cls, workflow_id, limit=None, skip=0):
        """Get runs for a workflow without filtering by user, newest first.

        Used by project-scoped run-history reads where the route ACL has
        already authorised the caller (e.g. project ``editor`` viewing
        runs of a workflow they didn't personally create).

        ``limit=None`` keeps the legacy unbounded behaviour.
        """
        wid = _as_uuid(workflow_id)
        if wid is None:
            return []
        stmt = (
            select(WorkflowRun)
            .where(WorkflowRun.workflow_id == wid)
            .order_by(WorkflowRun.started_at.desc().nulls_last())
        )
        if skip:
            stmt = stmt.offset(skip)
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = db.session.execute(stmt).scalars().all()
        return cls._serialize_runs(rows)

    @classmethod
    def find_running_for_workflow(cls, workflow_id):
        """Return the ``_id`` (str) of the first running run for a workflow,
        else None. Used to block concurrent execution attempts."""
        wid = _as_uuid(workflow_id)
        if wid is None:
            return None
        row_id = db.session.execute(
            select(WorkflowRun.id)
            .where(WorkflowRun.workflow_id == wid, WorkflowRun.status == 'running')
            .limit(1)
        ).scalar_one_or_none()
        return str(row_id) if row_id else None

    @classmethod
    def update_status(cls, run_id, status):
        """Update run status; set ``completed_at`` on terminal states."""
        rid = _as_uuid(run_id)
        if rid is None:
            return False
        values = {'status': status}
        if status in ('completed', 'failed', 'cancelled'):
            values['completed_at'] = datetime.utcnow()
        result = db.session.execute(
            sa_update(WorkflowRun).where(WorkflowRun.id == rid).values(**values)
        )
        db.session.commit()
        return (result.rowcount or 0) > 0

    @staticmethod
    def _shape_node_result(r):
        """Shape one ``WorkflowRunNodeResult`` row into the legacy dict.

        Single source of truth for the node-result wire shape so the per-run
        (:meth:`_list_node_results`) and bulk (:meth:`_node_results_map`)
        paths emit byte-identical dicts.
        """
        d = {
            'node_id': r.node_id,
            'status': r.status,
            'error': r.error,
            'started_at': r.started_at.isoformat() if r.started_at else None,
            'completed_at': r.completed_at.isoformat() if r.completed_at else None,
        }
        # Hoist JSONB output keys back to top-level for back-compat.
        if r.output:
            for k, v in r.output.items():
                d.setdefault(k, v)
        return d

    @classmethod
    def _list_node_results(cls, run_id_uuid):
        """Return node_results[] in topological (order_idx) order."""
        rows = db.session.execute(
            select(WorkflowRunNodeResult)
            .where(WorkflowRunNodeResult.run_id == run_id_uuid)
            .order_by(WorkflowRunNodeResult.order_idx.asc())
        ).scalars().all()
        return [cls._shape_node_result(r) for r in rows]

    @classmethod
    def _node_results_map(cls, run_ids):
        """Fetch node_results for many runs in ONE query, bucketed by run_id.

        Replaces the per-run :meth:`_list_node_results` loop in the runs-list
        methods (the 1+R N+1). Rows come back ordered by ``(run_id, order_idx)``
        — covered by ``ix_workflow_run_node_results_run_order`` — so each
        bucket preserves the same topological order the per-run path produced.
        """
        ids = [r for r in run_ids if r is not None]
        if not ids:
            return {}
        rows = db.session.execute(
            select(WorkflowRunNodeResult)
            .where(WorkflowRunNodeResult.run_id.in_(ids))
            .order_by(
                WorkflowRunNodeResult.run_id.asc(),
                WorkflowRunNodeResult.order_idx.asc(),
            )
        ).scalars().all()
        bucket: dict = {}
        for r in rows:
            bucket.setdefault(r.run_id, []).append(cls._shape_node_result(r))
        return bucket

    @classmethod
    def append_node_result(cls, run_id, node_id, **fields):
        """Append a new node-result row.

        ``order_idx`` is computed in the same session via
        ``MAX(order_idx) + 1`` so concurrent appends in different sessions
        are still well-defined (subject to PG row-locking on the parent run).
        """
        rid = _as_uuid(run_id)
        if rid is None:
            return False

        next_idx_row = db.session.execute(
            select(func.coalesce(func.max(WorkflowRunNodeResult.order_idx), -1) + 1)
            .where(WorkflowRunNodeResult.run_id == rid)
        ).scalar_one()
        next_idx = int(next_idx_row or 0)

        status = fields.pop('status', 'pending')
        error = fields.pop('error', None)
        started_at = fields.pop('started_at', None)
        completed_at = fields.pop('completed_at', None)
        # Everything else (image_data, image_id, text, audio_*, video_*, ...)
        # goes into the JSONB ``output`` blob — single canonical column for
        # node-specific media keys.
        output = {k: v for k, v in fields.items() if v is not None}

        row = WorkflowRunNodeResult(
            id=uuid.uuid4(),
            run_id=rid,
            node_id=node_id,
            order_idx=next_idx,
            status=status,
            output=output or None,
            error=error,
            started_at=started_at,
            completed_at=completed_at,
        )
        db.session.add(row)
        db.session.commit()
        return True

    @classmethod
    def update_node_result(cls, run_id, node_id, result):
        """Upsert a node result.

        - Existing row: update status/error/started_at/completed_at columns
          and merge ``result`` extras into JSONB ``output``.
        - Missing row: append via :meth:`append_node_result`.
        """
        rid = _as_uuid(run_id)
        if rid is None:
            return False

        existing = db.session.execute(
            select(WorkflowRunNodeResult)
            .where(
                WorkflowRunNodeResult.run_id == rid,
                WorkflowRunNodeResult.node_id == node_id,
            )
        ).scalar_one_or_none()

        if existing is None:
            return cls.append_node_result(run_id, node_id, **result)

        # Hoisted columns
        if 'status' in result:
            existing.status = result['status']
        if 'error' in result:
            existing.error = result['error']
        if 'started_at' in result:
            existing.started_at = result['started_at']
        if 'completed_at' in result:
            existing.completed_at = result['completed_at']

        # Merge anything else into JSONB output
        from sqlalchemy.orm.attributes import flag_modified
        merged = dict(existing.output or {})
        for k, v in result.items():
            if k in _FIRST_CLASS_NODE_RESULT_COLUMNS:
                continue
            merged[k] = v
        existing.output = merged
        flag_modified(existing, 'output')

        db.session.commit()
        return True
