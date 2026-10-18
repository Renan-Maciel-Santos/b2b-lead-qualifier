"""Integration tests for multi-turn conversational qualification flow and atomic idempotency."""

import asyncio
import os
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from httpx import AsyncClient
from psycopg_pool import AsyncConnectionPool

from lead_qualifier.api.dependencies import create_tenant_uow_factory
from lead_qualifier.api.main import app
from lead_qualifier.core.database import tenant_transaction
from lead_qualifier.core.enums import ConversationState, RevenueTier
from lead_qualifier.core.exceptions import LLMExtractionError
from lead_qualifier.core.messages import (
    ASK_REVENUE_REPLY,
    QUALIFIED_REPLY,
)
from lead_qualifier.core.schemas.conversation import TurnRequest
from lead_qualifier.core.schemas.slots import LeadSlots
from lead_qualifier.core.tenant import TenantContext
from lead_qualifier.integrations.llm.openai_adapter import OpenAIAdapter
from lead_qualifier.repositories.conversation_repo import ConversationRepository
from lead_qualifier.services.state_machine import StateMachineService
from tests.conftest import (
    API_KEY_TEST,
    TENANT_TEST,
)

pytestmark = pytest.mark.asyncio


async def test_multi_turn_conversation_accumulates_slots_and_qualifies(
    db_pool: AsyncConnectionPool,
) -> None:
    """Verify that a two-turn conversation correctly accumulates slots and completes qualification."""
    tenant_ctx = TenantContext(UUID(TENANT_TEST), "tenant_test")
    phone = f"+55119{uuid.uuid4().int % 100000000:08d}"

    # Mock OpenAI adapter to test deterministic domain extraction across turns
    mock_adapter = OpenAIAdapter(api_key="mock_key")

    # Turn 1: Lead provides role only
    mock_adapter.extract_slots = AsyncMock(return_value=LeadSlots(role="CEO"))  # type: ignore[method-assign]
    service = StateMachineService(
        uow_factory=create_tenant_uow_factory(db_pool, tenant_ctx),
        llm_adapter=mock_adapter,
        idempotency_timeout=60,
    )

    turn1_request = TurnRequest(
        message_id=f"msg_turn1_{uuid.uuid4()}",
        phone_number=phone,
        user_message="Ola, sou CEO da empresa.",
    )
    turn1_response = await service.process_turn(turn1_request)

    assert turn1_response.current_state == ConversationState.AWAITING_REVENUE
    assert turn1_response.reply_message == ASK_REVENUE_REPLY
    assert turn1_response.is_finished is False

    # Verify database state after Turn 1
    async with tenant_transaction(db_pool, tenant_ctx) as conn:
        repo = ConversationRepository(conn)
        state1, slots1 = await repo.get_or_create_conversation_state(phone)
        assert state1 == ConversationState.AWAITING_REVENUE
        assert slots1.get("role") == "CEO"
        assert "revenue_tier" not in slots1

    mock_adapter.extract_slots = AsyncMock(  # type: ignore[method-assign]
        return_value=LeadSlots(revenue_tier=RevenueTier.FROM_2M_TO_10M)
    )

    turn2_request = TurnRequest(
        message_id=f"msg_turn2_{uuid.uuid4()}",
        phone_number=phone,
        user_message="Nosso faturamento e de 5 milhoes ao ano.",
    )
    turn2_response = await service.process_turn(turn2_request)

    # Turn 2 should merge slots (CEO + 5 milhoes ao ano), evaluate score, and qualify
    assert turn2_response.current_state == ConversationState.QUALIFIED
    assert turn2_response.reply_message == QUALIFIED_REPLY
    assert turn2_response.is_finished is True

    # Verify final accumulated state in database
    async with tenant_transaction(db_pool, tenant_ctx) as conn:
        repo = ConversationRepository(conn)
        state2, slots2 = await repo.get_or_create_conversation_state(phone)
        assert state2 == ConversationState.QUALIFIED
        assert slots2.get("role") == "CEO"
        assert slots2.get("revenue_tier") == "2m_to_10m"


