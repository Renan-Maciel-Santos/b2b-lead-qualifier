"""Multi-tenant connection dependency with strict RLS and search_path isolation."""

import re
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException
from psycopg import AsyncConnection, sql
from psycopg.errors import Error as PsycopgError

from lead_qualifier.core.database import get_db_connection


async def get_tenant_connection(
    tenant: str,
    conn: Annotated[AsyncConnection, Depends(get_db_connection)],
) -> AsyncConnection:
    """Validate tenant identity, apply PostgreSQL RLS session GUC, and set the tenant search_path.

    Enforces fail-closed multi-tenancy: if the tenant is invalid or does not exist,
    the request is terminated immediately with an HTTP error before accessing application tables.

    Args:
        tenant: Tenant UUID string extracted from the request path.
        conn: Injected database connection from the application pool.

    Returns:
        AsyncConnection: Configured connection with tenant context set locally.

    Raises:
        HTTPException: If the tenant identifier is malformed, not found, or configuration fails.
    """
    try:
        tenant_uuid = UUID(tenant)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=400,
            detail="Invalid or unauthorized tenant identifier.",
        )

    async with conn.cursor() as cur:
        try:
            # Set session GUC locally for RLS row filtering (is_local=true ensures rollback on connection return)
            await cur.execute(
                "SELECT set_config('app.current_tenant', %s, true)",
                (str(tenant_uuid),),
            )

            # Query tenant catalog in core schema to locate dedicated tenant schema
            await cur.execute(
                "SELECT schema_name FROM core.tenants WHERE id = %s",
                (str(tenant_uuid),),
            )
            row = await cur.fetchone()
            if not row:
                raise HTTPException(
                    status_code=404,
                    detail="Tenant not found or inactive.",
                )

            schema_name = row[0]
            # Strict regex validation on schema name as defense-in-depth against SQL injection
            if not re.match(r"^tenant_[a-z0-9_]{1,40}$", schema_name):
                raise HTTPException(
                    status_code=500,
                    detail="Invalid tenant schema identifier.",
                )

            # Safe identifier formatting for search_path switching
            set_search_path_query = sql.SQL(
                "SET LOCAL search_path TO {}, public"
            ).format(sql.Identifier(schema_name))
            await cur.execute(set_search_path_query)

        except PsycopgError:
            raise HTTPException(
                status_code=400,
                detail="Failed to initialize tenant security context.",
            )

    return conn
