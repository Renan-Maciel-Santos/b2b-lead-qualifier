# Importa o BaseModel do Pydantic para validar os dados de entrada
# Importa List e Optional para tipagem de dados (se necessario futuramente)

from pydantic import BaseModel


# Define a estrutura de dados (Schema) que o n8n vai mandar para a API
class TurnRequest(BaseModel):
    # O ID unico da mensagem gerado pelo WhatsApp/n8n (usado como chave de idempotencia)
    message_id: str
    # O numero de telefone do lead (usado para recuperar a conversa no banco depois)
    phone_number: str
    # O texto que o lead digitou e enviou no WhatsApp
    user_message: str

# Define a estrutura de dados (Schema) de resposta da API de volta para o n8n
class TurnResponse(BaseModel):
    # A resposta de texto gerada pela IA/Motor que o n8n deve encaminhar pro usuario
    reply_message: str
    # O estado atual da conversa (ex: COLETANDO_NOME, SCORING, etc)
    current_state: str
    # Uma flag verdadeira indicando se a avaliacao terminou (para o n8n encerrar o fluxo)
    is_finished: bool
