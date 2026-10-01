"""Drop the revoked_tokens.user_id FK — the column is a polymorphic actor id.

``user_id`` on a revoked token can be:
  - a ``users.id`` (normal HS256 login),
  - a ``platform_admins.id`` (operator login), or
  - a raw Keycloak ``sub`` (KC RS256 tokens carry the KC uuid, not ours).

The 0001 baseline pointed it at ``users(id)``, so platform-admin and KC
logouts blew up with a ForeignKeyViolation (500 on POST /auth/logout).
Mirror of migration 0002's credit_ledger.created_by_user_id precedent:
informational id, no FK. Revocation correctness only ever keys on ``jti``.

Revision identifiers kept <=32 chars to fit alembic_version.version_num
(varchar(32)).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = '0011_revoked_tokens_no_fk'
down_revision: Union[str, Sequence[str], None] = '0010_spend_rollups'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('revoked_tokens_user_id_fkey', 'revoked_tokens', type_='foreignkey')


def downgrade() -> None:
    # NOTE: re-adding the FK fails if any row carries a platform-admin or
    # IdP-sub user_id; null those out first.
    op.execute(
        "UPDATE revoked_tokens SET user_id = NULL "
        "WHERE user_id IS NOT NULL "
        "AND user_id NOT IN (SELECT id FROM users)"
    )
    op.create_foreign_key(
        'revoked_tokens_user_id_fkey', 'revoked_tokens', 'users',
        ['user_id'], ['id'], ondelete='SET NULL',
    )
