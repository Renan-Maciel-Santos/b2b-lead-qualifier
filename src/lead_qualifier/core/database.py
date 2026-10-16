"""Database connection pooling and dependency injection.

This module provides utilities to instantiate the asynchronous connection pool
during application lifespan and inject scoped connections into FastAPI endpoints.
"""

from collections.abc import AsyncIterator

from fastapi import Request
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from lead_qualifier.core.settings import Settings


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
