"""Integration tests for conversation repository idempotency, state persistence, and scoring results."""

import uuid

import pytest
from psycopg_pool import AsyncConnectionPool

from lead_qualifier.repositories.conversation_repo import ConversationRepository
from tests.conftest import TENANT_TEST, set_test_tenant_context

pytestmark = pytest.mark.asyncio


async def test_repository_atomic_idempotency(db_pool: AsyncConnectionPool) -> None:
    """Verify race-free atomic idempotency using acquire_message_lock."""
    async with set_test_tenant_context(db_pool, TENANT_TEST, "tenant_test") as conn:
        repo = ConversationRepository(conn)
        msg_id = f"msg_{uuid.uuid4()}"

        # First acquisition succeeds (winner)
        assert await repo.acquire_message_lock(msg_id) is True

        # Duplicate acquisition fails atomically (loser) within same unit of work
        assert await repo.acquire_message_lock(msg_id) is False


async def test_repository_conversation_state_lifecycle(db_pool: AsyncConnectionPool) -> None:
    """Verify conversation state creation, row locking, and slot persistence."""
    async with set_test_tenant_context(db_pool, TENANT_TEST, "tenant_test") as conn:
        repo = ConversationRepository(conn)
        phone = f"+55119{uuid.uuid4().int % 100000000:08d}"

        # Initial state initialization
        state, slots = await repo.get_or_create_conversation_state(phone)
        assert state == "INITIAL"
        assert slots == {}

        # State transition and slot accumulation
        accumulated = {"role": "CEO", "name": "Alice"}
        await repo.save_conversation_state(
            phone_number=phone,
            current_state="AWAITING_REVENUE",
            accumulated_slots=accumulated,
        )

        # Subsequent retrieval retains accumulated state
        state2, slots2 = await repo.get_or_create_conversation_state(phone)
        assert state2 == "AWAITING_REVENUE"
        assert slots2 == accumulated


async def test_repository_save_scoring_result(db_pool: AsyncConnectionPool) -> None:
    """Verify that scoring decisions and audit trails are persisted with composite foreign keys."""
    phone = f"+55119{uuid.uuid4().int % 100000000:08d}"
    score = 100
    qualified = True
    audit = [
        {"rule_type": "exact_match", "field": "role", "value": "CEO", "points": 50},
        {"rule_type": "exact_match", "field": "revenue_tier", "value": "above_10m", "points": 50},
    ]

    async with set_test_tenant_context(db_pool, TENANT_TEST, "tenant_test") as conn:
        repo = ConversationRepository(conn)
        rule_set = await repo.get_active_scoring_rule_set()
        assert rule_set is not None
        rule_set_id = rule_set["id"]

        await repo.save_scoring_result(
            phone_number=phone,
            rule_set_id=rule_set_id,
            final_score=score,
            is_qualified=qualified,
            audit_trail=audit,
        )

    async with (
        set_test_tenant_context(db_pool, TENANT_TEST, "tenant_test") as conn,
        conn.cursor() as cur,
    ):
        await cur.execute(
            """
            SELECT phone_number, rule_set_id, final_score, is_qualified, audit_trail
            FROM scoring_results
            WHERE phone_number = %s
            """,
            (phone,),
        )
        row = await cur.fetchone()

        assert row is not None
        assert row[0] == phone
        assert str(row[1]) == str(rule_set_id)
        assert row[2] == score
        assert row[3] is True
        assert len(row[4]) == 2


async def test_stuck_message_reprocessing_after_timeout(
    db_pool: AsyncConnectionPool,
) -> None:
    """Verify that stuck processing messages can be reprocessed after timeout, active processing is blocked, and failed messages can be retried."""
    msg_id = f"msg_timeout_{uuid.uuid4()}"

    # 1. Message in processing within the timeout window remains blocked (DUPLICATE_IGNORED)
    async with set_test_tenant_context(db_pool, TENANT_TEST, "tenant_test") as conn1:
        repo1 = ConversationRepository(conn1)
        assert await repo1.acquire_message_lock(msg_id, timeout_seconds=10) is True

    async with set_test_tenant_context(db_pool, TENANT_TEST, "tenant_test") as conn2:
        repo2 = ConversationRepository(conn2)
        assert await repo2.acquire_message_lock(msg_id, timeout_seconds=10) is False

    # 2. Stuck message with updated_at older than timeout can be reprocessed
    async with (
        set_test_tenant_context(db_pool, TENANT_TEST, "tenant_test") as conn3,
        conn3.cursor() as cur,
    ):
        await cur.execute(
            """
            UPDATE processed_messages
            SET updated_at = now() - interval '30 seconds'
            WHERE message_id = %s
            """,
            (msg_id,),
        )

    async with set_test_tenant_context(db_pool, TENANT_TEST, "tenant_test") as conn4:
        repo4 = ConversationRepository(conn4)
        assert await repo4.acquire_message_lock(msg_id, timeout_seconds=10) is True

    # 3. Message in failed status can also be reprocessed immediately
    async with set_test_tenant_context(db_pool, TENANT_TEST, "tenant_test") as conn5:
        repo5 = ConversationRepository(conn5)
        await repo5.mark_message_failed(msg_id)

    async with set_test_tenant_context(db_pool, TENANT_TEST, "tenant_test") as conn6:
        repo6 = ConversationRepository(conn6)
        assert await repo6.acquire_message_lock(msg_id, timeout_seconds=10) is True
