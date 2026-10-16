# Importa a classe BaseSettings do pydantic_settings para carregar variaveis de ambiente
from pydantic_settings import BaseSettings


# Define a classe de configuracoes da aplicacao
class Settings(BaseSettings):
    # Define o ambiente da aplicacao (ex: development, production)
    api_env: str = "development"
    # Define o host da API
    api_host: str = "0.0.0.0"
    # Define a porta da API
    api_port: int = 8000
    
    # Define o host do banco de dados
    db_host: str
    # Define a porta do banco de dados
    db_port: int
    # Define o usuario do banco de dados
    db_user: str
    # Define a senha do banco de dados
    db_password: str
    # Define o nome do banco de dados
    db_name: str
    
    # Define a chave da OpenAI
    openai_api_key: str
    
    # Define as propriedades de configuracao da classe
    class Config:
        # Informa para o Pydantic ler as variaveis do arquivo .env da raiz do projeto
        env_file = ".env"

# Instancia a classe Settings para ser usada globalmente no projeto
settings = Settings()
