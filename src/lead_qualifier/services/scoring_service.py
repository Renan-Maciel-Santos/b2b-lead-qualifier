"""Lead scoring engine executing composite qualification strategies."""

from typing import Any

from lead_qualifier.core.logger import logger
from lead_qualifier.core.scoring.strategy import ScoringStrategy


class ScoringService:
    """Service evaluating lead attributes against a collection of configured scoring strategies."""

    def __init__(
        self,
        strategies: list[ScoringStrategy],
        qualification_threshold: int = 50,
    ) -> None:
        """Initialize scoring service.

        Args:
            strategies: Ordered collection of scoring strategies to evaluate.
            qualification_threshold: Minimum total score required for positive qualification.
        """
        self.strategies = strategies
        self.qualification_threshold = qualification_threshold

    def calculate_score(self, lead_data: dict[str, Any]) -> dict[str, Any]:
        """Evaluate lead data against active strategies and produce an audit trail.

        Halts evaluation early if an immediate knockout penalty (< -9000) is encountered.

        Args:
            lead_data: Key-value dictionary of extracted lead attributes.

        Returns:
            dict[str, Any]: Dictionary containing final_score, reasons (audit trail), and is_qualified.
        """
        total_score = 0
        audit_trail: list[str] = []

        for strategy in self.strategies:
            points, reason = strategy.evaluate(lead_data)

            if points != 0:
                total_score += points
                audit_trail.append(reason)
                logger.info(f"Scoring rule applied: {reason}")

            # Stop immediately on knockout penalty to prevent unnecessary processing
            if total_score < -9000:
                logger.warning("Lead met knockout criterion; halting rule evaluation early.")
                break

        return {
            "final_score": total_score,
            "reasons": audit_trail,
            "is_qualified": total_score >= self.qualification_threshold,
        }
