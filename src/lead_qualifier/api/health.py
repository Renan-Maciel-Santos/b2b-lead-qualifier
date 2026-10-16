from typing import Annotated

# Importa o objeto APIRouter do FastAPI para agrupar as rotas
from fastapi import APIRouter, Depends

# Importa a classe de conexao assincrona nativa do psycopg para anotacao de tipo
from psycopg import AsyncConnection
from psycopg.errors import Error as PsycopgError

# Importa a funcao que fornece a conexao do nosso pool
from lead_qualifier.core.database import get_db_connection

# Importa o logger configurado do projeto
from lead_qualifier.core.logger import logger

# Inicializa o roteador para os endpoints de verificacao de integridade (health)
router = APIRouter()


# Define a rota que respondera requisicoes HTTP do tipo GET no caminho '/health'
@router.get("/health")
# Define a funcao assincrona que responde a rota, recebendo a conexao do banco via injecao
async def health_check(conn: Annotated[AsyncConnection, Depends(get_db_connection)]):
    # Inicia um bloco try para tentar consultar o banco de dados
    try:
        # Executa uma query SQL ultra leve ("SELECT 1") apenas para ver se o banco responde
        await conn.execute("SELECT 1")
        # Retorna um dicionario JSON informando que a API e o banco estao perfeitamente saudaveis
        return {"status": "ok", "database": "healthy"}

    # Captura qualquer excecao especifica do banco de dados
    except PsycopgError as e:
        # Grava no log interno o motivo pelo qual a comunicacao com o banco falhou
        logger.error(f"Falha no healthcheck do banco de dados: {e!s}")
        # Retorna um JSON informando que a API funciona, porem o banco esta indisponivel
        return {"status": "ok", "database": "unhealthy"}
