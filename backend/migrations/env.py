"""Alembic environment for the uni-chat Postgres migration.

Migrations need only the DB URL + db.metadata, so this does NOT call
create_app(): the app factory runs production boot guards (RATELIMIT_ENABLED,
CORS_ORIGINS) + the admin bootstrap, which are irrelevant to schema migration
and fail in CI/CD (FLASK_ENV=production). ``import app.models`` registers
every ORM table on db.metadata at import time — no Flask app context required.

The URL is read from Config (env-backed) so deployment + dev hosts share a
single source of truth (no ``sqlalchemy.url`` in alembic.ini).
"""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import Config
from app.extensions import db
import app.models  # noqa: F401  (registers every ORM table on db.metadata)

# Alembic Config object — provides access to values in alembic.ini.
config = context.config

# Wire alembic.ini's [loggers]/[handlers]/[formatters] sections.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogenerate — the full schema.
target_metadata = db.metadata

# Read sqlalchemy.url from Config (SQLALCHEMY_DATABASE_URI env var) so prod +
# dev share one source. Config reads it at import time.
config.set_main_option('sqlalchemy.url', Config.SQLALCHEMY_DATABASE_URI)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — emits SQL to stdout without a DB.

    Useful for review + CI dry-runs.
    """
    url = config.get_main_option('sqlalchemy.url')
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={'paramstyle': 'named'},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode — connects + executes against the DB."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix='sqlalchemy.',
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
