"""Comprehensive unit tests for lead scoring strategies and scoring service (90%+ coverage target)."""

from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from lead_qualifier.core.enums import ConversationState
from lead_qualifier.core.exceptions import ActiveRuleSetNotFoundError
from lead_qualifier.core.schemas.conversation import TurnRequest
from lead_qualifier.core.scoring.strategy import (
    ExactMatchStrategy,
    KnockoutStrategy,
    StrategyResult,
    build_strategies_from_rules,
    parse_rule_set_config,
)
from lead_qualifier.services.scoring_service import ScoringResult, ScoringService
from lead_qualifier.services.state_machine import StateMachineService


def test_strategy_result_defaults() -> None:
    """Verify default attribute values of StrategyResult."""
    res = StrategyResult()
    assert res.points == 0
    assert res.reason == ""
    assert res.is_knockout is False


def test_exact_match_strategy_awards_points() -> None:
    """Verify that ExactMatchStrategy awards points on exact value match."""
    strategy = ExactMatchStrategy(field="role", target_value="CEO", points=50)
    lead_data = {"role": "CEO", "name": "Alice"}

    result = strategy.evaluate(lead_data)

    assert result.points == 50
    assert "equals 'CEO'" in result.reason
    assert result.is_knockout is False


def test_exact_match_strategy_no_match() -> None:
    """Verify that ExactMatchStrategy returns 0 points when value differs or field is missing."""
    strategy = ExactMatchStrategy(field="role", target_value="CEO", points=50)

    # Different value
    res1 = strategy.evaluate({"role": "Intern"})
    assert res1.points == 0
    assert res1.is_knockout is False

    # Missing field
    res2 = strategy.evaluate({"other_field": "123"})
    assert res2.points == 0
    assert res2.is_knockout is False

    # None value
    res3 = strategy.evaluate({"role": None})
    assert res3.points == 0


def test_exact_match_strategy_with_falsy_target() -> None:
    """Verify that ExactMatchStrategy correctly matches falsy targets (e.g. 0, False)."""
    strategy_zero = ExactMatchStrategy(field="tier", target_value=0, points=30)
    result_zero = strategy_zero.evaluate({"tier": 0})
    assert result_zero.points == 30

    strategy_false = ExactMatchStrategy(field="is_partner", target_value=False, points=10)
    result_false = strategy_false.evaluate({"is_partner": False})
    assert result_false.points == 10


def test_knockout_strategy_triggers_knockout() -> None:
    """Verify that KnockoutStrategy triggers is_knockout on restricted value."""
    strategy = KnockoutStrategy(field="role", knockout_value="estudante")
    lead_data = {"role": "estudante"}

    result = strategy.evaluate(lead_data)

    assert result.is_knockout is True
    assert result.points == 0
    assert "Disqualified" in result.reason


def test_knockout_strategy_no_trigger() -> None:
    """Verify that KnockoutStrategy does not trigger when value differs or field is missing."""
    strategy = KnockoutStrategy(field="role", knockout_value="estudante")

    res1 = strategy.evaluate({"role": "CEO"})
    assert res1.is_knockout is False

    res2 = strategy.evaluate({"name": "Bob"})
    assert res2.is_knockout is False

    res3 = strategy.evaluate({"role": None})
    assert res3.is_knockout is False


def test_knockout_strategy_with_falsy_value() -> None:
    """Verify that KnockoutStrategy triggers properly on falsy knockout values (e.g. 0)."""
    strategy = KnockoutStrategy(field="score", knockout_value=0)
    res = strategy.evaluate({"score": 0})
    assert res.is_knockout is True


def test_scoring_service_halts_immediately_on_knockout() -> None:
    """Verify that scoring evaluation stops immediately when a knockout rule is encountered."""
    strategies = [
        KnockoutStrategy(field="role", knockout_value="estudante"),
        ExactMatchStrategy(field="revenue", target_value="above_10m", points=100),
    ]
    service = ScoringService(strategies, qualification_threshold=50)

    # Lead has both the restricted role and the high revenue
    lead_data = {"role": "estudante", "revenue": "above_10m"}
    result: ScoringResult = service.calculate_score(lead_data)

    assert result.is_knocked_out is True
    assert result.is_qualified is False
    assert result.final_score == 0
    assert len(result.reasons) == 1
    assert "Disqualified" in result.reasons[0]


