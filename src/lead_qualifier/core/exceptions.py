# Importa Request e JSONResponse do FastAPI para manipular requisicoes HTTP
from fastapi import Request
from fastapi.responses import JSONResponse

# Importa o logger configurado do projeto
from lead_qualifier.core.logger import logger


# Cria a funcao que captura e lida com excecoes globais nao tratadas (Erro 500)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Registra o erro no log, salvando o caminho que deu erro e a pilha de execucao (traceback)
    logger.error(f"Erro nao tratado na rota {request.url.path}: {exc!s}", exc_info=True)
    
    # Cria a resposta generica que sera enviada ao cliente para mascarar detalhes internos
    response_content = {"message": "Ocorreu um erro interno no servidor."}
    
    # Retorna o JSON formatado com o codigo de erro 500 (Internal Server Error)
    return JSONResponse(status_code=500, content=response_content)
