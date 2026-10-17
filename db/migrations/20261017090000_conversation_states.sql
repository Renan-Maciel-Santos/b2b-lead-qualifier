-- migrate:up

-- Template step: conversation_states table tracking conversational state and accumulated slots per tenant and phone
CREATE OR REPLACE FUNCTION core.tenant_step_conversation_states(p_schema text)
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

    -- Index for lookup and ordering by updated_at
    EXECUTE format(
        'CREATE INDEX IF NOT EXISTS conversation_states_updated_idx ON %I.conversation_states (updated_at DESC)',
        p_schema
    );

    -- Apply RLS and grant privileges to app_user
    PERFORM core.secure_tenant_table(p_schema, 'conversation_states', 'SELECT, INSERT, UPDATE, DELETE');
END;
$$;

REVOKE EXECUTE ON FUNCTION core.tenant_step_conversation_states(text) FROM PUBLIC;

-- Register step in tenant schema template
INSERT INTO core.tenant_schema_steps (step_order, function_name)
VALUES (20, 'tenant_step_conversation_states')
ON CONFLICT (step_order) DO UPDATE SET function_name = EXCLUDED.function_name;

-- Apply step to all existing tenant schemas
DO $$
DECLARE
    v_schema text;
BEGIN
    FOR v_schema IN SELECT schema_name FROM core.tenants LOOP
        PERFORM core.tenant_step_conversation_states(v_schema);
    END LOOP;
END;
$$;

-- migrate:down

DO $$
DECLARE
    v_schema text;
BEGIN
    FOR v_schema IN SELECT schema_name FROM core.tenants LOOP
        EXECUTE format('DROP TABLE IF EXISTS %I.conversation_states', v_schema);
    END LOOP;
END;
$$;

DELETE FROM core.tenant_schema_steps WHERE function_name = 'tenant_step_conversation_states';
DROP FUNCTION IF EXISTS core.tenant_step_conversation_states(text);
