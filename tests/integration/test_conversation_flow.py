"""Integration tests for multi-turn conversational qualification flow and atomic idempotency."""

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from psycopg import AsyncConnection

from lead_qualifier.core.enums import ConversationState
from lead_qualifier.core.messages import (
    ASK_REVENUE_REPLY,
    QUALIFIED_REPLY,
)
from lead_qualifier.core.schemas.conversation import TurnRequest
from lead_qualifier.core.schemas.slots import LeadSlots
from lead_qualifier.integrations.llm.openai_adapter import OpenAIAdapter
from lead_qualifier.repositories.conversation_repo import ConversationRepository
from lead_qualifier.services.state_machine import StateMachineService
from tests.conftest import (
    API_KEY_DEMO,
    TENANT_DEMO,
    set_test_tenant_context,
)

pytestmark = pytest.mark.asyncio


async def test_multi_turn_conversation_accumulates_slots_and_qualifies(
    db_app: AsyncConnection,
) -> None:
    """Verify that a two-turn conversation correctly accumulates slots and completes qualification."""
    await set_test_tenant_context(db_app, TENANT_DEMO, "tenant_demo")

    repo = ConversationRepository(db_app)
    phone = f"+55119{uuid.uuid4().int % 100000000:08d}"

    # Mock OpenAI adapter to test deterministic domain extraction across turns
    mock_adapter = OpenAIAdapter(api_key="mock_key")

    # Turn 1: Lead provides role only
    mock_adapter.extract_slots = AsyncMock(return_value=LeadSlots(role="CEO"))  # type: ignore[method-assign]
    service = StateMachineService(repo=repo, llm_adapter=mock_adapter)

    turn1_request = TurnRequest(
        message_id=f"msg_turn1_{uuid.uuid4()}",
        phone_number=phone,
        user_message="Ola, sou CEO da empresa.",
    )
    turn1_response = await service.process_turn(turn1_request)
    await repo.conn.commit()

    assert turn1_response.current_state == ConversationState.AWAITING_REVENUE
    assert turn1_response.reply_message == ASK_REVENUE_REPLY
    assert turn1_response.is_finished is False

    # Verify database state after Turn 1
    state1, slots1 = await repo.get_or_create_conversation_state(phone)
    assert state1 == ConversationState.AWAITING_REVENUE
    assert slots1.get("role") == "CEO"
    assert "revenue" not in slots1

    # Turn 2: Lead provides revenue
    mock_adapter.extract_slots = AsyncMock(  # type: ignore[method-assign]
        return_value=LeadSlots(revenue="5 milhoes ao ano")
    )

    turn2_request = TurnRequest(
        message_id=f"msg_turn2_{uuid.uuid4()}",
        phone_number=phone,
        user_message="Nosso faturamento e de 5 milhoes ao ano.",
    )
    turn2_response = await service.process_turn(turn2_request)
    await repo.conn.commit()

    # Turn 2 should merge slots (CEO + 5 milhoes ao ano), evaluate score, and qualify
    assert turn2_response.current_state == ConversationState.QUALIFIED
    assert turn2_response.reply_message == QUALIFIED_REPLY
    assert turn2_response.is_finished is True

    # Verify final accumulated state in database
    state2, slots2 = await repo.get_or_create_conversation_state(phone)
    assert state2 == ConversationState.QUALIFIED
    assert slots2.get("role") == "CEO"
    assert slots2.get("revenue") == "5 milhoes ao ano"


async def test_duplicate_message_id_atomic_idempotency_via_service(
    db_app: AsyncConnection,
) -> None:
    """Verify that submitting the identical message_id twice returns DUPLICATE_IGNORED on the second turn."""
    await set_test_tenant_context(db_app, TENANT_DEMO, "tenant_demo")

    repo = ConversationRepository(db_app)
    phone = f"+55119{uuid.uuid4().int % 100000000:08d}"
    duplicate_message_id = f"msg_dup_{uuid.uuid4()}"

    mock_adapter = OpenAIAdapter(api_key="mock_key")
    mock_adapter.extract_slots = AsyncMock(return_value=LeadSlots(role="Diretor"))  # type: ignore[method-assign]
    service = StateMachineService(repo=repo, llm_adapter=mock_adapter)

    request = TurnRequest(
        message_id=duplicate_message_id,
        phone_number=phone,
        user_message="Sou Diretor de tecnologia",
    )

    # First delivery: processed
    first_response = await service.process_turn(request)
    await repo.conn.commit()
    assert first_response.current_state == ConversationState.AWAITING_REVENUE
    assert first_response.is_finished is False

    # Second delivery: discarded due to atomic idempotency check
    second_response = await service.process_turn(request)
    await repo.conn.commit()
    assert second_response.current_state == ConversationState.DUPLICATE_IGNORED
    assert second_response.reply_message == ""
    assert second_response.is_finished is False


async def test_duplicate_message_id_via_http_endpoint(
    api_client: AsyncClient,
) -> None:
    """Verify idempotency enforcement over HTTP POST /v1/conversations/turns."""
    phone = "+5511999990001"
    message_id = f"http_msg_{uuid.uuid4()}"
    headers = {"Authorization": f"Bearer {API_KEY_DEMO}"}

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
    db_app: AsyncConnection,
) -> None:
    """Verify with real PostgreSQL that the LLM extraction does not hold a row lock on conversation_states."""
    import asyncio
    import os

    await set_test_tenant_context(db_app, TENANT_DEMO, "tenant_demo")
    repo = ConversationRepository(db_app)
    phone = f"+55119{uuid.uuid4().int % 100000000:08d}"

    # Pre-create the conversation state row
    await repo.get_or_create_conversation_state(phone)
    await db_app.commit()

    llm_thinking = asyncio.Event()
    llm_can_proceed = asyncio.Event()

    async def slow_extract_slots(_message: str) -> LeadSlots:
        llm_thinking.set()
        await llm_can_proceed.wait()
        return LeadSlots(revenue="5 milhoes ao ano")

    mock_adapter = OpenAIAdapter(api_key="mock_key")
    mock_adapter.extract_slots = AsyncMock(side_effect=slow_extract_slots)  # type: ignore[method-assign]
    service = StateMachineService(repo=repo, llm_adapter=mock_adapter)

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

    # Open a SECOND concurrent database connection to test row lock availability
    app_user = os.getenv("DB_USER", "app_user")
    app_pwd = os.getenv("DB_PASSWORD", "secret")
    db_name = os.getenv("DB_NAME", "b2b_lead_qualifier")
    conn_str = f"postgresql://{app_user}:{app_pwd}@127.0.0.1:5432/{db_name}?connect_timeout=3"

    async with await AsyncConnection.connect(conn_str) as conn2:
        await set_test_tenant_context(conn2, TENANT_DEMO, "tenant_demo")
        # If StateMachine held an active lock during LLM execution, NOWAIT would raise LockNotAvailable
        async with conn2.cursor() as cur:
            await cur.execute(
                "SELECT current_state FROM conversation_states WHERE phone_number = %s FOR UPDATE NOWAIT",
                (phone,),
            )
            row = await cur.fetchone()
            assert row is not None
        await conn2.rollback()

    # Release LLM event and confirm turn finishes normally
    llm_can_proceed.set()
    response = await asyncio.wait_for(turn_task, timeout=5.0)
    assert response is not None
    assert response.current_state in (
        ConversationState.QUALIFIED,
        ConversationState.AWAITING_ROLE,
        ConversationState.AWAITING_REVENUE,
    )
