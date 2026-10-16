"""Evaluation harness benchmarking model accuracy against a golden dataset."""

import asyncio
import json
from typing import Any

from lead_qualifier.core.scoring.strategy import ExactMatchStrategy, KnockoutStrategy
from lead_qualifier.integrations.llm.openai_adapter import OpenAIAdapter
from lead_qualifier.services.scoring_service import ScoringService


def load_golden_dataset() -> list[dict[str, Any]]:
    """Load human-evaluated evaluation cases from data/golden_dataset.json.

    Returns:
        list[dict[str, Any]]: Parsed golden dataset cases.
    """
    with open("data/golden_dataset.json", encoding="utf-8") as f:
        return json.load(f)


async def run_evaluation() -> None:
    """Run end-to-end evaluation comparing slot extraction and scoring against human-labeled ground truth."""
    dataset = load_golden_dataset()
    llm_adapter = OpenAIAdapter()

    strategies = [
        KnockoutStrategy(field="role", knockout_value="estudante"),
        ExactMatchStrategy(field="revenue", target_value="5 milhoes ao ano", points=50),
        ExactMatchStrategy(field="role", target_value="CEO", points=50),
    ]
    scoring_service = ScoringService(strategies)

    correct_predictions = 0
    total_cases = len(dataset)

    for case in dataset:
        conversation_history = case["conversation_history"]
        expected_qualification = case["expected_qualified"]

        print(f"\nEvaluating case {case['id']}...")
        slots = await llm_adapter.extract_slots(conversation_history)
        lead_data = slots.model_dump(exclude_none=True)

        result = scoring_service.calculate_score(lead_data)
        matched = result["is_qualified"] == expected_qualification

        if matched:
            correct_predictions += 1
            print(f"[OK] Prediction matched! (Expected: {expected_qualification}, Predicted: {result['is_qualified']})")
        else:
            print(f"[FAIL] Prediction mismatch! (Expected: {expected_qualification}, Predicted: {result['is_qualified']})")
            print(f"Machine reasons: {result['reasons']}")
            print(f"Extracted slots: {lead_data}")

    accuracy = (correct_predictions / total_cases) * 100
    print("\n=== Final Accuracy Evaluation ===")
    print(f"Correct: {correct_predictions} / {total_cases}")
    print(f"Accuracy: {accuracy:.2f}% (Target: 80%)")

    if accuracy < 80:
        print("WARNING: Accuracy fell below the 80% deployment threshold; prompt tuning required.")
    else:
        print("SUCCESS: Model accuracy satisfies production gate.")


if __name__ == "__main__":
    asyncio.run(run_evaluation())
