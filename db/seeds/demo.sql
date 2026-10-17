-- Development seed: do not run in production.
-- Usage: docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U postgres -d b2b_lead_qualifier -f /db/seeds/demo.sql

-- Provision demo tenant (Acme Corp) with dedicated schema
SELECT core.provision_tenant(
    '11111111-1111-1111-1111-111111111111',
    'Acme Corp (Demo)',
    'tenant_demo'
);

-- Active scoring rules for demo tenant
INSERT INTO tenant_demo.scoring_rule_sets (tenant_id, version, rules, required_slots, qualification_threshold, is_active)
VALUES (
    '11111111-1111-1111-1111-111111111111',
    1,
    '[
        {"type": "knockout", "field": "role", "value": "estudante"},
        {"type": "knockout", "field": "role", "value": "estagiario"},
        {"type": "knockout", "field": "revenue", "value": "abaixo de 50 mil"},
        {"type": "exact_match", "field": "role", "value": "CEO", "points": 50},
        {"type": "exact_match", "field": "role", "value": "Diretor", "points": 40},
        {"type": "exact_match", "field": "role", "value": "Gerente", "points": 25},
        {"type": "exact_match", "field": "revenue", "value": "5 milhoes ao ano", "points": 50},
        {"type": "exact_match", "field": "revenue", "value": "10 milhoes ao ano", "points": 50},
        {"type": "exact_match", "field": "company_size", "value": "mais de 100", "points": 30}
    ]'::jsonb,
    ARRAY['role', 'revenue']::text[],
    50,
    true
)
ON CONFLICT (tenant_id, version) DO UPDATE SET
    rules = EXCLUDED.rules,
    required_slots = EXCLUDED.required_slots,
    qualification_threshold = EXCLUDED.qualification_threshold,
    is_active = EXCLUDED.is_active;

-- Demo API key (raw: b2b_live_demo_acme_111111111111111111111111)
INSERT INTO core.api_keys (tenant_id, key_hash, name)
VALUES (
    '11111111-1111-1111-1111-111111111111',
    'c48f33e192081d5ac00cfb904661389f1ca84c35360ba4d21a003f8dd23aa72c',
    'Acme Demo Default Key'
)
ON CONFLICT (key_hash) DO NOTHING;
