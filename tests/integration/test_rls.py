"""Integration tests validating multi-tenant PostgreSQL Row-Level Security isolation."""

import pytest
from psycopg import AsyncConnection
from psycopg.errors import Error as PsycopgError

from tests.conftest import TENANT_DEMO, TENANT_INVASOR, set_test_tenant_context

pytestmark = pytest.mark.asyncio


async def test_rls_fail_closed_without_tenant(db_app: AsyncConnection) -> None:
    """Verify fail-closed security: querying without setting a tenant session returns zero rows."""
    async with db_app.cursor() as cur:
        await cur.execute("SELECT * FROM core.tenants")
        rows = await cur.fetchall()
        assert len(rows) == 0


async def test_rls_isolates_tenant_data(db_app: AsyncConnection) -> None:
    """Verify tenant isolation: queries only return records owned by the active tenant session."""
    await set_test_tenant_context(db_app, TENANT_DEMO, "tenant_demo")

    async with db_app.cursor() as cur:
        await cur.execute("SELECT id, name FROM core.tenants")
        tenants = await cur.fetchall()
        assert len(tenants) == 1
        assert str(tenants[0][0]) == TENANT_DEMO

        await cur.execute("SELECT tenant_id FROM scoring_rule_sets")
        rule_sets = await cur.fetchall()
        assert len(rule_sets) >= 1
        assert str(rule_sets[0][0]) == TENANT_DEMO


async def test_rls_prevents_cross_tenant_inserts(db_app: AsyncConnection) -> None:
    """Verify defense-in-depth: RLS prevents an active tenant from forging another tenant's ID on insert."""
    await set_test_tenant_context(db_app, TENANT_INVASOR, "tenant_invasor")

    async with db_app.cursor() as cur:
        with pytest.raises(PsycopgError):
            await cur.execute(
                "INSERT INTO processed_messages (message_id, tenant_id) VALUES (%s, %s)",
                ("msg_malicious_001", TENANT_DEMO),
            )
