# Importa a classe base do FastAPI
import asyncio
import sys

from fastapi import FastAPI

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
# Importa o gerenciador de contexto para amarrar funcoes aos eventos de ligar/desligar a API
from contextlib import asynccontextmanager

# Importa as rotas criadas no arquivo de health check
from lead_qualifier.api.health import router as health_router

# Importa o roteador de conversa (Webhook n8n)
from lead_qualifier.api.routers.conversation import router as conversation_router

# Importa o roteador do Dashboard
from lead_qualifier.api.routers.dashboard import router as dashboard_router

# Importa a funcao que abre as conexoes com o banco
# Importa a funcao que fecha as conexoes com o banco
from lead_qualifier.core.database import close_db_pool, init_db_pool

# Importa a funcao que lida com os erros inesperados
from lead_qualifier.core.exceptions import global_exception_handler


# Define a funcao principal que gerencia o ciclo de vida do servidor web (Lifespan)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Aciona a conexao com o banco de dados ASSIM que o servidor iniciar, antes de receber acessos
    await init_db_pool()
    # Libera a execucao, mantendo a API operante ate que receba um sinal de termino (CTRL+C)
    yield
    # Quando o servidor comecar a desligar, encerra as conexoes com o banco de forma limpa
    await close_db_pool()

# Instancia a aplicacao principal do FastAPI, definindo o titulo e atrelando o ciclo de vida
app = FastAPI(title="Optime Lead Qualifier", lifespan=lifespan)

# Adiciona nosso interceptador de erros global, pegando qualquer Exception basica (Erro 500)
app.add_exception_handler(Exception, global_exception_handler)

# Adiciona as rotas declaradas no roteador de health_check para dentro da aplicacao
app.include_router(health_router)

# Registra o roteador de webhook no motor do FastAPI
app.include_router(conversation_router)

# Registra o roteador do Dashboard visual
app.include_router(dashboard_router)
