"""Integration tests verifying strict database-level immutability of scoring rule sets."""

import psycopg
import pytest
from psycopg import AsyncConnection

from tests.conftest import TENANT_TEST


@pytest.mark.asyncio
async def test_rule_set_immutability_blocks_updating_rules(
    db_admin: AsyncConnection,
    _setup_test_tenants: None,
) -> None:
    """Verify that updating the rules column on an existing version raises an exception."""
    async with db_admin.cursor() as cur:
        with pytest.raises(psycopg.errors.RaiseException) as exc_info:
            await cur.execute(
                """
                UPDATE tenant_test.scoring_rule_sets
                SET rules = '[]'::jsonb
                WHERE tenant_id = %s AND version = 1
                """,
                (TENANT_TEST,),
            )
        assert "Scoring rule sets are immutable per version" in str(exc_info.value)


@pytest.mark.asyncio
async def test_rule_set_immutability_blocks_updating_required_slots(
    db_admin: AsyncConnection,
    _setup_test_tenants: None,
) -> None:
    """Verify that updating required_slots on an existing version raises an exception."""
    async with db_admin.cursor() as cur:
        with pytest.raises(psycopg.errors.RaiseException) as exc_info:
            await cur.execute(
                """
                UPDATE tenant_test.scoring_rule_sets
                SET required_slots = ARRAY['role']::text[]
                WHERE tenant_id = %s AND version = 1
                """,
                (TENANT_TEST,),
            )
        assert "Scoring rule sets are immutable per version" in str(exc_info.value)


@pytest.mark.asyncio
async def test_rule_set_immutability_blocks_updating_threshold(
    db_admin: AsyncConnection,
    _setup_test_tenants: None,
) -> None:
    """Verify that updating qualification_threshold on an existing version raises an exception."""
    async with db_admin.cursor() as cur:
        with pytest.raises(psycopg.errors.RaiseException) as exc_info:
            await cur.execute(
                """
                UPDATE tenant_test.scoring_rule_sets
                SET qualification_threshold = 90
                WHERE tenant_id = %s AND version = 1
                """,
                (TENANT_TEST,),
            )
        assert "Scoring rule sets are immutable per version" in str(exc_info.value)


@pytest.mark.asyncio
async def test_rule_set_immutability_blocks_updating_version_or_tenant(
    db_admin: AsyncConnection,
    _setup_test_tenants: None,
) -> None:
    """Verify that reassigning version or tenant_id on an existing version is rejected."""
    async with db_admin.cursor() as cur:
        with pytest.raises(psycopg.errors.RaiseException) as exc_info:
            await cur.execute(
                """
                UPDATE tenant_test.scoring_rule_sets
                SET version = 99
                WHERE tenant_id = %s AND version = 1
                """,
                (TENANT_TEST,),
            )
        assert "Scoring rule sets are immutable per version" in str(exc_info.value)


@pytest.mark.asyncio
async def test_rule_set_allows_updating_is_active(
    db_admin: AsyncConnection,
    _setup_test_tenants: None,
) -> None:
    """Verify that toggling is_active is permitted to activate or deactivate versions."""
    async with db_admin.cursor() as cur:
        # Deactivating version 1 is permitted
        await cur.execute(
            """
            UPDATE tenant_test.scoring_rule_sets
            SET is_active = false
            WHERE tenant_id = %s AND version = 1
            """,
            (TENANT_TEST,),
        )
        await cur.execute(
            """
            SELECT is_active
            FROM tenant_test.scoring_rule_sets
            WHERE tenant_id = %s AND version = 1
            """,
            (TENANT_TEST,),
        )
        row = await cur.fetchone()
        assert row is not None
        assert row[0] is False


@pytest.mark.asyncio
async def test_rule_set_allows_inserting_new_version(
    db_admin: AsyncConnection,
    _setup_test_tenants: None,
) -> None:
    """Verify that a brand new version (version 2) can be inserted cleanly."""
    async with db_admin.cursor() as cur:
        # Clean up any residual version 2 from previous runs
        await cur.execute(
            """
            DELETE FROM tenant_test.scoring_rule_sets
            WHERE tenant_id = %s AND version = 2
            """,
            (TENANT_TEST,),
        )
        # First deactivate version 1 because of the partial unique index on is_active
        await cur.execute(
            """
            UPDATE tenant_test.scoring_rule_sets
            SET is_active = false
            WHERE tenant_id = %s AND version = 1
            """,
            (TENANT_TEST,),
        )
        # Insert version 2 with updated rules and threshold
        await cur.execute(
            """
            INSERT INTO tenant_test.scoring_rule_sets (
                tenant_id, version, rules, required_slots, qualification_threshold, is_active
            ) VALUES (
                %s, 2,
                '[{"type": "exact_match", "field": "role", "value": "CEO", "points": 60}]'::jsonb,
                ARRAY['role']::text[],
                60, true
            )
            """,
            (TENANT_TEST,),
        )
        await cur.execute(
            """
            SELECT version, qualification_threshold, is_active
            FROM tenant_test.scoring_rule_sets
            WHERE tenant_id = %s AND version = 2
            """,
            (TENANT_TEST,),
        )
        row = await cur.fetchone()
        assert row is not None
        assert row[0] == 2
        assert row[1] == 60
        assert row[2] is True
