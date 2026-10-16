-- Development seed: do not run in production.
-- Usage: docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U postgres -d b2b_lead_qualifier -f /db/seeds/demo.sql

-- Provision demo tenant (Acme Corp) with dedicated schema
SELECT core.provision_tenant(
    '11111111-1111-1111-1111-111111111111',
    'Acme Corp (Demo)',
    'tenant_demo'
);

-- Versao 1 das regras de scoring do tenant demo: B2B Enterprise ICP Matrix
INSERT INTO tenant_demo.scoring_rule_sets (tenant_id, version, rules, qualification_threshold, is_active)
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
    50,
    true
)
ON CONFLICT (tenant_id, version) DO NOTHING;
