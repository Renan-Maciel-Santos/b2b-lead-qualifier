"""Webhook orchestration controller.

Connects incoming HTTP webhook payloads to the conversational state machine.
"""

from lead_qualifier.core.schemas.conversation import TurnRequest, TurnResponse
from lead_qualifier.services.state_machine import StateMachineService


class WebhookController:
    """Controller coordinating conversation turn processing with injected StateMachineService."""

    def __init__(self, service: StateMachineService) -> None:
        """Initialize controller with pre-configured StateMachineService.

        Args:
            service: Injected state machine service instance.
        """
        self.service = service

    async def handle_turn(self, request: TurnRequest) -> TurnResponse:
        """Handle a single conversational turn from the messaging transport.

        Delegates execution to StateMachineService, which coordinates LLM extraction,
        deterministic scoring, and unit of work persistence.

        Args:
            request: Inbound turn payload containing message ID and user text.

        Returns:
            TurnResponse: System response and next state for the caller.
        """
        return await self.service.process_turn(request)