async def test_duplicate_message_id_atomic_idempotency_via_service(
    db_pool: AsyncConnectionPool,
) -> None:
    """Verify that submitting the identical message_id twice returns DUPLICATE_IGNORED on the second turn."""
    tenant_ctx = TenantContext(UUID(TENANT_TEST), "tenant_test")
    phone = f"+55119{uuid.uuid4().int % 100000000:08d}"
    duplicate_message_id = f"msg_dup_{uuid.uuid4()}"

    mock_adapter = OpenAIAdapter(api_key="mock_key")
    mock_adapter.extract_slots = AsyncMock(return_value=LeadSlots(role="Diretor"))  # type: ignore[method-assign]
    service = StateMachineService(
        uow_factory=create_tenant_uow_factory(db_pool, tenant_ctx),
        llm_adapter=mock_adapter,
        idempotency_timeout=60,
    )

    request = TurnRequest(
        message_id=duplicate_message_id,
        phone_number=phone,
        user_message="Sou Diretor de tecnologia",
    )

    # First delivery: processed
    first_response = await service.process_turn(request)
    assert first_response.current_state == ConversationState.AWAITING_REVENUE
    assert first_response.is_finished is False

    # Second delivery: discarded due to atomic idempotency check
    second_response = await service.process_turn(request)
    assert second_response.current_state == ConversationState.DUPLICATE_IGNORED
    assert second_response.reply_message == ""
    assert second_response.is_finished is False


async def test_duplicate_message_id_via_http_endpoint(
    api_client: AsyncClient,
) -> None:
    """Verify idempotency enforcement over HTTP POST /v1/conversations/turns."""
    phone = "+5511999990001"
    message_id = f"http_msg_{uuid.uuid4()}"
    headers = {"Authorization": f"Bearer {API_KEY_TEST}"}

    payload = {
        "message_id": message_id,
        "phone_number": phone,
        "user_message": "Ola",
    }

    # First attempt: accepted
    res1 = await api_client.post("/v1/conversations/turns", json=payload, headers=headers)
    assert res1.status_code == 200

    # Second attempt: ignored
    res2 = await api_client.post("/v1/conversations/turns", json=payload, headers=headers)
    assert res2.status_code == 200
    assert res2.json()["current_state"] == "DUPLICATE_IGNORED"
    assert res2.json()["reply_message"] == ""


async def test_llm_call_does_not_hold_conversation_lock(
    db_pool: AsyncConnectionPool,
) -> None:
    """Verify with real PostgreSQL that the LLM extraction does not hold a row lock on conversation_states."""
    import asyncio
    import os

    tenant_ctx = TenantContext(UUID(TENANT_TEST), "tenant_test")
    phone = f"+55119{uuid.uuid4().int % 100000000:08d}"

    # Pre-create the conversation state row
    async with tenant_transaction(db_pool, tenant_ctx) as conn:
        repo = ConversationRepository(conn)
        await repo.get_or_create_conversation_state(phone)

    llm_thinking = asyncio.Event()
    llm_can_proceed = asyncio.Event()

    async def slow_extract_slots(_message: str) -> LeadSlots:
        llm_thinking.set()
        await llm_can_proceed.wait()
        return LeadSlots(revenue_tier=RevenueTier.FROM_2M_TO_10M)

    mock_adapter = OpenAIAdapter(api_key="mock_key")
    mock_adapter.extract_slots = AsyncMock(side_effect=slow_extract_slots)  # type: ignore[method-assign]
    service = StateMachineService(
        uow_factory=create_tenant_uow_factory(db_pool, tenant_ctx),
        llm_adapter=mock_adapter,
        idempotency_timeout=60,
    )

    turn_task = asyncio.create_task(
        service.process_turn(
            TurnRequest(
                message_id=f"msg_lock_{uuid.uuid4()}",
                phone_number=phone,
                user_message="Faturamos 5 milhoes ao ano.",
            )
        )
    )

    # Wait until LLM is actively extracting slots
    await asyncio.wait_for(llm_thinking.wait(), timeout=5.0)

    # Open a SECOND concurrent database pool to test row lock availability
    app_user = os.getenv("DB_USER", "app_user")
    app_pwd = os.getenv("DB_PASSWORD", "secret")
    db_name = os.getenv("DB_NAME", "b2b_lead_qualifier")
    conn_str = f"postgresql://{app_user}:{app_pwd}@127.0.0.1:5432/{db_name}?connect_timeout=3"

    pool2 = AsyncConnectionPool(conninfo=conn_str, min_size=1, max_size=1, open=False)
    await pool2.open()
    try:
        async with (
            tenant_transaction(pool2, tenant_ctx) as scoped_conn,
            scoped_conn.cursor() as cur,
        ):
            # If StateMachine held an active lock during LLM execution, NOWAIT would raise LockNotAvailable
            await cur.execute(
                "SELECT current_state FROM conversation_states WHERE phone_number = %s FOR UPDATE NOWAIT",
                (phone,),
            )
            row = await cur.fetchone()
            assert row is not None
    finally:
        await pool2.close()

    # Release LLM event and confirm turn finishes normally
    llm_can_proceed.set()
    response = await asyncio.wait_for(turn_task, timeout=5.0)
    assert response is not None
    assert response.current_state in (
        ConversationState.QUALIFIED,
        ConversationState.AWAITING_ROLE,
        ConversationState.AWAITING_REVENUE,
    )


