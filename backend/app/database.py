"""SQLAlchemy async database setup for AegisMCP."""

import logging
from collections.abc import AsyncGenerator

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models import (
    Base,  # Share same Base from models.py so create_all() registers all models
)

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Columns added after the first release. create_all() does not alter existing
# tables, so each one is added idempotently for databases created by an older
# build. Keeping this list explicit makes the forward migration auditable.
_FORWARD_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "agent_traces": (
        ("org_id", "VARCHAR(64) NOT NULL DEFAULT '{default_org}'"),
    ),
    "api_keys": (
        ("org_id", "VARCHAR(64) NOT NULL DEFAULT '{default_org}'"),
    ),
    "mcp_servers": (
        ("tool_manifest_hash", "VARCHAR(64)"),
        ("pinned_tools", "JSON"),
    ),
    "trace_spans": (
        ("requester_id", "VARCHAR(255)"),
    ),
}


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async SQLAlchemy session as a FastAPI dependency.

    On any exception the session is rolled back before being closed, so a
    failed statement or commit can never leave a poisoned or locked
    transaction behind on the pooled connection.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def _table_columns(sync_conn, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(sync_conn).get_columns(table_name)}


async def _ensure_forward_columns(conn) -> None:
    """Add columns introduced after the first release when they are missing."""
    for table_name, columns_to_add in _FORWARD_COLUMNS.items():
        try:
            existing = await conn.run_sync(_table_columns, table_name)
        except Exception:  # noqa: BLE001 - table may not exist on a cold start
            logger.debug("Skipping column inspection for %s", table_name)
            continue
        for column_name, ddl in columns_to_add:
            if column_name in existing:
                continue
            logger.info("Migrating %s: adding %s column", table_name, column_name)
            await conn.execute(
                text(
                    f"ALTER TABLE {table_name} ADD COLUMN {column_name} "
                    + ddl.format(default_org=settings.DEFAULT_ORG_ID)
                )
            )


async def init_db() -> None:
    """Create all database tables and apply lightweight forward migrations."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_forward_columns(conn)
