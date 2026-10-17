# ADR 0002: Multi-Tenancy with Schema-per-Tenant and Row-Level Security

## Status
Accepted

## Context
The platform serves multiple commercial organizations (tenants), each holding private conversational transcripts, lead contact details, and custom scoring criteria. Data leakage between tenants represents an unacceptable security and compliance failure.

Standard multi-tenant strategies in relational databases face distinct trade-offs:
- **Shared tables with tenant ID column only**: High risk of catastrophic cross-tenant leakage if an application query omits `WHERE tenant_id = :id`.
- **Database-per-tenant**: High operational overhead, slow migrations, and connection pool starvation across hundreds of tenants.
- **Schema-per-tenant**: Clean namespace isolation, but application bugs can still cross schemas if permissions or `search_path` settings are misconfigured.

## Decision
We implement a hybrid multi-tenancy model combining **dedicated PostgreSQL schemas** with **strict Row-Level Security (RLS)** and **composite foreign keys**:

1. **Dedicated Client Schemas**:
   Each tenant receives a dedicated PostgreSQL schema (`tenant_<name>`) containing tenant-specific operational tables (`leads`, `messages`, `conversation_states`, `scoring_results`, `scoring_rule_sets`, `knowledge_base`). Shared platform metadata resides in `core`.

2. **Row-Level Security (RLS) Enforced**:
   All tenant tables have Row-Level Security enabled with `FORCE ROW LEVEL SECURITY`. Policies check `tenant_id = current_setting('app.current_tenant', true)::uuid`.
   The application connects as an unprivileged role (`app_user`) that does **not** possess the `BYPASSRLS` attribute.

3. **Fail-Closed Session Context**:
   The tenant context is established per transaction/session. If `app.current_tenant` is uninitialized or null, RLS policies evaluate to false, resulting in zero rows returned rather than accidental full-table exposure.

4. **Composite Foreign Keys**:
   All inter-table relationships enforce composite foreign keys including `tenant_id` (e.g. `FOREIGN KEY (tenant_id, lead_id) REFERENCES leads(tenant_id, id)`). This guarantees referential integrity within tenant boundaries and prevents cross-tenant record association even under malicious ID prediction.

## Consequences
- **Positive**:
  - Defense-in-depth: combines schema isolation, database engine-level RLS, and composite relational constraints.
  - Fail-closed security: missing tenant context safely returns zero records.
  - Per-tenant data management: simplifies tenant backups, selective data drops, and GDPR compliance (Right to Erasure).
- **Negative**:
  - DDL and migration complexity: database migrations must execute across all tenant schemas.
  - Schema scaling overhead: PostgreSQL maintains catalog metadata for each schema and table, making thousands of schemas per single cluster impractical without partitioning or sharding.
