"""Conversation payload schemas for messaging transports (e.g. n8n / WhatsApp)."""

from pydantic import BaseModel, Field


class TurnRequest(BaseModel):
    """Inbound message payload representing a single conversation turn from the user."""

    message_id: str = Field(..., description="Unique message ID used for idempotency enforcement.")
    phone_number: str = Field(..., description="Lead contact phone number in E.164 format.")
    user_message: str = Field(..., description="Inbound text content sent by the lead.")


class TurnResponse(BaseModel):
    """Outbound response payload returned to the messaging transport."""

    reply_message: str = Field(
        ..., description="Response message to be dispatched back to the lead."
    )
    current_state: str = Field(..., description="Current state machine status.")
    is_finished: bool = Field(..., description="Whether the qualification dialogue has completed.")
