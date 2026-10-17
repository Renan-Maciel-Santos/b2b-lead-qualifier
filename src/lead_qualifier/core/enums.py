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
