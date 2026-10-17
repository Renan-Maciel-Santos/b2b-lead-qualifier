"""Integration tests for conversation repository idempotency, state persistence, and scoring results."""

import uuid

import pytest
from psycopg import AsyncConnection

from lead_qualifier.repositories.conversation_repo import ConversationRepository
from tests.conftest import TENANT_DEMO, set_test_tenant_context

pytestmark = pytest.mark.asyncio


async def test_repository_atomic_idempotency(db_app: AsyncConnection) -> None:
    """Verify race-free atomic idempotency using acquire_message_lock."""
    await set_test_tenant_context(db_app, TENANT_DEMO, "tenant_demo")

    repo = ConversationRepository(db_app)
    msg_id = f"msg_{uuid.uuid4()}"

    # First acquisition succeeds (winner)
    assert await repo.acquire_message_lock(msg_id) is True

    # Duplicate acquisition fails atomically (loser)
    assert await repo.acquire_message_lock(msg_id) is False


async def test_repository_conversation_state_lifecycle(db_app: AsyncConnection) -> None:
    """Verify conversation state creation, row locking, and slot persistence."""
    await set_test_tenant_context(db_app, TENANT_DEMO, "tenant_demo")

    repo = ConversationRepository(db_app)
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


async def test_repository_save_scoring_result(db_app: AsyncConnection) -> None:
    """Verify that scoring decisions and audit trails are persisted with composite foreign keys."""
    await set_test_tenant_context(db_app, TENANT_DEMO, "tenant_demo")

    repo = ConversationRepository(db_app)

    rule_set = await repo.get_active_scoring_rule_set()
    assert rule_set is not None
    rule_set_id = rule_set["id"]

    phone = f"+55119{uuid.uuid4().int % 100000000:08d}"
    score = 100
    qualified = True
    audit = ["Awarded 50 pts for CEO role", "Awarded 50 pts for revenue tier"]

    await repo.save_scoring_result(
        phone_number=phone,
        rule_set_id=rule_set_id,
        final_score=score,
        is_qualified=qualified,
        audit_trail=audit,
    )

    async with db_app.cursor() as cur:
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
    db_app: AsyncConnection,
) -> None:
    """Verify that stuck processing messages can be reprocessed after timeout, active processing is blocked, and failed messages can be retried."""
    await set_test_tenant_context(db_app, TENANT_DEMO, "tenant_demo")
    repo = ConversationRepository(db_app)
    msg_id = f"msg_timeout_{uuid.uuid4()}"

    # 1. Message in processing within the timeout window remains blocked (DUPLICATE_IGNORED)
    assert await repo.acquire_message_lock(msg_id, timeout_seconds=10) is True
    await set_test_tenant_context(db_app, TENANT_DEMO, "tenant_demo")
    assert await repo.acquire_message_lock(msg_id, timeout_seconds=10) is False

    # 2. Stuck message with updated_at older than timeout can be reprocessed
    await set_test_tenant_context(db_app, TENANT_DEMO, "tenant_demo")
    async with db_app.cursor() as cur:
        await cur.execute(
            """
            UPDATE processed_messages
            SET updated_at = now() - interval '30 seconds'
            WHERE message_id = %s
            """,
            (msg_id,),
        )
    await db_app.commit()

    await set_test_tenant_context(db_app, TENANT_DEMO, "tenant_demo")
    assert await repo.acquire_message_lock(msg_id, timeout_seconds=10) is True

    # 3. Message in failed status can also be reprocessed immediately
    await set_test_tenant_context(db_app, TENANT_DEMO, "tenant_demo")
    await repo.mark_message_failed(msg_id)
    await set_test_tenant_context(db_app, TENANT_DEMO, "tenant_demo")
    assert await repo.acquire_message_lock(msg_id, timeout_seconds=10) is True
