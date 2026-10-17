# ADR 0003: API Key Authentication and Tenant Resolution

## Status
Accepted

## Context
Early prototypes received the tenant identifier directly in URL path segments (e.g. `POST /v1/{tenant}/conversa/turno` or `GET /v1/{tenant}/leads`). This approach exposed tenant naming structures in logs, proxies, and URLs, and created a vector for path parameter manipulation if authentication was omitted or desynchronized from the URL slug.

Furthermore, integrating webhook transports (such as n8n or WhatsApp Cloud API relays) requires a straightforward, stateless authentication mechanism that avoids complex OAuth handshakes while maintaining cryptographic security and revocation capabilities.

## Decision
We implement a cryptographically secure **Bearer API Key authentication** mechanism with centralized lookup and tenant resolution:

1. **Centralized Storage with Cryptographic Hashing**:
   API keys are provisioned per tenant and stored in the central `core.api_keys` table. The raw API key (prefixed with `lq_live_` followed by 32 cryptographically secure random bytes) is displayed to the administrator only once upon creation. Only the SHA-256 hash of the key is stored in the database.

2. **Decoupled API Paths**:
   Public HTTP endpoints no longer accept tenant parameters in URL routes. Endpoints use uniform paths:
   - `POST /v1/conversations/turns`
   - `GET /v1/leads`
   - `GET /v1/leads/{phone_number}`

3. **FastAPI Security Dependency**:
   All protected endpoints inject a FastAPI dependency (`resolve_tenant_from_api_key`) via `HTTPBearer`.
   - The dependency extracts the Bearer token, computes its SHA-256 digest, and queries `core.api_keys` for an active matching key.
   - If missing, invalid, or revoked, the request is immediately rejected with HTTP 401 Unauthorized.
   - Upon successful verification, the resolved `tenant_id` and `tenant_slug` are bound to the request context and injected into repository database sessions via `SET LOCAL app.current_tenant`.

4. **CLI Key Management**:
   A dedicated administrative CLI tool (`python -m lead_qualifier.cli.keys create-key`) generates keys securely, computes hashes, and updates database records without exposing secrets in code repositories or environment files.

## Consequences
- **Positive**:
  - Zero plain-text API keys in the database: compromised database dumps cannot be used to forge API requests.
  - Tenant resolution is strictly authenticated: callers cannot spoof or inspect other tenants' data by altering URL paths.
  - Revocability: keys can be marked inactive immediately in the database without service redeployment.
- **Negative**:
  - Every API request incurs a SHA-256 computation and a lightweight database lookup in `core.api_keys` (mitigated by a primary key B-tree index on `key_hash`).
  - Loss of the raw key requires generating a new key, as plain-text values cannot be recovered from the database.