async def test_connection_returned_to_pool_during_llm_call(
    _setup_test_tenants: None,
) -> None:
    """Prove that database connection is returned to the pool during LLM extraction.

    Uses a pool with max_size=1. While the fake LLM is blocked on an asyncio.Event,
    a second unit of work attempts to acquire a connection from the same pool.
    Because the connection was returned before calling LLM, the second unit of work
    acquires the single pool connection immediately without timing out.
    """
    tenant_ctx = TenantContext(UUID(TENANT_TEST), "tenant_test")
    phone = f"+55119{uuid.uuid4().int % 100000000:08d}"

    app_user = os.getenv("DB_USER", "app_user")
    app_pwd = os.getenv("DB_PASSWORD", "secret")
    db_name = os.getenv("DB_NAME", "b2b_lead_qualifier")
    conn_str = f"postgresql://{app_user}:{app_pwd}@127.0.0.1:5432/{db_name}?connect_timeout=3"

    pool_single = AsyncConnectionPool(conninfo=conn_str, min_size=1, max_size=1, open=False)
    await pool_single.open()

    llm_thinking = asyncio.Event()
    llm_can_proceed = asyncio.Event()

    async def slow_extract_slots(*_args: Any, **_kwargs: Any) -> LeadSlots:
        llm_thinking.set()
        await llm_can_proceed.wait()
        return LeadSlots(revenue_tier=RevenueTier.FROM_2M_TO_10M)

    try:
        mock_adapter = OpenAIAdapter(api_key="mock_key")
        mock_adapter.extract_slots = AsyncMock(side_effect=slow_extract_slots)  # type: ignore[method-assign]
        service = StateMachineService(
            uow_factory=create_tenant_uow_factory(pool_single, tenant_ctx),
            llm_adapter=mock_adapter,
            idempotency_timeout=60,
        )

        turn_task = asyncio.create_task(
            service.process_turn(
                TurnRequest(
                    message_id=f"msg_pool1_{uuid.uuid4()}",
                    phone_number=phone,
                    user_message="Faturamos 5 milhoes ao ano.",
                )
            )
        )

        # Wait until LLM is actively extracting slots
        await asyncio.wait_for(llm_thinking.wait(), timeout=5.0)

        # Attempt to acquire a connection via a second unit of work in the same pool with max_size=1
        async def acquire_second_uow() -> bool:
            async with (
                tenant_transaction(pool_single, tenant_ctx) as conn,
                conn.cursor() as cur,
            ):
                await cur.execute("SELECT 1")
                res = await cur.fetchone()
                return bool(res == (1,))

        # If StateMachine held the connection during LLM, this timeout would fail
        acquired = await asyncio.wait_for(acquire_second_uow(), timeout=2.0)
        assert acquired is True

        # Release LLM event and confirm turn finishes normally
        llm_can_proceed.set()
        response = await asyncio.wait_for(turn_task, timeout=5.0)
        assert response is not None
    finally:
        await pool_single.close()


