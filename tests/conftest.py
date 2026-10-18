"""Pytest fixtures and configuration for real PostgreSQL integration testing."""

import asyncio
import os
import sys
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

# Windows selector loop policy is required for psycopg async event loop support on Windows
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from psycopg import AsyncConnection, sql
from psycopg_pool import AsyncConnectionPool

from lead_qualifier.api.main import app
from lead_qualifier.core.database import tenant_transaction
from lead_qualifier.core.security import hash_api_key
from lead_qualifier.core.tenant import TenantContext

# Deterministic test and attacker tenant identifiers (isolated from seed's tenant_demo)
TENANT_TEST = "33333333-3333-3333-3333-333333333333"
TENANT_INVASOR = "22222222-2222-2222-2222-222222222222"

# Deterministic API keys for testing
API_KEY_TEST = "b2b_live_test_tenant_33333333333333333333"
API_KEY_INVASOR = "b2b_live_attacker_222222222222222222222222"
API_KEY_READONLY = "b2b_live_test_readonly_33333333333333333333"
API_KEY_WEBHOOK_ONLY = "b2b_live_test_webhook_33333333333333333333"

# Backward compatibility aliases
TENANT_DEMO = TENANT_TEST
API_KEY_DEMO = API_KEY_TEST


class TestTenantUnitOfWork:
    """Test helper supporting both `async with set_test_tenant_context(...)` and `await set_test_tenant_context(...)`."""

    def __init__(
        self,
        pool_or_conn: AsyncConnectionPool | AsyncConnection,
        tenant_id: str | UUID,
        schema_name: str,
    ) -> None:
        self.pool_or_conn = pool_or_conn
        self.tenant_ctx = TenantContext(
            tenant_id=UUID(str(tenant_id)),
            schema_name=schema_name,
        )
        self._cm = tenant_transaction(pool_or_conn, self.tenant_ctx)
        self._yielded_conn: AsyncConnection | None = None

    async def __aenter__(self) -> AsyncConnection:
        conn = await self._cm.__aenter__()
        self._yielded_conn = conn
        return conn

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Any:
        return await self._cm.__aexit__(exc_type, exc_val, exc_tb)

    def __await__(self) -> Any:
        # Backward-compatibility for direct calls awaiting tenant context setup
        async def _apply() -> None:
            if isinstance(self.pool_or_conn, AsyncConnection):
                async with self.pool_or_conn.cursor() as cur:
                    await cur.execute(
                        "SELECT set_config('app.current_tenant', %s, true)",
                        (str(self.tenant_ctx.tenant_id),),
                    )
                    await cur.execute(
                        sql.SQL("SET LOCAL search_path TO {}, public").format(
                            sql.Identifier(self.tenant_ctx.schema_name)
                        )
                    )

        return _apply().__await__()


def set_test_tenant_context(
    conn: AsyncConnection | AsyncConnectionPool,
    tenant_id: str | UUID,
    schema_name: str,
) -> TestTenantUnitOfWork:
    """Configure tenant transaction context safely using the tenant_transaction unit of work."""
    return TestTenantUnitOfWork(conn, tenant_id, schema_name)


@pytest_asyncio.fixture
async def db_admin() -> AsyncIterator[AsyncConnection]:
    """Yield a superuser connection for administrative operations and schema provisioning."""
    admin_user = os.getenv("DB_ADMIN_USER", "postgres")
    admin_pwd = os.getenv("DB_ADMIN_PASSWORD", "secret")
    db_name = os.getenv("DB_NAME", "b2b_lead_qualifier")
    conn_str = f"postgresql://{admin_user}:{admin_pwd}@127.0.0.1:5432/{db_name}?connect_timeout=3"
    async with await AsyncConnection.connect(conn_str) as conn:
        yield conn


