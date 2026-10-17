-- migrate:up

-- Falha cedo se o bootstrap de infraestrutura (db/bootstrap) nao criou o role da aplicacao
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'app_user') THEN
        RAISE EXCEPTION 'Role app_user inexistente: execute db/bootstrap/create_app_role.psql antes do dbmate.';
    END IF;
END
$$;

-- Habilita o pgvector no schema public (incluido no search_path de cada transacao do app)
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;

-- Cria o schema global da plataforma (dados compartilhados e funcoes de provisionamento)
CREATE SCHEMA IF NOT EXISTS core;

-- Permite que o app resolva objetos do schema global (tabelas continuam protegidas por GRANT + RLS)
GRANT USAGE ON SCHEMA core TO app_user;

-- Le o tenant da transacao atual; devolve NULL quando ausente, fazendo toda policy falhar fechada
-- STABLE permite que o planner use o resultado como chave de indice (policy sargavel)
CREATE FUNCTION core.current_tenant_id()
RETURNS uuid
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
    SELECT NULLIF(current_setting('app.current_tenant', true), '')::uuid
$$;

-- Cadastro global de tenants: cada cliente possui exatamente um schema dedicado
CREATE TABLE core.tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    -- Nome restrito por regex para ser seguro em SQL dinamico e no search_path
    schema_name TEXT NOT NULL UNIQUE
        CONSTRAINT tenants_schema_name_format CHECK (schema_name ~ '^tenant_[a-z0-9_]{1,40}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Ativa o RLS e o aplica inclusive ao dono da tabela (defesa em profundidade)
ALTER TABLE core.tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.tenants FORCE ROW LEVEL SECURITY;

-- O app enxerga somente a linha do proprio tenant da transacao
CREATE POLICY tenant_isolation ON core.tenants
    AS PERMISSIVE FOR SELECT
    TO app_user
    USING (id = core.current_tenant_id());

-- O app apenas le tenants; criacao e alteracao sao exclusivas do provisionamento administrativo
GRANT SELECT ON core.tenants TO app_user;

-- Registro ordenado das etapas de DDL aplicadas a todo schema de tenant (template versionado)
CREATE TABLE core.tenant_schema_steps (
    step_order INT PRIMARY KEY,
    -- Nome de uma funcao em core com assinatura (p_schema text) e corpo idempotente
    function_name TEXT NOT NULL UNIQUE
        CONSTRAINT tenant_schema_steps_function_format CHECK (function_name ~ '^tenant_step_[a-z0-9_]+$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Tabela de chaves de API para autenticacao Bearer por tenant
CREATE TABLE core.api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    key_hash VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ NULL
);

-- Indice parcial para consultas de autenticacao de chaves ativas
CREATE INDEX idx_api_keys_lookup ON core.api_keys (key_hash) WHERE revoked_at IS NULL;

-- Privilegio minimo: app_user nao consulta core.api_keys diretamente
REVOKE ALL ON core.api_keys FROM app_user;

-- Funcao SECURITY DEFINER para resolver tenant_id e schema_name a partir do hash da API key
CREATE FUNCTION core.resolve_tenant_by_api_key(p_key_hash varchar(64))
RETURNS TABLE (tenant_id uuid, schema_name text)
LANGUAGE sql
SECURITY DEFINER
SET search_path = core, pg_catalog
AS $$
    SELECT k.tenant_id, t.schema_name
    FROM core.api_keys k
    JOIN core.tenants t ON t.id = k.tenant_id
    WHERE k.key_hash = p_key_hash
      AND k.revoked_at IS NULL
    LIMIT 1;
$$;

-- Restringe execucao da funcao SECURITY DEFINER exclusivamente a app_user
REVOKE EXECUTE ON FUNCTION core.resolve_tenant_by_api_key(varchar(64)) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION core.resolve_tenant_by_api_key(varchar(64)) TO app_user;

-- Helper administrativo: ativa e forca RLS, recria a policy de isolamento e concede privilegios minimos
CREATE FUNCTION core.secure_tenant_table(p_schema text, p_table text, p_privileges text)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    -- Aceita apenas combinacoes de privilegios DML conhecidas, evitando SQL arbitrario
    IF p_privileges !~ '^(SELECT|INSERT|UPDATE|DELETE)(, (SELECT|INSERT|UPDATE|DELETE))*$' THEN
        RAISE EXCEPTION 'Lista de privilegios invalida: %', p_privileges;
    END IF;

    EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY', p_schema, p_table);
    EXECUTE format('ALTER TABLE %I.%I FORCE ROW LEVEL SECURITY', p_schema, p_table);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I.%I', p_schema, p_table);
    EXECUTE format(
        'CREATE POLICY tenant_isolation ON %I.%I AS PERMISSIVE FOR ALL TO app_user '
        'USING (tenant_id = core.current_tenant_id()) '
        'WITH CHECK (tenant_id = core.current_tenant_id())',
        p_schema, p_table
    );
    EXECUTE format('REVOKE ALL ON %I.%I FROM app_user', p_schema, p_table);
    EXECUTE format('GRANT %s ON %I.%I TO app_user', p_privileges, p_schema, p_table);
END
$$;

REVOKE EXECUTE ON FUNCTION core.secure_tenant_table(text, text, text) FROM PUBLIC;

-- Etapa 10: tabela de idempotencia por ID de mensagem do WhatsApp com status de processamento
CREATE FUNCTION core.tenant_step_processed_messages(p_schema text)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    EXECUTE format($ddl$
        CREATE TABLE IF NOT EXISTS %I.processed_messages (
            message_id VARCHAR(255) NOT NULL,
            -- Preenchido pelo tenant da transacao; sem tenant vira NULL e o INSERT falha fechado
            tenant_id UUID NOT NULL DEFAULT core.current_tenant_id(),
            status VARCHAR(20) NOT NULL DEFAULT 'processing',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, message_id),
            CONSTRAINT fk_tenant
                FOREIGN KEY (tenant_id)
                REFERENCES core.tenants (id)
                ON DELETE CASCADE,
            CONSTRAINT processed_messages_status_check
                CHECK (status IN ('processing', 'done', 'failed'))
        )
    $ddl$, p_schema);

    -- Suporta a rotina de expurgo por data (retencao)
    EXECUTE format(
        'CREATE INDEX IF NOT EXISTS processed_messages_created_at_idx ON %I.processed_messages (created_at)',
        p_schema
    );

    -- Suporta recuperacao de mensagens pendentes/travadas por timeout
    EXECUTE format(
        'CREATE INDEX IF NOT EXISTS processed_messages_status_idx ON %I.processed_messages (status, updated_at)',
        p_schema
    );

    -- O app consulta, insere e atualiza o status das mensagens
    PERFORM core.secure_tenant_table(p_schema, 'processed_messages', 'SELECT, INSERT, UPDATE');
END;
$$;

REVOKE EXECUTE ON FUNCTION core.tenant_step_processed_messages(text) FROM PUBLIC;

-- Etapa 15: regras de scoring versionadas e resultados append-only em um schema de tenant
CREATE FUNCTION core.tenant_step_scoring(p_schema text)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    -- Cada linha e uma versao imutavel do conjunto de regras (configuracao versionada, ADR 003)
    EXECUTE format($ddl$
        CREATE TABLE IF NOT EXISTS %I.scoring_rule_sets (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL DEFAULT core.current_tenant_id(),
            version INT NOT NULL CHECK (version > 0),
            -- Lista de regras no formato [{"type": "knockout" | "exact_match", "field": ..., ...}]
            rules JSONB NOT NULL CHECK (jsonb_typeof(rules) = 'array'),
            -- Slots obrigatorios para qualificacao completa (ordem de declaracao preservada)
            required_slots text[] NOT NULL CHECK (cardinality(required_slots) > 0),
            qualification_threshold INT NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, id),
            UNIQUE (tenant_id, version),
            CONSTRAINT fk_tenant
                FOREIGN KEY (tenant_id)
                REFERENCES core.tenants (id)
                ON DELETE CASCADE
        )
    $ddl$, p_schema);

    -- No maximo uma versao ativa por tenant
    EXECUTE format(
        'CREATE UNIQUE INDEX IF NOT EXISTS scoring_rule_sets_one_active_idx '
        'ON %I.scoring_rule_sets (tenant_id) WHERE is_active',
        p_schema
    );

    -- Resultado de cada avaliacao; referencia a versao exata das regras usadas (auditoria reproduzivel)
    EXECUTE format($ddl$
        CREATE TABLE IF NOT EXISTS %I.scoring_results (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL DEFAULT core.current_tenant_id(),
            rule_set_id UUID NOT NULL,
            -- Telefone normalizado em E.164 (dado pessoal, LGPD)
            phone_number VARCHAR(16) NOT NULL
                CONSTRAINT scoring_results_phone_e164 CHECK (phone_number ~ '^\+[1-9][0-9]{7,14}$'),
            final_score INT NOT NULL,
            is_qualified BOOLEAN NOT NULL,
            audit_trail JSONB NOT NULL CHECK (jsonb_typeof(audit_trail) = 'array'),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, id),
            CONSTRAINT fk_tenant
                FOREIGN KEY (tenant_id)
                REFERENCES core.tenants (id)
                ON DELETE CASCADE,
            -- FK composta: impede referenciar regras de outro tenant; RESTRICT preserva a auditoria
            CONSTRAINT fk_rule_set
                FOREIGN KEY (tenant_id, rule_set_id)
                REFERENCES %I.scoring_rule_sets (tenant_id, id)
                ON DELETE RESTRICT
        )
    $ddl$, p_schema, p_schema);

    -- Atende a listagem do dashboard (mais recentes primeiro)
    EXECUTE format(
        'CREATE INDEX IF NOT EXISTS scoring_results_recent_idx '
        'ON %I.scoring_results (tenant_id, created_at DESC)',
        p_schema
    );

    -- Atende o historico de um lead especifico
    EXECUTE format(
        'CREATE INDEX IF NOT EXISTS scoring_results_phone_idx '
        'ON %I.scoring_results (tenant_id, phone_number, created_at DESC)',
        p_schema
    );

    -- Regras sao mantidas pelo provisionamento administrativo; o app apenas le
    PERFORM core.secure_tenant_table(p_schema, 'scoring_rule_sets', 'SELECT');
    -- Append-only real: o app nao tem UPDATE nem DELETE sobre os resultados
    PERFORM core.secure_tenant_table(p_schema, 'scoring_results', 'SELECT, INSERT');
