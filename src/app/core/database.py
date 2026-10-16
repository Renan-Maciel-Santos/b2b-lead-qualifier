# Importa o pool assincrono de conexoes do pacote psycopg
from psycopg_pool import AsyncConnectionPool

# Importa o logger configurado do projeto
from src.app.core.logger import logger

# Importa a instancia de configuracoes do projeto (onde estao as senhas do BD)
from src.app.core.settings import settings

# Cria a string de conexao com o banco de dados usando as configuracoes
DATABASE_URL = f"postgresql://{settings.db_user}:{settings.db_password}@{settings.db_host}:{settings.db_port}/{settings.db_name}"

# Cria a variavel global que vai guardar a instancia do pool de conexoes
pool: AsyncConnectionPool = None

# Cria a funcao assincrona que inicializa o pool de conexoes
async def init_db_pool():
    # Informa ao Python que usaremos a variavel global 'pool' definida acima
    global pool
    # Inicializa o pool assincrono apontando para a URL do banco (sem abrir ainda)
    pool = AsyncConnectionPool(conninfo=DATABASE_URL, min_size=1, max_size=10, open=False)
    # Abre o pool de conexoes efetivamente, conectando ao banco
    await pool.open()
    # Registra no log que o pool foi conectado com sucesso
    logger.info("Pool de conexoes com o banco de dados iniciado.")

# Cria a funcao assincrona que fecha o pool de conexoes
async def close_db_pool():
    # Verifica se o pool realmente existe e esta inicializado
    if pool:
        # Fecha todas as conexoes abertas do pool
        await pool.close()
        # Registra no log que o pool foi encerrado
        logger.info("Pool de conexoes com o banco de dados fechado.")

# Cria a dependencia do FastAPI para fornecer uma conexao as rotas
async def get_db_connection():
    # Pega uma conexao valida do pool usando um gerenciador de contexto assincrono
    async with pool.connection() as conn:
        # Retorna a conexao para a rota/funcao que chamou a dependencia
        yield conn