async def test_ceo_knockout_on_revenue_disqualifies_immediately(
    db_pool: AsyncConnectionPool,
) -> None:
    """Prove that knockout on revenue_tier is evaluated even when role alone awards high score (e.g. CEO).

    Turn 1: Lead provides role="CEO" (50 pts, but revenue_tier is still required).
    State must transition to AWAITING_REVENUE, not QUALIFIED.
    Turn 2: Lead provides revenue_tier="below_500k" (knockout condition).
    State must immediately transition to DISQUALIFIED, terminating dialogue.
    """
    tenant_ctx = TenantContext(UUID(TENANT_TEST), "tenant_test")
    phone = f"+55119{uuid.uuid4().int % 100000000:08d}"

    mock_adapter = OpenAIAdapter(api_key="mock_key")
    service = StateMachineService(
        uow_factory=create_tenant_uow_factory(db_pool, tenant_ctx),
        llm_adapter=mock_adapter,
        idempotency_timeout=60,
    )

    # Turn 1: Lead is CEO -> requires revenue before qualification decision
    mock_adapter.extract_slots = AsyncMock(return_value=LeadSlots(role="CEO"))  # type: ignore[method-assign]
    turn1_response = await service.process_turn(
        TurnRequest(
            message_id=f"msg_ko_turn1_{uuid.uuid4()}",
            phone_number=phone,
            user_message="Ola, sou o CEO.",
        )
    )
    assert turn1_response.current_state == ConversationState.AWAITING_REVENUE
    assert turn1_response.is_finished is False

    mock_adapter.extract_slots = AsyncMock(  # type: ignore[method-assign]
        return_value=LeadSlots(revenue_tier=RevenueTier.BELOW_500K)
    )
    turn2_response = await service.process_turn(
        TurnRequest(
            message_id=f"msg_ko_turn2_{uuid.uuid4()}",
            phone_number=phone,
            user_message="Faturamos abaixo de 50 mil reais.",
        )
    )
    assert turn2_response.current_state == ConversationState.DISQUALIFIED
    assert turn2_response.is_finished is True


async def test_first_turn_knockout_terminates_immediately(
    db_pool: AsyncConnectionPool,
) -> None:
    """Verify that a knockout triggered on the first turn terminates immediately without asking further slots."""
    tenant_ctx = TenantContext(UUID(TENANT_TEST), "tenant_test")
    phone = f"+55119{uuid.uuid4().int % 100000000:08d}"

    mock_adapter = OpenAIAdapter(api_key="mock_key")
    mock_adapter.extract_slots = AsyncMock(return_value=LeadSlots(role="estagiario"))  # type: ignore[method-assign]
    service = StateMachineService(
        uow_factory=create_tenant_uow_factory(db_pool, tenant_ctx),
        llm_adapter=mock_adapter,
        idempotency_timeout=60,
    )

    response = await service.process_turn(
        TurnRequest(
            message_id=f"msg_first_ko_{uuid.uuid4()}",
            phone_number=phone,
            user_message="Sou estagiario na empresa.",
        )
    )
    assert response.current_state == ConversationState.DISQUALIFIED
    assert response.is_finished is True


