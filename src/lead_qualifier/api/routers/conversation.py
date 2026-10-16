"""Conversation webhook router for messaging platforms (e.g., WhatsApp)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from psycopg import AsyncConnection

from lead_qualifier.controllers.webhook_controller import WebhookController
from lead_qualifier.core.logger import logger
from lead_qualifier.core.schemas.conversation import TurnRequest, TurnResponse
from lead_qualifier.core.tenant import get_tenant_connection

router = APIRouter(tags=["Conversations"])


@router.post("/v1/{tenant}/conversa/turno", response_model=TurnResponse)
async def conversation_turn(
    tenant: str,
    request: TurnRequest,
    conn: Annotated[AsyncConnection, Depends(get_tenant_connection)],
) -> TurnResponse:
    """Process an inbound conversation message turn with idempotency and lead scoring.

    Args:
        tenant: Unique tenant identifier from URL path.
        request: Validated turn payload containing user message and sender phone.
        conn: Injected database connection pre-configured with tenant RLS session context.

    Returns:
        TurnResponse: Formatted reply message, current conversation state, and completion flag.
    """
    logger.info(f"Webhook received for tenant={tenant} | phone={request.phone_number}")
    controller = WebhookController(conn)
    return await controller.handle_turn(request)
