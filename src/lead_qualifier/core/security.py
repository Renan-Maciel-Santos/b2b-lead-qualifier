"""API key authentication and tenant security context resolution."""

import hashlib
import re
from collections.abc import Callable, Coroutine
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request
from psycopg.errors import Error as PsycopgError
from psycopg_pool import AsyncConnectionPool

from lead_qualifier.core.logger import logger
from lead_qualifier.core.tenant_context import TenantContext


def hash_api_key(raw_key: str) -> str:
    """Compute cryptographic SHA-256 hexadecimal hash of an API key.

    Args:
        raw_key: Plaintext API key provided by the caller.

    Returns:
        str: 64-character lowercase hexadecimal SHA-256 digest.
    """
    return hashlib.sha256(raw_key.strip().encode("utf-8")).hexdigest()


async def get_tenant_context(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> TenantContext:
    """Authenticate inbound request via Bearer API key and resolve tenant security context.

    Resolves tenant identity strictly from the API key hash via the SECURITY DEFINER
    function core.resolve_tenant_by_api_key. Returns an immutable TenantContext
    without holding or configuring any persistent database connection.

    Args:
        request: Current HTTP request containing app.state.db_pool.
        authorization: Inbound HTTP Authorization header.

    Returns:
        TenantContext: Strongly-typed, immutable tenant identity, schema, and granted scopes.

    Raises:
        HTTPException(401): If API key is missing, malformed, invalid, or revoked.
        HTTPException(503): If a database error occurs during tenant context resolution.
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

    pool: AsyncConnectionPool = request.app.state.db_pool
    try:
        # Borrow a connection briefly solely to resolve the tenant identity
        async with (
            pool.connection() as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                "SELECT tenant_id, schema_name, scopes FROM core.resolve_tenant_by_api_key(%s)",
                (key_hash,),
            )
            row = await cur.fetchone()
            if not row:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid or missing API key.",
                )

            tenant_id, schema_name, scopes = row[0], row[1], row[2]
            if not re.match(r"^tenant_[a-z0-9_]{1,40}$", schema_name):
                raise HTTPException(
                    status_code=500,
                    detail="Invalid tenant schema identifier.",
                )

            return TenantContext(
                tenant_id=UUID(str(tenant_id)),
                schema_name=schema_name,
                scopes=frozenset(scopes or []),
            )

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


def require_scope(
    required_scope: str,
) -> Callable[..., Coroutine[Any, Any, TenantContext]]:
    """Create a FastAPI dependency that verifies whether the authenticated tenant has a specific scope.

    Args:
        required_scope: Required permission scope identifier (e.g., 'webhook:write', 'leads:read').

    Returns:
        Callable dependency returning the validated TenantContext.

    Raises:
        HTTPException(403): If the authenticated tenant context lacks the required scope.
    """

    async def _scope_checker(
        tenant_ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    ) -> TenantContext:
        if required_scope not in tenant_ctx.scopes:
            raise HTTPException(
                status_code=403,
                detail="Forbidden",
            )
        return tenant_ctx

    return _scope_checker
