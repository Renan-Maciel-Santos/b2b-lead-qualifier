# Importa a tipagem da conexao assincrona do Postgres
from psycopg import AsyncConnection

# Importa a tipagem de dados dos payloads
from src.app.core.schemas.conversation import TurnRequest, TurnResponse

# Importa o repositorio de persistencia
from src.app.repositories.conversation_repo import ConversationRepository

# Importa a maquina de estados de regras de negocio
from src.app.services.state_machine import StateMachineService


# Cria a classe controladora que orquestra a solicitacao web HTTP ligando ao Service e Repository
class WebhookController:
    # E instanciada no Router injetando a conexao com o RLS ja isolado
    def __init__(self, conn: AsyncConnection):
        # Instancia o repositorio entregando a ele a conexao do banco
        self.repo = ConversationRepository(conn)
        # Instancia o servico da maquina de estados entregando a ele o repositorio configurado
        self.service = StateMachineService(self.repo)

    # Executa a orquestracao da acao de turno de fala do usuario
    async def handle_turn(self, request: TurnRequest) -> TurnResponse:
        # Pede para o service processar a mensagem (validar idempotencia, extrair LLM e escolher resposta)
        response = await self.service.process_turn(request)
        
        # Efetua o "commit" (salvamento definitivo) da transacao no PostgreSQL
        # Fazemos isso no controller para garantir que qualquer erro de execucao no service reverta os dados
        await self.repo.conn.commit()

        # Retorna o resultado JSON empacotado para o roteador enviar ao n8n
        return response
