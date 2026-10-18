# ADR 0003: API Key Authentication and Tenant Resolution

## Status
Accepted

## Context
Early prototypes received the tenant identifier directly in URL path segments (e.g. `POST /v1/{tenant}/conversa/turno` or `GET /v1/{tenant}/leads`). This approach exposed tenant naming structures in logs, proxies, and URLs, and created a vector for path parameter manipulation if authentication was omitted or desynchronized from the URL slug.

Furthermore, integrating webhook transports (such as n8n or WhatsApp Cloud API relays) requires a straightforward, stateless authentication mechanism that avoids complex OAuth handshakes while maintaining cryptographic security and revocation capabilities.

## Decision
We implement a cryptographically secure **Bearer API Key authentication** mechanism with centralized lookup and tenant resolution:

1. **Centralized Storage with Cryptographic Hashing and Scopes**:
   API keys are provisioned per tenant and stored in the central `core.api_keys` table. The raw API key (prefixed with `b2b_live_` followed by cryptographically secure random bytes) is displayed to the administrator only once upon creation. Only the SHA-256 hash of the key is stored in the database.
   Each API key includes a mandatory `scopes text[] NOT NULL` column constrained by:
   `CHECK (scopes <@ ARRAY['webhook:write', 'leads:read']::text[] AND cardinality(scopes) > 0)`

2. **Decoupled API Paths**:
   Public HTTP endpoints do not accept tenant parameters in URL routes. Endpoints use uniform paths:
   - `POST /v1/conversations/turns` (requires `webhook:write`)
   - `GET /v1/leads` (requires `leads:read`)

3. **FastAPI Security Dependency and Scope Enforcement**:
   All protected endpoints inject a FastAPI security dependency:
   - Authentication resolves tenant identity via the `SECURITY DEFINER` function `core.resolve_tenant_by_api_key(p_key_hash)`, which returns `(tenant_id uuid, schema_name text, scopes text[])`.
   - If missing, invalid, or revoked, the request is immediately rejected with HTTP 401 Unauthorized.
   - Upon successful verification, an immutable `TenantContext` containing `tenant_id`, `schema_name`, and `scopes` (`frozenset[str]`) is initialized.
   - Route-level permissions are enforced via parameterized dependencies (`require_scope("webhook:write")`, `require_scope("leads:read")`). If the authenticated key lacks the required scope, the request is rejected with a generic HTTP 403 Forbidden.

4. **CLI Key Management**:
   The administrative CLI tool (`b2b-lead-qualifier create-key`) requires one or more repeatable `--scope` flags (e.g. `--scope webhook:write --scope leads:read`) to enforce explicit privilege assignment upon key creation.

## Consequences
- **Positive**:
  - Zero plain-text API keys in the database: compromised database dumps cannot be used to forge API requests.
  - Tenant resolution is strictly authenticated: callers cannot spoof or inspect other tenants' data by altering URL paths.
  - Granular privilege separation: webhook relays cannot read lead analytics, and read-only dashboard keys cannot simulate conversation turns.
  - Revocability: keys can be marked inactive immediately in the database without service redeployment.
- **Negative**:
  - Every API request incurs a SHA-256 computation and a lightweight database lookup in `core.api_keys` (mitigated by a partial B-tree index on `key_hash WHERE revoked_at IS NULL`).
  - Loss of the raw key requires generating a new key, as plain-text values cannot be recovered from the database.
