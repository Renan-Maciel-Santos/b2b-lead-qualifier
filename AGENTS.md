# Engineering Guidelines & Conventions (b2b-lead-qualifier)

This document establishes the mandatory architectural rules, engineering standards, and workflow practices for the `b2b-lead-qualifier` project.

---

## 1. Architectural Principles

The application strictly follows a layered, decoupled architecture with unidirectional dependency flow:

$$\text{Routers (HTTP only)} \longrightarrow \text{Services (Business Logic)} \longrightarrow \text{Repositories (Database Access)}$$

- **Routers (`api/routers/`):** Responsible exclusively for HTTP concerns (request deserialization, status codes, response mapping). No business rules or direct SQL queries.
- **Services (`services/`):** Pure deterministic domain and business logic, orchestrating state machines and scoring strategies.
- **Repositories (`repositories/`):** The single layer permitted to execute SQL against the database. All queries must be strictly parameterized via `psycopg`.
- **Dependency Injection:** Dependencies are declared via constructors and wired using FastAPI `Depends`. Never instantiate repositories, services, or connection pools inside controllers or endpoints.

---

## 2. Multi-Tenancy & Database Security

- **Strict Multi-Tenancy:** Each customer operates within a dedicated PostgreSQL schema (`tenant_{name}`).
- **Row-Level Security (RLS):** All tenant tables enforce `FORCE ROW LEVEL SECURITY` with fail-closed security semantics.
- **Composite Foreign Keys:** All entity relationships enforce `(tenant_id, id)` foreign keys to prevent cross-tenant referencing.
- **Unprivileged App User:** The application connects exclusively as `app_user`, which does NOT have `BYPASSRLS` privileges.
- **Safe SQL Context:** Dynamic schema search paths must be set using `sql.Identifier` via `SET LOCAL search_path TO {}, public`. Session tenant context is managed via `app.current_tenant`.
- **Append-Only Auditing:** Qualification scores and versioned rule sets are immutable and audit-trailed.

---

## 3. Language & Documentation Standards

- **Conversational Language:** Portuguese (pt-BR) when communicating with the user/developer in conversation.
- **Versioned Artifacts:** Strictly in **English** (code, module names, commit messages, docstrings, technical documentation, and inline comments).
- **Comments:** Explain **WHY** a technical or architectural decision was made, never restate **WHAT** the code already expresses.
- **Docstrings:** Google-style docstrings are required for all public modules, classes, and functions.
- **Line-by-line Comments:** Do not write obvious line-by-line comments (e.g., `# imports library`, `# sets cursor`).

---

## 4. Testing & Quality Assurance

- **Real Integration Testing:** Tests must run against a live PostgreSQL 17 + pgvector instance in Docker or CI. Never mock the database or RLS security barriers.
- **Type Safety & Linting:** Strict static type analysis with `mypy` and linting/formatting with `ruff`.
- **Pre-commit:** Enforce `ruff` and `mypy` checks prior to committing.

---

## 5. Development Workflow (Phased Execution)

- **Phased Branches:** Work in dedicated feature/fix branches per phase (e.g., `chore/foundation`, `fix/security`).
- **Commits:** Small, atomic commits following the Conventional Commits specification in English.
- **Review Checkpoint:** After completing each phase, run lint, types, and tests, present a summary of changes, and wait for explicit approval before proceeding to the next phase.
- **Git Authority:** Never perform `push`, `merge`, or `rebase` directly to remote branches unless explicitly instructed. Pull Requests are created and managed by the repository owner.
- **Zero Secrets:** Never version `.env` files, production credentials, or real customer data.

---

## 6. Agent Skills

Project-specific agent skills reside in `.agent/skills/`. When there is any overlap between project skills and global agent skills, project skills take precedence and must be followed:

1. **`data-architecture`:** PostgreSQL data modeling, migrations, transactions, and data pipeline design rules.
2. **`delivery-report`:** Pre-push checklist and evidence-based delivery report format for task completions.
3. **`distinctive-frontend`:** Visual identity, accessibility, and quality rules for user-facing dashboards and templates.
4. **`git-workflow`:** Branching, conventional commits, pull requests, rebase merges, and git hygiene.
5. **`llm-integration`:** Rules for integrating LLMs at the edge with structured outputs and fail-fast configuration.
6. **`observability`:** Structured JSON logging, PII masking, health endpoints, and lifecycle event tracking.
7. **`secure-backend`:** Security rules, API key scopes, least-privilege roles, and defense-in-depth isolation.
8. **`testing-strategy`:** Real PostgreSQL integration tests, deterministic fixtures, and test design principles.
