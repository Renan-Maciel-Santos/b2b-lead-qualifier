# Importa asyncio e sys para ajustar o event loop no Windows
import asyncio
import os
import sys

# Verifica se a aplicacao esta rodando no sistema operacional Windows
if sys.platform == "win32":
    # Substitui o motor assincrono padrao pelo compativel com o psycopg
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Importa o pytest_asyncio
import pytest_asyncio

# Importa a conexao assincrona e modulos SQL do psycopg
from psycopg import AsyncConnection, sql

# Define o tenant ID oficial do ambiente demo (Nexus)
TENANT_DEMO = "11111111-1111-1111-1111-111111111111"
# Define o tenant ID do invasor simulado
TENANT_INVASOR = "22222222-2222-2222-2222-222222222222"


# Helper para configurar tenant e search_path em conexoes de teste de forma segura e parametrizada
async def set_test_tenant_context(
    conn: AsyncConnection,
    tenant_id: str,
    schema_name: str,
):
    """Configura o optime.current_tenant e search_path de forma parametrizada na sessao de teste."""
    async with conn.cursor() as cur:
        # Injeta o UUID no contexto de sessao RLS
        await cur.execute(
            "SELECT set_config('optime.current_tenant', %s, true)",
            (tenant_id,),
        )
        # Seta o search_path de forma segura para o schema do tenant
        await cur.execute(
            sql.SQL("SET LOCAL search_path TO {}, public").format(
                sql.Identifier(schema_name)
            )
        )


# Fixture administrativa para gerenciar schemas e tabelas nos testes
@pytest_asyncio.fixture
async def db_admin():
    """Conexao de superuser para operacoes administrativas e de preparacao de dados."""
    admin_user = os.getenv("DB_ADMIN_USER", "postgres")
    admin_pwd = os.getenv("DB_ADMIN_PASSWORD", "secret")
    db_name = os.getenv("DB_NAME", "optime")
    conn_str = f"postgresql://{admin_user}:{admin_pwd}@127.0.0.1:5432/{db_name}"
    async with await AsyncConnection.connect(conn_str) as conn:
        yield conn


# Fixture que garante que os tenants necessarios para testes estejam provisionados
@pytest_asyncio.fixture(autouse=True)
async def setup_test_tenants(db_admin):
    """Garante o provisionamento idempotente dos schemas de tenant para os testes."""
    async with db_admin.cursor() as cur:
        # Provisiona o tenant demonstrativo (tenant_demo)
        await cur.execute(
            "SELECT optime_core.provision_tenant(%s, %s, %s)",
            (TENANT_DEMO, "Nexus Enterprise (Demo)", "tenant_demo"),
        )
        # Provisiona o tenant invasor (tenant_invasor) para testes de barreira RLS
        await cur.execute(
            "SELECT optime_core.provision_tenant(%s, %s, %s)",
            (TENANT_INVASOR, "Tenant Invasor", "tenant_invasor"),
        )
        # Garante regra ativa para o tenant demo
        await cur.execute(
            """
            INSERT INTO tenant_demo.scoring_rule_sets (
                tenant_id, version, rules, qualification_threshold, is_active
            ) VALUES (
                %s, 1,
                '[
                    {"type": "knockout", "field": "role", "value": "estudante"},
                    {"type": "knockout", "field": "role", "value": "estagiario"},
                    {"type": "knockout", "field": "revenue", "value": "abaixo de 50 mil"},
                    {"type": "exact_match", "field": "role", "value": "CEO", "points": 50},
                    {"type": "exact_match", "field": "role", "value": "Diretor", "points": 40},
                    {"type": "exact_match", "field": "revenue", "value": "5 milhoes ao ano", "points": 50}
                ]'::jsonb,
                50, true
            ) ON CONFLICT (tenant_id, version) DO NOTHING
            """,
            (TENANT_DEMO,),
        )
        await db_admin.commit()


# Fixture restrita da aplicacao (optime_app) sem BYPASSRLS
@pytest_asyncio.fixture
async def db_app():
    """Conexao restrita da aplicacao onde o RLS sempre se aplica obrigatoriamente."""
    app_user = os.getenv("DB_USER", "optime_app")
    app_pwd = os.getenv("DB_PASSWORD", "secret")
    db_name = os.getenv("DB_NAME", "optime")
    conn_str = f"postgresql://{app_user}:{app_pwd}@127.0.0.1:5432/{db_name}"
    async with await AsyncConnection.connect(conn_str) as conn:
        yield conn
