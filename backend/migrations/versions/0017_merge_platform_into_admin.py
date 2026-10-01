"""merge platform-admin audit trail into admin audit_logs; drop dead tables

Eliminates the platform-admin principal. Adds a ``category`` discriminator to
``audit_logs`` ('app' for super-admin rows, 'holding' for the migrated
operator rows), moves every ``platform_audit_logs`` row into ``audit_logs``
(remapping ``platform_admin_id`` to the linked ``users.id`` via
``platform_admins.user_id`` — FK-safe, NULL when unlinked, original actor
stashed in ``details.platform_admin_id`` for traceability), then drops the two
now-dead tables ``platform_audit_logs`` and ``platform_admins``.

``platform_settings`` STAYS, but its ``updated_by_user_id`` FK pointed at
``platform_admins.id`` (retargeted there by migration 0002). That FK would block
``DROP TABLE platform_admins`` (DependentObjectsStillExist), so this revision
first NULLs any value that isn't a real ``users.id`` and retargets the FK back to
``users.id`` — which is also now correct, since the merged super-admin path writes
its own ``users.id`` into that column.

Ordering in ``upgrade`` is load-bearing: the column add + data move MUST run
while both source tables still exist, the FK retarget MUST precede the table
drops, and only then are the dead tables dropped.

``downgrade`` is best-effort: it structurally recreates the two tables (so the
schema reverses) and drops the column/index, but does NOT move the migrated
rows back out of ``audit_logs``.

Revision ID: 0017_merge_platform_into_admin
Revises: 0016_conversation_kind
Create Date: 2026-06-14 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, UUID

# revision identifiers, used by Alembic.
# NB: kept <=32 chars to fit alembic_version.version_num (varchar(32)).
revision: str = '0017_merge_platform_into_admin'
down_revision: Union[str, Sequence[str], None] = '0016_conversation_kind'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. New discriminator. server_default backfills every existing row to 'app'.
    op.add_column(
        'audit_logs',
        sa.Column('category', sa.Text(), nullable=False, server_default='app'),
    )
    op.create_index('ix_audit_logs_category', 'audit_logs', ['category'])

    # 2. Data move — runs while BOTH tables still exist. Map platform_admin_id
    #    -> the operator's linked users.id (platform_admins.user_id); NULL when
    #    unlinked (FK is users.id ON DELETE SET NULL — platform_admins.id is NOT
    #    a users.id, so inserting it directly would violate the FK). The original
    #    platform_admin_id is stashed into details so the actor is never lost.
    op.execute(sa.text(
        "INSERT INTO audit_logs "
        "(id, admin_user_id, action, target_id, target_type, details, category, created_at) "
        "SELECT gen_random_uuid(), pa.user_id, pal.action, pal.target_id, pal.target_type, "
        "jsonb_set(COALESCE(pal.details, '{}'::jsonb), '{platform_admin_id}', "
        "to_jsonb(pal.platform_admin_id::text)), "
        "'holding', pal.created_at "
        "FROM platform_audit_logs pal "
        "LEFT JOIN platform_admins pa ON pa.id = pal.platform_admin_id"
    ))

    # 3. Retarget the platform_settings FK off platform_admins (-> users) BEFORE
    #    the table drop, else DROP TABLE platform_admins raises
    #    DependentObjectsStillExist. NULL any value that isn't a live users.id
    #    first (it may currently hold a platform_admins.id) so the new FK
    #    validates on populated DBs. The merged super-admin write path stores a
    #    users.id here, so users(id) is the correct post-merge target.
    op.execute(sa.text(
        "UPDATE platform_settings SET updated_by_user_id = NULL "
        "WHERE updated_by_user_id IS NOT NULL "
        "AND updated_by_user_id NOT IN (SELECT id FROM users)"
    ))
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

    # 4. Drop the dead tables. Drop the child (FK -> platform_admins) first.
    op.drop_table('platform_audit_logs')
    op.drop_table('platform_admins')


def downgrade() -> None:
    # Structurally recreate the dropped tables (data move is NOT reversed —
    # migrated rows stay in audit_logs). Parent first so the child's FK resolves.
    op.create_table(
        'platform_admins',
        sa.Column('id', UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), nullable=True),
        sa.Column('email', CITEXT(), nullable=False),
        sa.Column('display_name', sa.Text(), nullable=True),
        sa.Column(
            'permissions', JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            'created_at',
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
        sa.UniqueConstraint('email'),
    )

    op.create_table(
        'platform_audit_logs',
        sa.Column('id', UUID(as_uuid=True), nullable=False),
        sa.Column('platform_admin_id', UUID(as_uuid=True), nullable=False),
        sa.Column('action', sa.Text(), nullable=False),
        sa.Column('target_type', sa.Text(), nullable=True),
        sa.Column('target_id', sa.Text(), nullable=True),
        sa.Column(
            'details', JSONB(), nullable=True, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            'created_at',
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.ForeignKeyConstraint(
            ['platform_admin_id'], ['platform_admins.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_platform_audit_logs_admin', 'platform_audit_logs', ['platform_admin_id']
    )
    op.create_index(
        'ix_platform_audit_logs_action', 'platform_audit_logs', ['action']
    )
    op.create_index(
        'ix_platform_audit_logs_created_brin',
        'platform_audit_logs',
        ['created_at'],
        postgresql_using='brin',
    )

    # Retarget the platform_settings FK back onto platform_admins (the pre-0017
    # state, now that the table exists again). Mirror upgrade's NULL-guard.
    op.execute(sa.text(
        "UPDATE platform_settings SET updated_by_user_id = NULL "
        "WHERE updated_by_user_id IS NOT NULL "
        "AND updated_by_user_id NOT IN (SELECT id FROM platform_admins)"
    ))
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

    # Drop the discriminator added in upgrade().
    op.drop_index('ix_audit_logs_category', table_name='audit_logs')
    op.drop_column('audit_logs', 'category')
