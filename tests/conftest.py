"""Pytest fixtures and configuration for real PostgreSQL integration testing."""

import asyncio
from collections.abc import AsyncIterator
import os
import sys

# Windows selector loop policy is required for psycopg async event loop support on Windows
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from psycopg import AsyncConnection, sql
import pytest_asyncio

# Deterministic demo and attacker tenant identifiers
TENANT_DEMO = "11111111-1111-1111-1111-111111111111"
TENANT_INVASOR = "22222222-2222-2222-2222-222222222222"


async def set_test_tenant_context(
    conn: AsyncConnection,
    tenant_id: str,
    schema_name: str,
) -> None:
    """Configure tenant session GUC and search_path safely using parameterized queries.

    Args:
        conn: Target database connection.
        tenant_id: Tenant UUID string.
        schema_name: Target schema name.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT set_config('app.current_tenant', %s, true)",
            (tenant_id,),
        )
        await cur.execute(
            sql.SQL("SET LOCAL search_path TO {}, public").format(
                sql.Identifier(schema_name)
            )
        )


@pytest_asyncio.fixture
async def db_admin() -> AsyncIterator[AsyncConnection]:
    """Yield a superuser connection for administrative operations and schema provisioning."""
    admin_user = os.getenv("DB_ADMIN_USER", "postgres")
    admin_pwd = os.getenv("DB_ADMIN_PASSWORD", "secret")
    db_name = os.getenv("DB_NAME", "b2b_lead_qualifier")
    conn_str = f"postgresql://{admin_user}:{admin_pwd}@127.0.0.1:5432/{db_name}"
    async with await AsyncConnection.connect(conn_str) as conn:
        yield conn


@pytest_asyncio.fixture(autouse=True)
async def setup_test_tenants(db_admin: AsyncConnection) -> None:
    """Ensure test tenants and baseline rule sets are provisioned idempotently before each test."""
    async with db_admin.cursor() as cur:
        await cur.execute(
            "SELECT core.provision_tenant(%s, %s, %s)",
            (TENANT_DEMO, "Acme Corp (Demo)", "tenant_demo"),
        )
        await cur.execute(
            "SELECT core.provision_tenant(%s, %s, %s)",
            (TENANT_INVASOR, "Tenant Invasor", "tenant_invasor"),
        )
        await cur.execute(
            """
            INSERT INTO tenant_demo.scoring_rule_sets (
                tenant_id, version, rules, qualification_threshold, is_active
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
                50, true
            ) ON CONFLICT (tenant_id, version) DO NOTHING
            """,
            (TENANT_DEMO,),
        )
        await db_admin.commit()


@pytest_asyncio.fixture
async def db_app() -> AsyncIterator[AsyncConnection]:
    """Yield an unprivileged application connection without BYPASSRLS."""
    app_user = os.getenv("DB_USER", "app_user")
    app_pwd = os.getenv("DB_PASSWORD", "secret")
    db_name = os.getenv("DB_NAME", "b2b_lead_qualifier")
    conn_str = f"postgresql://{app_user}:{app_pwd}@127.0.0.1:5432/{db_name}"
    async with await AsyncConnection.connect(conn_str) as conn:
        yield conn
