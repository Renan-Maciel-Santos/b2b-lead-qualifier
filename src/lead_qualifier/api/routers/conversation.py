"""Conversation webhook router for messaging platforms (e.g., WhatsApp)."""

from typing import Annotated

from fastapi import APIRouter, Depends

from lead_qualifier.api.dependencies import get_webhook_controller
from lead_qualifier.controllers.webhook_controller import WebhookController
from lead_qualifier.core.logger import logger
from lead_qualifier.core.masking import mask_phone_number
from lead_qualifier.core.schemas.conversation import TurnRequest, TurnResponse

router = APIRouter(tags=["Conversations"])


@router.post("/v1/conversations/turns", response_model=TurnResponse)
@router.post("/v1/conversa/turno", response_model=TurnResponse, include_in_schema=False)
async def conversation_turn(
    request: TurnRequest,
    controller: Annotated[WebhookController, Depends(get_webhook_controller)],
) -> TurnResponse:
    """Process an inbound conversation message turn with idempotency and lead scoring.

    Tenant context and dependencies are composed via the composition root.

    Args:
        request: Validated turn payload containing user message and sender phone.
        controller: Injected WebhookController instance.

    Returns:
        TurnResponse: Formatted reply message, current conversation state, and completion flag.
    """
    logger.info(f"Webhook received for phone={mask_phone_number(request.phone_number)}")
    return await controller.handle_turn(request)
