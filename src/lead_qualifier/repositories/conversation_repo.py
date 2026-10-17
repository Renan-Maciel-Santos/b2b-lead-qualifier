"""Conversation persistence repository for atomic idempotency, state locking, and scoring."""

import json
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import dict_row


class ConversationRepository:
    """Repository managing atomic message idempotency, conversation state locks, and scoring results."""

    def __init__(self, conn: AsyncConnection) -> None:
        """Initialize repository with an active tenant-scoped database connection.

        Args:
            conn: PostgreSQL async connection with tenant RLS and search_path active.
        """
        self.conn = conn

    async def acquire_message_lock(self, message_id: str, timeout_seconds: int = 60) -> bool:
        """Atomically register a message ID or reclaim a timed-out/failed message.

        Guarantees race-free idempotency across workers:
        - Inserts the message with status 'processing'.
        - If a conflict occurs on (tenant_id, message_id), reclaims the message only if:
          1. status is 'failed', OR
          2. status is 'processing' and updated_at is older than timeout_seconds.
        - Commits immediately in its own transaction so no database lock is held open.

        Args:
            message_id: Inbound message identifier from transport.
            timeout_seconds: Timeout window after which an unfinished 'processing' message is reclaimed.

        Returns:
            bool: True if this worker won the lock and should process the turn; False otherwise.
        """
        async with self.conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                INSERT INTO processed_messages (message_id, status, created_at, updated_at)
                VALUES (%s, 'processing', now(), now())
                ON CONFLICT (tenant_id, message_id) DO UPDATE
                SET status = 'processing',
                    updated_at = now()
                WHERE (processed_messages.status = 'failed')
                   OR (processed_messages.status = 'processing'
                       AND processed_messages.updated_at < now() - (%s || ' seconds')::interval)
                RETURNING message_id
                """,
                (message_id, timeout_seconds),
            )
            row = await cur.fetchone()
        await self.conn.commit()
        return row is not None

    async def mark_message_done(self, message_id: str) -> None:
        """Mark a processed message as successfully completed.

        Args:
            message_id: Message identifier to mark as done.
        """
        async with self.conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE processed_messages
                SET status = 'done', updated_at = now()
                WHERE message_id = %s
                """,
                (message_id,),
            )

    async def mark_message_failed(self, message_id: str) -> None:
        """Mark a message as failed and commit immediately so it can be retried.

        Args:
            message_id: Message identifier to mark as failed.
        """
        async with self.conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE processed_messages
                SET status = 'failed', updated_at = now()
                WHERE message_id = %s
                """,
                (message_id,),
            )
        await self.conn.commit()

    async def get_conversation_state_read_only(
        self,
        phone_number: str,
    ) -> tuple[str, dict[str, Any]]:
        """Retrieve conversation state and accumulated slots without acquiring a row lock.

        Allows inspecting state before invoking external services like the LLM.

        Args:
            phone_number: Evaluated lead phone number in E.164 format.

        Returns:
            tuple[str, dict[str, Any]]: Current state string and accumulated slots dictionary.
        """
        async with self.conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT current_state, accumulated_slots
                FROM conversation_states
                WHERE phone_number = %s
                """,
                (phone_number,),
            )
            row = await cur.fetchone()
            if not row:
                return "INITIAL", {}
            return str(row["current_state"]), dict(row["accumulated_slots"] or {})

    async def get_or_create_conversation_state(
        self,
        phone_number: str,
    ) -> tuple[str, dict[str, Any]]:
        """Retrieve conversation state and lock the row using SELECT ... FOR UPDATE.

        Ensures serialized state transitions and slot merging when concurrent turns
        arrive for the same lead.

        Args:
            phone_number: Evaluated lead phone number in E.164 format.

        Returns:
            tuple[str, dict[str, Any]]: Tuple of (current_state, accumulated_slots).
        """
        async with self.conn.cursor(row_factory=dict_row) as cur:
            # Guarantee the row exists idempotently
            await cur.execute(
                """
                INSERT INTO conversation_states (phone_number, current_state, accumulated_slots)
                VALUES (%s, 'INITIAL', '{}'::jsonb)
                ON CONFLICT (tenant_id, phone_number) DO NOTHING
                """,
                (phone_number,),
            )
            # Exclusively lock the row for the transaction
            await cur.execute(
                """
                SELECT current_state, accumulated_slots
                FROM conversation_states
                WHERE phone_number = %s
                FOR UPDATE
                """,
                (phone_number,),
            )
            row = await cur.fetchone()
            if not row:
                return "INITIAL", {}
            return str(row["current_state"]), dict(row["accumulated_slots"] or {})

    async def save_conversation_state(
        self,
        phone_number: str,
        current_state: str,
        accumulated_slots: dict[str, Any],
    ) -> None:
        """Update the conversation state and merged accumulated slots for the lead.

        Args:
            phone_number: Evaluated lead phone number in E.164 format.
            current_state: Target lifecycle state string.
            accumulated_slots: Comprehensive dictionary of accumulated lead slots.
        """
        async with self.conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE conversation_states
                SET current_state = %s,
                    accumulated_slots = %s,
                    updated_at = now()
                WHERE phone_number = %s
                """,
                (current_state, json.dumps(accumulated_slots), phone_number),
            )

    async def get_active_scoring_rule_set(self) -> dict[str, Any] | None:
        """Retrieve the currently active scoring rule set for the tenant.

        Returns:
            dict[str, Any] | None: Rule set record including JSONB rules, or None if not configured.
        """
        async with self.conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT id, version, rules, qualification_threshold
                FROM scoring_rule_sets
                WHERE is_active = true
                LIMIT 1
                """
            )
            return await cur.fetchone()

    async def save_scoring_result(
        self,
        phone_number: str,
        rule_set_id: str | UUID,
        final_score: int,
        is_qualified: bool,
        audit_trail: list[str],
    ) -> None:
        """Persist an immutable scoring outcome tied to the active rule set version.

        Args:
            phone_number: Evaluated lead phone number in E.164 format.
            rule_set_id: UUID of the rule set version applied.
            final_score: Computed integer score.
            is_qualified: Final boolean decision.
            audit_trail: Chronological list of rule evaluation explanations.
        """
        async with self.conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO scoring_results (
                    phone_number,
                    rule_set_id,
                    final_score,
                    is_qualified,
                    audit_trail
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    phone_number,
                    str(rule_set_id),
                    final_score,
                    is_qualified,
                    json.dumps(audit_trail),
                ),
            )
