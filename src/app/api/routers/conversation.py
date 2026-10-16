from typing import Annotated

# Importa APIRouter e Depends do FastAPI
from fastapi import APIRouter, Depends

# Importa tipagem de conexao assincrona
from psycopg import AsyncConnection

# Importa o controller do webhook
from src.app.controllers.webhook_controller import WebhookController

# Importa o logger estruturado
from src.app.core.logger import logger

# Importa os schemas de turno de conversa
from src.app.core.schemas.conversation import TurnRequest, TurnResponse

# Importa a dependencia de contexto seguro de tenant
from src.app.core.tenant import get_tenant_connection

# Alias para compatibilidade com middlewares anteriores
set_tenant_context = get_tenant_connection

# Cria uma instancia de Roteador do FastAPI exclusivo para endpoints de comunicacao
router = APIRouter()


# Cria a rota POST onde o n8n fara as chamadas: /v1/{tenant}/conversa/turno
@router.post("/v1/{tenant}/conversa/turno", response_model=TurnResponse)
async def conversation_turn(
    tenant: str,
    request: TurnRequest,
    conn: Annotated[AsyncConnection, Depends(get_tenant_connection)],
):
    """Processa o turno de mensagem do WhatsApp validando idempotencia e aplicando scoring."""
    # Registra no log o recebimento do webhook para o tenant
    logger.info(f"Webhook recebido para o tenant {tenant} | Lead Phone: {request.phone_number}")

    # Prepara o controller injetando a conexao com tenant e search_path devidamente isolados
    controller = WebhookController(conn)

    # Repassa a solicitacao para a arquitetura em camadas
    response = await controller.handle_turn(request)

    # Devolve a resposta estruturada para o n8n
    return response
