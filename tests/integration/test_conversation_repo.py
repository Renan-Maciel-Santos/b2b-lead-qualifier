import uuid

# Importa o framework pytest
import pytest

# Importa o repositorio de conversas
from lead_qualifier.repositories.conversation_repo import ConversationRepository

# Importa os identificadores e helper do conftest
from tests.conftest import TENANT_DEMO, set_test_tenant_context

# Marca todos os testes deste arquivo para rodarem com suporte ao asyncio
pytestmark = pytest.mark.asyncio


# Testa a idempotencia de mensagens no banco real
async def test_repository_idempotency(db_app):
    """Garante que uma mensagem registrada seja identificada como duplicada na proxima checagem."""
    # Configura o contexto do tenant demo e seu schema dedicado
    await set_test_tenant_context(db_app, TENANT_DEMO, "tenant_demo")

    repo = ConversationRepository(db_app)
    # Usa um identificador unico para cada execucao do teste
    msg_id = f"msg_{uuid.uuid4()}"

    # Inicialmente nao deve ter sido processada
    assert await repo.is_message_processed(msg_id) is False

    # Marca como processada
    await repo.mark_message_processed(msg_id)

    # Agora deve acusar que ja foi processada
    assert await repo.is_message_processed(msg_id) is True


# Testa a gravacao do resultado de qualificacao no banco real
async def test_repository_save_scoring_result(db_app):
    """Garante que o resultado de pontuacao e a trilha de auditoria sejam persistidos com sucesso."""
    # Configura o contexto do tenant demo
    await set_test_tenant_context(db_app, TENANT_DEMO, "tenant_demo")

    repo = ConversationRepository(db_app)

    # Recupera a regra ativa de scoring para associar a chave estrangeira composta
    rule_set = await repo.get_active_scoring_rule_set()
    assert rule_set is not None
    rule_set_id = rule_set["id"]

    # Telefone formatado em padrao internacional E.164 (valido pelo CHECK do banco)
    phone = f"+55119{uuid.uuid4().int % 100000000:08d}"
    score = 100
    qualified = True
    audit = ["Ganhou 50 pts por cargo CEO", "Ganhou 50 pts por faturamento alto"]

    # Salva o resultado
    await repo.save_scoring_result(
        phone_number=phone,
        rule_set_id=rule_set_id,
        final_score=score,
        is_qualified=qualified,
        audit_trail=audit,
    )

    # Consulta diretamente no banco para validar o registro
    async with db_app.cursor() as cur:
        await cur.execute(
            """
            SELECT phone_number, rule_set_id, final_score, is_qualified, audit_trail
            FROM scoring_results
            WHERE phone_number = %s
            """,
            (phone,),
        )
        row = await cur.fetchone()

        assert row is not None
        assert row[0] == phone
        assert str(row[1]) == str(rule_set_id)
        assert row[2] == score
        assert row[3] is True
        assert len(row[4]) == 2
