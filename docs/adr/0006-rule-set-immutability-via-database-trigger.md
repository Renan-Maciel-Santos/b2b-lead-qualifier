# ADR 0006: Rule Set Immutability via Database Trigger

## Status
Accepted

## Context
Lead qualification evaluations are stored in `scoring_results` and reference the exact version of the scoring rule set (`scoring_rule_sets.id`) under which the lead was evaluated. This architectural invariant guarantees forensic reproducibility: months after an evaluation, auditors and sales leadership can inspect the exact criteria, required slots, and qualification threshold that decided the lead's fate.

The web application user (`app_user`) has read-only (`SELECT`) permissions on `scoring_rule_sets`, preventing unauthorized mutations through the API. However, administrative connections, migration runners, and seed scripts operate with superuser privileges. Without database-level enforcement, an administrator or seed execution could perform an in-place `UPDATE` on existing version rows (e.g. updating `qualification_threshold` or `rules` on version 1). Such mutations would retroactively distort the audit trail of previously scored leads.

While the project strictly avoids unnecessary database triggers for business workflows, invariants that safeguard audit immutability across all connection roles (including administrators) require enforcement at the relational engine level.

## Decision
We enforce the immutability of versioned scoring rule sets using a PostgreSQL `BEFORE UPDATE` trigger (`trg_enforce_rule_set_immutability` executing `core.enforce_rule_set_immutability()`):

1. **Immutable Fields**:
   Any attempt to modify `rules`, `required_slots`, `qualification_threshold`, `version`, or `tenant_id` on an existing row raises an explicit PostgreSQL exception (`RAISE EXCEPTION`), aborting the transaction.

2. **Permitted Mutations**:
   Only the `is_active` boolean flag may be toggled via `UPDATE`, allowing operators to activate a newer version or deactivate an older one without mutating historical rules.

3. **Versioning Protocol**:
   To change rules or threshold criteria, administrators must insert a brand-new row with an incremented version number (`version > current_version`).

## Consequences
- **Positive**:
  - Absolute audit reproducibility: historical scoring evaluations remain permanently tied to untampered rule definitions, even against administrative updates.
  - Zero application overhead: verification happens transparently within PostgreSQL ACID transaction boundaries.
  - Fail-closed guarantees: scripts attempting `ON CONFLICT ... DO UPDATE` on rule fields fail immediately with an actionable error.
- **Negative**:
  - Rule updates require creating and activating a new version row rather than quick in-place edits.
  - Schema provisioning templates must register and maintain the trigger across tenant schemas.
