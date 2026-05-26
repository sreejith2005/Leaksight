"""
LeakSight V1 — Alembic Environment Configuration (Async)

Source: docs/DATABASE_SCHEMA.md, docs/DECISIONS.md (ADR-009)

Configures Alembic to use the async SQLAlchemy engine from core/database.py.
Supports both online (async) and offline (SQL script) migration modes.
"""

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Ensure the project root is on the Python path so that
# 'backend.app' imports work correctly when alembic is run
# from the backend/ directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from backend.app.core.config import get_settings
from backend.app.core.database import Base

# Import all models so Base.metadata is fully populated for autogenerate
import backend.app.models  # noqa: F401

# Alembic Config object — provides access to alembic.ini values
config = context.config

# Set the SQLAlchemy URL from application settings (not hardcoded in alembic.ini)
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

# Configure Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogenerate support — uses our Base's metadata
# so Alembic can detect model changes and generate migrations automatically.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Generates SQL scripts without requiring a live database connection.
    Useful for reviewing migration SQL before applying.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Execute migrations within a database connection context.

    Args:
        connection: Active database connection for running migrations.
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations using an async engine.

    Creates an async engine from the Alembic config, connects to the
    database, and runs migrations within the connection context.
    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode using async engine.

    Delegates to run_async_migrations() which handles the async
    engine creation and connection management.
    """
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
