import os
from typing import Annotated

# Importa APIRouter, Depends e HTTPException do FastAPI
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

# Importa tipagem de conexao e retorno em dicionario
from psycopg import AsyncConnection
from psycopg.rows import dict_row

# Importa a dependencia de contexto seguro de tenant
from src.app.core.tenant import get_tenant_connection

# Instancia o roteador do Dashboard
router = APIRouter()


# Rota da API para buscar a listagem de leads avaliados para o tenant
@router.get("/api/v1/{tenant}/leads")
async def get_leads(
    tenant: str,
    conn: Annotated[AsyncConnection, Depends(get_tenant_connection)],
):
    """Retorna os ultimos 100 resultados de qualificacao do tenant autenticado."""
    # Abre o cursor retornando dicionarios
    async with conn.cursor(row_factory=dict_row) as cur:
        # Consulta os resultados mais recentes no schema isolado pelo search_path
        await cur.execute(
            """
            SELECT id, phone_number, final_score, is_qualified, audit_trail, created_at 
            FROM scoring_results 
            ORDER BY created_at DESC 
            LIMIT 100
            """
        )
        leads = await cur.fetchall()
        # Retorna o payload estruturado
        return {"leads": leads}


# Rota para renderizar a interface visual do Dashboard
@router.get("/dashboard/{tenant}", response_class=HTMLResponse)
def render_dashboard(tenant: str):
    """Renderiza a pagina HTML do dashboard injetando o identificador do tenant."""
    # Carrega o arquivo HTML e injeta o UUID do tenant para as requisicoes JavaScript
    template_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "templates", "dashboard.html"
    )

    try:
        with open(template_path, encoding="utf-8") as file:
            html_content = file.read()
            # Substitui o marcador pelo tenant da requisicao
            return html_content.replace("{{TENANT_ID}}", tenant)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Template do dashboard nao encontrado.",
        )
