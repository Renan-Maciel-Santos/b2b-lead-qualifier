-- migrate:up

CREATE TABLE core.api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    key_hash VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ NULL
);

-- Partial index for high-performance authentication lookups on active keys
CREATE INDEX idx_api_keys_lookup ON core.api_keys (key_hash) WHERE revoked_at IS NULL;

-- Allow application role to query keys and execute lookup
GRANT SELECT ON core.api_keys TO app_user;

-- Security definer function to resolve tenant_id and schema_name before tenant session is set
CREATE OR REPLACE FUNCTION core.resolve_tenant_by_api_key(p_key_hash varchar(64))
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

GRANT EXECUTE ON FUNCTION core.resolve_tenant_by_api_key(varchar(64)) TO app_user;

-- migrate:down

DROP FUNCTION IF EXISTS core.resolve_tenant_by_api_key(varchar(64));
DROP TABLE IF EXISTS core.api_keys CASCADE;
