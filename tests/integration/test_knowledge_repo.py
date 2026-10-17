"""Integration tests for pgvector semantic search and RLS isolation on knowledge chunks."""

import pytest
from psycopg import AsyncConnection

from lead_qualifier.repositories.knowledge_repo import KnowledgeRepository
from tests.conftest import TENANT_INVASOR, TENANT_TEST, set_test_tenant_context

pytestmark = pytest.mark.asyncio


async def test_knowledge_vector_search_and_rls(db_app: AsyncConnection) -> None:
    """Verify semantic vector retrieval within the tenant and cross-tenant isolation."""
    await set_test_tenant_context(db_app, TENANT_TEST, "tenant_test")

    repo = KnowledgeRepository(db_app)

    # Synthetic 1536-dimensional unit vector matching OpenAI text-embedding-3-small dimension
    test_vector = [0.1] * 1536
    similar_query_vector = [0.1] * 1536

    await repo.insert_chunk(
        title="Enterprise Knowledge Base",
        content="Acme Corp is a B2B AI infrastructure platform for high-growth enterprises.",
        embedding=test_vector,
        embedding_model="text-embedding-3-small",
        metadata={"source": "whitepaper.pdf"},
    )

    results = await repo.search_similar_chunks(
        similar_query_vector,
        limit=1,
        embedding_model="text-embedding-3-small",
    )

    assert len(results) == 1
    assert results[0]["title"] == "Enterprise Knowledge Base"
    # Cosine similarity of identical unit vectors approaches 1.0
    assert results[0]["similarity"] > 0.99

    # Switch session context to attacker tenant to verify RLS barrier
    await set_test_tenant_context(db_app, TENANT_INVASOR, "tenant_invasor")

    attacker_repo = KnowledgeRepository(db_app)
    attacker_results = await attacker_repo.search_similar_chunks(similar_query_vector, limit=1)

    assert len(attacker_results) == 0
