"""widen status/role CHECK constraints + fix audit FK targets

Exposed by the Flask->FastAPI migration audit: the live schema carried CHECK
constraints narrower than the values the routes actually write, and two audit
FK columns (``platform_settings.updated_by_user_id`` /
``credit_ledger.created_by_user_id``) had the wrong referential target.

This migration:
  1. Widens ``ck_debate_sessions_status`` to allow the full session lifecycle.
  2. Widens ``ck_debate_messages_role`` to allow ``debater`` / ``judge``.
  3. Widens ``ck_automate_tasks_status`` to allow ``stopped`` / ``error`` /
     ``timed_out``.
  4. Retargets ``platform_settings.updated_by_user_id`` FK -> platform_admins(id).
     (Only platform admins ever write this column.)
  5. Drops the FK on ``credit_ledger.created_by_user_id`` entirely. This column
     is POLYMORPHIC: the workspace-owner billing route
     (``/workspaces/<wid>/billing/credits``) writes a ``users.id`` while the
     platform-admin route (``/platform/companies/<wid>/credits``) writes a
     ``platform_admins.id``. No single-table FK can serve both writers, so the
     column is a free-form UUID reference (matching the original Mongo design).

The platform_settings FK retarget first NULLs out any dangling references (rows
whose value is not a valid ``platform_admins.id``) so it is safe on populated DBs.

Revision ID: 0002_widen_constraints_retarget_fks
Revises: 0001_initial
Create Date: 2026-05-31 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
# NB: kept <=32 chars to fit alembic_version.version_num (varchar(32)); the
# descriptive filename can be longer than the revision id.
revision: str = '0002_widen_checks_retarget_fks'
down_revision: Union[str, Sequence[str], None] = '0001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Widen the three CHECK constraints + retarget the two audit FKs."""

    # 1. debate_sessions.status — allow the full session lifecycle.
    op.drop_constraint(
        'ck_debate_sessions_status', 'debate_sessions', type_='check'
    )
    op.create_check_constraint(
        'ck_debate_sessions_status',
        'debate_sessions',
        "status IN ('active','pending','in_progress','completed','cancelled','error')",
    )

    # 2. debate_messages.role — allow debate-specific speaker roles.
    op.drop_constraint(
        'ck_debate_messages_role', 'debate_messages', type_='check'
    )
    op.create_check_constraint(
        'ck_debate_messages_role',
        'debate_messages',
        "role IN ('user','assistant','system','tool','debater','judge')",
    )

    # 3. automate_tasks.status — allow the upstream terminal states.
    op.drop_constraint(
        'ck_automate_tasks_status', 'automate_tasks', type_='check'
    )
    op.create_check_constraint(
        'ck_automate_tasks_status',
        'automate_tasks',
        "status IN ('pending','running','completed','failed','cancelled','stopped','error','timed_out')",
    )

    # 4. platform_settings.updated_by_user_id -> platform_admins(id).
    #    NULL out dangling refs first so the new FK validates on populated DBs.
    op.execute(
        """
        UPDATE platform_settings
        SET updated_by_user_id = NULL
        WHERE updated_by_user_id IS NOT NULL
          AND updated_by_user_id NOT IN (SELECT id FROM platform_admins)
        """
    )
    op.drop_constraint(
        'platform_settings_updated_by_user_id_fkey',
        'platform_settings',
        type_='foreignkey',
    )
    op.create_foreign_key(
        'platform_settings_updated_by_user_id_fkey',
        'platform_settings',
        'platform_admins',
        ['updated_by_user_id'],
        ['id'],
        ondelete='SET NULL',
    )

    # 5. credit_ledger.created_by_user_id — drop the FK (polymorphic column).
    #    Written with a users.id by the workspace-owner billing route AND with a
    #    platform_admins.id by the platform-admin route; no single-table FK fits.
    op.drop_constraint(
        'credit_ledger_created_by_user_id_fkey',
        'credit_ledger',
        type_='foreignkey',
    )


def downgrade() -> None:
    """Reverse: restore the narrower CHECKs + the original users(id) FKs."""

    # 5. credit_ledger.created_by_user_id — restore the original users(id) FK.
    op.create_foreign_key(
        'credit_ledger_created_by_user_id_fkey',
        'credit_ledger',
        'users',
        ['created_by_user_id'],
        ['id'],
        ondelete='SET NULL',
    )

    # 4. platform_settings.updated_by_user_id -> users(id).
    op.drop_constraint(
        'platform_settings_updated_by_user_id_fkey',
        'platform_settings',
        type_='foreignkey',
    )
    op.create_foreign_key(
        'platform_settings_updated_by_user_id_fkey',
        'platform_settings',
        'users',
        ['updated_by_user_id'],
        ['id'],
        ondelete='SET NULL',
    )

    # 3. automate_tasks.status — restore the original narrow set.
    op.drop_constraint(
        'ck_automate_tasks_status', 'automate_tasks', type_='check'
    )
    op.create_check_constraint(
        'ck_automate_tasks_status',
        'automate_tasks',
        "status IN ('pending','running','completed','failed','cancelled')",
    )

    # 2. debate_messages.role — restore the original narrow set.
    op.drop_constraint(
        'ck_debate_messages_role', 'debate_messages', type_='check'
    )
    op.create_check_constraint(
        'ck_debate_messages_role',
        'debate_messages',
        "role IN ('user','assistant','system','tool')",
    )

    # 1. debate_sessions.status — restore the original narrow set.
    op.drop_constraint(
        'ck_debate_sessions_status', 'debate_sessions', type_='check'
    )
    op.create_check_constraint(
        'ck_debate_sessions_status',
        'debate_sessions',
        "status IN ('active','completed','error')",
    )
