"""Conversational state machine service orchestrating dialogue, LLM extraction, and scoring."""

from typing import Any

from lead_qualifier.core.enums import ConversationState
from lead_qualifier.core.exceptions import ActiveRuleSetNotFoundError
from lead_qualifier.core.logger import logger
from lead_qualifier.core.masking import mask_phone_number
from lead_qualifier.core.messages import (
    ASK_REVENUE_REPLY,
    ASK_ROLE_REPLY,
    DISQUALIFIED_REPLY,
    NOT_QUALIFIED_REPLY,
    QUALIFIED_REPLY,
)
from lead_qualifier.core.schemas.conversation import TurnRequest, TurnResponse
from lead_qualifier.core.scoring.strategy import build_strategies_from_rules
from lead_qualifier.integrations.llm.openai_adapter import OpenAIAdapter
from lead_qualifier.repositories.conversation_repo import ConversationRepository
from lead_qualifier.services.scoring_service import ScoringService


class StateMachineService:
    """Orchestrates dialogue turns by coordinating slot extraction, state transitions, and scoring."""

    def __init__(
        self,
        repo: ConversationRepository,
        llm_adapter: OpenAIAdapter | None = None,
        scoring_service: ScoringService | None = None,
    ) -> None:
        """Initialize state machine service with repository and optional adapters.

        Args:
            repo: ConversationRepository for database persistence and idempotency.
            llm_adapter: Optional OpenAI adapter instance (created on demand if omitted).
            scoring_service: Optional pre-configured scoring service (overrides dynamic loading).
        """
        self.repo = repo
        self.llm_adapter = llm_adapter or OpenAIAdapter()
        self.scoring_service = scoring_service

    async def _resolve_scoring_engine(self) -> tuple[ScoringService, str]:
        """Resolve the scoring engine and active rule set identifier strictly from database.

        Raises:
            ActiveRuleSetNotFoundError: If no active rule set is configured for the tenant.

        Returns:
            tuple[ScoringService, str]: Initialized engine and database rule set ID.
        """
        rule_set = await self.repo.get_active_scoring_rule_set()

        if self.scoring_service is not None:
            rule_set_id = str(rule_set["id"]) if rule_set else "injected"
            return self.scoring_service, rule_set_id

        if rule_set is not None:
            strategies = build_strategies_from_rules(rule_set["rules"])
            threshold = int(rule_set.get("qualification_threshold", 50))
            return ScoringService(strategies, qualification_threshold=threshold), str(
                rule_set["id"]
            )

        logger.error("No active scoring_rule_set configured for tenant in database.")
        raise ActiveRuleSetNotFoundError("No active scoring rule set found for tenant.")

    async def process_turn(self, request: TurnRequest) -> TurnResponse:
        """Process an inbound conversation turn and determine the appropriate response and next state.

        Coordinates atomic idempotency, per-lead row locking, multi-turn slot accumulation,
        deterministic rule scoring, and state persistence.

        Args:
            request: Inbound turn payload containing message ID and user message.

        Returns:
            TurnResponse: System reply message, conversation state, and completion flag.
        """
        logger.info(
            f"Processing turn for lead {mask_phone_number(request.phone_number)} (Msg ID: {request.message_id})"
        )

        # Atomic idempotency: insert-or-ignore returning check guarantees race-free execution
        acquired = await self.repo.acquire_message_lock(request.message_id)
        if not acquired:
            logger.warning(
                f"Message {request.message_id} discarded due to atomic idempotency check."
            )
            return TurnResponse(
                reply_message="",
                current_state=ConversationState.DUPLICATE_IGNORED,
                is_finished=False,
            )

        # Retrieve current conversation state and accumulated slots with an exclusive row lock
        _prev_state, accumulated_slots = await self.repo.get_or_create_conversation_state(
            request.phone_number
        )

        # Extract semantic slots from the inbound message
        slots = await self.llm_adapter.extract_slots(request.user_message)
        new_slots = slots.model_dump(exclude_none=True)

        # Accumulate and merge newly extracted slots over previous turn history
        lead_data: dict[str, Any] = {**accumulated_slots, **new_slots}

        scoring_engine, rule_set_id = await self._resolve_scoring_engine()
        score_result = scoring_engine.calculate_score(lead_data)

        final_score = score_result.final_score
        is_qualified = score_result.is_qualified
        is_knocked_out = score_result.is_knocked_out
        reasons = score_result.reasons

        has_role = lead_data.get("role") is not None
        has_revenue = (
            lead_data.get("revenue_tier") is not None or lead_data.get("revenue") is not None
        )

        # Branch 1: Immediate disqualification (knockout rule triggered)
        if is_knocked_out:
            logger.warning(
                f"Lead {mask_phone_number(request.phone_number)} disqualified immediately."
            )
            new_state = ConversationState.DISQUALIFIED
            reply = DISQUALIFIED_REPLY
            is_finished = True

            await self.repo.save_scoring_result(
                phone_number=request.phone_number,
                rule_set_id=rule_set_id,
                final_score=final_score,
                is_qualified=False,
                audit_trail=reasons,
            )

        # Branch 2: Lead qualified or all required slots collected
        elif is_qualified or (has_role and has_revenue):
            logger.info(
                f"Lead {mask_phone_number(request.phone_number)} completed qualification with score {final_score}."
            )
            if is_qualified:
                new_state = ConversationState.QUALIFIED
                reply = QUALIFIED_REPLY
            else:
                new_state = ConversationState.NOT_QUALIFIED
                reply = NOT_QUALIFIED_REPLY
            is_finished = True

            await self.repo.save_scoring_result(
                phone_number=request.phone_number,
                rule_set_id=rule_set_id,
                final_score=final_score,
                is_qualified=is_qualified,
                audit_trail=reasons,
            )

        # Branch 3: Slot filling - role missing
        elif not has_role:
            new_state = ConversationState.AWAITING_ROLE
            reply = ASK_ROLE_REPLY
            is_finished = False

        # Branch 4: Slot filling - revenue missing
        else:
            new_state = ConversationState.AWAITING_REVENUE
            reply = ASK_REVENUE_REPLY
            is_finished = False

        # Persist updated state and merged accumulated slots
        await self.repo.save_conversation_state(
            phone_number=request.phone_number,
            current_state=new_state,
            accumulated_slots=lead_data,
        )

        return TurnResponse(
            reply_message=reply,
            current_state=new_state,
            is_finished=is_finished,
        )
