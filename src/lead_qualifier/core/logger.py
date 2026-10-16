# Importa o modulo logging padrao do Python
# Importa o modulo json padrao do Python para converter dicts em string
import json
import logging

# Importa datetime para lidar com datas e horarios
# Importa timezone para fuso horario UTC
from datetime import UTC, datetime


# Cria a classe do formatador de logs em formato JSON
class JSONFormatter(logging.Formatter):
    # Sobrescreve o metodo padrao de formatacao de log
    def format(self, record: logging.LogRecord) -> str:
        # Cria um dicionario com os dados que serao impressos no log
        log_data = {
            # Adiciona o timestamp atual em formato ISO 8601 UTC
            "timestamp": datetime.now(UTC).isoformat(),
            # Adiciona o nivel de severidade do log (INFO, ERROR, etc)
            "level": record.levelname,
            # Adiciona a mensagem do log
            "message": record.getMessage(),
            # Adiciona o nome do modulo/arquivo que gerou o log
            "module": record.module,
            # Adiciona a funcao especifica que gerou o log
            "function": record.funcName
        }
        # Verifica se ocorreu alguma excecao (erro)
        if record.exc_info:
            # Formata a excecao e a adiciona ao dicionario
            log_data["exception"] = self.formatException(record.exc_info)
        # Retorna o dicionario convertido para uma string JSON
        return json.dumps(log_data)

# Cria a funcao para inicializar e configurar o logger global
def setup_logger() -> logging.Logger:
    # Cria uma instancia do logger com o nome da aplicacao
    logger = logging.getLogger("optime_app")
    # Define o nivel de log padrao como INFO
    logger.setLevel(logging.INFO)
    
    # Cria o manipulador que ira imprimir os logs no console (stdout)
    console_handler = logging.StreamHandler()
    # Atribui o nosso formatador JSON ao manipulador do console
    console_handler.setFormatter(JSONFormatter())
    
    # Adiciona o manipulador ao logger recem-criado
    logger.addHandler(console_handler)
    
    # Retorna o logger totalmente configurado
    return logger

# Instancia o logger configurado para ser importado em outros arquivos
logger = setup_logger()
