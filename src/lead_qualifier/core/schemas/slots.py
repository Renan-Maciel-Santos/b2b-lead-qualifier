"""Pydantic schema definitions for LLM-extracted qualification slots."""

from pydantic import BaseModel, Field

from lead_qualifier.core.enums import CompanySize, RevenueTier


class LeadSlots(BaseModel):
    """Structured qualification slots extracted from conversation history."""

    name: str | None = Field(default=None, description="The lead's full name if provided.")
    role: str | None = Field(
        default=None,
        description="Job title or decision-making role (e.g. CEO, Diretor, Gerente, Estudante).",
    )
    revenue_tier: RevenueTier | None = Field(
        default=None,
        description="Normalized company annual revenue bracket.",
    )
    company_size: CompanySize | None = Field(
        default=None,
        description="Normalized company employee headcount bracket.",
    )
