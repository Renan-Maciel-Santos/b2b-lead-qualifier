# B2B Lead Qualifier

[![Python](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17%20%2B%20pgvector-336791)](https://github.com/pgvector/pgvector)
[![Docker Compose](https://img.shields.io/badge/Docker-Compose-2496ED)](https://www.docker.com/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

> Conversational lead qualification service built on FastAPI and PostgreSQL 17. Combines LLM-based slot extraction at the edge with deterministic Strategy-pattern scoring and PostgreSQL Row-Level Security.

---

## Architectural Philosophy

Many conversational AI implementations delegate critical business decisions directly to large language models. This pattern often causes non-deterministic scoring, hallucinations, compliance risks, and an inability to audit why a lead was accepted or rejected.

**B2B Lead Qualifier enforces a strict separation of concerns:**

1. **Probabilistic Edge (LLM as Slot Extractor):** The language model listens to conversational input and extracts structured attributes into strongly-typed Pydantic schemas (`LeadSlots`) using OpenAI Structured Outputs. The LLM never computes scores, determines qualification, or controls state transitions.
2. **Deterministic Core (Python Services & PostgreSQL):** Business rules, multi-turn state transitions, knockout evaluations, and point scoring run in pure Python services backed by ACID database transactions.
3. **Database-Enforced Multi-Tenancy:** Isolation is enforced at the database layer via PostgreSQL 17 Row-Level Security (`FORCE ROW LEVEL SECURITY`), composite foreign keys `(tenant_id, id)`, and unprivileged application connections without `BYPASSRLS`.

---

## System Architecture

```mermaid
sequenceDiagram
    autonumber
    actor Client as Webhook Client / WhatsApp
    participant Auth as FastAPI Dependency (require_scope)
    participant Pool as AsyncConnectionPool
    participant UoW1 as Unit of Work 1 (Idempotency)
    participant LLM as LLM Adapter (OpenAI)
    participant UoW2 as Unit of Work 2 (Scoring & State)
    participant DB as PostgreSQL 17 (core & tenant schemas)

    Client->>Auth: POST /v1/conversations/turns (Bearer token)
    Note over Auth,DB: Authenticate key hash & verify 'webhook:write' scope
    Auth->>DB: core.resolve_tenant_by_api_key(key_hash)
    DB-->>Auth: TenantContext(tenant_id, schema, scopes={'webhook:write'})

    rect rgb(240, 245, 255)
    Note over Pool,UoW1: Unit of Work 1 — Transaction & Atomic Idempotency
    Auth->>Pool: Acquire connection
    Pool->>DB: SET LOCAL app.current_tenant = tenant_id
    UoW1->>DB: INSERT INTO messages (message_id) ON CONFLICT DO NOTHING
    UoW1->>DB: SELECT current_state FROM conversation_states (read-only)
    UoW1->>Pool: Commit transaction & return connection to pool
    end

    rect rgb(255, 250, 240)
    Note over LLM: Decoupled LLM Edge Call (Zero DB locks / No pooled connection held)
    Auth->>LLM: extract_slots(user_message)
    LLM-->>Auth: LeadSlots(role, revenue, ...)
    end

    rect rgb(240, 255, 245)
    Note over Pool,UoW2: Unit of Work 2 — Deterministic Scoring & State Update
    Auth->>Pool: Acquire new connection from pool
    Pool->>DB: SET LOCAL app.current_tenant = tenant_id
    UoW2->>DB: SELECT ... FROM conversation_states FOR UPDATE (Row Lock)
    Note over UoW2: Merge slots, test knockouts, verify required slots
    opt If Terminal State (Knockout / Qualified)
        UoW2->>DB: INSERT INTO scoring_results (Audit trail)
    end
    UoW2->>DB: UPDATE conversation_states & mark message processed
    UoW2->>Pool: Commit transaction & return connection to pool
    end

    Auth-->>Client: 200 OK TurnResponse(reply_message, current_state, is_finished)
```

---

## Security Model

The system applies defense-in-depth across the API, database, and presentation layers:

### 1. API Key Authentication & Scoped Authorization
- Webhook and lead management endpoints require a Bearer token (`Authorization: Bearer lq_live_<token>`).
- API keys are hashed using **SHA-256** prior to storage in `core.api_keys`. Raw keys are never stored in the database.
- Keys enforce granular scopes (`scopes text[]`):
  - `webhook:write`: Required to process conversation turns via `POST /v1/conversations/turns`.
  - `leads:read`: Required to inspect leads and state via `GET /v1/leads` and `/dashboard`.
- Routes validate authorization via a reusable dependency: `require_scope("webhook:write")`. Requests with missing or insufficient scopes fail closed with `403 Forbidden`.
- Endpoints use uniform paths, deriving tenant context and scopes entirely from the verified API key.

### 2. Multi-Tenancy via PostgreSQL Row-Level Security (RLS)
- Every tenant operates with dedicated schemas (`tenant_<slug>`) and tables configured with `FORCE ROW LEVEL SECURITY`.
- Application database connections use an unprivileged role (`app_user`) that does **not** have the `BYPASSRLS` permission.
- The active tenant is established per session via `SET LOCAL app.current_tenant = '<tenant_id>'`. If the variable is unset or invalid, RLS policies fail closed and queries return zero rows.
- All tenant tables enforce composite foreign keys including `tenant_id` to guarantee cross-tenant referential integrity.

### 3. Dashboard Anti-XSS Protection
- The administrative dashboard uses **Jinja2 autoescape** to prevent server-side template injection.
- Client-side DOM rendering is performed strictly via `document.createElement()` and `element.textContent`, eliminating `innerHTML` injection risks from untrusted lead input.

### 4. PII Protection & Structured Logging
- Phone numbers and identifying lead data are masked in application logs (e.g. `+55 11 9****-**88`).
- Logging outputs structured messages with lazy argument evaluation suitable for log aggregation.

---

## Scoring Engine (Strategy Pattern)

Lead scoring evaluates extracted lead attributes against data-driven rules stored in `scoring_rule_sets`:

- **Knockout Rules (`KnockoutStrategy`):** Immediate disqualification on prohibited attributes (e.g., students, unsupported regions). Returns a typed `StrategyResult(is_knockout=True)` that halts evaluation early and terminates dialogue immediately (fail-early).
- **Exact Match Rules (`ExactMatchStrategy`):** Cumulative point allocation based on validated values (e.g., job role, revenue bracket).
- **Fail-Early Knockout vs. Complete Qualification (ADR 0005):** Knockout rules terminate the conversation immediately at any turn (`DISQUALIFIED`). Conversely, positive qualification (`QUALIFIED` or `NOT_QUALIFIED`) can only be decided after **all required slots** configured in `required_slots` have been collected. This prevents high-scoring attributes (like a CEO title) from prematurely bypassing knockout checks on uncollected attributes (like minimum revenue).
- **Auditability:** Evaluation produces an immutable `ScoringResult(final_score, is_qualified, is_knocked_out, reasons)` stored in `scoring_results` only when a terminal state is reached, referencing the exact rule set version used.
- **Schema Validation:** Rule definitions loaded from database JSONB are strictly validated via Pydantic discriminated unions (`KnockoutRuleModel`, `ExactMatchRuleModel`), preventing runtime failures on malformed rules.

### Example Scoring Matrix

| Rule Type | Evaluated Field | Value / Condition | Points / Action |
|---|---|---|---|
| **Knockout** | `role` | `"estudante"` / `"intern"` | **Immediate Disqualification** |
| **Exact Match** | `role` | `"CEO"` / `"Founder"` | **+50 points** |
| **Exact Match** | `role` | `"Director"` / `"VP"` | **+40 points** |
| **Exact Match** | `revenue` | `"5 milhoes ao ano"` | **+50 points** |
| **Exact Match** | `revenue` | `"10 milhoes ao ano"` | **+50 points** |
| **Exact Match** | `company_size` | `"large_51_to_200"` | **+30 points** |

*Default qualification threshold: 50 points.*

---

## API Webhook Contract

### Ingestion Endpoint

```http
POST /v1/conversations/turns
Authorization: Bearer lq_live_your_tenant_api_key
Content-Type: application/json
```

#### Request Payload

```json
{
  "message_id": "wamid.HBgLMjU1NDk5OTk5ODg4OAA=",
  "phone_number": "+5511999998888",
  "user_message": "Hello, I am the CEO of a software company with 80 employees and annual revenue above $10M."
}
```

#### Response Payload

```json
{
  "reply_message": "Welcome! Your profile matches our qualification criteria. One of our account executives will contact you shortly!",
  "current_state": "QUALIFIED",
  "is_finished": true
}
```

#### Idempotency
Duplicate webhook retries with the same `message_id` are caught atomically via `INSERT INTO messages ... ON CONFLICT DO NOTHING`. If a duplicate is received, the system returns `current_state: DUPLICATE_IGNORED` without re-running LLM inference or scoring.

---

## Quick Start (Local Development)

### Prerequisites
- [Python 3.12+](https://www.python.org/)
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [Docker & Docker Compose](https://www.docker.com/)

### 1. Install Dependencies
```bash
uv sync
```

### 2. Configure Environment
Copy the example environment file:
```bash
cp .env.example .env
```
Ensure database credentials and your `OPENAI_API_KEY` are populated in `.env`.

### 3. Start Database & Run Migrations
```bash
# Start PostgreSQL 17 with pgvector
docker compose up -d postgres

# Apply database migrations via dbmate
docker compose --profile tools run --rm dbmate up

# Seed demo tenant
docker exec -i b2b_db psql -U postgres -d b2b_lead_qualifier -f /db/seeds/demo.sql
```

> **Note**: Database migrations were consolidated into a single baseline migration (`20261017000000_baseline.sql`) prior to the first public release, providing a clean schema definition without transitional migration artifacts.

### 4. Generate a Tenant API Key
Use the administrative CLI to provision a secure API key for the demo tenant:
```bash
uv run b2b-lead-qualifier keys create-key --tenant demo --name "Local Development Key" --scope webhook:write --scope leads:read
```
The CLI outputs the plain-text key (e.g. `lq_live_...`). Store it securely; the database retains only the SHA-256 hash.

### 5. Start the Application
```bash
uv run uvicorn lead_qualifier.api.main:app --reload --host 0.0.0.0 --port 8000
```

- **Interactive API Docs (Swagger UI):** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **Monitoring Dashboard:** [http://127.0.0.1:8000/dashboard](http://127.0.0.1:8000/dashboard)
- **Healthcheck:** [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

---

## Testing & Quality Assurance

### Run Unit Tests (In-Memory)
Unit tests validate scoring strategies, schema models, and edge cases in milliseconds without database dependencies:
```bash
uv run pytest tests/unit/
```

### Run Integration Tests (Real PostgreSQL)
Integration tests run against a running PostgreSQL 17 container, validating RLS boundaries, composite foreign keys, and API key authentication:
```bash
uv run pytest tests/integration/
```

### Run Evaluation Harness
Benchmark LLM slot extraction accuracy against the synthetic golden dataset (`data/golden_dataset.json`):
```bash
uv run python -m tests.evaluation.harness
```

### Linting & Static Type Checking
```bash
# Run Ruff lint checks
uv run ruff check .

# Check code formatting
uv run ruff format --check .

# Run strict type checking
uv run mypy src tests
```

---

## Architectural Decision Records (ADRs)

Key architectural decisions are documented in [`docs/adr/`](docs/adr/):

- [ADR 0001: LLM Only at the Edge](docs/adr/0001-llm-only-at-the-edge.md) — Constraining probabilistic AI to slot extraction while keeping decision logic deterministic.
- [ADR 0002: Multi-Tenancy with Schema-per-Tenant and RLS](docs/adr/0002-multi-tenancy-with-schema-per-tenant-and-rls.md) — Defense-in-depth isolation via PostgreSQL 17 schemas, RLS, and composite foreign keys.
- [ADR 0003: API Key Authentication and Tenant Resolution](docs/adr/0003-api-key-authentication.md) — Centralized SHA-256 API key authentication decoupling tenant IDs from public URLs.
- [ADR 0004: Transaction Boundaries and LLM Calls](docs/adr/0004-transaction-boundaries-and-llm-calls.md) — Decoupled transaction boundaries, zero database locks during LLM inference, and transaction-scoped fail-closed tenant context.
- [ADR 0005: Fail-Early Knockouts and Complete Qualification](docs/adr/0005-fail-early-knockout-and-complete-qualification.md) — Terminating dialogue immediately on knockout while requiring complete slot collection before qualification.

---

## Known Limitations

- **No Native Rate Limiting:** The application does not enforce in-app rate limiting or brute-force throttling per tenant or IP. Rate limiting, DDoS mitigation, and traffic shaping must be enforced upstream by an API gateway or reverse proxy (e.g., Caddy, NGINX, Cloudflare).
- **No Automated Key Rotation or Expiration:** API keys stored in `core.api_keys` have neither automated TTL expiration nor self-service rotation schedules. Key lifecycle and revocation are managed manually via administrative CLI commands.
- **Unauthenticated Operator Dashboard:** The `/dashboard` view relies on the caller supplying an authorized API key with `leads:read` scope; there is no separate operator authentication, user session management, or Role-Based Access Control (RBAC).
- **Synchronous Ingestion Processing:** Webhook turns are processed within standard asynchronous request handlers without a persistent message broker (e.g., Redis Streams, RabbitMQ, Kafka). Under massive broadcast campaign spikes, upstream webhook throttling or queuing is recommended to prevent connection pool exhaustion.
- **LLM Provider Latency:** Turns requiring semantic slot extraction perform an outbound HTTP call to OpenAI (~1-2 seconds). While database connections and locks are explicitly released during this call, total turn latency is constrained by the external provider.
- **PostgreSQL Catalog Scaling with Schema-per-Tenant:** Schema-per-tenant provides robust tenant isolation and simple retention management, but PostgreSQL catalogs experience performance degradation when scaling past several hundred schemas on a single instance.

---

## License

This project is licensed under the terms of the [MIT License](LICENSE).
