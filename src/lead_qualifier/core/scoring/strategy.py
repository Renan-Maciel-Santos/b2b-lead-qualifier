# Importa o modulo ABC para criar classes abstratas e metodos abstratos
from abc import ABC, abstractmethod

# Importa Dict, Any e Tuple para tipagem rigorosa dos dados estruturados
from typing import Any


# Define a classe abstrata (Interface) base para todas as estrategias de pontuacao que criarmos
class ScoringStrategy(ABC):
    
    # Metodo abstrato que toda estrategia filha devera implementar obrigatoriamente
    @abstractmethod
    def evaluate(self, lead_data: dict[str, Any]) -> tuple[int, str]:
        # Esse metodo sempre vai receber os dados do lead e retornar os pontos e uma justificativa textual
        pass

# Cria uma estrategia real focada em desqualificar leads fora de perfil imediatamente (Knockout/Eliminatoria)
class KnockoutStrategy(ScoringStrategy):
    # Inicializa a estrategia recebendo qual campo sera avaliado e qual o valor que causa a eliminacao sumaria
    def __init__(self, field: str, knockout_value: Any):
        # Guarda o nome do campo internamente
        self.field = field
        # Guarda o valor proibido internamente
        self.knockout_value = knockout_value

    # Implementa a regra de avaliacao obrigatoria exigida pela classe mae
    def evaluate(self, lead_data: dict[str, Any]) -> tuple[int, str]:
        # Pega o valor real do campo no dicionario do lead (ou None se o dado nao existir/nao foi perguntado)
        value = lead_data.get(self.field)
        # Verifica se o valor extraido e exatamente o valor que causa eliminacao
        if value == self.knockout_value:
            # Se for, aplica uma penalidade gigantesca (Knockout) e justifica o motivo
            return -9999, f"Lead eliminado sumariamente por campo '{self.field}' ter o valor restrito '{value}'"
        # Caso contrario, o lead passa ileso por essa regra (0 pontos e razao vazia)
        return 0, ""

# Cria uma estrategia real para somar pontos positivamente baseada em acertos simples
class ExactMatchStrategy(ScoringStrategy):
    # Inicializa informando o campo alvo, o valor desejado e quantos pontos essa caracteristica vale
    def __init__(self, field: str, target_value: Any, points: int):
        # Guarda o campo alvo
        self.field = field
        # Guarda o valor desejado
        self.target_value = target_value
        # Guarda a pontuacao de recompensa da regra
        self.points = points

    # Implementa a regra de avaliacao verificando o acerto
    def evaluate(self, lead_data: dict[str, Any]) -> tuple[int, str]:
        # Extrai o valor preenchido pelo lead
        value = lead_data.get(self.field)
        # Compara de forma estrita com o valor desejado pela configuracao
        if value == self.target_value:
            # Se acertar perfeitamente, devolve os pontos cadastrados e a razao detalhada para a auditoria
            return self.points, f"Ganhou {self.points} pts pois '{self.field}' e igual a '{value}'"
        # Se nao acertar, ou se o campo vier vazio, nao ganha nada
        return 0, ""


# Funcao que monta a lista de estrategias de pontuacao a partir do array JSONB lido do banco
def build_strategies_from_rules(rules: list[dict[str, Any]]) -> list[ScoringStrategy]:
    # Lista onde serao acumuladas as instancias construidas
    strategies: list[ScoringStrategy] = []
    # Itera sobre cada especificacao de regra no JSON
    for rule in rules:
        # Extrai o tipo da regra
        rule_type = rule.get("type")
        # Regra do tipo knockout (eliminatoria)
        if rule_type == "knockout":
            strategies.append(
                KnockoutStrategy(
                    field=rule["field"],
                    knockout_value=rule.get("value") or rule.get("knockout_value"),
                )
            )
        # Regra do tipo exact_match (bonificacao por correspondencia exata)
        elif rule_type == "exact_match":
            strategies.append(
                ExactMatchStrategy(
                    field=rule["field"],
                    target_value=rule.get("value") or rule.get("target_value"),
                    points=int(rule.get("points", 0)),
                )
            )
    # Retorna todas as estrategias montadas dinamicamente
    return strategies

