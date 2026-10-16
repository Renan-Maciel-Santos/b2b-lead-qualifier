"""Conversation persistence repository for message idempotency and qualification scoring."""

import json
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import dict_row


class ConversationRepository:
    """Repository managing message idempotency and append-only scoring results."""

    def __init__(self, conn: AsyncConnection) -> None:
        """Initialize repository with an active tenant-scoped database connection.

        Args:
            conn: PostgreSQL async connection with tenant RLS and search_path active.
        """
        self.conn = conn

    async def is_message_processed(self, message_id: str) -> bool:
        """Check whether a message ID has already been processed by the tenant.

        Args:
            message_id: Inbound message identifier from transport.

        Returns:
            bool: True if already recorded, False otherwise.
        """
        async with self.conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT 1 FROM processed_messages WHERE message_id = %s",
                (message_id,),
            )
            result = await cur.fetchone()
            return result is not None

    async def mark_message_processed(self, message_id: str) -> None:
        """Record an inbound message in the idempotency table.

        Args:
            message_id: Unique message identifier to record.
        """
        async with self.conn.cursor() as cur:
            # tenant_id is automatically assigned via DEFAULT (app.current_tenant)
            await cur.execute(
                "INSERT INTO processed_messages (message_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (message_id,),
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
                (phone_number, str(rule_set_id), final_score, is_qualified, json.dumps(audit_trail)),
            )
