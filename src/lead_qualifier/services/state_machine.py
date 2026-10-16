"""Conversational state machine service orchestrating dialogue, LLM extraction, and scoring."""

from lead_qualifier.core.logger import logger
from lead_qualifier.core.masking import mask_phone_number
from lead_qualifier.core.schemas.conversation import TurnRequest, TurnResponse
from lead_qualifier.core.scoring.strategy import (
    ExactMatchStrategy,
    KnockoutStrategy,
    build_strategies_from_rules,
)
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

    async def _resolve_scoring_engine(self) -> tuple[ScoringService, str | None]:
        """Resolve the scoring engine and active rule set identifier.

        Returns:
            tuple[ScoringService, str | None]: Initialized engine and database rule set ID.
        """
        rule_set = await self.repo.get_active_scoring_rule_set()

        if self.scoring_service is not None:
            rule_set_id = str(rule_set["id"]) if rule_set else None
            return self.scoring_service, rule_set_id

        if rule_set is not None:
            strategies = build_strategies_from_rules(rule_set["rules"])
            threshold = int(rule_set.get("qualification_threshold", 50))
            return ScoringService(strategies, qualification_threshold=threshold), str(
                rule_set["id"]
            )

        logger.warning(
            "No active scoring_rule_set found for tenant; falling back to in-memory defaults."
        )
        default_strategies = [
            KnockoutStrategy(field="role", knockout_value="estudante"),
            ExactMatchStrategy(field="revenue", target_value="5 milhoes ao ano", points=50),
            ExactMatchStrategy(field="role", target_value="CEO", points=50),
        ]
        return ScoringService(default_strategies, qualification_threshold=50), None

    async def process_turn(self, request: TurnRequest) -> TurnResponse:
        """Process an inbound conversation turn and determine the appropriate response and next state.

        Args:
            request: Inbound turn payload containing message ID and user message.

        Returns:
            TurnResponse: System reply message, conversation state, and completion flag.
        """
        logger.info(
            f"Processing turn for lead {mask_phone_number(request.phone_number)} (Msg ID: {request.message_id})"
        )

        # Reject duplicated messages immediately based on the WhatsApp message ID
        if await self.repo.is_message_processed(request.message_id):
            logger.warning(f"Message {request.message_id} discarded due to idempotency check.")
            return TurnResponse(
                reply_message="",
                current_state="DUPLICATE_IGNORED",
                is_finished=False,
            )

        await self.repo.mark_message_processed(request.message_id)

        slots = await self.llm_adapter.extract_slots(request.user_message)
        lead_data = slots.model_dump(exclude_none=True)

        scoring_engine, rule_set_id = await self._resolve_scoring_engine()
        score_result = scoring_engine.calculate_score(lead_data)

        final_score = score_result["final_score"]
        is_qualified = score_result["is_qualified"]
        reasons = score_result["reasons"]

        # Immediate disqualification branch
        if final_score < -9000:
            logger.warning(
                f"Lead {mask_phone_number(request.phone_number)} disqualified immediately."
            )
            if rule_set_id:
                await self.repo.save_scoring_result(
                    phone_number=request.phone_number,
                    rule_set_id=rule_set_id,
                    final_score=final_score,
                    is_qualified=False,
                    audit_trail=reasons,
                )
            return TurnResponse(
                reply_message="Agradecemos o seu contato com a nossa equipe! No momento nosso atendimento e focado em clientes corporativos.",
                current_state="DISQUALIFIED",
                is_finished=True,
            )

        # Qualification completed branch
        if is_qualified or (slots.role is not None and slots.revenue is not None):
            logger.info(
                f"Lead {mask_phone_number(request.phone_number)} completed qualification with score {final_score}."
            )
            if rule_set_id:
                await self.repo.save_scoring_result(
                    phone_number=request.phone_number,
                    rule_set_id=rule_set_id,
                    final_score=final_score,
                    is_qualified=is_qualified,
                    audit_trail=reasons,
                )

            if is_qualified:
                reply = "Excelente! Seu perfil se encaixa perfeitamente nas solucoes da nossa plataforma. Um executivo de contas entrara em contato!"
                state = "QUALIFIED"
            else:
                reply = "Muito obrigado pelas informacoes! Seu cadastro foi recebido com sucesso pela nossa equipe comercial."
                state = "NOT_QUALIFIED"

            return TurnResponse(
                reply_message=reply,
                current_state=state,
                is_finished=True,
            )

        # Slot filling dialogue progression
        if slots.role is None:
            return TurnResponse(
                reply_message="Ola! Para direcionarmos a melhor solucao da plataforma, qual o seu cargo ou atuacao na empresa?",
                current_state="AWAITING_ROLE",
                is_finished=False,
            )

        return TurnResponse(
            reply_message="Entendido! E qual a media de faturamento anual ou mensal da sua empresa atualmente?",
            current_state="AWAITING_REVENUE",
            is_finished=False,
        )
