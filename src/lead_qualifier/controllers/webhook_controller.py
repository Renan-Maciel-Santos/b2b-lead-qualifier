"""Webhook orchestration controller.

Connects incoming HTTP webhook payloads to the conversational state machine
and manages database transaction boundaries.
"""

from psycopg import AsyncConnection

from lead_qualifier.core.schemas.conversation import TurnRequest, TurnResponse
from lead_qualifier.repositories.conversation_repo import ConversationRepository
from lead_qualifier.services.state_machine import StateMachineService


class WebhookController:
    """Controller coordinating conversation turn processing and transaction commits."""

    def __init__(self, conn: AsyncConnection) -> None:
        """Initialize controller with a tenant-scoped connection.

        Args:
            conn: Active AsyncConnection already initialized with tenant RLS context.
        """
        self.repo = ConversationRepository(conn)
        self.service = StateMachineService(self.repo)

    async def handle_turn(self, request: TurnRequest) -> TurnResponse:
        """Handle a single conversational turn from the messaging transport.

        Delegates execution to StateMachineService, which manages short, dedicated
        transaction boundaries around idempotency registration and state updates.

        Args:
            request: Inbound turn payload containing message ID and user text.

        Returns:
            TurnResponse: System response and next state for the caller.
        """
        return await self.service.process_turn(request)
