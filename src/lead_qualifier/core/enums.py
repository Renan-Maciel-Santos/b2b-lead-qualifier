"""Domain enumeration definitions for conversational state and scoring."""

from enum import StrEnum


class ConversationState(StrEnum):
    """Lifecycle states for conversational lead qualification."""

    INITIAL = "INITIAL"
    AWAITING_ROLE = "AWAITING_ROLE"
    AWAITING_REVENUE = "AWAITING_REVENUE"
    QUALIFIED = "QUALIFIED"
    NOT_QUALIFIED = "NOT_QUALIFIED"
    DISQUALIFIED = "DISQUALIFIED"
    DUPLICATE_IGNORED = "DUPLICATE_IGNORED"


class RevenueTier(StrEnum):
    """Annual company revenue brackets for qualification scoring."""

    BELOW_500K = "below_500k"
    FROM_500K_TO_2M = "500k_to_2m"
    FROM_2M_TO_10M = "2m_to_10m"
    ABOVE_10M = "above_10m"


class CompanySize(StrEnum):
    """Company headcount brackets for qualification scoring."""

    SOLO = "solo"
    SMALL = "small_2_to_10"
    MEDIUM = "medium_11_to_50"
    LARGE = "large_51_to_200"
    ENTERPRISE = "enterprise_above_200"
