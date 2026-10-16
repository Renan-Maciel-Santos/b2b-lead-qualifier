import json

# Importa tipagem de conexao assincrona e dict_row
from psycopg import AsyncConnection
from psycopg.rows import dict_row


# Repositorio responsavel pela busca semantica e gestao da base de conhecimento (pgvector)
class KnowledgeRepository:
    """Gerencia a persistencia e recuperacao vetorial de fragmentos de conhecimento."""

    # Inicializa recebendo a conexao isolada do tenant
    def __init__(self, conn: AsyncConnection):
        # Armazena a conexao internamente
        self.conn = conn

    # Busca os fragmentos de texto mais similares semanticamente a pergunta do usuario
    async def search_similar_chunks(
        self,
        embedding: list[float],
        limit: int = 3,
        embedding_model: str | None = None,
    ) -> list[dict]:
        """Recupera os fragmentos mais proximos usando distancia de cosseno do pgvector."""
        # Formata o vetor para a representacao textual que o pgvector espera
        embedding_str = f"[{','.join(map(str, embedding))}]"

        # Abre o cursor configurado para retornar dicionarios
        async with self.conn.cursor(row_factory=dict_row) as cur:
            # Filtro opcional por modelo para evitar comparar espacos vetoriais diferentes
            if embedding_model:
                await cur.execute(
                    """
                    SELECT title, content, metadata, 1 - (embedding <=> %s::public.vector) AS similarity
                    FROM knowledge_base
                    WHERE embedding_model = %s
                    ORDER BY embedding <=> %s::public.vector
                    LIMIT %s
                    """,
                    (embedding_str, embedding_model, embedding_str, limit),
                )
            # Busca semantica padrao ordenada por distancia de cosseno
            else:
                await cur.execute(
                    """
                    SELECT title, content, metadata, 1 - (embedding <=> %s::public.vector) AS similarity
                    FROM knowledge_base
                    ORDER BY embedding <=> %s::public.vector
                    LIMIT %s
                    """,
                    (embedding_str, embedding_str, limit),
                )
            # Retorna as linhas mais relevantes encontradas
            return await cur.fetchall()

    # Metodo para indexar novos fragmentos ou paginas de documentos de forma idempotente
    async def insert_chunk(
        self,
        title: str,
        content: str,
        embedding: list[float],
        embedding_model: str = "text-embedding-3-small",
        metadata: dict | None = None,
    ):
        """Insere ou atualiza um fragmento na base de conhecimento vetorial do tenant."""
        # Formata o vetor para string
        embedding_str = f"[{','.join(map(str, embedding))}]"
        meta_json = json.dumps(metadata or {})

        # Abre o cursor
        async with self.conn.cursor() as cur:
            # Insere no banco com deduplicacao automatica baseada no hash do conteudo
            await cur.execute(
                """
                INSERT INTO knowledge_base (
                    title, content, embedding, embedding_model, metadata
                ) VALUES (%s, %s, %s::public.vector, %s, %s)
                ON CONFLICT (tenant_id, content_hash) DO UPDATE
                SET title = EXCLUDED.title,
                    metadata = EXCLUDED.metadata,
                    updated_at = now()
                """,
                (title, content, embedding_str, embedding_model, meta_json),
            )
