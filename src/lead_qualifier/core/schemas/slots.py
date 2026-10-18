"""Pydantic schema definitions for LLM-extracted qualification slots."""

from pydantic import BaseModel, Field

from lead_qualifier.core.enums import CompanySize


class LeadSlots(BaseModel):
    """Structured qualification slots extracted from conversation history."""

    name: str | None = Field(default=None, description="The lead's full name if provided.")
    role: str | None = Field(
        default=None,
        description="Job title or decision-making role (e.g. CEO, Diretor, Gerente, Estudante).",
    )
    revenue: str | None = Field(
        default=None,
        description="Company annual revenue or billing information.",
    )
    company_size: CompanySize | None = Field(
        default=None,
        description="Normalized company employee headcount bracket.",
    )
