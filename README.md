# b2b-lead-qualifier

[![Python](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.143+-009688)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17%20%2B%20pgvector-336791)](https://github.com/pgvector/pgvector)
[![Docker](https://img.shields.io/badge/Docker-Multi--stage%2072MB-2496ED)](https://www.docker.com/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

> **Production-grade conversational lead qualification platform for Enterprise B2B SaaS.**  
> Built with strict multi-tenancy on **PostgreSQL 17 + pgvector**, deterministic **Strategy-pattern scoring engine**, and **LLM at the edge** (OpenAI Structured Outputs).

---

## 💡 The Core Architectural Philosophy

Most conversational AI bots fail in production because they rely on generative LLMs to make business decisions. This leads to **hallucinations, non-deterministic scores, compliance violations, and zero auditability**.

**Nexus Lead Qualifier enforces a strict separation of concerns:**
1. **Probabilistic Edge (LLM):** The language model *only* listens to WhatsApp chats and extracts structured slots into strongly-typed Pydantic schemas. It never decides points, eligibility, or qualification.
2. **Deterministic Core (Python + PostgreSQL):** The business rules, state machine transitions, knockout criteria, and cumulative scores run in pure, predictable Python services backed by ACID database transactions.
3. **Fail-Closed Multi-Tenancy:** Hardened with PostgreSQL 17 Row-Level Security (`FORCE RLS`), composite foreign keys `(tenant_id, id)`, and non-superuser application connections without `BYPASSRLS`.

---

## 🏛️ System Architecture

```mermaid
flowchart TD
    subgraph Channel ["Ingestion & Edge"]
        WPP["WhatsApp Cloud API"] -->|Webhook| N8N["n8n (Pure Transport)"]
        N8N -->|POST /v1/{tenant}/conversa/turno| API["FastAPI Application"]
    end

    subgraph Core ["Application Core"]
        API --> CTRL["WebhookController"]
        CTRL --> IDEMP["Idempotency Guard (message_id)"]
        CTRL --> SM["State Machine (Guided Slot-Filling)"]
        CTRL --> LLM["LLM Adapter (OpenAI Structured Outputs)"]
        CTRL --> SCORE["Scoring Service (Strategy Pattern)"]
    end

    subgraph Storage ["PostgreSQL 17 + pgvector (FORCE RLS)"]
        SCORE --> R_SCORE[("scoring_results (Append-Only Audit)")]
        SCORE --> R_RULES[("scoring_rule_sets (Versioned JSONB)")]
        SM --> R_STATE[("conversation_states")]
        LLM -.->|HNSW Cosine Search| R_VEC[("knowledge_base (pgvector)")]
    end

    subgraph Observability ["Real-Time UI & Docs"]
        API --> DASH["Glassmorphism Dashboard (/dashboard)"]
        API --> SWAG["Interactive Swagger UI (/docs)"]
    end
```

---

## ⚡ Key Engineering Highlights

### 1. True Multi-Tenancy with PostgreSQL 17 RLS & Composite FKs
- **Zero data bleeding:** Every customer schema (`tenant_{name}`) operates under PostgreSQL 17 Row-Level Security (`FORCE ROW LEVEL SECURITY`).
- **Composite Foreign Keys:** All entity relationships enforce `(tenant_id, id)` foreign keys, preventing a tenant from referencing another tenant's records even if UUIDs are guessed.
- **Fail-Closed Session Context:** The app connects as an unprivileged user (`optime_app`) with no `BYPASSRLS`. If tenant context is missing, the query immediately returns `0` rows.

### 2. Deterministic Scoring Engine (Strategy Pattern)
- **Knockout Rules (Immediate Disqualification):** Instant rejection for out-of-ICP profiles (e.g., students, interns, zero budget).
- **Cumulative Weighted Scoring:** Criteria points based on Role, Revenue, Headcount, and Urgency.
- **Versioned & Immutable Rules (ADR 003):** Rules are stored in database JSONB rows versioned by `(tenant_id, version)`. New weights take effect instantly without restarting containers.
- **Append-Only Audit Trail:** Every score record links to the exact `rule_set_id` used, recording an itemized breakdown of why each point was awarded.

### 3. Native pgvector Semantic Search (RAG)
- Uses PostgreSQL's `pgvector` extension with **HNSW (Hierarchical Navigable Small World)** indexing for sub-millisecond cosine similarity queries over institutional documents.
- No external vector database clusters needed (eliminates extra operational overhead and sync latency).

### 4. Message Idempotency
- Incoming WhatsApp webhook retries are deduplicated using `message_id`. Replays return the cached response with zero LLM API cost.

---

## 🎯 Lead Scoring Matrix (B2B ICP Example)

The active rule set evaluates leads deterministically against an ideal customer profile:

| Rule Type | Evaluated Field | Matching Value | Outcome / Points |
|---|---|---|---|
| **Knockout** | `role` | `"student"` / `"intern"` | **Immediate Disqualification (0 pts)** |
| **Knockout** | `revenue` | `"below $50k/yr"` | **Immediate Disqualification (0 pts)** |
| **Exact Match** | `role` | `"CEO"` / `"Founder"` | **+50 points** |
| **Exact Match** | `role` | `"Director"` / `"VP"` | **+40 points** |
| **Exact Match** | `role` | `"Manager"` / `"Lead"` | **+25 points** |
| **Exact Match** | `revenue` | `">$10M/year"` | **+50 points** |
| **Exact Match** | `revenue` | `"$1M - $10M/year"` | **+35 points** |
| **Exact Match** | `company_size` | `"100+ employees"` | **+30 points** |
| **Exact Match** | `urgency` | `"immediate"` | **+15 points** |

- **Qualification Threshold:** `50 points`  
  - **Score >= 50:** Lead marked as **`QUALIFIED`** (routed to executive sales demo).
  - **Score < 50:** Lead marked as **`NOT_QUALIFIED`** (nurturing sequence).

---

## 🔌 API Webhook Contract

### Ingestion Endpoint
```http
POST /v1/{tenant}/conversa/turno
Content-Type: application/json
```

#### Request Payload (from n8n / WhatsApp Gateway):
```json
{
  "message_id": "wamid.HBgLMjU1NDk5OTk5ODg4OAA=",
  "phone_number": "+5511999998888",
  "user_message": "Hello, I am the CEO of a tech company with 120 employees and $10M annual revenue. We need to deploy enterprise automation."
}
```

#### Response Payload (Deterministic Response & State):
```json
{
  "reply_message": "Welcome! Your profile matches our enterprise solutions perfectly. One of our account executives will contact you shortly!",
  "current_state": "QUALIFIED",
  "is_finished": true
}
```

---

## 🛠️ Environment Configuration (`.env`)

```ini
# Database Connection (PostgreSQL 17 + pgvector)
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=optime
DB_USER=optime_app
DB_PASSWORD=your-secure-app-password
DB_ADMIN_USER=postgres
DB_ADMIN_PASSWORD=your-secure-admin-password

# Application Settings
API_ENV=development
API_HOST=0.0.0.0
API_PORT=8000
OPENAI_API_KEY=sk-...

# Production SSL (Automatic Caddy Let's Encrypt)
DOMAIN=api.yourdomain.com
```

---

## 🚀 Quick Start (Local Development)

### Prerequisites
- [Python 3.12+](https://www.python.org/)
- [uv](https://docs.astral.sh/uv/) (Extremely fast Python package installer)
- [Docker & Docker Compose](https://www.docker.com/)

### 1. Install Dependencies
```bash
uv sync
```

### 2. Start PostgreSQL 17 + pgvector
```bash
docker compose up -d postgres
```

### 3. Run Migrations & Demo Seed
```bash
# Run migrations via dbmate container
docker compose --profile tools run --rm dbmate up

# Seed demo tenant with active B2B scoring rules
docker exec -i optime_db psql -U postgres -d optime -f /db/seeds/demo.sql
```

### 4. Start the Application
```bash
uv run uvicorn src.app.api.main:app --reload
```

### 5. Open in Your Browser
- **Swagger UI (Interactive API Docs):** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **Live Glassmorphism Dashboard:** [http://127.0.0.1:8000/dashboard](http://127.0.0.1:8000/dashboard)
- **Healthcheck:** [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

---

## 🧪 Real-World Integration Tests (No Mocks)

This project strictly adheres to **real-world database integration testing**. Tests run against a live PostgreSQL 17 instance inside Docker:

```bash
# Run complete test suite (RLS isolation, pgvector HNSW search, idempotency)
uv run pytest

# Static analysis and formatting validation
uv run ruff check .
```

---

## 📦 Production Deployment

The project features a **multi-stage Docker build** producing an ultra-compact **72MB image**, fronted by **Caddy** for automatic Let's Encrypt TLS:

```bash
# Production deployment with automated HTTPS
docker compose --profile prod up --build -d
```

Continuous Deployment pipeline included via **GitHub Actions** (`.github/workflows/deploy.yml`) with zero-downtime container rolling.

---

## 👤 Author

**Renan Maciel**  
Backend & Data Engineer · Python · PostgreSQL · AI Agents  
- [LinkedIn](https://www.linkedin.com/in/rmacielsantos/)  
- [GitHub Profile](https://github.com/Renan-Maciel-Santos)
