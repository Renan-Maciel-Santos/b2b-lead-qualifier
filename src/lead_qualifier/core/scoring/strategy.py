"""Scoring strategies implementing pluggable qualification logic (Strategy Pattern)."""

from abc import ABC, abstractmethod
from typing import Any


class ScoringStrategy(ABC):
    """Abstract base class for all lead qualification scoring rules."""

    @abstractmethod
    def evaluate(self, lead_data: dict[str, Any]) -> tuple[int, str]:
        """Evaluate lead attributes and return points awarded with an audit reason.

        Args:
            lead_data: Key-value dictionary of extracted lead properties.

        Returns:
            tuple[int, str]: Tuple of (score_delta, audit_reason).
        """


class KnockoutStrategy(ScoringStrategy):
    """Disqualifying strategy applying an extreme negative score on forbidden values."""

    def __init__(self, field: str, knockout_value: Any) -> None:
        """Initialize the knockout rule.

        Args:
            field: Name of the lead slot/attribute to inspect.
            knockout_value: Prohibited value triggering immediate disqualification.
        """
        self.field = field
        self.knockout_value = knockout_value

    def evaluate(self, lead_data: dict[str, Any]) -> tuple[int, str]:
        """Check whether the lead property matches the knockout criterion."""
        value = lead_data.get(self.field)
        if value == self.knockout_value:
            # -9999 represents a knockout penalty that triggers immediate rule execution halt
            return -9999, f"Disqualified: '{self.field}' matches restricted value '{value}'"
        return 0, ""


class ExactMatchStrategy(ScoringStrategy):
    """Strategy awarding points when a lead attribute matches a target value."""

    def __init__(self, field: str, target_value: Any, points: int) -> None:
        """Initialize exact match rule.

        Args:
            field: Name of the lead slot/attribute to inspect.
            target_value: Desired target value.
            points: Score awarded when the value matches.
        """
        self.field = field
        self.target_value = target_value
        self.points = points

    def evaluate(self, lead_data: dict[str, Any]) -> tuple[int, str]:
        """Evaluate equality against target value and award points on match."""
        value = lead_data.get(self.field)
        if value == self.target_value:
            return self.points, f"Awarded {self.points} pts: '{self.field}' equals '{value}'"
        return 0, ""


def build_strategies_from_rules(rules: list[dict[str, Any]]) -> list[ScoringStrategy]:
    """Dynamically instantiate scoring strategies from JSON rule specifications.

    Args:
        rules: List of rule definitions loaded from the database JSONB column.

    Returns:
        list[ScoringStrategy]: Instantiated rule evaluators.
    """
    strategies: list[ScoringStrategy] = []
    for rule in rules:
        rule_type = rule.get("type")
        if rule_type == "knockout":
            strategies.append(
                KnockoutStrategy(
                    field=rule["field"],
                    knockout_value=rule.get("value") or rule.get("knockout_value"),
                )
            )
        elif rule_type == "exact_match":
            strategies.append(
                ExactMatchStrategy(
                    field=rule["field"],
                    target_value=rule.get("value") or rule.get("target_value"),
                    points=int(rule.get("points", 0)),
                )
            )
    return strategies
