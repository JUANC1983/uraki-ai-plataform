# alembic/env.py
"""
Alembic environment for URAKI AI Platform (async SQLAlchemy).

Usage:
    alembic upgrade head          # apply all pending migrations
    alembic downgrade -1          # roll back one migration
    alembic revision --autogenerate -m "describe change"  # generate new migration
    alembic current               # show current revision
    alembic history               # show migration history

For an existing database created by create_tables() before Alembic was set up:
    alembic stamp 0001                  # mark DB as already at initial revision
    alembic upgrade head                # apply only newer migrations (e.g. 0002+)
"""
import asyncio
import logging
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

# Import Base and all models so metadata is fully populated before autogenerate
from database.base import Base
from database import models  # noqa: F401 — side-effect: registers ORM classes

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

logger = logging.getLogger("alembic.env")


def get_url() -> str:
    from config.settings import get_settings
    return get_settings().DATABASE_URL


# ---------------------------------------------------------------------------
# Offline mode — generate SQL without a live DB connection
# ---------------------------------------------------------------------------

def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Include schema name if using PostgreSQL schemas per tenant in future
        include_schemas=False,
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online mode — connect to DB and apply migrations
# ---------------------------------------------------------------------------

def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Compare server defaults so autogenerate detects DEFAULT changes
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(get_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()
    logger.info("Alembic migrations complete.")


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
