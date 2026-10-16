# Importa pytest e excecao do psycopg
import pytest
from psycopg.errors import Error as PsycopgError

# Importa os identificadores e helper do conftest
from tests.conftest import TENANT_DEMO, TENANT_INVASOR, set_test_tenant_context

# Marca os testes do modulo para execucao assincrona
pytestmark = pytest.mark.asyncio


# Testa a garantia de falha fechada: sem contexto de tenant, nenhuma linha pode ser retornada
async def test_rls_fail_closed_without_tenant(db_app):
    """Garante que consultas sem contexto de tenant retornem zero linhas (fail-closed)."""
    async with db_app.cursor() as cur:
        # Consulta tabela global de tenants sem definir a sessao
        await cur.execute("SELECT * FROM optime_core.tenants")
        rows = await cur.fetchall()
        # O RLS deve bloquear a visibilidade de todas as linhas
        assert len(rows) == 0


# Testa o isolamento correto: o tenant ativo enxerga somente os seus proprios dados
async def test_rls_isolates_tenant_data(db_app):
    """Garante que ao definir o tenant demonstrativo, apenas os seus registros sejam visiveis."""
    # Configura o contexto do tenant demo
    await set_test_tenant_context(db_app, TENANT_DEMO, "tenant_demo")

    async with db_app.cursor() as cur:
        # Consulta os tenants visiveis
        await cur.execute("SELECT id, name FROM optime_core.tenants")
        tenants = await cur.fetchall()
        # Deve enxergar apenas o seu proprio tenant
        assert len(tenants) == 1
        assert str(tenants[0][0]) == TENANT_DEMO

        # Consulta as regras de scoring no schema isolado
        await cur.execute("SELECT tenant_id FROM scoring_rule_sets")
        rule_sets = await cur.fetchall()
        assert len(rule_sets) >= 1
        assert str(rule_sets[0][0]) == TENANT_DEMO


# Testa a prevencao de insercoes cruzadas (tentativa de forjar tenant_id)
async def test_rls_prevents_cross_tenant_inserts(db_app):
    """Garante que o RLS bloqueia tentativas de um tenant gravar dados fingindo ser outro."""
    # O invasor entra no sistema e injeta seu tenant ID
    await set_test_tenant_context(db_app, TENANT_INVASOR, "tenant_invasor")

    async with db_app.cursor() as cur:
        # O invasor tenta inserir uma mensagem forjando o tenant_id de outro cliente
        with pytest.raises(PsycopgError):
            await cur.execute(
                "INSERT INTO processed_messages (message_id, tenant_id) VALUES (%s, %s)",
                ("msg_maliciosa_001", TENANT_DEMO),
            )
