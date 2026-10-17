"""Unit tests validating terminal conversation states (QUALIFIED, NOT_QUALIFIED, DISQUALIFIED)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from lead_qualifier.core.enums import ConversationState
from lead_qualifier.core.messages import CONVERSATION_FINISHED_REPLY
from lead_qualifier.core.schemas.conversation import TurnRequest
from lead_qualifier.services.state_machine import StateMachineService

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    "terminal_state",
    [
        ConversationState.QUALIFIED,
        ConversationState.NOT_QUALIFIED,
        ConversationState.DISQUALIFIED,
    ],
)
async def test_lead_in_terminal_state_does_not_invoke_llm_or_scoring(
    terminal_state: ConversationState,
) -> None:
    """Verify that inbound messages for a lead in a terminal state skip LLM and scoring completely."""
    mock_conn = MagicMock()
    mock_conn.commit = AsyncMock()

    mock_repo = MagicMock()
    mock_repo.conn = mock_conn
    mock_repo.acquire_message_lock = AsyncMock(return_value=True)
    mock_repo.get_conversation_state_read_only = AsyncMock(
        return_value=(terminal_state.value, {"role": "CEO"})
    )
    mock_repo.get_or_create_conversation_state = AsyncMock()
    mock_repo.save_scoring_result = AsyncMock()
    mock_repo.save_conversation_state = AsyncMock()
    mock_repo.mark_message_done = AsyncMock()

    mock_llm = MagicMock()
    mock_llm.extract_slots = AsyncMock()

    service = StateMachineService(repo=mock_repo, llm_adapter=mock_llm)

    request = TurnRequest(
        message_id="msg_post_qualification_999",
        phone_number="+5511999997777",
        user_message="Gostaria de mandar mais uma mensagem apos a qualificacao",
    )

    response = await service.process_turn(request)

    # Must preserve the terminal state and return finished reply
    assert response.current_state == terminal_state
    assert response.reply_message == CONVERSATION_FINISHED_REPLY
    assert response.is_finished is True

    # Critical assertions: zero LLM extraction and zero new scoring result
    mock_llm.extract_slots.assert_not_called()
    mock_repo.save_scoring_result.assert_not_called()
    mock_repo.save_conversation_state.assert_not_called()
    mock_repo.get_or_create_conversation_state.assert_not_called()

    # Message must be marked done and committed
    mock_repo.mark_message_done.assert_awaited_once_with("msg_post_qualification_999")
    assert mock_conn.commit.await_count >= 1
