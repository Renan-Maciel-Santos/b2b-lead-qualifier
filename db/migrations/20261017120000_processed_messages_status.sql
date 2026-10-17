-- migrate:up

-- Add status and updated_at columns to processed_messages across all tenant schemas
DO $$
DECLARE
    v_schema text;
BEGIN
    FOR v_schema IN SELECT schema_name FROM core.tenants LOOP
        EXECUTE format(
            'ALTER TABLE %I.processed_messages ' ||
            'ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT ''processing'', ' ||
            'ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()',
            v_schema
        );

        EXECUTE format(
            'ALTER TABLE %I.processed_messages ' ||
            'DROP CONSTRAINT IF EXISTS processed_messages_status_check, ' ||
            'ADD CONSTRAINT processed_messages_status_check CHECK (status IN (''processing'', ''done'', ''failed''))',
            v_schema
        );

        -- Grant UPDATE privilege to app_user so the service can update status
        PERFORM core.secure_tenant_table(v_schema, 'processed_messages', 'SELECT, INSERT, UPDATE');
    END LOOP;
END;
$$;

-- Update tenant provisioning step function for future tenants
CREATE OR REPLACE FUNCTION core.tenant_step_processed_messages(p_schema text)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    EXECUTE format($ddl$
        CREATE TABLE IF NOT EXISTS %I.processed_messages (
            message_id VARCHAR(255) NOT NULL,
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

    EXECUTE format(
        'CREATE INDEX IF NOT EXISTS processed_messages_created_at_idx ON %I.processed_messages (created_at)',
        p_schema
    );

    EXECUTE format(
        'CREATE INDEX IF NOT EXISTS processed_messages_status_idx ON %I.processed_messages (status, updated_at)',
        p_schema
    );

    PERFORM core.secure_tenant_table(p_schema, 'processed_messages', 'SELECT, INSERT, UPDATE');
END;
$$;

REVOKE EXECUTE ON FUNCTION core.tenant_step_processed_messages(text) FROM PUBLIC;

-- migrate:down

DO $$
DECLARE
    v_schema text;
BEGIN
    FOR v_schema IN SELECT schema_name FROM core.tenants LOOP
        EXECUTE format(
            'ALTER TABLE %I.processed_messages ' ||
            'DROP CONSTRAINT IF EXISTS processed_messages_status_check, ' ||
            'DROP COLUMN IF EXISTS status, ' ||
            'DROP COLUMN IF EXISTS updated_at',
            v_schema
        );
        PERFORM core.secure_tenant_table(v_schema, 'processed_messages', 'SELECT, INSERT');
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION core.tenant_step_processed_messages(p_schema text)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    EXECUTE format($ddl$
        CREATE TABLE IF NOT EXISTS %I.processed_messages (
            message_id VARCHAR(255) NOT NULL,
            tenant_id UUID NOT NULL DEFAULT core.current_tenant_id(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, message_id),
            CONSTRAINT fk_tenant
                FOREIGN KEY (tenant_id)
                REFERENCES core.tenants (id)
                ON DELETE CASCADE
        )
    $ddl$, p_schema);

    EXECUTE format(
        'CREATE INDEX IF NOT EXISTS processed_messages_created_at_idx ON %I.processed_messages (created_at)',
        p_schema
    );

    PERFORM core.secure_tenant_table(p_schema, 'processed_messages', 'SELECT, INSERT');
END;
$$;

REVOKE EXECUTE ON FUNCTION core.tenant_step_processed_messages(text) FROM PUBLIC;
