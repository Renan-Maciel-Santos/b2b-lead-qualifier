"""API key authentication and tenant security context resolution."""

import hashlib
import re
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from psycopg import AsyncConnection, sql
from psycopg.errors import Error as PsycopgError

from lead_qualifier.core.database import get_db_connection
from lead_qualifier.core.logger import logger


def hash_api_key(raw_key: str) -> str:
    """Compute cryptographic SHA-256 hexadecimal hash of an API key.

    Args:
        raw_key: Plaintext API key provided by the caller.

    Returns:
        str: 64-character lowercase hexadecimal SHA-256 digest.
    """
    return hashlib.sha256(raw_key.strip().encode("utf-8")).hexdigest()


async def get_tenant_connection(
    authorization: Annotated[str | None, Header()] = None,
    conn: Annotated[AsyncConnection, Depends(get_db_connection)] = None,  # type: ignore[assignment]
) -> AsyncConnection:
    """Authenticate inbound request via Bearer API key and set tenant security context.

    Resolves tenant identity strictly from the API key hash, sets the PostgreSQL
    RLS session GUC (app.current_tenant), and scopes search_path to the dedicated schema.

    Args:
        authorization: Inbound HTTP Authorization header.
        conn: Injected database connection from the application pool.

    Returns:
        AsyncConnection: Initialized connection with tenant RLS context active.

    Raises:
        HTTPException(401): If API key is missing, malformed, invalid, or revoked.
        HTTPException(503): If a database error occurs during tenant context initialization.
    """
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key.",
        )

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key.",
        )

    raw_key = parts[1]
    key_hash = hash_api_key(raw_key)

    try:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT tenant_id, schema_name FROM core.resolve_tenant_by_api_key(%s)",
                (key_hash,),
            )
            row = await cur.fetchone()
            if not row:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid or missing API key.",
                )

            tenant_id, schema_name = row[0], row[1]
            if not re.match(r"^tenant_[a-z0-9_]{1,40}$", schema_name):
                raise HTTPException(
                    status_code=500,
                    detail="Invalid tenant schema identifier.",
                )

            # Enforce RLS session GUC locally for the request transaction
            await cur.execute(
                "SELECT set_config('app.current_tenant', %s, true)",
                (str(tenant_id),),
            )

            # Safely switch search_path to tenant schema
            set_search_path = sql.SQL("SET LOCAL search_path TO {}, public").format(
                sql.Identifier(schema_name)
            )
            await cur.execute(set_search_path)

    except HTTPException:
        raise
    except PsycopgError as err:
        logger.error(
            "Database error during tenant security context initialization: %s",
            err,
            exc_info=True,
        )
        raise HTTPException(
            status_code=503,
            detail="Service temporarily unavailable.",
        ) from err

    return conn