def test_scoring_service_threshold_evaluation() -> None:
    """Verify qualification verdict according to configured threshold."""
    strategies = [
        ExactMatchStrategy(field="role", target_value="CEO", points=40),
        ExactMatchStrategy(field="revenue", target_value="above_10m", points=20),
    ]
    service = ScoringService(strategies, qualification_threshold=50)

    # 40 points -> below threshold
    res_below = service.calculate_score({"role": "CEO"})
    assert res_below.final_score == 40
    assert res_below.is_qualified is False
    assert res_below.is_knocked_out is False

    # 60 points -> meets threshold
    res_above = service.calculate_score({"role": "CEO", "revenue": "above_10m"})
    assert res_above.final_score == 60
    assert res_above.is_qualified is True
    assert res_above.is_knocked_out is False


def test_scoring_service_empty_lead_data() -> None:
    """Verify that empty lead attributes safely result in 0 score and unqualified verdict."""
    strategies = [
        KnockoutStrategy(field="role", knockout_value="estudante"),
        ExactMatchStrategy(field="role", target_value="CEO", points=50),
    ]
    service = ScoringService(strategies, qualification_threshold=50)

    result = service.calculate_score({})
    assert result.final_score == 0
    assert result.is_qualified is False
    assert result.is_knocked_out is False
    assert result.reasons == []


def test_build_strategies_from_rules_valid() -> None:
    """Verify successful instantiation of strategies from valid JSONB rule specifications."""
    rules: list[dict[str, Any]] = [
        {"type": "knockout", "field": "role", "value": "estudante"},
        {"type": "exact_match", "field": "role", "value": "CEO", "points": 50},
        {"type": "exact_match", "field": "revenue", "target_value": "above_10m", "points": 50},
    ]

    strategies = build_strategies_from_rules(rules)
    assert len(strategies) == 3
    assert isinstance(strategies[0], KnockoutStrategy)
    assert isinstance(strategies[1], ExactMatchStrategy)
    assert isinstance(strategies[2], ExactMatchStrategy)


def test_build_strategies_from_rules_with_falsy_values() -> None:
    """Verify that build_strategies does not drop falsy rule values (e.g. value=0 or value=False)."""
    rules: list[dict[str, Any]] = [
        {"type": "knockout", "field": "level", "value": 0},
        {"type": "exact_match", "field": "active", "value": False, "points": 10},
    ]

    strategies = build_strategies_from_rules(rules)
    assert strategies[0].knockout_value == 0  # type: ignore[attr-defined]
    assert strategies[1].target_value is False  # type: ignore[attr-defined]


def test_build_strategies_rejects_unknown_rule_type() -> None:
    """Verify that unknown rule types trigger a Pydantic ValidationError."""
    invalid_rules: list[dict[str, Any]] = [
        {"type": "unsupported_rule_type", "field": "role", "value": "CEO"}
    ]
    with pytest.raises(ValidationError):
        build_strategies_from_rules(invalid_rules)


def test_build_strategies_rejects_missing_mandatory_fields() -> None:
    """Verify that rules missing required fields (e.g. points in exact_match) trigger ValidationError."""
    incomplete_rules: list[dict[str, Any]] = [
        {"type": "exact_match", "field": "role", "value": "CEO"}  # Missing 'points'
    ]
    with pytest.raises(ValidationError):
        build_strategies_from_rules(incomplete_rules)


