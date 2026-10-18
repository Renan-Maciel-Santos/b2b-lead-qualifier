"""Health check and readiness endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from psycopg.errors import Error as PsycopgError
from psycopg_pool import AsyncConnectionPool

from lead_qualifier.core.database import get_db_pool
from lead_qualifier.core.logger import logger

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check(
    pool: Annotated[AsyncConnectionPool, Depends(get_db_pool)],
) -> dict[str, Any]:
    """Verify application liveness and database connectivity.

    Args:
        pool: Injected application database pool.

    Returns:
        dict: Service health status and database connectivity indicator.
    """
    try:
        async with pool.connection() as conn:
            await conn.execute("SELECT 1")
        return {"status": "ok", "database": "healthy"}
    except PsycopgError as e:
        logger.error("Database healthcheck failed: %s", e)
        return {"status": "ok", "database": "unhealthy"}
