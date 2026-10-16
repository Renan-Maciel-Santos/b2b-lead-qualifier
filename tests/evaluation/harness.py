# Importa o pacote asyncio nativo para que possamos rodar funcoes assincronas da OpenAI em um script terminal
import asyncio

# Importa a biblioteca padrao json para carregar o golden dataset do disco
import json

# Importa as regras de negocio (Eliminatoria e de Bonificacao) criadas no Passo 6
from src.app.core.scoring.strategy import ExactMatchStrategy, KnockoutStrategy

# Importa o adaptador LLM estruturado criado no Passo 7
from src.app.integrations.llm.openai_adapter import OpenAIAdapter

# Importa o motor executor de Scoring criado no Passo 6
from src.app.services.scoring_service import ScoringService


# Funcao sincrona auxiliar para carregar o golden dataset
def load_golden_dataset():
    # Abre o arquivo de lote (Golden Dataset) que o especialista humano ja pre-avaliou
    with open("data/golden_dataset.json", encoding="utf-8") as f:
        # Parseia o JSON gravando na memoria como uma lista de dicionarios
        return json.load(f)


# Cria a funcao assincrona mestre que ira orquestrar o teste simulando o fluxo completo da aplicacao
async def run_evaluation():
    # Carrega os dados pre-avaliados
    dataset = load_golden_dataset()

    # Instancia o adaptador de comunicacao com a OpenAI
    llm_adapter = OpenAIAdapter()
    
    # Cria uma lista injetando as condicoes e regras estritas exigidas pelo cliente
    strategies = [
        # Regra 1: Se o LLM identificar a palavra 'estudante' como cargo, encerra imediatamente (Nota -9999)
        KnockoutStrategy(field="role", knockout_value="estudante"),
        # Regra 2: Se o LLM identificar exatamente esse faturamento, o lead ganha 50 pontos
        ExactMatchStrategy(field="revenue", target_value="5 milhoes ao ano", points=50),
        # Regra 3: Se o LLM abstrair que a pessoa e um CEO, soma 50 pontos
        ExactMatchStrategy(field="role", target_value="CEO", points=50)
    ]
    # Instancia o motor de pontuacao passando as regras
    scoring_service = ScoringService(strategies)

    # Cria contador da quantidade de acertos do robo perante o julgamento humano
    acertos = 0
    # Verifica o tamanho da prova a ser executada
    total = len(dataset)

    # Percorre sequencialmente a lista de casos pre-avaliados
    for case in dataset:
        # Pega a string com o texto que simularemos ter vindo do WhatsApp
        texto_conversa = case["conversation_history"]
        # Pega o boolean de aprovacao que a equipe comercial faria manualmente
        esperado = case["expected_qualified"]
        
        # Imprime de forma crua o caso sendo testado para log no console
        print(f"\nAvaliando caso {case['id']}...")
        
        # Manda a conversa embaraçada para a API da OpenAI forçando-a a montar um quebra-cabecas Pydantic
        slots = await llm_adapter.extract_slots(texto_conversa)
        
        # Transforma os slots inteligentes em um dicionario comum do python, omitindo valores que a IA nao encontrou
        lead_data_dict = slots.model_dump(exclude_none=True)
        
        # Entrega o dicionario recem formatado para as engrenagens de regras calcularem a nota cega
        resultado = scoring_service.calculate_score(lead_data_dict)
        
        # Compara rigidamente se o julgamento binario final do motor bateu com a gabarito
        bateu = resultado["is_qualified"] == esperado
        
        # Se os dois julgamentos baterem perfeitamente
        if bateu:
            # Incrementa o acerto
            acertos += 1
            # Loga a vitoria
            print(f"[OK] Robo acertou! (Esperado: {esperado}, Robo: {resultado['is_qualified']})")
        # Se divergir (quer dizer que o modelo alucinou ou a regra ta branda demais)
        else:
            # Aponta a falha e avisa que o prompt requer fine-tuning
            print(f"[FALHA] Robo errou! (Esperado: {esperado}, Robo: {resultado['is_qualified']})")
            # Extrai do append-only audit trail o por que o robo decidiu isso
            print(f"Motivos da maquina: {resultado['reasons']}")
            # Exibe o que a LLM achou que era
            print(f"Extracao do LLM: {lead_data_dict}")

    # Efetua o calculo do Indice de Concordancia (Acuracia)
    acuracia = (acertos / total) * 100
    # Printa os limites finais no console
    print("\n=== Resultado Final da Acuracia ===")
    print(f"Acertos: {acertos} de {total}")
    print(f"Concordancia: {acuracia:.2f}% (Meta: 80%)")
    
    # Trava logica: 80% foi a meta exigida no escopo, valida se estamos aptos para rodar ou se travamos o deploy
    if acuracia < 80:
        print("ALERTA: A acuracia ficou abaixo do aceitavel para colocar em producao! Ajuste os Prompts.")
    else:
        print("SUCESSO: O modelo esta maduro o suficiente para o Go-Live!")

# Ponto de checagem raiz para saber se o usuario executou o script direto no console
if __name__ == "__main__":
    # Aciona a esteira assincrona do Python engatando na funcao mestre
    asyncio.run(run_evaluation())
