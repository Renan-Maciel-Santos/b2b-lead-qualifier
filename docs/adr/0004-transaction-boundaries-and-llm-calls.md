# ADR 0004: Transaction Boundaries and LLM Calls

## Status
Accepted

## Context
Early implementations of the conversation turn pipeline acquired a pessimistic row lock (`SELECT ... FOR UPDATE`) on the conversation state record and held the database transaction open while awaiting an external HTTP response from the Large Language Model (LLM) API.

Holding database locks and connection pool slots open across unpredictable, multi-second external network calls causes severe architectural hazards:
1. **Connection Pool Starvation**: Webhook traffic spikes hold PostgreSQL connections idle waiting for OpenAI responses, exhausting the application pool for other concurrent turns.
2. **Database Deadlocks and Contention**: Rapid sequential messages from the same lead block each other at the database level for the entire duration of the LLM call.
3. **Stalled Idempotency Keys**: A transient network crash during the LLM call leaves the message key stuck, preventing retry processing.

## Decision
We decouple database transaction boundaries from external LLM execution:

1. **Short Transaction 1 (Idempotency Claim)**:
   The inbound `message_id` is registered in a short, dedicated transaction via `INSERT INTO processed_messages ... ON CONFLICT DO UPDATE` with immediate commit. The record tracks `status` (`processing`, `done`, `failed`) and an `updated_at` timestamp.
   - If a message crashes or stalls in `processing` beyond a configurable timeout (default 60 seconds), it can be reclaimed and reprocessed atomically.
   - Duplicate messages received during active processing or after completion (`done`) are immediately discarded without invoking the LLM.

2. **Unbounded LLM Execution (Zero Database Locks)**:
   Semantic slot extraction (`llm_adapter.extract_slots`) is performed outside any active database transaction and without holding any row locks or open connection handles.

3. **Short Transaction 2 (State Mutation and Scoring)**:
   A second short transaction is opened only after LLM extraction completes:
   - Acquires the exclusive row lock via `SELECT ... FOR UPDATE` on `conversation_states`.
   - Merges newly extracted slots with previously accumulated slots.
   - Computes deterministic qualification scoring via `ScoringService`.
   - Persists the updated conversation state and immutable scoring audit trail.
   - Marks the processed message `status = 'done'`.
   - Commits the transaction atomically.

4. **Failure Recovery**:
   If unhandled errors occur during turn processing, the message status is marked `failed` so subsequent retries are immediately processable without waiting for the timeout.

## Consequences
- **Positive**:
  - PostgreSQL row locks and connection slots are held for only single-digit milliseconds during local database operations.
  - Zero pool exhaustion during LLM API latency spikes or rate limiting.
  - Failures during LLM inference are recoverable and do not leave database transactions dangling.
- **Negative**:
  - Two short database transactions per conversational turn instead of one continuous transaction.
  - Requires maintaining message lifecycle status (`processing`, `done`, `failed`) and handling timeout edge cases.
