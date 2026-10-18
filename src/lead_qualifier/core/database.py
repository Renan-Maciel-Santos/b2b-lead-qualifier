"""Database connection pooling, dependency injection, and transaction unit of work.

This module provides utilities to instantiate the asynchronous connection pool
during application lifespan and inject scoped transactions and connection pools
into FastAPI endpoints.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from fastapi import Request
from psycopg import AsyncConnection, sql
from psycopg_pool import AsyncConnectionPool

from lead_qualifier.core.settings import Settings
from lead_qualifier.core.tenant_context import TenantContext


def create_connection_pool(settings: Settings) -> AsyncConnectionPool:
    """Create a configured, un-opened connection pool.

    Args:
        settings: Application settings containing database credentials.

    Returns:
        AsyncConnectionPool configured with min and max pool sizing.
    """
    return AsyncConnectionPool(
        conninfo=settings.database_url,
        min_size=settings.db_pool_min,
        max_size=settings.db_pool_max,
        open=False,
    )


def get_db_pool(request: Request) -> AsyncConnectionPool:
    """FastAPI dependency yielding the shared connection pool from application state.

    Args:
        request: Current HTTP request containing app.state.db_pool.

    Returns:
        AsyncConnectionPool: The active application database pool.
    """
    return cast(AsyncConnectionPool, request.app.state.db_pool)


async def get_db_connection(request: Request) -> AsyncIterator[AsyncConnection]:
    """FastAPI dependency yielding a connection from the application state pool.

    Args:
        request: Current HTTP request containing the initialized app.state.db_pool.

    Yields:
        AsyncConnection: Checked out connection from the pool.
    """
    pool: AsyncConnectionPool = request.app.state.db_pool
    async with pool.connection() as conn:
        yield conn


@asynccontextmanager
async def tenant_transaction(
    pool: AsyncConnectionPool,
    tenant_ctx: TenantContext,
) -> AsyncIterator[AsyncConnection]:
    """Execute operations inside an atomic transaction scoped strictly to a tenant.

    Lifecycle:
    1. Acquires a connection from pool.
    2. Opens a transaction block.
    3. Executes set_config('app.current_tenant', ..., true) and SET LOCAL search_path.
    4. Yields connection to caller.
    5. Commits upon clean exit, rollbacks on exception.
    6. Returns connection to pool.

    Args:
        pool: Asynchronous PostgreSQL connection pool.
        tenant_ctx: Immutable tenant context (tenant_id and schema_name).

    Yields:
        AsyncConnection: Connection within an active, tenant-scoped transaction.
    """
    async with pool.connection() as conn, conn.transaction():
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT set_config('app.current_tenant', %s, true)",
                (str(tenant_ctx.tenant_id),),
            )
            await cur.execute(
                sql.SQL("SET LOCAL search_path TO {}, public").format(
                    sql.Identifier(tenant_ctx.schema_name)
                )
            )
        yield conn