async def test_llm_extraction_failure_marks_message_failed_and_returns_503(
    api_client: AsyncClient,
    db_pool: AsyncConnectionPool,
) -> None:
    """Verify that when LLM extraction fails, the message is marked failed, no state is updated, and HTTP 503 is returned."""
    phone = f"+55119{uuid.uuid4().int % 100000000:08d}"
    message_id = f"http_msg_err_{uuid.uuid4()}"
    headers = {"Authorization": f"Bearer {API_KEY_TEST}"}

    failing_adapter = AsyncMock()
    failing_adapter.extract_slots = AsyncMock(
        side_effect=LLMExtractionError("Outbound OpenAI connection timeout")
    )

    with patch.object(app.state, "llm_adapter", failing_adapter):
        payload = {
            "message_id": message_id,
            "phone_number": phone,
            "user_message": "Ola, sou CEO",
        }
        response = await api_client.post(
            "/v1/conversations/turns",
            json=payload,
            headers=headers,
        )

        assert response.status_code == 503
        assert (
            response.json()["detail"] == "LLM extraction service unavailable. Please retry later."
        )

    # Verify database state under isolation
    tenant_ctx = TenantContext(UUID(TENANT_TEST), "tenant_test")
    async with tenant_transaction(db_pool, tenant_ctx) as conn, conn.cursor() as cur:
        # Message must be marked failed
        await cur.execute(
            "SELECT status FROM tenant_test.processed_messages WHERE message_id = %s",
            (message_id,),
        )
        row = await cur.fetchone()
        assert row is not None
        assert row[0] == "failed"

        # Conversation state must NOT have been created or modified
        await cur.execute(
            "SELECT current_state FROM tenant_test.conversation_states WHERE phone_number = %s",
            (phone,),
        )
        state_row = await cur.fetchone()
        assert state_row is None


async def test_failed_message_reprocessed_successfully_after_timeout(
    api_client: AsyncClient,
    db_pool: AsyncConnectionPool,
) -> None:
    """Verify that a failed message can be re-delivered and successfully processed after timeout expiration."""
    phone = f"+55119{uuid.uuid4().int % 100000000:08d}"
    message_id = f"http_msg_retry_{uuid.uuid4()}"
    headers = {"Authorization": f"Bearer {API_KEY_TEST}"}

    # Step 1: Initial failure
    failing_adapter = AsyncMock()
    failing_adapter.extract_slots = AsyncMock(
        side_effect=LLMExtractionError("Outbound OpenAI connection timeout")
    )
    with patch.object(app.state, "llm_adapter", failing_adapter):
        payload = {
            "message_id": message_id,
            "phone_number": phone,
            "user_message": "Ola, sou CEO da empresa",
        }
        res1 = await api_client.post("/v1/conversations/turns", json=payload, headers=headers)
        assert res1.status_code == 503

    # Step 2: Simulate timeout expiration (70 seconds in the past)
    tenant_ctx = TenantContext(UUID(TENANT_TEST), "tenant_test")
    async with tenant_transaction(db_pool, tenant_ctx) as conn, conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE tenant_test.processed_messages
            SET updated_at = NOW() - INTERVAL '70 seconds'
            WHERE message_id = %s
            """,
            (message_id,),
        )

    # Step 3: Re-submit the exact same message_id with working LLM adapter
    successful_adapter = AsyncMock()
    successful_adapter.extract_slots = AsyncMock(return_value=LeadSlots(role="CEO"))
    with patch.object(app.state, "llm_adapter", successful_adapter):
        res2 = await api_client.post("/v1/conversations/turns", json=payload, headers=headers)
        assert res2.status_code == 200
        data = res2.json()
        assert data["current_state"] == "AWAITING_REVENUE"
        assert data["is_finished"] is False

    # Step 4: Verify message is now done and state is persisted
    async with tenant_transaction(db_pool, tenant_ctx) as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT status FROM tenant_test.processed_messages WHERE message_id = %s",
            (message_id,),
        )
        row = await cur.fetchone()
        assert row is not None
        assert row[0] == "done"

        await cur.execute(
            "SELECT current_state, accumulated_slots FROM tenant_test.conversation_states WHERE phone_number = %s",
            (phone,),
        )
        state_row = await cur.fetchone()
        assert state_row is not None
        assert state_row[0] == "AWAITING_REVENUE"
        assert state_row[1] == {"role": "CEO"}
