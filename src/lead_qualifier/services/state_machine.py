"""Conversational state machine service orchestrating dialogue, LLM extraction, and scoring."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from lead_qualifier.core.database import tenant_transaction
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
from lead_qualifier.core.scoring.strategy import parse_rule_set_config
from lead_qualifier.core.tenant import TenantContext
from lead_qualifier.integrations.llm.openai_adapter import OpenAIAdapter
from lead_qualifier.repositories.conversation_repo import ConversationRepository
from lead_qualifier.services.scoring_service import ScoringService


class StateMachineService:
    """Orchestrates dialogue turns by coordinating slot extraction, state transitions, and scoring."""

    def __init__(
        self,
        repo: ConversationRepository | None = None,
        llm_adapter: OpenAIAdapter | None = None,
        scoring_service: ScoringService | None = None,
        idempotency_timeout_seconds: int = 60,
        pool: AsyncConnectionPool | AsyncConnection | None = None,
        tenant_ctx: TenantContext | None = None,
        required_slots: list[str] | None = None,
    ) -> None:
        """Initialize state machine service with repository or unit of work dependencies.

        Args:
            repo: Optional ConversationRepository instance (for direct or mocked usage).
            llm_adapter: Optional OpenAI adapter instance (created on demand if omitted).
            scoring_service: Optional pre-configured scoring service (overrides dynamic loading).
            idempotency_timeout_seconds: Timeout after which stalled processing messages can be reclaimed.
            pool: Optional connection pool or direct connection for transaction-scoped unit of work.
            tenant_ctx: Optional immutable TenantContext.
            required_slots: Optional list of mandatory slots before qualification can complete.
        """
        self.repo = repo
        self.pool = pool
        self.tenant_ctx = tenant_ctx
        self.llm_adapter = llm_adapter or OpenAIAdapter()
        self.scoring_service = scoring_service
        self.idempotency_timeout_seconds = idempotency_timeout_seconds
        self.required_slots = required_slots

    @asynccontextmanager
    async def _uow(self) -> AsyncIterator[ConversationRepository]:
        """Provide a tenant-scoped unit of work yielding a ConversationRepository.

        If a connection pool or direct connection with tenant_ctx is configured,
        executes inside an atomic tenant_transaction. Otherwise, falls back to
        the injected repository instance (e.g. in unit tests with mocks).
        """
        if self.pool is not None and self.tenant_ctx is not None:
            async with tenant_transaction(self.pool, self.tenant_ctx) as conn:
                yield ConversationRepository(conn)
        elif self.repo is not None:
            yield self.repo
            # Trigger mock commit if present for unit test call verification
            if hasattr(self.repo, "conn") and hasattr(self.repo.conn, "commit"):
                res = self.repo.conn.commit()
                if asyncio.iscoroutine(res):
                    await res
        else:
            raise RuntimeError("StateMachineService requires either (pool, tenant_ctx) or repo.")

    async def _resolve_scoring_engine(
        self,
        repo: ConversationRepository,
    ) -> tuple[ScoringService, str, list[str]]:
        """Resolve the scoring engine, rule set ID, and required slot dependencies.

        Args:
            repo: Active repository instance within the current unit of work.

        Raises:
            ActiveRuleSetNotFoundError: If no active rule set is configured for the tenant.

        Returns:
            tuple[ScoringService, str, list[str]]: Engine, rule set ID, and mandatory slots.
        """
        rule_set = await repo.get_active_scoring_rule_set()

        if self.scoring_service is not None:
            rule_set_id = str(rule_set["id"]) if rule_set else "injected"
            if self.required_slots is not None:
                req_slots = self.required_slots
            elif rule_set is not None:
                _, req_slots = parse_rule_set_config(rule_set)
            else:
                req_slots = ["role", "revenue"]
            return self.scoring_service, rule_set_id, req_slots

        if rule_set is not None:
            strategies, required_slots = parse_rule_set_config(rule_set)
            req_slots = self.required_slots if self.required_slots is not None else required_slots
            threshold = int(rule_set.get("qualification_threshold", 50))
            return (
                ScoringService(strategies, qualification_threshold=threshold),
                str(rule_set["id"]),
                req_slots,
            )

        logger.error("No active scoring_rule_set configured for tenant in database.")
        raise ActiveRuleSetNotFoundError("No active scoring rule set found for tenant.")

    async def process_turn(self, request: TurnRequest) -> TurnResponse:
        """Process an inbound conversation turn with decoupled transaction boundaries.

        Execution lifecycle:
        1. Unit of work 1: Atomic idempotency registration and terminal state check in a short transaction.
        2. Unbounded LLM semantic slot extraction strictly outside of database locks or checked-out connections.
        3. Unit of work 2: Second short transaction exclusively locking conversation state via
           SELECT ... FOR UPDATE, merging slots, evaluating deterministic scoring, persisting state &
           audit trail, and marking message done.

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

        # Unit of Work 1: Idempotency registration and terminal state pre-check
        async with self._uow() as repo:
            acquired = await repo.acquire_message_lock(
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

            # Check if lead conversation is already in a terminal state
            prev_state, _ = await repo.get_conversation_state_read_only(request.phone_number)
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
                await repo.mark_message_done(request.message_id)
                return TurnResponse(
                    reply_message=CONVERSATION_FINISHED_REPLY,
                    current_state=ConversationState(prev_state),
                    is_finished=True,
                )

        # Unit of Work 1 completed and connection returned to pool before calling LLM
        # Step 2: Extract semantic slots outside any active transaction or checked-out connection
        try:
            slots = await self.llm_adapter.extract_slots(request.user_message)
            new_slots = slots.model_dump(exclude_none=True)

            # Unit of Work 2: Lock conversation state, merge slots, score, persist, mark done
            async with self._uow() as repo:
                locked_state, accumulated_slots = await repo.get_or_create_conversation_state(
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
                    await repo.mark_message_done(request.message_id)
                    return TurnResponse(
                        reply_message=CONVERSATION_FINISHED_REPLY,
                        current_state=ConversationState(locked_state),
                        is_finished=True,
                    )

                # Accumulate and merge newly extracted slots over previous turn history
                lead_data: dict[str, Any] = {**accumulated_slots, **new_slots}

                scoring_engine, rule_set_id, required_slots = await self._resolve_scoring_engine(
                    repo
                )
                score_result = scoring_engine.calculate_score(lead_data)

                final_score = score_result.final_score
                is_qualified = score_result.is_qualified
                is_knocked_out = score_result.is_knocked_out
                reasons = score_result.reasons

                def _is_slot_filled(slot_name: str, data: dict[str, Any]) -> bool:
                    if slot_name in ("revenue", "revenue_tier"):
                        return (
                            data.get("revenue_tier") is not None or data.get("revenue") is not None
                        )
                    val = data.get(slot_name)
                    return val is not None and val != ""

                missing_slots = [s for s in required_slots if not _is_slot_filled(s, lead_data)]

                # Branch 1: Immediate disqualification (knockout rule triggered at any time)
                if is_knocked_out:
                    logger.warning(
                        "Lead %s disqualified immediately via knockout rule.",
                        mask_phone_number(request.phone_number),
                    )
                    new_state = ConversationState.DISQUALIFIED
                    reply = DISQUALIFIED_REPLY
                    is_finished = True

                    await repo.save_scoring_result(
                        phone_number=request.phone_number,
                        rule_set_id=rule_set_id,
                        final_score=final_score,
                        is_qualified=False,
                        audit_trail=reasons,
                    )

                # Branch 2: All required slots collected -> final evaluation (QUALIFIED or NOT_QUALIFIED)
                elif not missing_slots:
                    logger.info(
                        "Lead %s completed all required slots with score %s.",
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

                    await repo.save_scoring_result(
                        phone_number=request.phone_number,
                        rule_set_id=rule_set_id,
                        final_score=final_score,
                        is_qualified=is_qualified,
                        audit_trail=reasons,
                    )

                # Branch 3: Missing required slot(s) -> ask next missing slot in configured order
                else:
                    next_slot = missing_slots[0]
                    if next_slot in ("revenue", "revenue_tier"):
                        new_state = ConversationState.AWAITING_REVENUE
                        reply = ASK_REVENUE_REPLY
                    elif next_slot == "role":
                        new_state = ConversationState.AWAITING_ROLE
                        reply = ASK_ROLE_REPLY
                    else:
                        candidate_state = f"AWAITING_{next_slot.upper()}"
                        new_state = (
                            ConversationState(candidate_state)
                            if candidate_state in ConversationState._value2member_map_
                            else ConversationState.AWAITING_ROLE
                        )
                        reply = f"Por favor, informe seu {next_slot}."
                    is_finished = False
                    # Do not save scoring_result until a final terminal state is reached

                # Persist updated state and merged accumulated slots
                await repo.save_conversation_state(
                    phone_number=request.phone_number,
                    current_state=new_state.value,
                    accumulated_slots=lead_data,
                )
                await repo.mark_message_done(request.message_id)

                logger.info(
                    "Turn finished for lead %s. Next state: %s, Score: %d",
                    mask_phone_number(request.phone_number),
                    new_state,
                    final_score,
                )
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
            # Reclaim / mark message as failed for retry in a dedicated unit of work
            try:
                async with self._uow() as repo:
                    await repo.mark_message_failed(request.message_id)
            except Exception as mark_err:
                logger.warning(
                    "Failed to record message %s failure status: %s",
                    request.message_id,
                    mark_err,
                )
            raise exc
