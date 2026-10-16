# Importa o logger global do sistema
from src.app.core.logger import logger

# Importa as estruturas de dados de requisicao e resposta
from src.app.core.schemas.conversation import TurnRequest, TurnResponse

# Importa as regras de negocio do motor de scoring e a factory
from src.app.core.scoring.strategy import (
    ExactMatchStrategy,
    KnockoutStrategy,
    build_strategies_from_rules,
)

# Importa o adaptador de extracao de slots da OpenAI
from src.app.integrations.llm.openai_adapter import OpenAIAdapter

# Importa o repositorio de conversas
from src.app.repositories.conversation_repo import ConversationRepository

# Importa o motor executor de pontuacao (Scoring)
from src.app.services.scoring_service import ScoringService


# Cria o servico responsavel por gerenciar as regras de negocio da maquina de estados do Chatbot
class StateMachineService:
    """Orquestra o ciclo conversacional com o lead, conectando LLM, maquina de estados e pontuacao."""

    # Ao ser instanciado, permite injetar repositorio, adaptador LLM e servico de scoring (opcional para testes)
    def __init__(
        self,
        repo: ConversationRepository,
        llm_adapter: OpenAIAdapter | None = None,
        scoring_service: ScoringService | None = None,
    ):
        # Guarda a instancia do repositorio na memoria do objeto
        self.repo = repo
        # Instancia ou reutiliza o adaptador inteligente da OpenAI
        self.llm_adapter = llm_adapter or OpenAIAdapter()
        # Servico de scoring opcionalmente pre-configurado
        self.scoring_service = scoring_service

    # Resolve o motor de scoring e o identificador do conjunto de regras (do banco ou injetado)
    async def _resolve_scoring_engine(self) -> tuple[ScoringService, str | None]:
        # Busca a regra ativa persistida para o tenant no banco
        rule_set = await self.repo.get_active_scoring_rule_set()

        # Se um servico especifico foi fornecido no construtor
        if self.scoring_service is not None:
            rule_set_id = str(rule_set["id"]) if rule_set else None
            return self.scoring_service, rule_set_id

        # Se encontrou regra ativa configurada no banco (ADR 003: data-driven)
        if rule_set is not None:
            strategies = build_strategies_from_rules(rule_set["rules"])
            threshold = int(rule_set.get("qualification_threshold", 50))
            return ScoringService(strategies, qualification_threshold=threshold), str(rule_set["id"])

        # Fallback padrao caso nenhum conjunto ativo tenha sido encontrado
        logger.warning("Nenhum scoring_rule_set ativo encontrado para o tenant. Usando regras padrao em memoria.")
        default_strategies = [
            KnockoutStrategy(field="role", knockout_value="estudante"),
            ExactMatchStrategy(field="revenue", target_value="5 milhoes ao ano", points=50),
            ExactMatchStrategy(field="role", target_value="CEO", points=50),
        ]
        return ScoringService(default_strategies, qualification_threshold=50), None

    # Metodo principal que avalia a entrada do usuario e decide o proximo passo
    async def process_turn(self, request: TurnRequest) -> TurnResponse:
        """Processa a mensagem recebida pelo webhook e determina a proxima acao conversacional."""
        # Registra no log a chegada da mensagem com os dados de rastreio
        logger.info(f"Processando turno para o lead {request.phone_number} (Msg: {request.message_id})")

        # Chama o repositorio para verificar se ocorreu alguma duplicacao de rede/webhook no n8n (Idempotencia)
        if await self.repo.is_message_processed(request.message_id):
            # Registra no log que a mensagem foi descartada pois ja havia sido processada
            logger.warning(f"Mensagem {request.message_id} descartada por idempotencia.")
            # Retorna uma instrucao para o n8n ignorar, preservando o banco de insercoes duplas
            return TurnResponse(
                reply_message="",
                current_state="DUPLICATE_IGNORED",
                is_finished=False,
            )

        # Como a mensagem e nova, chama o repositorio para salvar no banco imediatamente
        await self.repo.mark_message_processed(request.message_id)

        # Solicita a OpenAI a extracao dos slots semanticos da mensagem do usuario
        slots = await self.llm_adapter.extract_slots(request.user_message)
        # Converte os slots populados para um dicionario enxuto
        lead_data = slots.model_dump(exclude_none=True)

        # Carrega o motor de scoring dinamicamente do banco de dados (regras versionadas)
        scoring_engine, rule_set_id = await self._resolve_scoring_engine()

        # Calcula a pontuacao atual com base nos dados obtidos do lead
        score_result = scoring_engine.calculate_score(lead_data)
        final_score = score_result["final_score"]
        is_qualified = score_result["is_qualified"]
        reasons = score_result["reasons"]

        # Se o lead caiu em uma regra eliminatoria sumaria (pontuacao negativa extrema)
        if final_score < -9000:
            logger.warning(f"Lead {request.phone_number} desqualificado sumariamente.")
            # Salva o resultado definitivo no banco se houver rule_set persistido
            if rule_set_id:
                await self.repo.save_scoring_result(
                    phone_number=request.phone_number,
                    rule_set_id=rule_set_id,
                    final_score=final_score,
                    is_qualified=False,
                    audit_trail=reasons,
                )
            # Retorna mensagem educada de encerramento do fluxo
            return TurnResponse(
                reply_message="Agradecemos o seu contato com a nossa equipe! No momento nosso atendimento e focado em clientes corporativos.",
                current_state="DISQUALIFIED",
                is_finished=True,
            )

        # Se ja temos o faturamento ou cargo e a pontuacao alcancou a nota de corte para aprovacao
        if is_qualified or (slots.role is not None and slots.revenue is not None):
            logger.info(f"Lead {request.phone_number} finalizou qualificacao com nota {final_score}.")
            # Salva o resultado oficial no banco de dados para alimentar o dashboard
            if rule_set_id:
                await self.repo.save_scoring_result(
                    phone_number=request.phone_number,
                    rule_set_id=rule_set_id,
                    final_score=final_score,
                    is_qualified=is_qualified,
                    audit_trail=reasons,
                )
            # Define mensagem de sucesso caso tenha atingido o perfil ideal
            if is_qualified:
                reply = "Excelente! Seu perfil se encaixa perfeitamente nas solucoes da nossa plataforma. Um executivo de contas entrara em contato!"
                state = "QUALIFIED"
            # Caso tenha respondido mas nao bateu a pontuacao minima
            else:
                reply = "Muito obrigado pelas informacoes! Seu cadastro foi recebido com sucesso pela nossa equipe comercial."
                state = "NOT_QUALIFIED"

            return TurnResponse(
                reply_message=reply,
                current_state=state,
                is_finished=True,
            )

        # Caso ainda faltem dados cruciais, a maquina de estados pergunta o proximo slot pendente
        if slots.role is None:
            # Pergunta qual o cargo do lead
            return TurnResponse(
                reply_message="Ola! Para direcionarmos a melhor solucao da plataforma, qual o seu cargo ou atuacao na empresa?",
                current_state="AWAITING_ROLE",
                is_finished=False,
            )

        # Se ja temos o cargo mas falta o faturamento
        return TurnResponse(
            reply_message="Entendido! E qual a media de faturamento anual ou mensal da sua empresa atualmente?",
            current_state="AWAITING_REVENUE",
            is_finished=False,
        )