END;
$$;

REVOKE EXECUTE ON FUNCTION core.tenant_step_scoring(text) FROM PUBLIC;

-- Etapa 20: tabela de estados de conversa e acumulacao progressiva de slots por telefone
CREATE FUNCTION core.tenant_step_conversation_states(p_schema text)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    EXECUTE format($ddl$
        CREATE TABLE IF NOT EXISTS %I.conversation_states (
            phone_number VARCHAR(30) NOT NULL,
            tenant_id UUID NOT NULL DEFAULT core.current_tenant_id(),
            current_state VARCHAR(50) NOT NULL DEFAULT 'INITIAL',
            accumulated_slots JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, phone_number),
            CONSTRAINT fk_conversation_states_tenant
                FOREIGN KEY (tenant_id)
                REFERENCES core.tenants (id)
                ON DELETE CASCADE
        )
    $ddl$, p_schema);

    -- Indice para ordenacao e consulta por atualizacao recente
    EXECUTE format(
        'CREATE INDEX IF NOT EXISTS conversation_states_updated_idx ON %I.conversation_states (updated_at DESC)',
        p_schema
    );

    -- O app gerencia o ciclo completo de estado da conversa
    PERFORM core.secure_tenant_table(p_schema, 'conversation_states', 'SELECT, INSERT, UPDATE, DELETE');
