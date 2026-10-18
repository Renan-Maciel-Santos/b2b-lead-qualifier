"""Unit tests validating terminal conversation states (QUALIFIED, NOT_QUALIFIED, DISQUALIFIED)."""

import pytest

from lead_qualifier.core.enums import ConversationState
from lead_qualifier.core.messages import CONVERSATION_FINISHED_REPLY
from lead_qualifier.core.schemas.conversation import TurnRequest
from lead_qualifier.services.state_machine import StateMachineService
from tests.fakes import FakeConversationRepository, FakeLLMAdapter, make_fake_uow_factory

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
    repo = FakeConversationRepository(
        states={"+5511999997777": (terminal_state.value, {"role": "CEO"})},
    )
    llm = FakeLLMAdapter()

    service = StateMachineService(
        uow_factory=make_fake_uow_factory(repo),
        llm_adapter=llm,
        idempotency_timeout=60,
    )

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
    assert llm.call_count == 0
    assert len(repo.scoring_results) == 0

    # Message must be marked done
    assert repo.messages["msg_post_qualification_999"] == "done"
