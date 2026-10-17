"""Scoring strategies implementing pluggable qualification logic (Strategy Pattern)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class StrategyResult:
    """Outcome of an individual scoring strategy evaluation.

    Attributes:
        points: Integer delta to add to the cumulative lead score.
        reason: Explanation of the evaluation decision for the audit trail.
        is_knockout: Flag indicating whether this rule immediately disqualifies the lead.
    """

    points: int = 0
    reason: str = ""
    is_knockout: bool = False


class ScoringStrategy(ABC):
    """Abstract base class for all lead qualification scoring rules."""

    @abstractmethod
    def evaluate(self, lead_data: dict[str, Any]) -> StrategyResult:
        """Evaluate lead attributes and return a structured evaluation result.

        Args:
            lead_data: Key-value dictionary of extracted lead properties.

        Returns:
            StrategyResult: Score points, explanation, and knockout indicator.
        """


class KnockoutStrategy(ScoringStrategy):
    """Disqualifying strategy marking the lead as knocked out on restricted values."""

    def __init__(self, field: str, knockout_value: Any) -> None:
        """Initialize the knockout rule.

        Args:
            field: Name of the lead slot/attribute to inspect.
            knockout_value: Prohibited value triggering immediate disqualification.
        """
        self.field = field
        self.knockout_value = knockout_value

    def evaluate(self, lead_data: dict[str, Any]) -> StrategyResult:
        """Check whether the lead property matches the knockout criterion."""
        value = lead_data.get(self.field)
        if value is not None and value == self.knockout_value:
            return StrategyResult(
                points=0,
                reason=f"Disqualified: '{self.field}' matches restricted value '{value}'",
                is_knockout=True,
            )
        return StrategyResult()


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

    def evaluate(self, lead_data: dict[str, Any]) -> StrategyResult:
        """Evaluate equality against target value and award points on match."""
        value = lead_data.get(self.field)
        if value is not None and value == self.target_value:
            return StrategyResult(
                points=self.points,
                reason=f"Awarded {self.points} pts: '{self.field}' equals '{value}'",
                is_knockout=False,
            )
        return StrategyResult()


class KnockoutRuleModel(BaseModel):
    """Schema definition for a knockout scoring rule."""

    type: Literal["knockout"]
    field: str
    value: Any


class ExactMatchRuleModel(BaseModel):
    """Schema definition for an exact match scoring rule."""

    type: Literal["exact_match"]
    field: str
    value: Any
    points: int


RuleConfig = Annotated[KnockoutRuleModel | ExactMatchRuleModel, Field(discriminator="type")]


class RuleListValidator(BaseModel):
    """Validator ensuring every rule conforms to supported discriminated schemas."""

    rules: list[RuleConfig]


def build_strategies_from_rules(rules: list[dict[str, Any]]) -> list[ScoringStrategy]:
    """Dynamically instantiate and strictly validate scoring strategies from JSON specifications.

    Uses Pydantic discriminated union validation to reject unknown rule types or invalid payloads.
    Fixes falsy value bugs by checking explicit key presence rather than boolean truthiness.

    Args:
        rules: List of rule definitions loaded from the database JSONB column.

    Returns:
        list[ScoringStrategy]: Instantiated rule evaluators.

    Raises:
        pydantic.ValidationError: If any rule specification is malformed or uses an unknown type.
    """
    normalized_rules: list[dict[str, Any]] = []
    for raw in rules:
        entry = dict(raw)
        # Check explicit key presence to prevent false-negative bugs when value is falsy (0, False, "")
        if "value" not in entry:
            if "knockout_value" in entry:
                entry["value"] = entry["knockout_value"]
            elif "target_value" in entry:
                entry["value"] = entry["target_value"]
        normalized_rules.append(entry)

    validated = RuleListValidator(rules=normalized_rules)  # type: ignore[arg-type]

    strategies: list[ScoringStrategy] = []
    for rule in validated.rules:
        if isinstance(rule, KnockoutRuleModel):
            strategies.append(KnockoutStrategy(field=rule.field, knockout_value=rule.value))
        elif isinstance(rule, ExactMatchRuleModel):
            strategies.append(
                ExactMatchStrategy(field=rule.field, target_value=rule.value, points=rule.points)
            )

    return strategies