END;
$$;

REVOKE EXECUTE ON FUNCTION core.tenant_step_conversation_states(text) FROM PUBLIC;

-- Etapa 30: base de conhecimento vetorial (RAG) em um schema de tenant
CREATE FUNCTION core.tenant_step_knowledge_base(p_schema text)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    EXECUTE format($ddl$
        CREATE TABLE IF NOT EXISTS %I.knowledge_base (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL DEFAULT core.current_tenant_id(),
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
                REFERENCES core.tenants (id)
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
    PERFORM core.secure_tenant_table(p_schema, 'knowledge_base', 'SELECT, INSERT, UPDATE, DELETE');
END;
$$;

REVOKE EXECUTE ON FUNCTION core.tenant_step_knowledge_base(text) FROM PUBLIC;

-- Registra as etapas no template ordenado aplicado a novos tenants
INSERT INTO core.tenant_schema_steps (step_order, function_name)
VALUES
    (10, 'tenant_step_processed_messages'),
    (15, 'tenant_step_scoring'),
    (20, 'tenant_step_conversation_states'),
    (30, 'tenant_step_knowledge_base')
ON CONFLICT (step_order) DO UPDATE SET function_name = EXCLUDED.function_name;

-- Provisiona (ou reconcilia) um tenant: registra, cria o schema e aplica todas as etapas em ordem
-- Idempotente: pode ser executada novamente para o mesmo tenant sem efeitos colaterais
CREATE FUNCTION core.provision_tenant(p_tenant_id uuid, p_name text, p_schema text)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_step record;
BEGIN
    INSERT INTO core.tenants (id, name, schema_name)
    VALUES (p_tenant_id, p_name, p_schema)
    ON CONFLICT (id) DO NOTHING;

    -- Impede reapontar um tenant existente para outro schema
    IF NOT EXISTS (
        SELECT 1 FROM core.tenants WHERE id = p_tenant_id AND schema_name = p_schema
    ) THEN
        RAISE EXCEPTION 'Tenant % ja cadastrado com outro schema.', p_tenant_id;
    END IF;

    EXECUTE format('CREATE SCHEMA IF NOT EXISTS %I', p_schema);
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO app_user', p_schema);

    FOR v_step IN
        SELECT function_name FROM core.tenant_schema_steps ORDER BY step_order
    LOOP
        EXECUTE format('SELECT core.%I($1)', v_step.function_name) USING p_schema;
    END LOOP;
END;
$$;

REVOKE EXECUTE ON FUNCTION core.provision_tenant(uuid, text, text) FROM PUBLIC;

-- Expurgo administrativo de chaves de idempotencia antigas em todos os tenants; devolve linhas removidas
CREATE FUNCTION core.purge_processed_messages(p_retention interval)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    v_schema text;
    v_rows bigint;
    v_total bigint := 0;
BEGIN
    FOR v_schema IN SELECT schema_name FROM core.tenants LOOP
        EXECUTE format('DELETE FROM %I.processed_messages WHERE created_at < now() - $1', v_schema)
            USING p_retention;
        GET DIAGNOSTICS v_rows = ROW_COUNT;
        v_total := v_total + v_rows;
    END LOOP;
    RETURN v_total;
END;
$$;

REVOKE EXECUTE ON FUNCTION core.purge_processed_messages(interval) FROM PUBLIC;

-- migrate:down

-- Remove os schemas de todos os tenants provisionados (incluindo scoring_rule_sets com required_slots) antes de apagar o catalogo global
DO $$
DECLARE
    v_schema text;
BEGIN
    FOR v_schema IN SELECT schema_name FROM core.tenants LOOP
        EXECUTE format('DROP SCHEMA IF EXISTS %I CASCADE', v_schema);
    END LOOP;
END
$$;

DROP SCHEMA IF EXISTS core CASCADE;
DROP EXTENSION IF EXISTS vector;
