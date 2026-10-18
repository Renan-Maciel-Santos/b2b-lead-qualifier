"""Deterministic rule-based fake LLM adapter for local development and offline demonstrations."""

import re

from lead_qualifier.core.enums import RevenueTier
from lead_qualifier.core.logger import logger
from lead_qualifier.core.schemas.slots import LeadSlots


class FakeDeterministicLLMAdapter:
    """Deterministic keyword-based slot extractor for offline demonstration without external API costs."""

    async def extract_slots(self, conversation_history: str) -> LeadSlots:
        """Extract lead qualification slots deterministically using keyword heuristics.

        Args:
            conversation_history: Text payload from user turn.

        Returns:
            LeadSlots: Populated qualification slots according to matched domain keywords.
        """
        text = conversation_history.lower()
        role: str | None = None
        revenue_tier: RevenueTier | None = None

        # Role extraction keywords
        if "estudante" in text:
            role = "estudante"
        elif "estagiario" in text or "estagiário" in text:
            role = "estagiario"
        elif "ceo" in text:
            role = "CEO"
        elif "diretor" in text or "diretora" in text:
            role = "Diretor"
        elif "gerente" in text:
            role = "Gerente"

        # Revenue tier extraction keywords
        if "abaixo de 500" in text or "menos de 500" in text or "< 500" in text:
            revenue_tier = RevenueTier.BELOW_500K
        elif (
            "acima de 10" in text
            or "mais de 10" in text
            or "> 10" in text
            or re.search(r"\b(1[1-9]|[2-9]\d)\s*(milh[oõ]es|m\b)", text)
        ):
            revenue_tier = RevenueTier.ABOVE_10M
        elif (
            "5 milh" in text
            or "2 milh" in text
            or "3 milh" in text
            or "4 milh" in text
            or "6 milh" in text
            or "7 milh" in text
            or "8 milh" in text
            or "9 milh" in text
            or "10 milh" in text
            or re.search(r"\b([2-9]|10)\s*(milh[oõ]es|m\b)", text)
        ):
            revenue_tier = RevenueTier.FROM_2M_TO_10M
        elif (
            "500k" in text
            or "500 mil" in text
            or "1 milh" in text
            or "1.5 milh" in text
            or "1m" in text
        ):
            revenue_tier = RevenueTier.FROM_500K_TO_2M

        logger.info(
            "FakeDeterministicLLMAdapter extracted: role=%s, revenue_tier=%s",
            role,
            revenue_tier,
        )
        return LeadSlots(role=role, revenue_tier=revenue_tier)