@pytest.mark.asyncio
async def test_state_machine_raises_when_no_active_rule_set() -> None:
    """Verify that StateMachineService raises ActiveRuleSetNotFoundError when DB has no active rules."""
    mock_repo = AsyncMock()
    mock_repo.acquire_message_lock.return_value = True
    mock_repo.get_conversation_state_read_only.return_value = ("INITIAL", {})
    mock_repo.get_or_create_conversation_state.return_value = ("INITIAL", {})
    mock_repo.get_active_scoring_rule_set.return_value = None

    mock_llm = AsyncMock()
    mock_llm.extract_slots.return_value = AsyncMock(model_dump=lambda **_: {"role": "CEO"})

    service = StateMachineService(repo=mock_repo, llm_adapter=mock_llm)

    request = TurnRequest(
        message_id="msg_test_no_rules",
        phone_number="+5511999990000",
        user_message="Sou CEO",
    )

    with pytest.raises(ActiveRuleSetNotFoundError):
        await service.process_turn(request)


def test_rule_set_rejects_missing_or_empty_required_slots() -> None:
    """Verify that rule sets without mandatory required_slots trigger a ValidationError."""
    rules: list[dict[str, Any]] = [
        {"type": "knockout", "field": "role", "value": "estagiario"},
        {"type": "exact_match", "field": "role", "value": "CEO", "points": 50},
    ]

    # 1. Rejects dictionary payload missing required_slots
    with pytest.raises(ValidationError):
        parse_rule_set_config({"rules": rules})

    # 2. Rejects raw list payload without required_slots envelope
    with pytest.raises(ValidationError):
        parse_rule_set_config(rules)

    # 3. Rejects empty required_slots list
    with pytest.raises(ValidationError):
        parse_rule_set_config({"rules": rules, "required_slots": []})


def test_rule_set_rejects_invalid_required_slot_fields_or_duplicates() -> None:
    """Verify that required_slots rejects unknown fields or duplicate entries."""
    rules: list[dict[str, Any]] = [
        {"type": "exact_match", "field": "role", "value": "CEO", "points": 50},
    ]

    # 1. Rejects non-existent slot fields
    with pytest.raises(ValidationError) as exc_info:
        parse_rule_set_config({"rules": rules, "required_slots": ["non_existent_slot"]})
    assert "not a valid field in LeadSlots" in str(exc_info.value)

    # 2. Rejects duplicate slots
    with pytest.raises(ValidationError) as exc_info2:
        parse_rule_set_config({"rules": rules, "required_slots": ["role", "role"]})
    assert "duplicate fields" in str(exc_info2.value)


@pytest.mark.asyncio
async def test_state_machine_question_order_respects_required_slots_list() -> None:
    """Verify that the state machine prompts for missing slots strictly in the declared order."""
    scoring_service = ScoringService(
        strategies=[
            ExactMatchStrategy(field="role", target_value="CEO", points=50),
            ExactMatchStrategy(field="revenue", target_value="5m", points=50),
        ],
        qualification_threshold=50,
    )

    mock_llm = AsyncMock()
    mock_llm.extract_slots.return_value = AsyncMock(model_dump=lambda **_: {})

    mock_repo = AsyncMock()
    mock_repo.acquire_message_lock.return_value = True
    mock_repo.get_conversation_state_read_only.return_value = ("INITIAL", {})
    mock_repo.get_or_create_conversation_state.return_value = ("INITIAL", {})
    mock_repo.save_conversation_state.return_value = None
    mock_repo.mark_message_done.return_value = None

    # Order 1: revenue declared before role -> prompts for revenue first
    service_rev_first = StateMachineService(
        repo=mock_repo,
        llm_adapter=mock_llm,
        scoring_service=scoring_service,
        required_slots=["revenue", "role"],
    )
    req1 = TurnRequest(message_id="msg_order_1", phone_number="+5511999991111", user_message="Ola")
    res1 = await service_rev_first.process_turn(req1)
    assert res1.current_state == ConversationState.AWAITING_REVENUE

    # Order 2: role declared before revenue -> prompts for role first
    service_role_first = StateMachineService(
        repo=mock_repo,
        llm_adapter=mock_llm,
        scoring_service=scoring_service,
        required_slots=["role", "revenue"],
    )
    req2 = TurnRequest(message_id="msg_order_2", phone_number="+5511999992222", user_message="Ola")
    res2 = await service_role_first.process_turn(req2)
    assert res2.current_state == ConversationState.AWAITING_ROLE
