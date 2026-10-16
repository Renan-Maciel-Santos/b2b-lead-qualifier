-- migrate:up

-- 1. Ensure app_user role exists and rename optime_app if it exists
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'optime_app') 
       AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'app_user') THEN
        ALTER ROLE optime_app RENAME TO app_user;
    ELSIF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'app_user') THEN
        CREATE ROLE app_user WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
END
$$;

-- 2. Rename optime_core schema to core
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'optime_core') THEN
        ALTER SCHEMA optime_core RENAME TO core;
    ELSE
        CREATE SCHEMA IF NOT EXISTS core;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA core TO app_user;

-- 3. Update current_tenant_id function to read from session GUC app.current_tenant
CREATE OR REPLACE FUNCTION core.current_tenant_id()
RETURNS uuid
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
    SELECT NULLIF(current_setting('app.current_tenant', true), '')::uuid
$$;

-- 4. Recreate secure_tenant_table helper pointing to core and app_user
CREATE OR REPLACE FUNCTION core.secure_tenant_table(p_schema text, p_table text, p_privileges text)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    IF p_privileges !~ '^(SELECT|INSERT|UPDATE|DELETE)(, (SELECT|INSERT|UPDATE|DELETE))*$' THEN
        RAISE EXCEPTION 'Invalid privileges list: %', p_privileges;
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

-- 5. Recreate provision_tenant function pointing to core and app_user
CREATE OR REPLACE FUNCTION core.provision_tenant(p_tenant_id uuid, p_name text, p_schema text)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_step record;
BEGIN
    INSERT INTO core.tenants (id, name, schema_name)
    VALUES (p_tenant_id, p_name, p_schema)
    ON CONFLICT (id) DO NOTHING;

    IF NOT EXISTS (
        SELECT 1 FROM core.tenants WHERE id = p_tenant_id AND schema_name = p_schema
    ) THEN
        RAISE EXCEPTION 'Tenant % already registered with another schema.', p_tenant_id;
    END IF;

    EXECUTE format('CREATE SCHEMA IF NOT EXISTS %I', p_schema);
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO app_user', p_schema);

    FOR v_step IN
        SELECT function_name FROM core.tenant_schema_steps ORDER BY step_order
    LOOP
        EXECUTE format('SELECT core.%I($1)', v_step.function_name) USING p_schema;
    END LOOP;
END
$$;

REVOKE EXECUTE ON FUNCTION core.secure_tenant_table(text, text, text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION core.provision_tenant(uuid, text, text) FROM PUBLIC;

-- 6. Update tenant_isolation policy on core.tenants for app_user
DROP POLICY IF EXISTS tenant_isolation ON core.tenants;
CREATE POLICY tenant_isolation ON core.tenants
    AS PERMISSIVE FOR SELECT
    TO app_user
    USING (id = core.current_tenant_id());

GRANT SELECT ON core.tenants TO app_user;

-- 7. Re-apply secure_tenant_table on all active tenant schemas
DO $$
DECLARE
    v_schema text;
BEGIN
    FOR v_schema IN SELECT schema_name FROM core.tenants LOOP
        EXECUTE format('GRANT USAGE ON SCHEMA %I TO app_user', v_schema);
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema AND table_name = 'processed_messages') THEN
            PERFORM core.secure_tenant_table(v_schema, 'processed_messages', 'SELECT, INSERT');
        END IF;
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema AND table_name = 'conversation_states') THEN
            PERFORM core.secure_tenant_table(v_schema, 'conversation_states', 'SELECT, INSERT, UPDATE');
        END IF;
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema AND table_name = 'scoring_rule_sets') THEN
            PERFORM core.secure_tenant_table(v_schema, 'scoring_rule_sets', 'SELECT');
        END IF;
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema AND table_name = 'scoring_results') THEN
            PERFORM core.secure_tenant_table(v_schema, 'scoring_results', 'SELECT, INSERT');
        END IF;
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = v_schema AND table_name = 'knowledge_base') THEN
            PERFORM core.secure_tenant_table(v_schema, 'knowledge_base', 'SELECT, INSERT, UPDATE, DELETE');
        END IF;
    END LOOP;
END
$$;

-- migrate:down

ALTER SCHEMA core RENAME TO optime_core;
ALTER ROLE app_user RENAME TO optime_app;
