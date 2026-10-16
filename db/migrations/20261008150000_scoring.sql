-- migrate:up

-- Etapa de template: regras de scoring versionadas e resultados append-only em um schema de tenant
CREATE FUNCTION optime_core.tenant_step_scoring(p_schema text)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    -- Cada linha e uma versao imutavel do conjunto de regras (configuracao versionada, ADR 003)
    EXECUTE format($ddl$
        CREATE TABLE IF NOT EXISTS %I.scoring_rule_sets (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL DEFAULT optime_core.current_tenant_id(),
            version INT NOT NULL CHECK (version > 0),
            -- Lista de regras no formato [{"type": "knockout" | "exact_match", "field": ..., ...}]
            rules JSONB NOT NULL CHECK (jsonb_typeof(rules) = 'array'),
            qualification_threshold INT NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, id),
            UNIQUE (tenant_id, version),
            CONSTRAINT fk_tenant
                FOREIGN KEY (tenant_id)
                REFERENCES optime_core.tenants (id)
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
            tenant_id UUID NOT NULL DEFAULT optime_core.current_tenant_id(),
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
                REFERENCES optime_core.tenants (id)
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
    PERFORM optime_core.secure_tenant_table(p_schema, 'scoring_rule_sets', 'SELECT');
    -- Append-only real: o app nao tem UPDATE nem DELETE sobre os resultados
    PERFORM optime_core.secure_tenant_table(p_schema, 'scoring_results', 'SELECT, INSERT');
END
$$;

REVOKE EXECUTE ON FUNCTION optime_core.tenant_step_scoring(text) FROM PUBLIC;

-- Registra a etapa no template aplicado a novos tenants
INSERT INTO optime_core.tenant_schema_steps (step_order, function_name)
VALUES (20, 'tenant_step_scoring');

-- Aplica a etapa aos tenants ja existentes
SELECT optime_core.tenant_step_scoring(schema_name) FROM optime_core.tenants;

-- migrate:down

DO $$
DECLARE
    v_schema text;
BEGIN
    FOR v_schema IN SELECT schema_name FROM optime_core.tenants LOOP
        EXECUTE format('DROP TABLE IF EXISTS %I.scoring_results', v_schema);
        EXECUTE format('DROP TABLE IF EXISTS %I.scoring_rule_sets', v_schema);
    END LOOP;
END
$$;

DELETE FROM optime_core.tenant_schema_steps WHERE function_name = 'tenant_step_scoring';
DROP FUNCTION IF EXISTS optime_core.tenant_step_scoring(text);
