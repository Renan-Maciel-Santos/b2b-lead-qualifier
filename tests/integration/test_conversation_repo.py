"""Integration tests for conversation repository idempotency and append-only scoring results."""

import uuid

from psycopg import AsyncConnection
import pytest

from lead_qualifier.repositories.conversation_repo import ConversationRepository
from tests.conftest import TENANT_DEMO, set_test_tenant_context

pytestmark = pytest.mark.asyncio


async def test_repository_idempotency(db_app: AsyncConnection) -> None:
    """Verify that processed message IDs are identified as duplicates on subsequent checks."""
    await set_test_tenant_context(db_app, TENANT_DEMO, "tenant_demo")

    repo = ConversationRepository(db_app)
    msg_id = f"msg_{uuid.uuid4()}"

    assert await repo.is_message_processed(msg_id) is False

    await repo.mark_message_processed(msg_id)

    assert await repo.is_message_processed(msg_id) is True


async def test_repository_save_scoring_result(db_app: AsyncConnection) -> None:
    """Verify that scoring decisions and audit trails are persisted with composite foreign keys."""
    await set_test_tenant_context(db_app, TENANT_DEMO, "tenant_demo")

    repo = ConversationRepository(db_app)

    rule_set = await repo.get_active_scoring_rule_set()
    assert rule_set is not None
    rule_set_id = rule_set["id"]

    # Generate valid E.164 phone number satisfying the database CHECK constraint
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
