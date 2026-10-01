"""conversations.workspace_id + drop personal workspaces

Org-only workspaces. Users live only inside Keycloak orgs (team workspaces);
chat history and usage follow the selected org.

1. ``conversations.workspace_id`` (FK workspaces ON DELETE CASCADE) + list
   index ``(user_id, workspace_id, kind, last_message_at DESC)``.
2. Backfill it from ``projects.workspace_id``.
3. Re-point ``users.active_workspace_id`` off personal workspaces to the
   user's first active team membership (else NULL).
4. Detach user assets (workflows, llm_configs, knowledge, dlp_events,
   images, presentations, ocr jobs) from personal workspaces + their
   projects so the workspace delete does not CASCADE them away.
5. DELETE every conversation with no workspace (= ALL chats with
   ``project_id IS NULL``, incl. data/agent) and every conversation in a
   personal workspace. Messages/branches cascade; their shares are removed.
6. DELETE personal workspaces (members, invites, ledger, projects cascade;
   ``usage_logs.workspace_id`` goes NULL so billing history is kept) and
   their company spend_rollups / budget_allocations rows (no FK).
7. ``scope_type`` CHECKs on ``budget_allocations`` + ``spend_rollups`` gain
   ``'member'`` (per-user monthly budget inside one org).

DOWNGRADE drops the column and restores the CHECKs only. Deleted
conversations, messages, personal workspaces and their ledgers are NOT
recoverable — restore from a pg_dump taken before upgrade.

Revision ID: 0026_conv_ws_drop_personal
Revises: 0025_ocr_jobs
Create Date: 2026-09-29 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = '0026_conv_ws_drop_personal'
down_revision: Union[str, Sequence[str], None] = '0025_ocr_jobs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'conversations',
        sa.Column(
            'workspace_id',
            UUID(as_uuid=True),
            sa.ForeignKey(
                'workspaces.id',
                name='fk_conversations_workspace_id',
                ondelete='CASCADE',
            ),
            nullable=True,
        ),
    )
    op.create_index(
        'ix_conversations_user_ws_kind_last_message_at',
        'conversations',
        ['user_id', 'workspace_id', 'kind', sa.text('last_message_at DESC NULLS LAST')],
    )

    op.execute(
        """
        UPDATE conversations c SET workspace_id = p.workspace_id
        FROM projects p WHERE c.project_id = p.id
        """
    )

    op.execute(
        """
        CREATE TEMP TABLE pws ON COMMIT DROP AS
        SELECT id FROM workspaces WHERE is_personal
        """
    )
    op.execute(
        """
        CREATE TEMP TABLE pws_projects ON COMMIT DROP AS
        SELECT id FROM projects WHERE workspace_id IN (SELECT id FROM pws)
        """
    )

    # Re-point the active workspace before the delete SET NULLs it.
    op.execute(
        """
        UPDATE users u SET active_workspace_id = (
            SELECT m.workspace_id FROM workspace_members m
            JOIN workspaces w ON w.id = m.workspace_id
            WHERE m.user_id = u.id AND m.status = 'active' AND NOT w.is_personal
            ORDER BY w.display_name ASC, w.created_at ASC
            LIMIT 1
        )
        WHERE u.active_workspace_id IS NULL
           OR u.active_workspace_id IN (SELECT id FROM pws)
        """
    )

    # Keep user assets: these CASCADE from workspaces otherwise.
    for table in ('workflows', 'llm_configs', 'knowledge_items', 'dlp_events'):
        op.execute(
            f"""
            UPDATE {table} SET workspace_id = NULL, project_id = NULL
            WHERE workspace_id IN (SELECT id FROM pws)
               OR project_id IN (SELECT id FROM pws_projects)
            """
        )
    for table in ('workflows', 'llm_configs'):
        # A 'project' visibility with no project would be unreachable.
        op.execute(
            f"""
            UPDATE {table} SET visibility = 'private'
            WHERE visibility = 'project' AND project_id IS NULL
            """
        )
    # Knowledge folders move to the owner's personal namespace; any same-name
    # sibling of that owner forces a short id suffix so the (scope_key, name)
    # unique index holds even when several moved folders share a name.
    op.execute(
        """
        UPDATE knowledge_folders f SET
            workspace_id = NULL,
            project_id = NULL,
            scope_key = 'u:' || f.user_id::text,
            name = CASE WHEN EXISTS (
                SELECT 1 FROM knowledge_folders o
                WHERE o.user_id = f.user_id AND o.name = f.name AND o.id <> f.id
            ) THEN f.name || ' (' || left(f.id::text, 8) || ')' ELSE f.name END
        WHERE f.user_id IS NOT NULL
          AND (f.workspace_id IN (SELECT id FROM pws)
               OR f.project_id IN (SELECT id FROM pws_projects))
        """
    )
    op.execute(
        """
        UPDATE knowledge_folders SET workspace_id = NULL
        WHERE workspace_id IN (SELECT id FROM pws)
        """
    )
    # No FK on these — clear ids that would dangle after the delete.
    for table in ('image_conversations', 'presentations'):
        op.execute(
            f"""
            UPDATE {table} SET workspace_id = NULL, project_id = NULL
            WHERE workspace_id IN (SELECT id FROM pws)
               OR project_id IN (SELECT id FROM pws_projects)
            """
        )
    op.execute(
        """
        UPDATE ocr_jobs SET workspace_id = NULL
        WHERE workspace_id IN (SELECT id FROM pws)
        """
    )

    # Conversations: every no-team chat + anything filed in a personal ws.
    op.execute(
        """
        CREATE TEMP TABLE dead_convs ON COMMIT DROP AS
        SELECT id FROM conversations
        WHERE workspace_id IS NULL OR workspace_id IN (SELECT id FROM pws)
        """
    )
    op.execute(
        """
        DELETE FROM conversation_shares
        WHERE conversation_id IN (SELECT id FROM dead_convs)
           OR project_id IN (SELECT id FROM pws_projects)
        """
    )
    op.execute("DELETE FROM conversations WHERE id IN (SELECT id FROM dead_convs)")
    # Chat folders would otherwise fall back to personal scope (SET NULL).
    op.execute(
        "DELETE FROM folders WHERE project_id IN (SELECT id FROM pws_projects)"
    )

    op.execute(
        """
        DELETE FROM spend_rollups
        WHERE (scope_type = 'company' AND scope_id IN (SELECT id FROM pws))
           OR (scope_type = 'team' AND scope_id IN (SELECT id FROM pws_projects))
        """
    )
    op.execute(
        """
        DELETE FROM budget_allocations
        WHERE (scope_type = 'company' AND scope_id IN (SELECT id FROM pws))
           OR (scope_type = 'team' AND scope_id IN (SELECT id FROM pws_projects))
        """
    )

    op.execute("DELETE FROM workspaces WHERE id IN (SELECT id FROM pws)")

    op.drop_constraint('ck_budget_allocations_scope_type', 'budget_allocations', type_='check')
    op.create_check_constraint(
        'ck_budget_allocations_scope_type',
        'budget_allocations',
        "scope_type IN ('holding','company','team','user','member')",
    )
    op.drop_constraint('ck_spend_rollups_scope_type', 'spend_rollups', type_='check')
    op.create_check_constraint(
        'ck_spend_rollups_scope_type',
        'spend_rollups',
        "scope_type IN ('company','team','user','member')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM spend_rollups WHERE scope_type = 'member'")
    op.execute("DELETE FROM budget_allocations WHERE scope_type = 'member'")
    op.drop_constraint('ck_spend_rollups_scope_type', 'spend_rollups', type_='check')
    op.create_check_constraint(
        'ck_spend_rollups_scope_type',
        'spend_rollups',
        "scope_type IN ('company','team','user')",
    )
    op.drop_constraint('ck_budget_allocations_scope_type', 'budget_allocations', type_='check')
    op.create_check_constraint(
        'ck_budget_allocations_scope_type',
        'budget_allocations',
        "scope_type IN ('holding','company','team','user')",
    )
    op.drop_index('ix_conversations_user_ws_kind_last_message_at', table_name='conversations')
    op.drop_constraint('fk_conversations_workspace_id', 'conversations', type_='foreignkey')
    op.drop_column('conversations', 'workspace_id')
