# Importa o cliente oficial da OpenAI (que na versao atual ja possui suporte nativo a saida Pydantic)
from openai import AsyncOpenAI, OpenAIError

# Importa o logger para registrarmos a comunicacao
from src.app.core.logger import logger

# Importa a estrutura de dados que forcaremos o LLM a cuspir
from src.app.core.schemas.slots import LeadSlots

# Importa as configuracoes do projeto para pegar a chave da API (API KEY)
from src.app.core.settings import settings


# Cria a classe adaptadora que encapsula a interacao com a OpenAI para nao espalharmos logica externa no Service
class OpenAIAdapter:
    # Ao ser instanciada (geralmente pelo Controller/Service), inicializa o cliente assincrono da OpenAI
    def __init__(self):
        # Cria o cliente usando a chave que configuramos no nosso arquivo .env
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        # Define o modelo padrao que usaremos para extrair dados (gpt-4o-mini e super barato e excelente para parsing estruturado)
        self.model = "gpt-4o-mini"

    # Metodo publico para extrair os dados do texto da conversa e colocar direto num objeto validado (LeadSlots)
    async def extract_slots(self, conversation_history: str) -> LeadSlots:
        # Inicia um bloco try para evitar que quedas nos servidores da OpenAI derrubem nossa API
        try:
            # Registra no log que o pedido saiu
            logger.info("Solicitando extracao de slots estruturada para a OpenAI...")
            
            # Faz a chamada usando a funcionalidade 'parse', que exige que o modelo retorne um JSON exato compativel com Pydantic
            response = await self.client.beta.chat.completions.parse(
                # Diz qual modelo inteligente usar
                model=self.model,
                # Envia as mensagens de contexto que o robo vai ler
                messages=[
                    # A instrucao (system prompt) que guia o papel do robo
                    {
                        "role": "system", 
                        "content": "Voce e um assistente de qualificacao de leads. Analise a conversa rigorosamente e extraia as informacoes exatas."
                    },
                    # O texto real da conversa que o usuario (lead) enviou
                    {
                        "role": "user", 
                        "content": conversation_history
                    }
                ],
                # Forca a OpenAI a preencher o nosso modelo Pydantic (Structured Output nativo)
                response_format=LeadSlots,
                # Zera a temperatura (criatividade = 0) pois queremos apenas extracao crua e fatual de dados
                temperature=0.0
            )
            
            # Extrai o objeto Pydantic ja perfeitamente populado da resposta gorda da OpenAI
            extracted_data = response.choices[0].message.parsed
            
            # Registra no log o que o LLM conseguiu achar no texto
            logger.info(f"Slots extraidos com sucesso: {extracted_data.model_dump()}")
            
            # Devolve o objeto perfeitamente formatado para a nossa maquina de estados julgar
            return extracted_data
            
        # Captura qualquer excecao de rede, chave invalida, ou falha da OpenAI
        except OpenAIError as e:
            # Grava o erro gravissimo com todos os detalhes no log do servidor
            logger.error(f"Falha critica ao tentar extrair dados com a OpenAI: {e!s}", exc_info=True)
            # Retorna um objeto LeadSlots vazio para a maquina de estados tratar a falha sem quebrar o n8n
            return LeadSlots()
