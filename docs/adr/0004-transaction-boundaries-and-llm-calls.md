# ADR 0004: Transaction Boundaries and LLM Calls

## Status
Accepted

## Context
Early implementations of the conversation turn pipeline acquired a pessimistic row lock (`SELECT ... FOR UPDATE`) on the conversation state record and held the database transaction open while awaiting an external HTTP response from the Large Language Model (LLM) API.

Holding database locks and connection pool slots open across unpredictable, multi-second external network calls causes severe architectural hazards:
1. **Connection Pool Starvation**: Webhook traffic spikes hold PostgreSQL connections idle waiting for OpenAI responses, exhausting the application pool for other concurrent turns.
2. **Database Deadlocks and Contention**: Rapid sequential messages from the same lead block each other at the database level for the entire duration of the LLM call.
3. **Stalled Idempotency Keys**: A transient network crash during the LLM call leaves the message key stuck, preventing retry processing.
4. **Session-Level Tenant Leakage Risk**: Binding tenant GUCs (`app.current_tenant`, `search_path`) at the session/connection level introduces critical cross-tenant data leakage vulnerabilities when pooled connections are recycled across concurrent requests, directly violating the fail-closed guarantee established in ADR 0002.

## Decision
We decouple database transaction boundaries from external LLM execution and enforce tenant isolation strictly per transaction:

1. **Short Transaction 1 (Idempotency Claim)**:
   The inbound `message_id` is registered in a short, dedicated transaction via `INSERT INTO processed_messages ... ON CONFLICT DO UPDATE` with immediate commit. The record tracks `status` (`processing`, `done`, `failed`) and an `updated_at` timestamp.
   - If a message crashes or stalls in `processing` beyond a configurable timeout (default 60 seconds), it can be reclaimed and reprocessed atomically.
   - Duplicate messages received during active processing or after completion (`done`) are immediately discarded without invoking the LLM.

2. **Unbounded LLM Execution (Zero Database Locks & Zero Checked-Out Connections)**:
   Semantic slot extraction (`llm_adapter.extract_slots`) is performed outside any active database transaction, without holding any row locks and without borrowing any connection from the pool. The connection from Transaction 1 is returned immediately before the LLM call begins.

3. **Short Transaction 2 (State Mutation and Scoring)**:
   A second short transaction is opened only after LLM extraction completes:
   - Acquires the exclusive row lock via `SELECT ... FOR UPDATE` on `conversation_states`.
   - Merges newly extracted slots with previously accumulated slots.
   - Computes deterministic qualification scoring via `ScoringService`.
   - Persists the updated conversation state and immutable scoring audit trail.
   - Marks the processed message `status = 'done'`.
   - Commits the transaction atomically and returns the connection to the pool.

4. **Failure Recovery**:
   If unhandled errors occur during turn processing, the message status is marked `failed` in a dedicated unit of work so subsequent retries are immediately processable without waiting for the timeout.

5. **Transaction-Scoped Tenant Context (Fail-Closed Unit of Work)**:
   Session-level tenant context on pooled connections is strictly prohibited. Tenant isolation is enforced exclusively per transaction via an asynchronous unit of work (`tenant_transaction(pool, tenant_ctx)`):
   - **Authentication**: Yields an immutable `TenantContext(tenant_id, schema_name)` resolved via the `SECURITY DEFINER` function `core.resolve_tenant_by_api_key`, without retaining any open connection.
   - **Unit of Work Lifecycle**:
     a) Acquires a connection from the pool;
     b) Opens an atomic transaction block;
     c) Executes `SELECT set_config('app.current_tenant', %s, true)` and `SET LOCAL search_path TO {}, public` using parameterized `sql.Identifier`;
     d) Yields the connection to repositories (repositories never execute `commit` or `rollback` independently);
     e) Commits on clean exit, rolls back on exception;
     f) Automatically resets transaction GUCs and returns the pristine connection to the pool.
   - **Fail-Closed Verification**: Because `is_local = true` and `SET LOCAL` are enforced, any query executed outside an active unit of work evaluates `core.current_tenant_id()` to `NULL`, causing PostgreSQL Row Level Security (RLS) to immediately drop all rows (fail-closed).

## Consequences
- **Positive**:
  - PostgreSQL row locks and connection slots are held for only single-digit milliseconds during local database operations.
  - Zero connection pool exhaustion during LLM API latency spikes, rate limiting, or network timeouts.
  - Failures during LLM inference are recoverable and do not leave database transactions or row locks dangling.
  - Cross-tenant context leakage is structurally impossible: pooled connections revert to an unauthenticated, zero-access state outside active units of work.
- **Negative & Trade-offs**:
  - Two short database transactions per conversational turn instead of one continuous transaction.
  - Requires maintaining message lifecycle status (`processing`, `done`, `failed`) and handling timeout edge cases.
  - Re-applying tenant context (`SET LOCAL` and `set_config`) per transaction adds a minor overhead. Because these are in-memory GUC assignments executed locally on the PostgreSQL backend, their latency cost is sub-millisecond (negligible) compared to the absolute safety and fail-closed security guarantees provided.
