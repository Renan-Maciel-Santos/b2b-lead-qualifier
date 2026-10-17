"""Webhook orchestration controller.

Connects incoming HTTP webhook payloads to the conversational state machine
and manages transaction-scoped unit of work boundaries.
"""

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from lead_qualifier.core.schemas.conversation import TurnRequest, TurnResponse
from lead_qualifier.core.tenant import TenantContext
from lead_qualifier.services.state_machine import StateMachineService


class WebhookController:
    """Controller coordinating conversation turn processing and unit of work boundaries."""

    def __init__(
        self,
        pool: AsyncConnectionPool | AsyncConnection,
        tenant_ctx: TenantContext,
    ) -> None:
        """Initialize controller with database pool and immutable tenant context.

        Args:
            pool: Database pool or connection used to spawn scoped transactions.
            tenant_ctx: Verified immutable tenant context.
        """
        self.pool = pool
        self.tenant_ctx = tenant_ctx
        self.service = StateMachineService(pool=pool, tenant_ctx=tenant_ctx)

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
