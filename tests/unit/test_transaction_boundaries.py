"""Unit tests validating decoupled transaction boundaries and status-aware idempotency."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from lead_qualifier.core.enums import ConversationState
from lead_qualifier.core.schemas.conversation import TurnRequest
from lead_qualifier.core.schemas.slots import LeadSlots
from lead_qualifier.core.scoring.strategy import ExactMatchStrategy
from lead_qualifier.services.scoring_service import ScoringService
from lead_qualifier.services.state_machine import StateMachineService

pytestmark = pytest.mark.asyncio


async def test_slow_llm_does_not_hold_conversation_state_lock() -> None:
    """Verify that semantic slot extraction occurs strictly before acquiring the conversation row lock.

    Guarantees that slow or stalled external LLM requests do not hold PostgreSQL
    SELECT ... FOR UPDATE locks or pool connections open during turn processing.
    """
    call_order: list[str] = []

    mock_conn = MagicMock()
    mock_conn.commit = AsyncMock()

    mock_repo = MagicMock()
    mock_repo.conn = mock_conn

    async def mock_acquire_message_lock(message_id: str, timeout_seconds: int = 60) -> bool:
        _ = (message_id, timeout_seconds)
        call_order.append("acquire_message_lock")
        return True

    mock_repo.acquire_message_lock = AsyncMock(side_effect=mock_acquire_message_lock)

    async def mock_get_or_create_state(phone_number: str) -> tuple[str, dict[str, str]]:
        _ = phone_number
        call_order.append("get_or_create_conversation_state_FOR_UPDATE")
        return "INITIAL", {}

    mock_repo.get_or_create_conversation_state = AsyncMock(side_effect=mock_get_or_create_state)
    mock_repo.save_conversation_state = AsyncMock()
    mock_repo.save_scoring_result = AsyncMock()
    mock_repo.mark_message_done = AsyncMock()
    mock_repo.get_active_scoring_rule_set = AsyncMock(return_value=None)

    mock_llm = MagicMock()

    async def mock_extract_slots(message: str) -> LeadSlots:
        _ = message
        call_order.append("llm_extract_slots")
        # Assert that the row lock has NOT been acquired yet when LLM is executing
        assert "get_or_create_conversation_state_FOR_UPDATE" not in call_order
        return LeadSlots(role="CEO")

    mock_llm.extract_slots = AsyncMock(side_effect=mock_extract_slots)

    # Injected scoring service
    scoring = ScoringService([ExactMatchStrategy(field="role", target_value="CEO", points=50)])
    service = StateMachineService(
        repo=mock_repo,
        llm_adapter=mock_llm,
        scoring_service=scoring,
    )

    request = TurnRequest(
        message_id="msg_slow_llm_1",
        phone_number="+5511999998888",
        user_message="Sou o CEO",
    )

    response = await service.process_turn(request)

    assert response.current_state == ConversationState.QUALIFIED
    assert call_order == [
        "acquire_message_lock",
        "llm_extract_slots",
        "get_or_create_conversation_state_FOR_UPDATE",
    ]
    # Verify transaction 2 commit was executed
    assert mock_conn.commit.await_count >= 1
    mock_repo.mark_message_done.assert_awaited_once_with("msg_slow_llm_1")


async def test_failed_message_marks_status_failed_for_retry() -> None:
    """Verify that when processing encounters an exception, the message status is marked 'failed'."""
    mock_conn = MagicMock()
    mock_conn.commit = AsyncMock()

    mock_repo = MagicMock()
    mock_repo.conn = mock_conn
    mock_repo.acquire_message_lock = AsyncMock(return_value=True)
    mock_repo.mark_message_failed = AsyncMock()

    mock_llm = MagicMock()
    mock_llm.extract_slots = AsyncMock(side_effect=RuntimeError("OpenAI API unreachable"))

    service = StateMachineService(repo=mock_repo, llm_adapter=mock_llm)

    request = TurnRequest(
        message_id="msg_error_retry",
        phone_number="+5511999998888",
        user_message="Ola",
    )

    with pytest.raises(RuntimeError, match="OpenAI API unreachable"):
        await service.process_turn(request)

    mock_repo.mark_message_failed.assert_awaited_once_with("msg_error_retry")


async def test_duplicate_message_short_circuits_immediately() -> None:
    """Verify that a concurrent or duplicate message is discarded without calling LLM or state locking."""
    mock_conn = MagicMock()
    mock_conn.commit = AsyncMock()

    mock_repo = MagicMock()
    mock_repo.conn = mock_conn
    # Simulates loser of atomic idempotency race
    mock_repo.acquire_message_lock = AsyncMock(return_value=False)
    mock_repo.get_or_create_conversation_state = AsyncMock()

    mock_llm = MagicMock()
    mock_llm.extract_slots = AsyncMock()

    service = StateMachineService(repo=mock_repo, llm_adapter=mock_llm)

    request = TurnRequest(
        message_id="msg_dup_123",
        phone_number="+5511999998888",
        user_message="Sou Diretor",
    )

    response = await service.process_turn(request)

    assert response.current_state == ConversationState.DUPLICATE_IGNORED
    assert response.reply_message == ""
    assert response.is_finished is False

    # LLM and row lock must NEVER be touched on duplicates
    mock_llm.extract_slots.assert_not_called()
    mock_repo.get_or_create_conversation_state.assert_not_called()
