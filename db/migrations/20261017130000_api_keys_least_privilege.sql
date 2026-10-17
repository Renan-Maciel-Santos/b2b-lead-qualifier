-- migrate:up

-- Enforce least privilege on core.api_keys: prevent app_user from querying the table directly
REVOKE SELECT ON core.api_keys FROM app_user;

-- Restrict execution of the SECURITY DEFINER function to app_user only
REVOKE EXECUTE ON FUNCTION core.resolve_tenant_by_api_key(varchar(64)) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION core.resolve_tenant_by_api_key(varchar(64)) TO app_user;

-- migrate:down

REVOKE EXECUTE ON FUNCTION core.resolve_tenant_by_api_key(varchar(64)) FROM app_user;
GRANT EXECUTE ON FUNCTION core.resolve_tenant_by_api_key(varchar(64)) TO PUBLIC;
GRANT SELECT ON core.api_keys TO app_user;
