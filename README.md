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
flowchart TD
    subgraph Ingestion ["Ingestion & Authentication"]
        CLIENT["WhatsApp Relay / Webhook Caller"] -->|POST /v1/conversations/turns<br/>Authorization: Bearer lq_live_...| AUTH["FastAPI Security Dependency"]
        AUTH -->|SHA-256 Lookup| DB_KEYS[("core.api_keys")]
        AUTH -->|Resolved tenant_id| APP["Application Context"]
    end

    subgraph AppCore ["Core Application Services"]
        APP --> CTRL["TurnController"]
        CTRL --> IDEMP["Idempotency Guard<br/>(Atomic INSERT ON CONFLICT)"]
        CTRL --> SM["StateMachineService"]
        SM --> LLM["LLM Adapter<br/>(OpenAI Structured Outputs)"]
        SM --> SCORE["ScoringService<br/>(Strategy Pattern)"]
    end

    subgraph Storage ["PostgreSQL 17 (FORCE RLS)"]
        APP -.->|SET LOCAL app.current_tenant| DB_SESSION["Tenant DB Session"]
        SCORE --> R_SCORE[("scoring_results (Audit Trail)")]
        SCORE --> R_RULES[("scoring_rule_sets (Versioned JSONB)")]
        SM --> R_STATE[("conversation_states (Row Lock FOR UPDATE)")]
        LLM -.->|HNSW Vector Search| R_VEC[("knowledge_base (pgvector)")]
    end

    subgraph AdminUI ["Management & Inspection"]
        APP --> DASH["Real-Time Dashboard (/dashboard)"]
        APP --> SWAG["Interactive Docs (/docs)"]
        CLI["CLI Tool (keys)"] -->|Generate & Hash Keys| DB_KEYS
    end
```

---

## Security Model

The system applies defense-in-depth across the API, database, and presentation layers:

### 1. API Key Authentication & Tenant Resolution
- Webhook endpoints require a Bearer token (`Authorization: Bearer lq_live_<token>`).
- API keys are hashed using **SHA-256** prior to storage in `core.api_keys`. Raw keys are never stored in the database.
- Endpoints use uniform paths (`/v1/conversations/turns`, `/v1/leads`), removing tenant identifiers from URLs and deriving tenant scope entirely from the verified API key.

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
- Logging outputs structured JSON suitable for central log aggregation.

---

## Scoring Engine (Strategy Pattern)

Lead scoring evaluates extracted lead attributes against data-driven rules stored in `scoring_rule_sets`:

- **Knockout Rules (`KnockoutStrategy`):** Immediate disqualification on prohibited attributes (e.g., students, unsupported regions). Returns a typed `StrategyResult(is_knockout=True)` that halts evaluation early.
- **Exact Match Rules (`ExactMatchStrategy`):** Cumulative point allocation based on validated values (e.g., job role, revenue bracket).
- **Auditability:** Evaluation produces an immutable `ScoringResult(final_score, is_qualified, is_knocked_out, reasons)` stored in `scoring_results` with foreign keys referencing the exact rule set version used.
- **Schema Validation:** Rule definitions loaded from database JSONB are strictly validated via Pydantic discriminated unions (`KnockoutRuleModel`, `ExactMatchRuleModel`), preventing runtime failures on malformed rules.

### Example Scoring Matrix

| Rule Type | Evaluated Field | Value / Condition | Points / Action |
|---|---|---|---|
| **Knockout** | `role` | `"estudante"` / `"intern"` | **Immediate Disqualification** |
| **Exact Match** | `role` | `"CEO"` / `"Founder"` | **+50 points** |
| **Exact Match** | `role` | `"Director"` / `"VP"` | **+40 points** |
| **Exact Match** | `revenue_tier` | `"above_10m"` | **+50 points** |
| **Exact Match** | `revenue_tier` | `"2m_to_10m"` | **+35 points** |
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
  "reply_message": "Welcome! Your profile matches our enterprise solutions perfectly. One of our account executives will contact you shortly!",
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

### 4. Generate a Tenant API Key
Use the administrative CLI to provision a secure API key for the demo tenant:
```bash
uv run python -m lead_qualifier.cli.keys create-key --tenant demo --name "Local Development Key"
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

---

## Known Trade-offs & Limitations

1. **LLM Edge Latency:** Each turn requiring slot extraction issues a synchronous request to the LLM API (~1-2 seconds response time). Future revisions can introduce local quantized models or caching for repeated phrases.
2. **Schema-per-Tenant Scale:** Schema-per-tenant provides strong isolation and straightforward data lifecycle management, but PostgreSQL catalogs experience overhead beyond several hundred schemas on a single instance.
3. **Webhook Concurrency:** Webhooks are currently processed within FastAPI worker processes. In high-volume WhatsApp campaign spikes, fronting the endpoint with a persistent message broker (e.g., Redis Streams, RabbitMQ) is recommended to absorb ingestion bursts.

---

## License

This project is licensed under the terms of the [MIT License](LICENSE).
