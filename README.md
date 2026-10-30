# B2B Lead Qualifier

[![CI](https://github.com/Renan-Maciel-Santos/b2b-lead-qualifier/actions/workflows/ci.yml/badge.svg)](https://github.com/Renan-Maciel-Santos/b2b-lead-qualifier/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/Renan-Maciel-Santos/b2b-lead-qualifier)](https://github.com/Renan-Maciel-Santos/b2b-lead-qualifier/releases)
[![Python](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.143.0+-009688)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17%20%2B%20pgvector-336791)](https://github.com/pgvector/pgvector)
[![Docker Compose](https://img.shields.io/badge/Docker-Compose-2496ED)](https://www.docker.com/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

> Conversational lead qualification service built on FastAPI and PostgreSQL 17. Combines LLM-based slot extraction at the edge with deterministic Strategy-pattern scoring and PostgreSQL Row-Level Security.

---

## Demo

![B2B Lead Qualifier Demonstration](docs/images/demo.gif)

*To regenerate this demonstration GIF, run `uv run python scripts/record_demo_gif.py` with the API running.*

Run an automated end-to-end interactive demonstration simulating three distinct business qualification scenarios and inspect the live evaluation results in the dashboard:

1. **Qualified Lead:** CEO role (+50 pts) and revenue tier 2M–10M (+35 pts) achieving 85 pts (>= 50 cutoff).
2. **Not Qualified Lead (Score Deficit):** Gerente role (+25 pts) and revenue tier 500k–2M (+0 pts) achieving 25 pts (< 50 cutoff).
3. **Disqualified Lead (Knockout):** Student role triggering an immediate fail-early knockout in turn 1 (0 pts).

### Quick Demo Run

With the API running (`uv run b2b-lead-qualifier run` or Docker Compose), run the demo script in PowerShell or Bash:

**PowerShell (Windows):**
```powershell
powershell -File scripts/demo.ps1
```

**Bash (Linux / macOS):**
```bash
bash scripts/demo.sh
```

The script evaluates scoring rules deterministically, records structured audit trails in PostgreSQL, and verifies the outcome via `GET /v1/leads`.

### Operator Dashboard

The real-time dashboard (`/dashboard`) visualizes evaluated leads using a strict light audit ledger aesthetic, scaling score tracks dynamically by `max_possible_score` with an explicit cutoff marker and itemized audit reasons:

**Desktop View:**
![Dashboard Desktop](docs/images/dashboard_desktop.png)

**Mobile View:**
![Dashboard Mobile](docs/images/dashboard_mobile.png)

For detailed coverage of all operational and error states (authentication prompt, invalid token, empty state), see [docs/ui-states.md](docs/ui-states.md).

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
    participant StateMachine as StateMachineService
    participant LLM as OpenAIAdapter (LLMAdapterPort)
    participant DB as PostgreSQL 17 (core & tenant schemas)

    Client->>Auth: POST /v1/conversations/turns (Bearer b2b_live_...)
    Note over Auth,DB: Authenticate SHA-256 key hash & verify 'webhook:write' scope
    Auth->>DB: core.resolve_tenant_by_api_key(key_hash)
    DB-->>Auth: TenantContext(tenant_id, schema, scopes={'webhook:write'})

    rect rgb(240, 245, 255)
    Note over Pool,StateMachine: Unit of Work 1 — Idempotency & Terminal Check
    Auth->>StateMachine: process_turn(TurnRequest)
    StateMachine->>Pool: Acquire connection via uow_factory()
    Pool->>DB: SET LOCAL app.current_tenant = tenant_id
    StateMachine->>DB: INSERT INTO processed_messages (message_id) ON CONFLICT DO NOTHING
    StateMachine->>DB: SELECT current_state FROM conversation_states (read-only)
    StateMachine->>Pool: Commit transaction & return connection to pool
    end

    rect rgb(255, 250, 240)
    Note over LLM: Unlocked Edge Extraction (Zero DB locks / No pooled connection held)
    StateMachine->>LLM: extract_slots(user_message)
    LLM-->>StateMachine: LeadSlots(role, revenue_tier, company_size)
    end

    rect rgb(240, 255, 245)
    Note over Pool,StateMachine: Unit of Work 2 — Scoring & State Transition
    StateMachine->>Pool: Acquire new connection via uow_factory()
    Pool->>DB: SET LOCAL app.current_tenant = tenant_id
    StateMachine->>DB: SELECT ... FROM conversation_states FOR UPDATE (Row Lock)
    Note over StateMachine: Merge slots, evaluate knockout rules, verify required_slots
    opt If Terminal State (Knockout / Qualified / Not Qualified)
        StateMachine->>DB: INSERT INTO scoring_results (Audit trail)
    end
    StateMachine->>DB: UPDATE conversation_states & mark message done in processed_messages
    StateMachine->>Pool: Commit transaction & return connection to pool
    end

    StateMachine-->>Auth: TurnResponse(reply_message, current_state, is_finished)
    Auth-->>Client: 200 OK TurnResponse
```

---

## Security Model

The system applies defense-in-depth across the API, database, and presentation layers:

### 1. API Key Authentication & Scoped Authorization
- Webhook and lead management endpoints require a Bearer token (`Authorization: Bearer b2b_live_<token>`).
- API keys are hashed using **SHA-256** prior to storage in `core.api_keys`. Raw keys are never stored in the database.
- Keys enforce granular scopes (`scopes text[]`):
  - `webhook:write`: Required to process conversation turns via `POST /v1/conversations/turns`.
  - `leads:read`: Required to inspect leads and state via `GET /v1/leads` and `/dashboard`.
- Routes validate authorization via a reusable dependency: `require_scope("webhook:write")`. Requests with missing or insufficient scopes fail closed with `403 Forbidden`.
- Endpoints use uniform paths, deriving tenant context and scopes entirely from the verified API key.

### 2. Multi-Tenancy via PostgreSQL Row-Level Security (RLS)
- Every tenant operates with dedicated schemas (`tenant_<slug>`) and tables configured with `FORCE ROW LEVEL SECURITY`.
- Application database connections use an unprivileged role (`app_user`) that does **not** have the `BYPASSRLS` permission.
- The active tenant is established per transaction (re-applied in each short Unit of Work via `SET LOCAL app.current_tenant = '<tenant_id>'`) inside an active transaction block. If the variable is unset or invalid, RLS policies fail closed and queries return zero rows.
- All tenant tables enforce composite foreign keys including `tenant_id` to guarantee cross-tenant referential integrity.

### 3. Dashboard Anti-XSS Protection
- The administrative dashboard uses **Jinja2 autoescape**, preventing reflected and stored XSS in the rendered HTML.
- Client-side DOM rendering is performed strictly via `document.createElement()` and `element.textContent`, eliminating `innerHTML` injection risks from untrusted lead input.

### 4. PII Protection & Structured Logging
- Phone numbers and identifying lead data are masked in application logs using the exact format produced by `mask_phone_number` (e.g. `+5511*****8888`).
- Logging outputs structured messages with lazy argument evaluation (`logger.info("...%s", value)`).

---

## Scoring Engine (Strategy Pattern)

Lead scoring evaluates extracted lead attributes against data-driven rules stored in `scoring_rule_sets`:

- **Knockout Rules (`KnockoutStrategy`):** Immediate disqualification on prohibited attributes (e.g., students, unsupported regions). Returns a typed `StrategyResult(is_knockout=True)` that halts evaluation early and terminates dialogue immediately (fail-early).
- **Exact Match Rules (`ExactMatchStrategy`):** Cumulative point allocation based on validated values (e.g., job role, revenue bracket).
- **Fail-Early Knockout vs. Complete Qualification (ADR 0005):** Knockout rules terminate the conversation immediately at any turn (`DISQUALIFIED`). Conversely, positive qualification (`QUALIFIED` or `NOT_QUALIFIED`) can only be decided after **all required slots** configured in `required_slots` have been collected. This prevents high-scoring attributes (like a CEO title) from prematurely bypassing knockout checks on uncollected attributes (like minimum revenue).
- **Auditability:** Evaluation produces an immutable `ScoringResult(final_score, is_qualified, is_knocked_out, reasons)` stored in `scoring_results` only when a terminal state is reached, referencing the exact rule set version used.
- **Schema Validation:** Rule definitions loaded from database JSONB are strictly validated via Pydantic discriminated unions (`KnockoutRuleModel`, `ExactMatchRuleModel`), preventing runtime failures on malformed rules.

### Example Scoring Matrix (Demo Tenant Rules)

| Rule Type | Evaluated Field | Value / Condition | Points / Action |
|---|---|---|---|
| **Knockout** | `role` | `"estudante"` | **Immediate Disqualification** |
| **Knockout** | `role` | `"estagiario"` | **Immediate Disqualification** |
| **Knockout** | `revenue_tier` | `"below_500k"` | **Immediate Disqualification** |
| **Exact Match** | `role` | `"CEO"` | **+50 points** |
| **Exact Match** | `role` | `"Diretor"` | **+40 points** |
| **Exact Match** | `role` | `"Gerente"` | **+25 points** |
| **Exact Match** | `revenue_tier` | `"2m_to_10m"` | **+35 points** |
| **Exact Match** | `revenue_tier` | `"above_10m"` | **+50 points** |
| **Exact Match** | `company_size` | `"enterprise_above_200"` | **+30 points** |

*Default qualification threshold: 50 points.*
*Mandatory required slots: `["role", "revenue_tier"]`.*

---

## API Webhook Contract

### Ingestion Endpoint

```http
POST /v1/conversations/turns
Authorization: Bearer b2b_live_your_tenant_api_key
Content-Type: application/json
```

#### Turn 1: Lead provides job title (Role)

**Request Payload:**
```json
{
  "message_id": "wamid.HBgLMjU1NDk5OTk5ODg4OAA=",
  "phone_number": "+5511999998888",
  "user_message": "Ola! Sou CEO de uma empresa de tecnologia."
}
```

**Response Payload:**
```json
{
  "reply_message": "Entendido! E qual a media de faturamento anual ou mensal da sua empresa atualmente?",
  "current_state": "AWAITING_REVENUE",
  "is_finished": false
}
```

#### Turn 2: Lead provides annual revenue bracket (Revenue Tier)

**Request Payload:**
```json
{
  "message_id": "wamid.HBgLMjU1NDk5OTk5ODg4OAE=",
  "phone_number": "+5511999998888",
  "user_message": "Nosso faturamento anual fica em torno de 5 milhoes ao ano."
}
```

**Response Payload:**
```json
{
  "reply_message": "Excelente! Seu perfil se encaixa perfeitamente nas solucoes da nossa plataforma. Um executivo de contas entrara em contato!",
  "current_state": "QUALIFIED",
  "is_finished": true
}
```

#### Idempotency & Message Lifecycle
Duplicate webhook retries with the same `message_id` are tracked atomically in the tenant's `processed_messages` table across three distinct statuses:
- **`done`:** Successfully completed turns. Subsequent deliveries with the same `message_id` return `current_state: DUPLICATE_IGNORED` immediately, without re-executing LLM inference or scoring.
- **`processing`:** Active turns. Concurrent duplicate deliveries while a turn is in flight are ignored. If a worker process dies unexpectedly, messages stuck in `processing` are atomically reclaimed for retry once `idempotency_timeout` has elapsed (default 60 seconds).
- **`failed`:** Turns that encountered an upstream exception (such as an LLM provider outage causing a 503). On the next delivery of the same `message_id` (e.g. from a webhook retry), the message lock is immediately reclaimed (without waiting for the timeout window) and the turn is fully reprocessed.

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
Ensure database credentials and `ADMIN_DATABASE_URL` (used exclusively for key provisioning) are populated in `.env`.

**LLM Provider Options:**
- **OpenAI (Default):** Requires `OPENAI_API_KEY=sk-...`. If `LLM_PROVIDER=openai` and the API key is missing or unset, the application fails fast upon startup with an explicit configuration error.
- **Offline Demonstration Mode (`LLM_PROVIDER=fake`):** Set `LLM_PROVIDER=fake` in `.env` to run full conversational qualification turns completely offline using a deterministic, rule-based keyword extractor without OpenAI API costs.

### 3. Start Database & Run Migrations
```bash
# Start PostgreSQL 17 with pgvector
docker compose up -d postgres

# Apply database migrations via dbmate runner
docker compose run --rm migrator

# Seed demo tenant
docker compose exec -T postgres psql -U postgres -d b2b_lead_qualifier -f /db/seeds/demo.sql
```

> **Note**: Database migrations were consolidated into a single baseline migration (`20261017000000_baseline.sql`) prior to the first public release, providing a clean schema definition without transitional migration artifacts.

### 4. Generate a Tenant API Key
Use the administrative CLI to provision a secure API key for the demo tenant (Acme Corp UUID: `11111111-1111-1111-1111-111111111111`). The CLI connects via `ADMIN_DATABASE_URL` configured in `.env`:
```bash
uv run b2b-lead-qualifier create-key \
  --tenant 11111111-1111-1111-1111-111111111111 \
  --name "Local Development Key" \
  --scope webhook:write \
  --scope leads:read
```
The CLI outputs the plain-text key (e.g. `b2b_live_...`). Store it securely; the database retains only the SHA-256 hash.

### 5. Start the Application

**Standard CLI (Windows, Linux, macOS):**
```bash
uv run b2b-lead-qualifier run
```
*Note for Windows users:* The `run` CLI entrypoint automatically configures the `WindowsSelectorEventLoopPolicy` required by `psycopg` async mode. On Windows, launch the application via `uv run b2b-lead-qualifier run` or Docker.

**Direct Uvicorn Command (Linux / macOS only):**
```bash
uv run uvicorn lead_qualifier.api.main:app --reload --host 0.0.0.0 --port 8000
```

- **Interactive API Docs (Swagger UI):** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **Inspection Dashboard:** [http://127.0.0.1:8000/dashboard](http://127.0.0.1:8000/dashboard)
- **Healthcheck & Readiness:** [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

### Alternative: Run Entire Stack via Docker Compose
To run PostgreSQL 17, migrations, and the FastAPI application in isolated containers with zero local Python/PostgreSQL setup:
```bash
docker compose up --build -d
```
All services start with verified health checks and automated migrations on any operating system.

---

## Testing & Quality Assurance

### Run Unit Tests (In-Memory)
Unit tests validate scoring strategies, schema models, and edge cases in milliseconds without database dependencies:
```bash
uv run pytest tests/unit/
```

### Run Integration Tests (Real PostgreSQL)
Integration tests run against a running PostgreSQL 17 container, validating RLS boundaries, composite foreign keys, and API key authentication.

The test suite reads configuration values from `.env` (created by copying `.env.example`). The following variables are required by integration tests:
- `DB_ADMIN_PASSWORD`: Superuser password required by test fixtures to provision and reset isolated tenant schemas.
- `ADMIN_DATABASE_URL`: Administrative database connection string used by CLI provisioning tests (when applicable).
- `LLM_PROVIDER=fake`: Ensures offline, deterministic test execution without external API dependencies (note: `tests/conftest.py` automatically defaults `LLM_PROVIDER` to `fake` if not explicitly set).

To run integration tests locally, ensure your PostgreSQL container is running and export the administrative credentials matching your `.env` (illustrated below using the default value from `.env.example`):
```bash
# Linux / macOS:
DB_ADMIN_PASSWORD="change-this-admin-password" uv run pytest tests/integration/

# Windows (PowerShell):
$env:DB_ADMIN_PASSWORD="change-this-admin-password"; uv run pytest tests/integration/
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
- **Unauthenticated Operator Dashboard Page:** The `/dashboard` endpoint serves a public HTML skeleton that contains zero lead data. The browser fetches lead data on-demand via `GET /v1/leads` requiring an operator key with `leads:read` scope; there is no user login session or Role-Based Access Control (RBAC).
- **Dashboard Key Storage in sessionStorage:** The dashboard operator key is stored client-side in `sessionStorage`; closing the browser tab clears the key.
- **Synchronous Ingestion Processing:** Webhook turns are processed within standard asynchronous request handlers without a persistent message broker (e.g., Redis Streams, RabbitMQ, Kafka). Under massive broadcast campaign spikes, upstream webhook throttling or queuing is recommended to prevent connection pool exhaustion.
- **LLM Provider Latency:** Turns requiring semantic slot extraction perform an outbound HTTP call to OpenAI (~1-2 seconds). While database connections and locks are explicitly released during this call, total turn latency is constrained by the external provider.
- **RAG Pipeline Prepared but Not Integrated:** PostgreSQL 17 with `pgvector` and HNSW indexing is configured in tenant schemas (`knowledge_base`), but vector retrieval is not currently wired into the conversational state machine turn loop.
- **PostgreSQL Catalog Scaling with Schema-per-Tenant:** Schema-per-tenant provides robust tenant isolation and simple retention management, but PostgreSQL catalogs experience performance degradation when scaling past several hundred schemas on a single instance.
- **CLI Key Provisioning Connection:** The administrative CLI requires administrative database access (`ADMIN_DATABASE_URL`) to insert into `core.api_keys` because the web application's unprivileged role (`app_user`) has `REVOKE ALL` on that table. In production, key provisioning should use a dedicated deployment/infrastructure role with least-privilege permissions on `core.api_keys`, rather than the database superuser.

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for the notable changes in each release.

---

## License

This project is licensed under the terms of the [MIT License](LICENSE).
