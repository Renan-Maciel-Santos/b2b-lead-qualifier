# Importa o BaseModel e Field do Pydantic para estruturar e validar os dados extraidos
# Importa Optional para marcar campos que podem nao ter sido falados na conversa ainda

from pydantic import BaseModel, Field


# Cria o objeto que representara os dados (slots) que a Inteligencia Artificial deve conseguir garimpar da conversa
class LeadSlots(BaseModel):
    # Campo para o nome do lead (se ele disser)
    name: str | None = Field(default=None, description="O nome do usuario, se ele informou na conversa.")
    
    # Campo para o faturamento (usado pelas nossas regras do ScoringService depois)
    revenue: str | None = Field(default=None, description="A faixa de faturamento ou valor exato informado pelo lead.")
    
    # Campo para o cargo ou poder de decisao
    role: str | None = Field(default=None, description="O cargo do lead ou sua posicao decisoria na empresa.")
