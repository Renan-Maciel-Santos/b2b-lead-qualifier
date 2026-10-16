-- migrate:up

-- Habilita o pgvector no schema public (incluido no search_path de cada transacao do app)
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;

-- Etapa de template: base de conhecimento vetorial (RAG) em um schema de tenant
CREATE FUNCTION optime_core.tenant_step_knowledge_base(p_schema text)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    EXECUTE format($ddl$
        CREATE TABLE IF NOT EXISTS %I.knowledge_base (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL DEFAULT optime_core.current_tenant_id(),
            -- Titulo ou identificador do documento (ex: Apresentacao, Tabela de Servicos)
            title VARCHAR(255) NOT NULL,
            content TEXT NOT NULL,
            -- Hash do conteudo para ingestao idempotente (deduplicacao, nao seguranca)
            content_hash TEXT NOT NULL GENERATED ALWAYS AS (md5(content)) STORED,
            -- Obrigatorio: fragmento sem vetor nao participa da busca semantica
            embedding public.vector(1536) NOT NULL,
            -- Modelo que gerou o vetor; permite reindexar e nunca comparar vetores de modelos diferentes
            embedding_model TEXT NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, id),
            CONSTRAINT knowledge_base_content_unique UNIQUE (tenant_id, content_hash),
            CONSTRAINT fk_tenant
                FOREIGN KEY (tenant_id)
                REFERENCES optime_core.tenants (id)
                ON DELETE CASCADE
        )
    $ddl$, p_schema);

    -- Indice HNSW para similaridade de cosseno
    EXECUTE format(
        'CREATE INDEX IF NOT EXISTS knowledge_base_embedding_idx '
        'ON %I.knowledge_base USING hnsw (embedding public.vector_cosine_ops)',
        p_schema
    );

    -- UPDATE e necessario para o upsert de reingestao
    PERFORM optime_core.secure_tenant_table(p_schema, 'knowledge_base', 'SELECT, INSERT, UPDATE, DELETE');
END
$$;

REVOKE EXECUTE ON FUNCTION optime_core.tenant_step_knowledge_base(text) FROM PUBLIC;

-- Registra a etapa no template aplicado a novos tenants
INSERT INTO optime_core.tenant_schema_steps (step_order, function_name)
VALUES (30, 'tenant_step_knowledge_base');

-- Aplica a etapa aos tenants ja existentes
SELECT optime_core.tenant_step_knowledge_base(schema_name) FROM optime_core.tenants;

-- migrate:down

DO $$
DECLARE
    v_schema text;
BEGIN
    FOR v_schema IN SELECT schema_name FROM optime_core.tenants LOOP
        EXECUTE format('DROP TABLE IF EXISTS %I.knowledge_base', v_schema);
    END LOOP;
END
$$;

DELETE FROM optime_core.tenant_schema_steps WHERE function_name = 'tenant_step_knowledge_base';
DROP FUNCTION IF EXISTS optime_core.tenant_step_knowledge_base(text);
