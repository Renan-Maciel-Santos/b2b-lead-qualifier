"""Conversational state machine service orchestrating dialogue, LLM extraction, and scoring."""

from typing import Any

from lead_qualifier.core.enums import ConversationState
from lead_qualifier.core.exceptions import ActiveRuleSetNotFoundError
from lead_qualifier.core.logger import logger
from lead_qualifier.core.masking import mask_phone_number
from lead_qualifier.core.messages import (
    ASK_REVENUE_REPLY,
    ASK_ROLE_REPLY,
    CONVERSATION_FINISHED_REPLY,
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
        idempotency_timeout_seconds: int = 60,
    ) -> None:
        """Initialize state machine service with repository and optional adapters.

        Args:
            repo: ConversationRepository for database persistence and idempotency.
            llm_adapter: Optional OpenAI adapter instance (created on demand if omitted).
            scoring_service: Optional pre-configured scoring service (overrides dynamic loading).
            idempotency_timeout_seconds: Timeout after which stalled processing messages can be reclaimed.
        """
        self.repo = repo
        self.llm_adapter = llm_adapter or OpenAIAdapter()
        self.scoring_service = scoring_service
        self.idempotency_timeout_seconds = idempotency_timeout_seconds

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
        """Process an inbound conversation turn with decoupled transaction boundaries.

        Execution lifecycle:
        1. Atomic idempotency registration in a dedicated short transaction with immediate commit.
        2. Unbounded LLM semantic slot extraction outside of database locks or active transactions.
        3. Second short transaction: exclusively locks conversation state via SELECT ... FOR UPDATE,
           merges slots, evaluates deterministic scoring, persists state & audit trail, marks message
           done, and commits atomically.

        Args:
            request: Inbound turn payload containing message ID and user message.

        Returns:
            TurnResponse: System reply message, conversation state, and completion flag.
        """
        logger.info(
            "Processing turn for lead %s (Msg ID: %s)",
            mask_phone_number(request.phone_number),
            request.message_id,
        )

        # Step 1: Idempotency registration in its own short transaction (commits immediately)
        acquired = await self.repo.acquire_message_lock(
            request.message_id,
            timeout_seconds=self.idempotency_timeout_seconds,
        )
        if not acquired:
            logger.warning(
                "Message %s discarded due to atomic idempotency check.",
                request.message_id,
            )
            return TurnResponse(
                reply_message="",
                current_state=ConversationState.DUPLICATE_IGNORED,
                is_finished=False,
            )

        try:
            # Step 2: Check if lead conversation is already in a terminal state (QUALIFIED, NOT_QUALIFIED, DISQUALIFIED)
            prev_state, _ = await self.repo.get_conversation_state_read_only(request.phone_number)
            if prev_state in (
                ConversationState.QUALIFIED,
                ConversationState.NOT_QUALIFIED,
                ConversationState.DISQUALIFIED,
            ):
                logger.info(
                    "Lead %s is in terminal state %s; skipping LLM extraction and scoring.",
                    mask_phone_number(request.phone_number),
                    prev_state,
                )
                await self.repo.mark_message_done(request.message_id)
                await self.repo.conn.commit()
                return TurnResponse(
                    reply_message=CONVERSATION_FINISHED_REPLY,
                    current_state=ConversationState(prev_state),
                    is_finished=True,
                )

            # Step 3: Extract semantic slots outside any active transaction or row lock
            slots = await self.llm_adapter.extract_slots(request.user_message)
            new_slots = slots.model_dump(exclude_none=True)

            # Step 4: Second short transaction - lock conversation state, merge slots, score, persist
            locked_state, accumulated_slots = await self.repo.get_or_create_conversation_state(
                request.phone_number
            )

            # Re-verify terminal state under lock in case another turn finished concurrently
            if locked_state in (
                ConversationState.QUALIFIED,
                ConversationState.NOT_QUALIFIED,
                ConversationState.DISQUALIFIED,
            ):
                logger.info(
                    "Lead %s reached terminal state %s concurrently; skipping re-evaluation.",
                    mask_phone_number(request.phone_number),
                    locked_state,
                )
                await self.repo.mark_message_done(request.message_id)
                await self.repo.conn.commit()
                return TurnResponse(
                    reply_message=CONVERSATION_FINISHED_REPLY,
                    current_state=ConversationState(locked_state),
                    is_finished=True,
                )

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
                    "Lead %s disqualified immediately.",
                    mask_phone_number(request.phone_number),
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
                    "Lead %s completed qualification with score %s.",
                    mask_phone_number(request.phone_number),
                    final_score,
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
                current_state=new_state.value,
                accumulated_slots=lead_data,
            )
            await self.repo.mark_message_done(request.message_id)

            # Atomically commit Transaction 2
            await self.repo.conn.commit()

            return TurnResponse(
                reply_message=reply,
                current_state=new_state,
                is_finished=is_finished,
            )

        except Exception as exc:
            logger.error(
                "Error processing turn for message %s: %s",
                request.message_id,
                exc,
                exc_info=True,
            )
            try:
                await self.repo.mark_message_failed(request.message_id)
            except Exception as mark_err:
                logger.warning(
                    "Failed to record message %s failure status: %s",
                    request.message_id,
                    mark_err,
                )
            raise exc
