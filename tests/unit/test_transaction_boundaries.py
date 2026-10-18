"""Unit tests validating decoupled transaction boundaries and status-aware idempotency."""

import pytest

from lead_qualifier.core.enums import ConversationState
from lead_qualifier.core.schemas.conversation import TurnRequest
from lead_qualifier.core.schemas.slots import LeadSlots
from lead_qualifier.services.state_machine import StateMachineService
from tests.fakes import FakeConversationRepository, FakeLLMAdapter, make_fake_uow_factory

pytestmark = pytest.mark.asyncio


async def test_slow_llm_does_not_hold_conversation_state_lock() -> None:
    """Verify that semantic slot extraction occurs strictly before acquiring the conversation row lock.

    Guarantees that slow or stalled external LLM requests do not hold PostgreSQL
    SELECT ... FOR UPDATE locks or pool connections open during turn processing.
    """
    repo = FakeConversationRepository(
        active_rule_set={
            "id": "11111111-1111-1111-1111-111111111111",
            "rules": [
                {"type": "exact_match", "field": "role", "value": "CEO", "points": 50},
            ],
            "required_slots": ["role"],
            "qualification_threshold": 50,
        }
    )

    async def mock_extract_slots(message: str) -> LeadSlots:
        _ = message
        # Assert that the row lock has NOT been acquired yet when LLM is executing
        assert "get_or_create_conversation_state" not in repo.call_log
        return LeadSlots(role="CEO")

    llm = FakeLLMAdapter(extractor=mock_extract_slots, call_tracker=repo.call_log)

    service = StateMachineService(
        uow_factory=make_fake_uow_factory(repo),
        llm_adapter=llm,
        idempotency_timeout=60,
    )

    request = TurnRequest(
        message_id="msg_slow_llm_1",
        phone_number="+5511999998888",
        user_message="Sou o CEO",
    )

    response = await service.process_turn(request)

    assert response.current_state == ConversationState.QUALIFIED
    assert "acquire_message_lock" in repo.call_log
    assert "llm_extract_slots" in repo.call_log
    assert "get_or_create_conversation_state" in repo.call_log
    # Acquire lock must precede LLM extraction, and LLM must precede state row lock
    assert (
        repo.call_log.index("acquire_message_lock")
        < repo.call_log.index("llm_extract_slots")
        < repo.call_log.index("get_or_create_conversation_state")
    )
    assert repo.messages["msg_slow_llm_1"] == "done"


async def test_failed_message_marks_status_failed_for_retry() -> None:
    """Verify that when processing encounters an exception, the message status is marked 'failed'."""
    repo = FakeConversationRepository()
    llm = FakeLLMAdapter(error=RuntimeError("OpenAI API unreachable"))

    service = StateMachineService(
        uow_factory=make_fake_uow_factory(repo),
        llm_adapter=llm,
        idempotency_timeout=60,
    )

    request = TurnRequest(
        message_id="msg_error_retry",
        phone_number="+5511999998888",
        user_message="Ola",
    )

    with pytest.raises(RuntimeError, match="OpenAI API unreachable"):
        await service.process_turn(request)

    assert repo.messages["msg_error_retry"] == "failed"


async def test_duplicate_message_short_circuits_immediately() -> None:
    """Verify that a concurrent or duplicate message is discarded without calling LLM or state locking."""
    # Pre-populate message as processing so acquire_message_lock returns False
    repo = FakeConversationRepository(messages={"msg_dup_123": "processing"})
    llm = FakeLLMAdapter()

    service = StateMachineService(
        uow_factory=make_fake_uow_factory(repo),
        llm_adapter=llm,
        idempotency_timeout=60,
    )

    request = TurnRequest(
        message_id="msg_dup_123",
        phone_number="+5511999998888",
        user_message="Sou Diretor",
    )

    response = await service.process_turn(request)

    assert response.current_state == ConversationState.DUPLICATE_IGNORED
    assert response.reply_message == ""
    assert response.is_finished is False

    # LLM must NEVER be touched on duplicates
    assert llm.call_count == 0
