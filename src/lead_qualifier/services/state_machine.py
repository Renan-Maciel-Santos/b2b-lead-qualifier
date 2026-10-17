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
from lead_qualifier.core.scoring.strategy import build_strategies_from_rules
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
    ) -> None:
        """Initialize state machine service with repository or unit of work dependencies.

        Args:
            repo: Optional ConversationRepository instance (for direct or mocked usage).
            llm_adapter: Optional OpenAI adapter instance (created on demand if omitted).
            scoring_service: Optional pre-configured scoring service (overrides dynamic loading).
            idempotency_timeout_seconds: Timeout after which stalled processing messages can be reclaimed.
            pool: Optional connection pool or direct connection for transaction-scoped unit of work.
            tenant_ctx: Optional immutable TenantContext.
        """
        self.repo = repo
        self.pool = pool
        self.tenant_ctx = tenant_ctx
        self.llm_adapter = llm_adapter or OpenAIAdapter()
        self.scoring_service = scoring_service
        self.idempotency_timeout_seconds = idempotency_timeout_seconds

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
    ) -> tuple[ScoringService, str]:
        """Resolve the scoring engine and active rule set identifier strictly from database.

        Args:
            repo: Active repository instance within the current unit of work.

        Raises:
            ActiveRuleSetNotFoundError: If no active rule set is configured for the tenant.

        Returns:
            tuple[ScoringService, str]: Initialized engine and database rule set ID.
        """
        rule_set = await repo.get_active_scoring_rule_set()

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

                scoring_engine, rule_set_id = await self._resolve_scoring_engine(repo)
                score_result = scoring_engine.calculate_score(lead_data)

                final_score = score_result.final_score
                is_qualified = score_result.is_qualified
                is_knocked_out = score_result.is_knocked_out
                reasons = score_result.reasons

                has_role = lead_data.get("role") is not None
                has_revenue = (
                    lead_data.get("revenue_tier") is not None
                    or lead_data.get("revenue") is not None
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

                    await repo.save_scoring_result(
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

                    await repo.save_scoring_result(
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
