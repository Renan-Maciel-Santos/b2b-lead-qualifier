-- migrate:up
-- Enforce strict immutability of versioned scoring rule sets across all tenant schemas.
-- Ensures reproducible audit trails by preventing in-place modifications to rules, required slots,
-- qualification threshold, version, and tenant_id. Only the is_active toggle may be updated.

CREATE OR REPLACE FUNCTION core.enforce_rule_set_immutability()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF (OLD.rules IS DISTINCT FROM NEW.rules OR
        OLD.required_slots IS DISTINCT FROM NEW.required_slots OR
        OLD.qualification_threshold IS DISTINCT FROM NEW.qualification_threshold OR
        OLD.version IS DISTINCT FROM NEW.version OR
        OLD.tenant_id IS DISTINCT FROM NEW.tenant_id) THEN
        RAISE EXCEPTION 'Scoring rule sets are immutable per version. Field updates to rules, required_slots, qualification_threshold, version, or tenant_id are prohibited. Insert a new version instead.';
    END IF;
    RETURN NEW;
END;
$$;

REVOKE EXECUTE ON FUNCTION core.enforce_rule_set_immutability() FROM PUBLIC;

-- Tenant provisioning step to attach immutability trigger
CREATE OR REPLACE FUNCTION core.tenant_step_rule_set_immutability(p_schema text)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    EXECUTE format(
        'DROP TRIGGER IF EXISTS trg_enforce_rule_set_immutability ON %I.scoring_rule_sets',
        p_schema
    );
    EXECUTE format(
        'CREATE TRIGGER trg_enforce_rule_set_immutability '
        'BEFORE UPDATE ON %I.scoring_rule_sets '
        'FOR EACH ROW EXECUTE FUNCTION core.enforce_rule_set_immutability()',
        p_schema
    );
END;
$$;

REVOKE EXECUTE ON FUNCTION core.tenant_step_rule_set_immutability(text) FROM PUBLIC;

-- Register step in tenant provisioning template
INSERT INTO core.tenant_schema_steps (step_order, function_name)
VALUES (16, 'tenant_step_rule_set_immutability')
ON CONFLICT (step_order) DO UPDATE SET function_name = EXCLUDED.function_name;

-- Apply immutability trigger to all existing provisioned tenant schemas
DO $$
DECLARE
    v_tenant record;
BEGIN
    FOR v_tenant IN SELECT schema_name FROM core.tenants LOOP
        PERFORM core.tenant_step_rule_set_immutability(v_tenant.schema_name);
    END LOOP;
END;
$$;

-- migrate:down

-- Remove provisioning step
DELETE FROM core.tenant_schema_steps WHERE step_order = 16;

-- Detach immutability triggers from all tenant schemas
DO $$
DECLARE
    v_tenant record;
BEGIN
    FOR v_tenant IN SELECT schema_name FROM core.tenants LOOP
        EXECUTE format(
            'DROP TRIGGER IF EXISTS trg_enforce_rule_set_immutability ON %I.scoring_rule_sets',
            v_tenant.schema_name
        );
    END LOOP;
END;
$$;

DROP FUNCTION IF EXISTS core.tenant_step_rule_set_immutability(text);
DROP FUNCTION IF EXISTS core.enforce_rule_set_immutability();
