"""Domain ports defining abstract protocols for adapters and persistence."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Protocol

from lead_qualifier.core.schemas.slots import LeadSlots
from lead_qualifier.repositories.conversation_repo import ConversationRepository


class LLMAdapterPort(Protocol):
    """Protocol for structured entity and slot extraction from conversation dialogue."""

    async def extract_slots(self, conversation_history: str) -> LeadSlots:
        """Extract structured qualification slots from conversation dialogue text."""
        ...


UnitOfWork = AbstractAsyncContextManager[ConversationRepository]
UnitOfWorkFactory = Callable[[], AbstractAsyncContextManager[ConversationRepository]]
