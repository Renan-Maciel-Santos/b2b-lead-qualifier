# Importa o pytest
import pytest

# Importa o repositorio de conhecimento
from lead_qualifier.repositories.knowledge_repo import KnowledgeRepository

# Importa os identificadores e helper do conftest
from tests.conftest import TENANT_DEMO, TENANT_INVASOR, set_test_tenant_context

# Marca todos os testes como assincronos
pytestmark = pytest.mark.asyncio


# Testa a insercao e a recuperacao vetorial semantica com pgvector
async def test_knowledge_vector_search_and_rls(db_app):
    """Testa a insercao e busca semantica de documentos via pgvector e isolamento RLS."""
    # Configura o contexto do tenant demo
    await set_test_tenant_context(db_app, TENANT_DEMO, "tenant_demo")

    repo = KnowledgeRepository(db_app)

    # Cria um vetor sintetico de 1536 dimensoes
    test_vector = [0.1] * 1536
    similar_query_vector = [0.1] * 1536

    # Insere um fragmento de apresentacao institucional de forma idempotente
    await repo.insert_chunk(
        title="Enterprise Knowledge Base",
        content="A Acme Corp e uma plataforma de infraestrutura B2B e IA conversacional para empresas de alto crescimento.",
        embedding=test_vector,
        embedding_model="text-embedding-3-small",
        metadata={"origem": "whitepaper.pdf"},
    )

    # Executa a busca vetorial no schema do tenant
    results = await repo.search_similar_chunks(
        similar_query_vector,
        limit=1,
        embedding_model="text-embedding-3-small",
    )

    assert len(results) == 1
    assert results[0]["title"] == "Enterprise Knowledge Base"
    # Similaridade de cosseno entre vetores identicos deve ser aproximadamente 1.0
    assert results[0]["similarity"] > 0.99

    # Agora troca para outro tenant e verifica o isolamento RLS
    await set_test_tenant_context(db_app, TENANT_INVASOR, "tenant_invasor")

    invasor_repo = KnowledgeRepository(db_app)
    invasor_results = await invasor_repo.search_similar_chunks(similar_query_vector, limit=1)

    # O invasor nao pode encontrar os documentos do outro tenant
    assert len(invasor_results) == 0
