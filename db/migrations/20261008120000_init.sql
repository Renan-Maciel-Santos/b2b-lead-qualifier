-- migrate:up

-- Falha cedo se o bootstrap de infraestrutura (db/bootstrap) nao criou o role da aplicacao
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'optime_app') THEN
        RAISE EXCEPTION 'Role optime_app inexistente: execute db/bootstrap/create_app_role.psql antes do dbmate.';
    END IF;
END
$$;

-- Cria o schema global da plataforma (dados compartilhados e funcoes de provisionamento)
CREATE SCHEMA IF NOT EXISTS optime_core;

-- Permite que o app resolva objetos do schema global (tabelas continuam protegidas por GRANT + RLS)
GRANT USAGE ON SCHEMA optime_core TO optime_app;

-- Le o tenant da transacao atual; devolve NULL quando ausente, fazendo toda policy falhar fechada
-- STABLE permite que o planner use o resultado como chave de indice (policy sargavel)
CREATE FUNCTION optime_core.current_tenant_id()
RETURNS uuid
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
    SELECT NULLIF(current_setting('optime.current_tenant', true), '')::uuid
$$;

-- Cadastro global de tenants: cada cliente possui exatamente um schema dedicado
CREATE TABLE optime_core.tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    -- Nome restrito por regex para ser seguro em SQL dinamico e no search_path
    schema_name TEXT NOT NULL UNIQUE
        CONSTRAINT tenants_schema_name_format CHECK (schema_name ~ '^tenant_[a-z0-9_]{1,40}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Ativa o RLS e o aplica inclusive ao dono da tabela (defesa em profundidade)
ALTER TABLE optime_core.tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE optime_core.tenants FORCE ROW LEVEL SECURITY;

-- O app enxerga somente a linha do proprio tenant da transacao
CREATE POLICY tenant_isolation ON optime_core.tenants
    AS PERMISSIVE FOR SELECT
    TO optime_app
    USING (id = optime_core.current_tenant_id());

-- O app apenas le tenants; criacao e alteracao sao exclusivas do provisionamento administrativo
GRANT SELECT ON optime_core.tenants TO optime_app;

-- Registro ordenado das etapas de DDL aplicadas a todo schema de tenant (template versionado)
CREATE TABLE optime_core.tenant_schema_steps (
    step_order INT PRIMARY KEY,
    -- Nome de uma funcao em optime_core com assinatura (p_schema text) e corpo idempotente
    function_name TEXT NOT NULL UNIQUE
        CONSTRAINT tenant_schema_steps_function_format CHECK (function_name ~ '^tenant_step_[a-z0-9_]+$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Helper administrativo: ativa e forca RLS, recria a policy de isolamento e concede privilegios minimos
CREATE FUNCTION optime_core.secure_tenant_table(p_schema text, p_table text, p_privileges text)
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
        'CREATE POLICY tenant_isolation ON %I.%I AS PERMISSIVE FOR ALL TO optime_app '
        'USING (tenant_id = optime_core.current_tenant_id()) '
        'WITH CHECK (tenant_id = optime_core.current_tenant_id())',
        p_schema, p_table
    );
    EXECUTE format('REVOKE ALL ON %I.%I FROM optime_app', p_schema, p_table);
    EXECUTE format('GRANT %s ON %I.%I TO optime_app', p_privileges, p_schema, p_table);
END
$$;

-- Provisiona (ou reconcilia) um tenant: registra, cria o schema e aplica todas as etapas em ordem
-- Idempotente: pode ser executada novamente para o mesmo tenant sem efeitos colaterais
CREATE FUNCTION optime_core.provision_tenant(p_tenant_id uuid, p_name text, p_schema text)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_step record;
BEGIN
    INSERT INTO optime_core.tenants (id, name, schema_name)
    VALUES (p_tenant_id, p_name, p_schema)
    ON CONFLICT (id) DO NOTHING;

    -- Impede reapontar um tenant existente para outro schema
    IF NOT EXISTS (
        SELECT 1 FROM optime_core.tenants WHERE id = p_tenant_id AND schema_name = p_schema
    ) THEN
        RAISE EXCEPTION 'Tenant % ja cadastrado com outro schema.', p_tenant_id;
    END IF;

    EXECUTE format('CREATE SCHEMA IF NOT EXISTS %I', p_schema);
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO optime_app', p_schema);

    FOR v_step IN
        SELECT function_name FROM optime_core.tenant_schema_steps ORDER BY step_order
    LOOP
        EXECUTE format('SELECT optime_core.%I($1)', v_step.function_name) USING p_schema;
    END LOOP;
END
$$;

-- Funcoes administrativas nao podem ser chamadas pelo app (EXECUTE e concedido a PUBLIC por padrao)
REVOKE EXECUTE ON FUNCTION optime_core.secure_tenant_table(text, text, text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION optime_core.provision_tenant(uuid, text, text) FROM PUBLIC;

-- migrate:down

-- Remove os schemas de todos os tenants provisionados antes de apagar o catalogo global
DO $$
DECLARE
    v_schema text;
BEGIN
    FOR v_schema IN SELECT schema_name FROM optime_core.tenants LOOP
        EXECUTE format('DROP SCHEMA IF EXISTS %I CASCADE', v_schema);
    END LOOP;
END
$$;

DROP SCHEMA IF EXISTS optime_core CASCADE;
