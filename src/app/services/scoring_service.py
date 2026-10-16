# Importa List, Dict e Any para anotacoes de tipos
from typing import Any

# Importa o logger para registrar o processo de scoring no terminal/cloud
from src.app.core.logger import logger

# Importa a classe base de estrategia para injetar a lista de regras ativas
from src.app.core.scoring.strategy import ScoringStrategy


# Cria o servico responsavel por rodar todas as estrategias configuradas no banco contra um Lead
class ScoringService:
    # Ao ser instanciado, recebe uma lista de estrategias ja montadas e opcionalmente a nota de corte
    def __init__(self, strategies: list[ScoringStrategy], qualification_threshold: int = 50):
        # Armazena a lista de estrategias no objeto
        self.strategies = strategies
        # Armazena a nota de corte minima para aprovacao
        self.qualification_threshold = qualification_threshold

    # Metodo que avalia os dados crus do Lead passando-os pelo corredor polones de estrategias
    def calculate_score(self, lead_data: dict[str, Any]) -> dict[str, Any]:
        # Inicializa a pontuacao total daquele lead como zero
        total_score = 0
        # Cria uma lista vazia para registrar o motivo de cada ponto ganho/perdido (Trilha de auditoria append-only)
        audit_trail = []

        # Percorre sequencialmente cada uma das estrategias (regras) cadastradas
        for strategy in self.strategies:
            # Roda a estrategia injetando os dados do lead, recuperando os pontos dados e a justificativa
            points, reason = strategy.evaluate(lead_data)
            
            # Se a estrategia reagiu e alterou alguma pontuacao (pontos diferentes de zero)
            if points != 0:
                # Soma (ou subtrai) os pontos na pontuacao total acumulada do lead
                total_score += points
                # Adiciona a justificativa daquela regra no rastro de auditoria, para nunca apagarmos o motivo da nota
                audit_trail.append(reason)
                # Loga a operacao em tempo real
                logger.info(f"Regra de scoring aplicada: {reason}")
            
            # Condicao de parada imediata: Se a pontuacao total despencar devido a uma penalidade de eliminacao (< -9000)
            if total_score < -9000:
                # Loga o aviso de eliminacao automatica do lead
                logger.warning("Lead eliminado sumariamente. Interrompendo motor de regras.")
                # Quebra o laco 'for' (break), parando de processar outras regras atoa para economizar processamento
                break
        
        # Devolve um dicionario limpo com a nota final, o veredito e o historico imutavel (append-only) de como ela foi atingida
        return {
            # A nota final contabilizada
            "final_score": total_score,
            # O array de historico de razoes
            "reasons": audit_trail,
            # Define se e um lead qualificado para compra caso a nota for maior ou igual a nota de corte
            "is_qualified": total_score >= self.qualification_threshold
        }