@pytest_asyncio.fixture
async def _setup_test_tenants(db_admin: AsyncConnection) -> None:
    """Ensure test tenants, baseline rule sets, and test API keys are provisioned before each integration test."""
    async with db_admin.cursor() as cur:
        await cur.execute(
            "SELECT core.provision_tenant(%s, %s, %s)",
            (TENANT_TEST, "Acme Corp (Test)", "tenant_test"),
        )
        await cur.execute(
            "SELECT core.provision_tenant(%s, %s, %s)",
            (TENANT_INVASOR, "Tenant Invasor", "tenant_invasor"),
        )
        await cur.execute(
            """
            INSERT INTO tenant_test.scoring_rule_sets (
                tenant_id, version, rules, required_slots, qualification_threshold, is_active
            ) VALUES (
                %s, 1,
                '[
                    {"type": "knockout", "field": "role", "value": "estudante"},
                    {"type": "knockout", "field": "role", "value": "estagiario"},
                    {"type": "knockout", "field": "revenue", "value": "abaixo de 50 mil"},
                    {"type": "exact_match", "field": "role", "value": "CEO", "points": 50},
                    {"type": "exact_match", "field": "role", "value": "Diretor", "points": 40},
                    {"type": "exact_match", "field": "revenue", "value": "5 milhoes ao ano", "points": 50}
                ]'::jsonb,
                ARRAY['role', 'revenue']::text[],
                50, true
            ) ON CONFLICT (tenant_id, version) DO UPDATE SET
                rules = EXCLUDED.rules,
                required_slots = EXCLUDED.required_slots,
                qualification_threshold = EXCLUDED.qualification_threshold,
                is_active = EXCLUDED.is_active
            """,
            (TENANT_TEST,),
        )
        # Seed test API keys deterministically
        await cur.execute(
            """
            INSERT INTO core.api_keys (tenant_id, key_hash, name, scopes)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (key_hash) DO UPDATE SET
                tenant_id = EXCLUDED.tenant_id,
                scopes = EXCLUDED.scopes,
                revoked_at = NULL
            """,
            (
                TENANT_TEST,
                hash_api_key(API_KEY_TEST),
                "Test Tenant API Key",
                ["webhook:write", "leads:read"],
            ),
        )
        await cur.execute(
            """
            INSERT INTO core.api_keys (tenant_id, key_hash, name, scopes)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (key_hash) DO UPDATE SET
                tenant_id = EXCLUDED.tenant_id,
                scopes = EXCLUDED.scopes,
                revoked_at = NULL
            """,
            (
                TENANT_TEST,
                hash_api_key(API_KEY_READONLY),
                "Test Tenant Read-Only Key",
                ["leads:read"],
            ),
        )
        await cur.execute(
            """
            INSERT INTO core.api_keys (tenant_id, key_hash, name, scopes)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (key_hash) DO UPDATE SET
                tenant_id = EXCLUDED.tenant_id,
                scopes = EXCLUDED.scopes,
                revoked_at = NULL
            """,
            (
                TENANT_TEST,
                hash_api_key(API_KEY_WEBHOOK_ONLY),
                "Test Tenant Webhook-Only Key",
                ["webhook:write"],
            ),
        )
        await cur.execute(
            """
            INSERT INTO core.api_keys (tenant_id, key_hash, name, scopes)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (key_hash) DO UPDATE SET
                tenant_id = EXCLUDED.tenant_id,
                scopes = EXCLUDED.scopes,
                revoked_at = NULL
            """,
            (
                TENANT_INVASOR,
                hash_api_key(API_KEY_INVASOR),
                "Attacker Tenant Test Key",
                ["webhook:write", "leads:read"],
            ),
        )
        # Enforce least privilege permissions on core.api_keys
        await cur.execute("REVOKE SELECT ON core.api_keys FROM app_user")
        await cur.execute(
            "REVOKE EXECUTE ON FUNCTION core.resolve_tenant_by_api_key(varchar(64)) FROM PUBLIC"
        )
        await cur.execute(
            "GRANT EXECUTE ON FUNCTION core.resolve_tenant_by_api_key(varchar(64)) TO app_user"
        )
        await db_admin.commit()


@pytest_asyncio.fixture
async def db_app(_setup_test_tenants: None) -> AsyncIterator[AsyncConnection]:
    """Yield an unprivileged application connection without BYPASSRLS."""
    app_user = os.getenv("DB_USER", "app_user")
    app_pwd = os.getenv("DB_PASSWORD", "secret")
    db_name = os.getenv("DB_NAME", "b2b_lead_qualifier")
    conn_str = f"postgresql://{app_user}:{app_pwd}@127.0.0.1:5432/{db_name}?connect_timeout=3"
    async with await AsyncConnection.connect(conn_str) as conn:
        yield conn


@pytest_asyncio.fixture
async def db_pool(_setup_test_tenants: None) -> AsyncIterator[AsyncConnectionPool]:
    """Yield an unprivileged application connection pool for integration testing."""
    app_user = os.getenv("DB_USER", "app_user")
    app_pwd = os.getenv("DB_PASSWORD", "secret")
    db_name = os.getenv("DB_NAME", "b2b_lead_qualifier")
    conn_str = f"postgresql://{app_user}:{app_pwd}@127.0.0.1:5432/{db_name}?connect_timeout=3"
    pool = AsyncConnectionPool(conninfo=conn_str, min_size=1, max_size=10, open=False)
    await pool.open()
    yield pool
    await pool.close()


@pytest_asyncio.fixture
async def api_client(_setup_test_tenants: None) -> AsyncIterator[AsyncClient]:
    """Yield an async HTTP test client with application lifespan active."""
    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as client,
        app.router.lifespan_context(app),
    ):
        yield client
