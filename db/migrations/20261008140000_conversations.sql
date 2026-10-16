-- migrate:up

-- Etapa de template: tabela de idempotencia por ID de mensagem do WhatsApp em um schema de tenant
CREATE FUNCTION optime_core.tenant_step_processed_messages(p_schema text)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    EXECUTE format($ddl$
        CREATE TABLE IF NOT EXISTS %I.processed_messages (
            message_id VARCHAR(255) NOT NULL,
            -- Preenchido pelo tenant da transacao; sem tenant vira NULL e o INSERT falha fechado
            tenant_id UUID NOT NULL DEFAULT optime_core.current_tenant_id(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, message_id),
            CONSTRAINT fk_tenant
                FOREIGN KEY (tenant_id)
                REFERENCES optime_core.tenants (id)
                ON DELETE CASCADE
        )
    $ddl$, p_schema);

    -- Suporta a rotina de expurgo por data (retencao)
    EXECUTE format(
        'CREATE INDEX IF NOT EXISTS processed_messages_created_at_idx ON %I.processed_messages (created_at)',
        p_schema
    );

    -- O app so consulta e registra mensagens; o expurgo e administrativo
    PERFORM optime_core.secure_tenant_table(p_schema, 'processed_messages', 'SELECT, INSERT');
END
$$;

REVOKE EXECUTE ON FUNCTION optime_core.tenant_step_processed_messages(text) FROM PUBLIC;

-- Registra a etapa no template aplicado a novos tenants
INSERT INTO optime_core.tenant_schema_steps (step_order, function_name)
VALUES (10, 'tenant_step_processed_messages');

-- Aplica a etapa aos tenants ja existentes
SELECT optime_core.tenant_step_processed_messages(schema_name) FROM optime_core.tenants;

-- Expurgo administrativo de chaves de idempotencia antigas em todos os tenants; devolve linhas removidas
CREATE FUNCTION optime_core.purge_processed_messages(p_retention interval)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    v_schema text;
    v_rows bigint;
    v_total bigint := 0;
BEGIN
    FOR v_schema IN SELECT schema_name FROM optime_core.tenants LOOP
        EXECUTE format('DELETE FROM %I.processed_messages WHERE created_at < now() - $1', v_schema)
            USING p_retention;
        GET DIAGNOSTICS v_rows = ROW_COUNT;
        v_total := v_total + v_rows;
    END LOOP;
    RETURN v_total;
END
$$;

REVOKE EXECUTE ON FUNCTION optime_core.purge_processed_messages(interval) FROM PUBLIC;

-- migrate:down

DO $$
DECLARE
    v_schema text;
BEGIN
    FOR v_schema IN SELECT schema_name FROM optime_core.tenants LOOP
        EXECUTE format('DROP TABLE IF EXISTS %I.processed_messages', v_schema);
    END LOOP;
END
$$;

DROP FUNCTION IF EXISTS optime_core.purge_processed_messages(interval);
DELETE FROM optime_core.tenant_schema_steps WHERE function_name = 'tenant_step_processed_messages';
DROP FUNCTION IF EXISTS optime_core.tenant_step_processed_messages(text);
