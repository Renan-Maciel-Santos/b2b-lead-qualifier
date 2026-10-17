# ADR 0001: LLM Only at the Edge

## Status
Accepted

## Context
Conversational lead qualification applications frequently delegate end-to-end decision-making—including qualification verdicts, score calculations, and sales routing—to generative Large Language Models (LLMs). While LLMs excel at processing unstructured natural language, relying on them for core business logic introduces non-deterministic outputs, hallucinated qualification scores, inability to strictly audit why a lead was accepted or rejected, and high latency and API cost per decision.

In enterprise B2B sales operations, lead qualification rules (such as budget thresholds, prohibited job titles, or minimum company size) must be strict, deterministic, explainable, and compliant with business policies.

## Decision
We enforce a strict separation of concerns between natural language interpretation and business decision logic:

1. **Probabilistic Edge (LLM as Slot Extractor)**:
   The LLM operates exclusively at the boundary of the system. Its single responsibility is parsing unstructured conversational messages into strongly-typed Pydantic schemas (`LeadSlots`) using OpenAI Structured Outputs with strict JSON schemas. The LLM never computes scores, determines qualification, or controls the state machine.

2. **Deterministic Core (Python Services & PostgreSQL)**:
   All business logic, multi-turn state transitions, knockout evaluations, and point scoring run in pure Python services backed by ACID transactions in PostgreSQL.
   - Qualification criteria are modeled via the Strategy pattern (`KnockoutStrategy`, `ExactMatchStrategy`).
   - Scoring rules are stored as versioned records in the database (`scoring_rule_sets`), ensuring reproducible and fully auditable evaluation without modifying code.
   - Evaluation adheres to a fail-early knockout principle (disqualifying immediately upon prohibited values) while deferring positive qualification until all mandatory slots are collected (see ADR 0005).

## Consequences
- **Positive**:
  - Deterministic evaluation: identical lead inputs always yield identical qualification scores and verdicts.
  - Complete auditability: every scoring run produces an append-only audit trail linking points awarded to the exact versioned rule set in the database.
  - Testability: scoring logic can be tested in-memory in milliseconds without mock servers or external LLM API calls.
  - Lower operating costs: token usage is constrained to slot extraction rather than chain-of-thought business calculations.
- **Negative**:
  - Unstructured nuances not captured by configured slots require explicit schema updates.
  - Slot extraction latency remains tied to LLM API response times during interactive conversational turns.
