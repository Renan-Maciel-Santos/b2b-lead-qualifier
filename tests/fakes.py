"""Test fakes implementing domain ports for unit testing."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from lead_qualifier.core.schemas.slots import LeadSlots
from lead_qualifier.domain.ports import UnitOfWorkFactory
from lead_qualifier.repositories.conversation_repo import ConversationRepository


class FakeConversationRepository:
    """In-memory fake implementation of ConversationRepository."""

    def __init__(
        self,
        active_rule_set: dict[str, Any] | None = None,
        states: dict[str, tuple[str, dict[str, Any]]] | None = None,
        messages: dict[str, str] | None = None,
    ) -> None:
        self.active_rule_set = active_rule_set
        self.states = dict(states) if states else {}
        self.messages = dict(messages) if messages else {}
        self.scoring_results: list[dict[str, Any]] = []
        self.call_log: list[str] = []

    async def acquire_message_lock(self, message_id: str, timeout_seconds: int = 60) -> bool:
        _ = timeout_seconds
        self.call_log.append("acquire_message_lock")
        status = self.messages.get(message_id)
        if status in ("processing", "done"):
            return False
        self.messages[message_id] = "processing"
        return True

    async def get_conversation_state_read_only(
        self,
        phone_number: str,
    ) -> tuple[str, dict[str, Any]]:
        _ = phone_number
        self.call_log.append("get_conversation_state_read_only")
        return self.states.get(phone_number, ("INITIAL", {}))

    async def get_or_create_conversation_state(
        self,
        phone_number: str,
    ) -> tuple[str, dict[str, Any]]:
        self.call_log.append("get_or_create_conversation_state")
        if phone_number not in self.states:
            self.states[phone_number] = ("INITIAL", {})
        return self.states[phone_number]

    async def save_conversation_state(
        self,
        phone_number: str,
        current_state: str,
        accumulated_slots: dict[str, Any],
    ) -> None:
        self.call_log.append("save_conversation_state")
        self.states[phone_number] = (current_state, accumulated_slots)

    async def save_scoring_result(
        self,
        phone_number: str,
        rule_set_id: str,
        final_score: int,
        is_qualified: bool,
        audit_trail: list[dict[str, Any]] | list[Any],
    ) -> None:
        self.call_log.append("save_scoring_result")
        self.scoring_results.append(
            {
                "phone_number": phone_number,
                "rule_set_id": rule_set_id,
                "final_score": final_score,
                "is_qualified": is_qualified,
                "audit_trail": audit_trail,
            }
        )

    async def mark_message_done(self, message_id: str) -> None:
        self.call_log.append("mark_message_done")
        self.messages[message_id] = "done"

    async def mark_message_failed(self, message_id: str) -> None:
        self.call_log.append("mark_message_failed")
        self.messages[message_id] = "failed"

    async def get_active_scoring_rule_set(self) -> dict[str, Any] | None:
        self.call_log.append("get_active_scoring_rule_set")
        return self.active_rule_set


def make_fake_uow_factory(repo: FakeConversationRepository) -> UnitOfWorkFactory:
    """Return a UnitOfWorkFactory yielding the provided FakeConversationRepository."""

    @asynccontextmanager
    async def _fake_uow() -> AsyncIterator[ConversationRepository]:
        # Cast fake to ConversationRepository for type checking
        yield repo  # type: ignore[misc]

    return _fake_uow


class FakeLLMAdapter:
    """Fake LLM adapter implementing LLMAdapterPort for unit tests."""

    def __init__(
        self,
        extracted_slots: LeadSlots | None = None,
        error: Exception | None = None,
        call_tracker: list[str] | None = None,
        extractor: Callable[[str], Awaitable[LeadSlots]] | None = None,
    ) -> None:
        self.extracted_slots = extracted_slots or LeadSlots()
        self.error = error
        self.call_tracker = call_tracker
        self.extractor = extractor
        self.call_count = 0

    async def extract_slots(self, conversation_history: str) -> LeadSlots:
        self.call_count += 1
        if self.call_tracker is not None:
            self.call_tracker.append("llm_extract_slots")
        if self.error is not None:
            raise self.error
        if self.extractor is not None:
            return await self.extractor(conversation_history)
        return self.extracted_slots
