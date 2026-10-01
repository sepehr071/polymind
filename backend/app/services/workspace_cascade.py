"""
Workspace cascade-delete (P0.5) — PG-backed.

``cascade_delete(workspace_id)`` walks the dependency graph leaf-first,
deletes everything scoped to the workspace (directly via ``workspace_id``
or indirectly via a ``project_id`` whose project belongs to it), and
returns the per-table deletion counts.

SQLAlchemy semantics:
    - The default session is transactional: every ``db.session.execute(delete...)``
      participates in the surrounding transaction.
    - We wrap the whole cascade in ``db.session.begin()`` so a failure mid-
      cascade rolls back everything (no half-cascaded workspaces).
    - On Postgres many of these FK constraints have ``ON DELETE CASCADE``
      themselves — the explicit per-table deletes are belt-and-suspenders
      for tables that don't, and they let us return precise per-table
      deletion counts for the audit_log entry the route writes.

Idempotency: re-running on an already-gone workspace returns ``{}``.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from sqlalchemy import delete as sa_delete, select

from app.extensions import db

_logger = logging.getLogger(__name__)


def _to_uuid(value) -> Optional[uuid.UUID]:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def cascade_delete(workspace_id) -> dict:
    """Cascade-delete every resource scoped to ``workspace_id``.

    Returns ``{table_name: deleted_count}`` for every table that had rows
    removed. Idempotent — already-deleted workspaces produce ``{}``.
    """
    wid = _to_uuid(workspace_id)
    if wid is None:
        return {}

    # Lazy ORM imports — keep this module light at import time and avoid
    # circular import pain.
    from app.models.workspace import Workspace
    from app.models.workspace_member import WorkspaceMember
    from app.models.workspace_invite import WorkspaceInvite
    from app.models.project import Project
    from app.models.project_member import ProjectMember
    from app.models.project_group_access import ProjectGroupAccess
    from app.models.project_webhook import ProjectWebhook
    from app.models.conversation import Conversation
    from app.models.message import Message
    from app.models.folder import Folder
    from app.models.workflow import Workflow
    from app.models.workflow_run import WorkflowRun
    from app.models.knowledge_item import KnowledgeItem
    from app.models.knowledge_folder import KnowledgeFolder
    from app.models.llm_config import LLMConfig
    from app.models.dlp_event import DLPEvent
    from app.models.credit_ledger import CreditLedger
    from app.models.usage_log import UsageLog
    from app.models.group import Group
    from app.models.group_member import GroupMember

    counts: dict = {}

    def _del(model_cls, where, label: str):
        result = db.session.execute(sa_delete(model_cls).where(where))
        rc = result.rowcount or 0
        if rc:
            counts[label] = counts.get(label, 0) + rc

    try:
        # 1. Discover project IDs in this workspace so we can chain-delete
        #    project-scoped tables that lack ``workspace_id`` themselves.
        project_ids = [
            r[0] for r in db.session.execute(
                select(Project.id).where(Project.workspace_id == wid)
            ).all()
        ]

        # 2/3. conversations belong to the workspace directly (``workspace_id``)
        #    or via a project; folders are PROJECT-scoped only. Chain-delete
        #    them (and their messages) so the audit counts are precise.
        from sqlalchemy import or_ as _or
        conv_scope = Conversation.workspace_id == wid
        if project_ids:
            conv_scope = _or(conv_scope, Conversation.project_id.in_(project_ids))
        conv_ids = [
            r[0] for r in db.session.execute(
                select(Conversation.id).where(conv_scope)
            ).all()
        ]
        if conv_ids:
            _del(Message, Message.conversation_id.in_(conv_ids), 'messages')
            _del(Conversation, Conversation.id.in_(conv_ids), 'conversations')
        if project_ids:
            _del(Folder, Folder.project_id.in_(project_ids), 'folders')

        # 4. Workflow-scoped tables — WorkflowRun has a workflow_id FK so
        #    we resolve workflow IDs first then chain-delete the runs.
        wf_ids = [
            r[0] for r in db.session.execute(
                select(Workflow.id).where(Workflow.workspace_id == wid)
            ).all()
        ]
        if wf_ids:
            _del(WorkflowRun, WorkflowRun.workflow_id.in_(wf_ids), 'workflow_runs')
        _del(Workflow, Workflow.workspace_id == wid, 'workflows')

        # 5. Knowledge + LLM config + DLP + credit ledger + usage logs.
        _del(KnowledgeItem, KnowledgeItem.workspace_id == wid, 'knowledge_items')
        _del(KnowledgeFolder, KnowledgeFolder.workspace_id == wid, 'knowledge_folders')
        _del(LLMConfig, LLMConfig.workspace_id == wid, 'llm_configs')
        _del(DLPEvent, DLPEvent.workspace_id == wid, 'dlp_events')
        _del(CreditLedger, CreditLedger.workspace_id == wid, 'credit_ledger')
        _del(UsageLog, UsageLog.workspace_id == wid, 'usage_logs')

        # 6. Group + group access scoped to workspace.
        group_ids = [
            r[0] for r in db.session.execute(
                select(Group.id).where(Group.workspace_id == wid)
            ).all()
        ]
        if group_ids:
            _del(GroupMember, GroupMember.group_id.in_(group_ids), 'group_members')
            _del(
                ProjectGroupAccess,
                ProjectGroupAccess.group_id.in_(group_ids),
                'project_group_access',
            )
        _del(Group, Group.workspace_id == wid, 'groups')

        # 7. Project-scoped tables: project_members + project_group_access
        #    + project_webhooks. ``project_group_access`` may have been hit
        #    in step 6 already; the second hit catches grants where the
        #    project's workspace is this one but the group isn't.
        if project_ids:
            _del(
                ProjectMember,
                ProjectMember.project_id.in_(project_ids),
                'project_members',
            )
            _del(
                ProjectGroupAccess,
                ProjectGroupAccess.project_id.in_(project_ids),
                'project_group_access',
            )
            _del(
                ProjectWebhook,
                ProjectWebhook.project_id.in_(project_ids),
                'project_webhooks',
            )

        # 8. Workspace memberships + invites + projects last.
        _del(
            WorkspaceInvite,
            WorkspaceInvite.workspace_id == wid,
            'workspace_invites',
        )
        _del(
            WorkspaceMember,
            WorkspaceMember.workspace_id == wid,
            'workspace_members',
        )
        _del(Project, Project.workspace_id == wid, 'projects')

        # 9. The workspace row itself.
        _del(Workspace, Workspace.id == wid, 'workspaces')

        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        _logger.exception('workspace_cascade: rollback after error %s', exc)
        raise

    return counts
