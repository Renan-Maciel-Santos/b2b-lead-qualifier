"""Conversation webhook router for messaging platforms (e.g., WhatsApp)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from psycopg import AsyncConnection

from lead_qualifier.controllers.webhook_controller import WebhookController
from lead_qualifier.core.logger import logger
from lead_qualifier.core.masking import mask_phone_number
from lead_qualifier.core.schemas.conversation import TurnRequest, TurnResponse
from lead_qualifier.core.security import get_tenant_connection

router = APIRouter(tags=["Conversations"])


@router.post("/v1/conversations/turns", response_model=TurnResponse)
@router.post("/v1/conversa/turno", response_model=TurnResponse, include_in_schema=False)
async def conversation_turn(
    request: TurnRequest,
    conn: Annotated[AsyncConnection, Depends(get_tenant_connection)],
) -> TurnResponse:
    """Process an inbound conversation message turn with idempotency and lead scoring.

    Tenant context is resolved strictly from the Bearer API key in the Authorization header.

    Args:
        request: Validated turn payload containing user message and sender phone.
        conn: Injected database connection pre-configured with tenant RLS session context.

    Returns:
        TurnResponse: Formatted reply message, current conversation state, and completion flag.
    """
    logger.info(f"Webhook received for phone={mask_phone_number(request.phone_number)}")
    controller = WebhookController(conn)
    return await controller.handle_turn(request)
