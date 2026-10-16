"""Pydantic schema definitions for LLM-extracted qualification slots."""

from pydantic import BaseModel, Field


class LeadSlots(BaseModel):
    """Structured qualification slots extracted from conversation history."""

    name: str | None = Field(default=None, description="The lead's full name if provided.")
    revenue: str | None = Field(
        default=None, description="Annual or monthly revenue reported by the lead."
    )
    role: str | None = Field(
        default=None, description="Job title or decision-making role within the company."
    )
