"""Health check and readiness endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from psycopg import AsyncConnection
from psycopg.errors import Error as PsycopgError

from lead_qualifier.core.database import get_db_connection
from lead_qualifier.core.logger import logger

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check(
    conn: Annotated[AsyncConnection, Depends(get_db_connection)],
) -> dict[str, Any]:
    """Verify application liveness and database connectivity.

    Args:
        conn: Injected database connection from the application pool.

    Returns:
        dict: Service health status and database connectivity indicator.
    """
    try:
        await conn.execute("SELECT 1")
        return {"status": "ok", "database": "healthy"}
    except PsycopgError as e:
        logger.error(f"Database healthcheck failed: {e!s}")
        return {"status": "ok", "database": "unhealthy"}
