"""Scoring strategies implementing pluggable qualification logic (Strategy Pattern)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter, field_validator

from lead_qualifier.core.schemas.slots import LeadSlots


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


class RuleSetConfigModel(BaseModel):
    """Configuration model for scoring rule sets with mandatory required_slots."""

    rules: list[RuleConfig]
    required_slots: list[str]

    # Valida que required_slots seja nao-vazia, sem duplicatas e com campos validos em LeadSlots
    @field_validator("required_slots")
    @classmethod
    def validate_required_slots(cls, v: list[str]) -> list[str]:
        """Validate non-empty list, absence of duplicates, and field existence in LeadSlots."""
        if not v:
            raise ValueError("required_slots must be a non-empty list.")
        if len(v) != len(set(v)):
            raise ValueError("required_slots must not contain duplicate fields.")
        valid_fields = set(LeadSlots.model_fields.keys())
        for slot in v:
            if slot not in valid_fields:
                raise ValueError(
                    f"Slot '{slot}' is not a valid field in LeadSlots. Valid fields: {sorted(valid_fields)}"
                )
        return v


def parse_rule_set_config(
    raw_config: list[dict[str, Any]] | dict[str, Any],
    required_slots: list[str] | None = None,
) -> tuple[list[ScoringStrategy], list[str]]:
    """Parse, validate, and extract scoring strategies and mandatory required slots.

    Args:
        raw_config: Dict with 'rules' and 'required_slots', or list of rules.
        required_slots: Optional list of mandatory slots if not present in raw_config.

    Returns:
        tuple[list[ScoringStrategy], list[str]]: Validated strategies and ordered required slots.

    Raises:
        pydantic.ValidationError: If rule definitions or required_slots are malformed or missing.
    """
    if isinstance(raw_config, dict):
        raw_rules = raw_config.get("rules", [])
        raw_required_slots = (
            required_slots if required_slots is not None else raw_config.get("required_slots")
        )
    else:
        raw_rules = raw_config
        raw_required_slots = required_slots

    normalized_rules: list[dict[str, Any]] = []
    if isinstance(raw_rules, list):
        for raw in raw_rules:
            if isinstance(raw, dict):
                entry = dict(raw)
                # Check explicit key presence to prevent false-negative bugs when value is falsy (0, False, "")
                if "value" not in entry:
                    if "knockout_value" in entry:
                        entry["value"] = entry["knockout_value"]
                    elif "target_value" in entry:
                        entry["value"] = entry["target_value"]
                normalized_rules.append(entry)

    # Validates rules and strictly mandatory required_slots
    validated = RuleSetConfigModel(
        rules=normalized_rules,  # type: ignore[arg-type]
        required_slots=raw_required_slots,  # type: ignore[arg-type]
    )

    strategies: list[ScoringStrategy] = []
    for rule in validated.rules:
        if isinstance(rule, KnockoutRuleModel):
            strategies.append(KnockoutStrategy(field=rule.field, knockout_value=rule.value))
        elif isinstance(rule, ExactMatchRuleModel):
            strategies.append(
                ExactMatchStrategy(field=rule.field, target_value=rule.value, points=rule.points)
            )

    return strategies, validated.required_slots


def build_strategies_from_rules(
    rules: list[dict[str, Any]] | dict[str, Any],
) -> list[ScoringStrategy]:
    """Dynamically instantiate and strictly validate scoring strategies from JSON specifications.

    Uses Pydantic discriminated union validation to reject unknown rule types or invalid payloads.
    Fixes falsy value bugs by checking explicit key presence rather than boolean truthiness.

    Args:
        rules: List or dict of rule definitions loaded from the database JSONB column.

    Returns:
        list[ScoringStrategy]: Instantiated rule evaluators.

    Raises:
        pydantic.ValidationError: If any rule specification is malformed or uses an unknown type.
    """
    raw_rules = rules.get("rules", []) if isinstance(rules, dict) else rules

    normalized_rules: list[dict[str, Any]] = []
    if isinstance(raw_rules, list):
        for raw in raw_rules:
            if isinstance(raw, dict):
                entry = dict(raw)
                # Check explicit key presence to prevent false-negative bugs when value is falsy (0, False, "")
                if "value" not in entry:
                    if "knockout_value" in entry:
                        entry["value"] = entry["knockout_value"]
                    elif "target_value" in entry:
                        entry["value"] = entry["target_value"]
                normalized_rules.append(entry)

    rule_adapter: TypeAdapter[RuleConfig] = TypeAdapter(RuleConfig)
    strategies: list[ScoringStrategy] = []
    for r in normalized_rules:
        validated_rule = rule_adapter.validate_python(r)
        if isinstance(validated_rule, KnockoutRuleModel):
            strategies.append(
                KnockoutStrategy(field=validated_rule.field, knockout_value=validated_rule.value)
            )
        elif isinstance(validated_rule, ExactMatchRuleModel):
            strategies.append(
                ExactMatchStrategy(
                    field=validated_rule.field,
                    target_value=validated_rule.value,
                    points=validated_rule.points,
                )
            )

    return strategies
