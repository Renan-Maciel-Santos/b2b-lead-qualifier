import re
from typing import Annotated
from uuid import UUID

# Importa o FastAPI Depends e HTTPException
from fastapi import Depends, HTTPException

# Importa a conexao assincrona nativa e modulos SQL seguros do psycopg
from psycopg import AsyncConnection, sql
from psycopg.errors import Error as PsycopgError

# Importa o pool de conexoes
from lead_qualifier.core.database import get_db_connection


# Dependencia que valida o tenant, injeta o RLS e define o search_path com o schema do cliente
async def get_tenant_connection(
    tenant: str,
    conn: Annotated[AsyncConnection, Depends(get_db_connection)],
) -> AsyncConnection:
    """Valida o UUID do tenant, injeta o contexto no PostgreSQL e configura o search_path do schema."""
    # Valida formato UUID da URL antes de qualquer chamada ao banco
    try:
        tenant_uuid = UUID(tenant)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=400,
            detail="Identificador de Tenant Invalido ou Bloqueado.",
        )

    # Abre o cursor para parametrizar a transacao
    async with conn.cursor() as cur:
        try:
            # Seta a variavel de sessao de forma 100% parametrizada (evita SQL injection)
            await cur.execute(
                "SELECT set_config('optime.current_tenant', %s, true)",
                (str(tenant_uuid),),
            )

            # Busca o schema dedicado cadastrado para o tenant no catalogo global
            await cur.execute(
                "SELECT schema_name FROM optime_core.tenants WHERE id = %s",
                (str(tenant_uuid),),
            )
            row = await cur.fetchone()
            # Se o tenant nao existir no catalogo, retorna 404
            if not row:
                raise HTTPException(
                    status_code=404,
                    detail="Tenant nao encontrado ou desativado.",
                )

            schema_name = row[0]
            # Valida expressao regular do nome do schema como camada de defesa em profundidade
            if not re.match(r"^tenant_[a-z0-9_]{1,40}$", schema_name):
                raise HTTPException(
                    status_code=500,
                    detail="Nome de schema do tenant invalido.",
                )

            # Define o search_path da transacao de forma segura usando psycopg sql.Identifier
            set_search_path_query = sql.SQL(
                "SET LOCAL search_path TO {}, public"
            ).format(sql.Identifier(schema_name))
            await cur.execute(set_search_path_query)

        # Captura eventuais erros de execucao do PostgreSQL
        except PsycopgError:
            raise HTTPException(
                status_code=400,
                detail="Erro ao inicializar contexto seguro do tenant.",
            )

    # Retorna a conexao isolada para uso na rota
    return conn
