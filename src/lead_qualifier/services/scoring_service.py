"""Lead scoring engine executing composite qualification strategies."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from lead_qualifier.core.logger import logger
from lead_qualifier.core.scoring.strategy import ScoringStrategy


@dataclass(frozen=True)
class ScoringResult:
    """Comprehensive scoring evaluation outcome.

    Attributes:
        final_score: Accumulated qualification score.
        is_qualified: Final boolean approval verdict.
        is_knocked_out: Whether an immediate knockout rule triggered disqualification.
        reasons: Chronological audit trail of rule justifications.
    """

    final_score: int
    is_qualified: bool
    is_knocked_out: bool
    reasons: list[str]


class ScoringService:
    """Service evaluating lead attributes against a collection of configured scoring strategies."""

    def __init__(
        self,
        strategies: Sequence[ScoringStrategy],
        qualification_threshold: int = 50,
    ) -> None:
        """Initialize scoring service.

        Args:
            strategies: Ordered collection of scoring strategies to evaluate.
            qualification_threshold: Minimum total score required for positive qualification.
        """
        self.strategies = strategies
        self.qualification_threshold = qualification_threshold

    def calculate_score(self, lead_data: dict[str, Any]) -> ScoringResult:
        """Evaluate lead data against active strategies and produce an audit trail.

        Halts evaluation immediately upon encountering a knockout rule without using sentinel scores.

        Args:
            lead_data: Key-value dictionary of extracted lead attributes.

        Returns:
            ScoringResult: Typed outcome containing final_score, is_qualified, is_knocked_out, and reasons.
        """
        total_score = 0
        audit_trail: list[str] = []
        is_knocked_out = False

        for strategy in self.strategies:
            res = strategy.evaluate(lead_data)

            if res.is_knockout:
                is_knocked_out = True
                audit_trail.append(res.reason)
                logger.warning("Lead met knockout criterion; halting rule evaluation early.")
                break

            if res.points != 0:
                total_score += res.points
                audit_trail.append(res.reason)
                logger.info("Scoring rule applied: %s", res.reason)

        is_qualified = not is_knocked_out and (total_score >= self.qualification_threshold)

        return ScoringResult(
            final_score=total_score,
            is_qualified=is_qualified,
            is_knocked_out=is_knocked_out,
            reasons=audit_trail,
        )
