"""Alembic migration environment.

Reads DATABASE_URL from the process env (populated by python-dotenv via
src/debate_gpt/config.py when the user runs `python -m alembic` from the
repo root, or directly via the shell).

Schema is managed with raw `op.execute()` (no SQLAlchemy model) — see
migrations/versions/0001_init.py.
"""
from __future__ import annotations

import os
from logging.config import fileConfig
from dotenv import load_dotenv
load_dotenv()
from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

# Override sqlalchemy.url from the env if set.
db_url = os.environ.get("DATABASE_URL")
if db_url:
    # Alembic uses sync drivers; asyncpg DSNs need a `+psycopg2://` prefix or
    # the URL rewritten. We rewrite the scheme so psycopg2 (which is
    # installed via psycopg2-binary) is used.
    if db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    elif db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
    config.set_main_option("sqlalchemy.url", db_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# No SQLAlchemy model — schema is raw SQL.
target_metadata = None


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live DB connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
