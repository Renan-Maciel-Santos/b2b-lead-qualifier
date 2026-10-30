# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-30

First release: a conversational B2B lead qualification service in which an LLM only extracts structured data from free text, while scoring, qualification and tenant isolation are enforced by deterministic Python and PostgreSQL.

### Added

- **LLM at the edge only.** The LLM extracts typed qualification slots from each message; extraction failures are propagated instead of being turned into empty slots, and the provider configuration fails fast at startup ([ADR 0001](docs/adr/0001-llm-only-at-the-edge.md)).
- **Multi-tenancy enforced by the database.** Each tenant has its own schema, every tenant table uses `FORCE ROW LEVEL SECURITY`, the application connects as an unprivileged role without `BYPASSRLS`, and the tenant is set per transaction with `SET LOCAL`, so a missing tenant context returns no rows ([ADR 0002](docs/adr/0002-multi-tenancy-with-schema-per-tenant-and-rls.md)).
- **API key authentication with scopes.** Keys are stored only as SHA-256 hashes, resolve the tenant on their own (no tenant in URLs), carry scopes (`webhook:write`, `leads:read`) checked per route, and are provisioned by a CLI command ([ADR 0003](docs/adr/0003-api-key-authentication.md)).
- **Multi-turn conversations.** Conversation state with row locking and status-aware idempotency; the LLM call runs outside the database transaction, so the lock and the pooled connection are not held while waiting for the model, and messages stuck after a timeout are reprocessed ([ADR 0004](docs/adr/0004-transaction-boundaries-and-llm-calls.md)).
- **Deterministic scoring engine.** Strategy-pattern scoring with typed results, fail-early knockout rules, qualification only after every required slot is collected, and structured reasons for each score ([ADR 0005](docs/adr/0005-fail-early-knockout-and-complete-qualification.md)).
- **Immutable rule sets.** A database trigger prevents changing a scoring rule set after it is in use, so past scores remain explainable ([ADR 0006](docs/adr/0006-rule-set-immutability-via-database-trigger.md)).
- **Leads API and dashboard.** A scoped leads API and an analytical dashboard that shows each lead's score, maximum score and the reasons behind it.
- **Evaluation and demo.** A synthetic golden dataset for evaluating extraction, demo scripts, dashboard screenshots and a recorded demo.
- **Quality gates.** Pre-commit with ruff and mypy in strict mode, GitHub Actions CI, and unit and integration tests against real PostgreSQL, including tests that prove tenant context never leaks across pooled connections.

### Security

- Least privilege for API keys: the application role can only verify keys through a `SECURITY DEFINER` function, not read the keys table.
- The dashboard relies on Jinja2 autoescaping and renders untrusted lead data only through `textContent`; a test fails if `innerHTML` appears in the template.
- Phone numbers are masked in logs.

[Unreleased]: https://github.com/Renan-Maciel-Santos/b2b-lead-qualifier/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Renan-Maciel-Santos/b2b-lead-qualifier/releases/tag/v0.1.0
