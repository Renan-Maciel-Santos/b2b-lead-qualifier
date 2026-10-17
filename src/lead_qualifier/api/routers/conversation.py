"""Conversation webhook router for messaging platforms (e.g., WhatsApp)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from psycopg_pool import AsyncConnectionPool

from lead_qualifier.controllers.webhook_controller import WebhookController
from lead_qualifier.core.database import get_db_pool
from lead_qualifier.core.logger import logger
from lead_qualifier.core.masking import mask_phone_number
from lead_qualifier.core.schemas.conversation import TurnRequest, TurnResponse
from lead_qualifier.core.tenant import TenantContext, get_tenant_context

router = APIRouter(tags=["Conversations"])


@router.post("/v1/conversations/turns", response_model=TurnResponse)
@router.post("/v1/conversa/turno", response_model=TurnResponse, include_in_schema=False)
async def conversation_turn(
    request: TurnRequest,
    pool: Annotated[AsyncConnectionPool, Depends(get_db_pool)],
    tenant_ctx: Annotated[TenantContext, Depends(get_tenant_context)],
) -> TurnResponse:
    """Process an inbound conversation message turn with idempotency and lead scoring.

    Tenant context is resolved strictly from the Bearer API key in the Authorization header.

    Args:
        request: Validated turn payload containing user message and sender phone.
        pool: Injected shared application database pool.
        tenant_ctx: Injected immutable tenant security context.

    Returns:
        TurnResponse: Formatted reply message, current conversation state, and completion flag.
    """
    logger.info(f"Webhook received for phone={mask_phone_number(request.phone_number)}")
    controller = WebhookController(pool=pool, tenant_ctx=tenant_ctx)
    return await controller.handle_turn(request)
