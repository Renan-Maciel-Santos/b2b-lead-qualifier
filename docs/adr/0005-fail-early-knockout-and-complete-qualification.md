# ADR 0005: Fail-Early Knockouts and Complete Qualification Slot Collection

## Status
Accepted

## Context
Early implementations of the conversation turn pipeline evaluated lead qualification after every turn based solely on cumulative score versus the qualification threshold. If a single extracted slot awarded enough points to meet or exceed the threshold (for instance, a `role == "CEO"` rule granting 50 points when the threshold was 50), the state machine immediately finalized the dialogue as `QUALIFIED`.

This behavior created critical business and domain evaluation hazards:
1. **Unchecked Knockout Conditions**: Business rules often include knockout criteria on subsequent attributes (e.g., minimum annual revenue or unsupported regions). If a lead was prematurely qualified based on their job title alone, their revenue was never collected and the revenue knockout rule was never evaluated.
2. **Incomplete Sales Handoff**: Sales teams received "qualified" leads lacking mandatory qualification context required for effective follow-up.
3. **Premature Dialogue Termination**: The dialogue completed prematurely before the lead had provided all necessary profile attributes.

## Decision
We establish a strict dual-principle evaluation model: **knockouts fail early; qualification requires complete slot collection**:

1. **Immediate Knockout Disqualification (Fail-Early)**:
   If any extracted slot matches a knockout rule (`KnockoutStrategy`), evaluation halts immediately. The lead transitions to `ConversationState.DISQUALIFIED`, the dialogue terminates, and the audit trail is persisted. There is no reason to spend user time or LLM tokens asking for further information once disqualification is determined.

2. **Complete Slot Collection Before Positive Qualification**:
   A final status of `QUALIFIED` or `NOT_QUALIFIED` can **only** be decided when **all required slots** have been collected.
   - Even if cumulative points exceed the qualification threshold on early turns, the lead is not qualified until all mandatory fields are gathered.
   - While required slots remain missing, the state machine asks for the next missing slot in the configured sequence.

3. **Data-Driven Slot Dependencies**:
   Mandatory slots are modeled in their own dedicated PostgreSQL column `scoring_rule_sets.required_slots text[] NOT NULL CHECK (cardinality(required_slots) > 0)` alongside the rule specifications in `scoring_rule_sets.rules JSONB NOT NULL CHECK (jsonb_typeof(rules) = 'array')`:
   - Enforces relational array integrity at the database layer (non-null, non-empty array).
   - In Python, the repository retrieves both columns and constructs `RuleSetConfigModel` where Pydantic strictly validates: non-empty list, absence of duplicate entries, and existence of every field in `LeadSlots`.
   - If missing or invalid, rule set loading fails fast with an explicit validation error.
   - The dialogue question sequence strictly adheres to the declaration order in `required_slots`.

4. **Deferred Scoring Persistence**:
   Scoring outcomes are only written to the `scoring_results` audit table once a terminal state (`QUALIFIED`, `NOT_QUALIFIED`, `DISQUALIFIED`) is reached. Incomplete, in-flight turns do not pollute audit tables or analytics dashboards.

## Consequences
- **Positive**:
  - Eliminates false-positive qualifications where prohibited conditions would have occurred in uncollected attributes.
  - Ensures every lead marked `QUALIFIED` has full profile coverage across all required dimensions.
  - Preserves token and user efficiency by aborting disqualified leads immediately on the first offending attribute.
- **Negative & Trade-offs**:
  - High-scoring leads must complete all required question turns before receiving a qualification confirmation.
